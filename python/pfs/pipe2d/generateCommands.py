# Developed for the LSST Data Management System.
# This product includes software developed by the LSST Project
# (http://www.lsst.org).
# See the COPYRIGHT file at the top-level directory of this distribution
# for details of code ownership.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the LSST License Statement and
# the GNU General Public License along with this program.  If not,
# see <http://www.lsstcorp.org/LegalNotices/>.
#
"""Components to implement a program ``generateCommands.py``.
"""

__all__ = []  # modified by @export

import lsst.log

import argparse
import collections.abc
import contextlib
import dataclasses
import enum
import os
import re
import shlex
import stat

import yaml

from typing import (
    Any,
    Collection,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    TextIO,
    Tuple,
    Type,
    Union,
)


def export(obj):
    """Decorator to add obj to __all__."""
    __all__.append(obj.__name__)
    return obj


DEFAULT_CALIB_VALIDITY = 1800
"""Calibs' valid days, used if 'validity' field is not present in YAML files.
"""


@export
def main():
    """Parse ``sys.argv`` and call ``generateCommands()``."""
    parser = argparse.ArgumentParser(
        description="""
    Process a yaml file and generate shell commands.
    """
    )

    parser.add_argument("dataDir", type=str, help="Root of data repository")
    parser.add_argument("specFile", type=str, help="Name of file specifying the work")
    parser.add_argument("output", type=str, help="Path to output file (shell script)")
    parser.add_argument("--init", action="store_true", help="Install initial calibs")
    parser.add_argument("--blocks", type=str, nargs="+", help="Blocks to execute")
    parser.add_argument(
        "--calib",
        type=str,
        help="Name of output calibration directory (default: dataDir/CALIB",
    )
    parser.add_argument(
        "--calibTypes",
        type=str,
        nargs="+",
        default=[],
        choices=CalibBlock.calibTypes,
        help="Types of calibs to process",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Clean up byproducts after ingesting calibs",
    )
    parser.add_argument(
        "--copyMode",
        choices=["move", "copy", "link", "skip"],
        default="copy",
        help="How to move files into calibration directory",
    )
    parser.add_argument(
        "--devel",
        action="store_true",
        help="Run commands in the development mode (no versioning)",
    )
    parser.add_argument(
        "--force", action="store_true", help="Continue in the face of problems"
    )
    parser.add_argument(
        "-j", "--processes", type=int, default=1, help="Number of processes to use"
    )
    parser.add_argument(
        "-L",
        "--loglevel",
        type=str,
        choices=list(LogLevel.__members__),
        default="INFO",
        help="How chatty should I be?",
    )
    parser.add_argument(
        "--overwriteCalib",
        action="store_true",
        help="Overwrite old calibs on ingestion",
    )
    parser.add_argument(
        "--rerun", type=str, default="noname", help="Name of rerun to use"
    )
    parser.add_argument(
        "--scienceSteps",
        type=str,
        nargs="+",
        default=[],
        choices=ScienceBlock.steps,
        help="pipeline steps to execute",
    )
    parser.add_argument(
        "--allowErrors",
        default=False,
        action="store_true",
        help="Allow processing errors to be non-fatal?",
    )

    args = parser.parse_args()
    logger = lsst.log.getLogger("")
    logger.setLevel(LogLevel.__members__[args.loglevel])
    del args.loglevel

    return generateCommands(logger=logger, **vars(args))


class LogLevel(enum.IntEnum):
    """Possible arguments of ``lsst.log.setLevel()``."""

    TRACE = lsst.log.TRACE
    DEBUG = lsst.log.DEBUG
    INFO = lsst.log.INFO
    WARN = lsst.log.WARN
    ERROR = lsst.log.ERROR
    FATAL = lsst.log.FATAL


@export
class CommandConfig:
    """This class represents ``--config key=value`` and ``--configfile=path``
    in a command line.

    Parameters
    ----------
    configs : `Iterable[str]`
        List of config strings ("key=value").
    configfile : `Optional[str]`
        Path to a configuration file
    """

    __slots__ = ["configs", "configfile"]

    def __init__(
        self, *, configs: Iterable[str] = [], configfile: Optional[str] = None
    ):
        self.configs = list(configs)
        self.configfile = configfile

    @classmethod
    def fromYaml(
        cls, yamlBlock: Mapping[str, Any], *, remove: bool = False
    ) -> "CommandConfig":
        """Extract "config: ..." from ``yamlBlock``.

        Parameters
        ----------
        yamlBlock : `Mapping[str, Any]`
            A block of a YAML data structure:

            ``"config"``
                A config string, or a list of config strings.
            ``"configfile"``
                Path to a configuration file
        remove : `bool`
            Remove those keys from `yamlBlock` that are used by this method.

        Returns
        -------
        config : `CommandConfig`
        """
        if not remove:
            yamlBlock = dict(yamlBlock)

        configs = yamlBlock.pop("config", [])
        if isinstance(configs, str):
            configs = [configs]
        if not isinstance(configs, list):
            raise RuntimeError(
                f"'config' must be a string or a list of string: ({configs})"
            )

        configs = [ensureKeyEqValue(str(x)) for x in configs]

        configfile = yamlBlock.pop("configfile", None)
        if not (configfile is None or isinstance(configfile, str)):
            raise RuntimeError(f"'configfile' must be a string: '{configfile}'")

        return cls(configs=configs, configfile=configfile)

    def getCommandLine(self) -> List[str]:
        """Get command line options for this config.

        Returns
        -------
        options : `List[str]`
            Like ["--config", "key=value", "key=value"]
        """
        commands = []
        if self.configfile:
            commands.append(f"--configfile={self.configfile}")
        if self.configs:
            commands += ["--config"] + self.configs
        return commands


@export
class SourceFilter:
    """This class represents ``--id`` in a command line.

    If two or more arguments are specified in construction,
    the result will be their intersection.

    Parameters
    ----------
    id : `Iterable[str]`
        Arguments given to ``--id`` in a command line,
        like ``["field=BIAS", "dateObs=2000-01-01"]``
    """

    __slots__ = ["id"]

    def __init__(self, id: Iterable[str] = []):
        self.id = list(id)

    @classmethod
    def fromYaml(
        cls, yamlBlock: Mapping[str, Any], *, key: str = "id", remove: bool = False
    ) -> "SourceFilter":
        """Extract "id:..." from ``yamlBlock``.

        Parameters
        ----------
        yamlBlock : `Mapping[str, Any]`
            A block of a YAML data structure:

            ``"id"``
                A string like ``"field=BIAS"``, or
                a list of str like ``["field=BIAS", "dateObs=2000-01-01"]``
        key : `str`
            If you give this argument, ``key`` will be used
            instead of ``"id"`` for the key of the extracted field.
        remove : `bool`
            Remove those keys from `yamlBlock` that are used by this method.

        Returns
        -------
        sourceFilter : `SourceFilter`
        """
        if not remove:
            yamlBlock = dict(yamlBlock)

        id = yamlBlock.pop(key, [])
        if isinstance(id, str):
            id = [id]
        if not isinstance(id, list):
            raise RuntimeError(f"'{key}' must be a string or a list of string: '{id}'")

        return cls(ensureKeyEqValue(str(x)) for x in id)

    def getCommandLine(self, *, key: str = "id") -> List[str]:
        """Get command line options for this source filter.

        Parameters
        ----------
        key : `str`
            If you give this argument, ``--{key}`` will be used
            instead of ``--id`` for the command line option.

        Returns
        -------
        options : `List[str]`
            Like ["--id", "field=BIAS"]
        """
        if self.id:
            commands = [f"--{key}"] + self.id
        else:
            commands = []
        return commands


@export
class InitSource:
    """Initial calibs that are necessary in order to start creating calibs.

    Parameters
    ----------
    dirName : `str`
        Path to a directory where files exist.
    detectorMapFmt : `str`
        Name of detectorMap files.
        Occurrences of "{arm}" in it will be replaced by "r1", "b1" etc.
    arms : `Iterable[str]`
        ["r1", "b1"] for example.
    """

    __slots__ = ["dirName", "detectorMapFmt", "arms"]

    def __init__(self, dirName: str, detectorMapFmt: str, arms: Iterable[str]):
        self.dirName = dirName
        self.detectorMapFmt = detectorMapFmt
        self.arms = list(arms)

    @classmethod
    def fromYaml(cls, yamlBlock: Mapping[str, Any]) -> "InitSource":
        """Construct ``InitSource`` from a YAML block.

        Parameters
        ----------
        yamlBlock : `Mapping[str, Any]`
            A block of a YAML data structure:

            ``"dirName"``
                ``"$DRP_STELLA_DATA_DIR/raw"`` for example.
            ``"detectorMapFmt"``
                ``"detectorMap-sim-{arm}.fits"`` for example.
                "{arm}" in it will be replaced by "r1", "b1" etc.
            ``"arms"``
                ``["r1", "b1"]`` for example.

        Returns
        -------
        initSource : `InitSource`
        """
        yamlBlock = dict(yamlBlock)
        dirName = yamlBlock.pop("dirName")
        detectorMapFmt = yamlBlock.pop("detectorMapFmt")
        arms = yamlBlock.pop("arms")

        if yamlBlock:
            raise RuntimeError(
                f"Invalid keys for {cls.__name__}: {list(yamlBlock.keys())}"
            )

        return cls(dirName, detectorMapFmt, arms)

    def execute(
        self,
        logger: lsst.log.Log,
        fout: TextIO,
        dataDir: str,
        calib: str,
        allowErrors: bool = False,
    ):
        """Put to ``fout`` commands to ingest this source.

        Parameters
        ----------
        logger : `lsst.log.Log`
            Logger.
        fout : `TextIO`
            Output file where to write the command.
        dataDir : `str`
            Root of data repository.
        calib : `str`
            Name of output calibration directory.
        allowErrors : `bool`
            Allow processing errors to be non-fatal?
        """
        initDir = os.path.join(dataDir, os.path.expandvars(self.dirName))
        logger.info("Reading init files from '%s'", initDir)

        detectorMaps = []
        for arm in self.arms:
            detectorMaps.append(
                os.path.join(initDir, self.detectorMapFmt.format(arm=arm))
            )

        command = [
            "ingestPfsCalibs.py",
            dataDir,
            f"--output={calib}",
            f"--validity={DEFAULT_CALIB_VALIDITY}",
            "--create",
            "--longlog=1",
            "--mode=copy",
        ]

        if not allowErrors:
            command += ["--doraise"]

        command += ["--"]
        command += detectorMaps

        print(f"{shellCommand(command)}", file=fout)


@export
class CalibSource:
    """Sources to construct a type of calib.
    The concrete type of the calib is defined by subclasses.

    Parameters
    ----------
    config : `CommandConfig`
        Configurations used in constructing this calib.
    source : `SourceFilter`
        Sources for this calib.
    validity : `int`
        Valid days of the resulting calib.

    Notes
    -----
    To make a subclass, ``typeName``` and ``commandName`` are required:

        class DarkSource(
                CalibSource,
                typeName="dark", commandName="constructPfsDark.py"):
            pass

    ``typeName``
        Name of the calib type. This is the name used in YAML files.
    ``commandName``
        Name of the command to construct the calib.
    ``isBatchPoolTask``
        Is the called task a subclass of `lsst.ctrl.pool.parallel.BatchPoolTask`?
        (Default: True)
    """

    __slots__ = ["config", "source", "validity"]

    # This property may be replaced by __subclasses__() once it is documented.
    __subclasses: Dict[str, type] = {}

    def __init__(self, config: CommandConfig, source: SourceFilter, validity: int):
        self.config = config
        self.source = source
        self.validity = validity

    def __init_subclass__(
        cls, *, typeName: str, commandName: str, isBatchPoolTask=True, **kwargs
    ):
        super().__init_subclass__(**kwargs)
        CalibSource.__subclasses[typeName] = cls
        cls.typeName = typeName
        cls.commandName = commandName
        cls.isBatchPoolTask = isBatchPoolTask

    @classmethod
    def fromYaml(cls, yamlBlock: Mapping[str, Any]) -> "CalibSource":
        """Construct ``CalibSource`` from a YAML block.

        Parameters
        ----------
        yamlBlock : `Mapping[str, Any]`
            A block of a YAML data structure:

            ``"config"``
                A config string, or a list of config strings.
            ``"configfile"``
                Path to a configuration file
            ``"validity"``
                Valid days for the resulting calib
                before and after the date of the calib.
            ``"id"``
                A string like ``"field=BIAS"``, or
                a list of str like ``["field=BIAS", "dateObs=2000-01-01"]``

            Additional fields must exist when a subclass overrides
            ``cls._fromYamlAdditionalFields().``

        Returns
        -------
        calibSource : `CalibSource`
        """
        yamlBlock = dict(yamlBlock)
        config = CommandConfig.fromYaml(yamlBlock, remove=True)
        source = SourceFilter.fromYaml(yamlBlock, remove=True)
        validity = int(yamlBlock.pop("validity", DEFAULT_CALIB_VALIDITY))
        additionalFields = cls._fromYamlAdditionalFields(yamlBlock)

        if yamlBlock:
            raise RuntimeError(
                f"Invalid keys for {cls.__name__}: {list(yamlBlock.keys())}"
            )

        return cls(config, source, validity, **additionalFields)

    @classmethod
    def _fromYamlAdditionalFields(cls, yamlBlock: Mapping[str, Any]) -> Dict[str, Any]:
        """Construct additional members of ``CalibSource`` from a YAML block.

        By default, this method does nothing.
        Subclasses can override this method instead of overriding ``fromYaml()``
        as a whole. Subclasses must pop those items from ``yamlBlock`` that they use.

        Parameters
        ----------
        yamlBlock : `Mapping[str, Any]`
            A block of a YAML data structure.

        Returns
        -------
        members : `Dict[str, Any]`
            Additional members of ``CalibSource``.
            This is passed to the constructor as ``cls(..., **members)``
        """
        return {}

    @staticmethod
    def getSubclass(typeName: str) -> Type["CalibSource"]:
        """Get a subclass by ``typeName``.

        Parameters
        ----------
        typeName : `str`
            ``typeName`` of the subclass.

        Returns
        -------
        subclass : type
            The class object of the subclass.
        """
        return CalibSource.__subclasses[typeName]

    def execute(
        self,
        fout: TextIO,
        dataDir: str,
        calib: str,
        rerun: str,
        *,
        processes: int = 1,
        devel: bool = False,
        allowErrors: bool = False,
    ):
        """Put to ``fout`` commands to construct this calib from its source.

        Parameters
        ----------
        fout : `TextIO`
            Output file where to write the command.
        dataDir : `str`
            Root of data repository.
        calib : `str`
            Name of output calibration directory.
        rerun : `str`
            Name of rerun.
        processes : `int`
            Number of processes to use.
        devel : `bool`
            Run commands in the development mode (no versioning).
        allowErrors : `bool`
            Allow processing errors to be non-fatal?
        """
        command = [
            self.commandName,
            dataDir,
            f"--calib={calib}",
            f"--rerun={rerun}",
            "--longlog=1",
        ]

        if self.isBatchPoolTask:
            command += [
                "--batch-type=smp",
                f"--cores={processes}",
            ]
        else:
            command += [
                f"-j{processes}",
            ]

        if not allowErrors:
            command += ["--doraise"]

        command += getDevelopmentOptions() if devel else []
        command += self.source.getCommandLine()
        command += self.config.getCommandLine()
        command += self._getAdditionalCommandLineArgs()

        print(f"{shellCommand(command)}", file=fout)

    def _getAdditionalCommandLineArgs(self) -> List[str]:
        """Get additional command line arguments.

        By default, this method returns the empty list.
        Subclasses can override this method instead of overriding ``execute()``
        as a whole.

        Returns
        -------
        args : `List[str]`
            Additional command line arguments.
        """
        return []

    def ingest(
        self,
        fout: TextIO,
        dataDir: str,
        calib: str,
        rerun: str,
        copyMode: str,
        *,
        overwrite: bool,
        allowErrors: bool = False,
    ):
        """Put to ``fout`` commands to ingest this calib.

        Parameters
        ----------
        fout : `TextIO`
            Output file where to write the command.
        dataDir : `str`
            Root of data repository.
        calib : `str`
            Name of output calibration directory.
        rerun : `str`
            Name of rerun.
        copyMode : `str`
            How to move files into calibration directory.
        overwrite : `bool`
            Overwrite old calibs on ingestion.
            This argument is ignored if ``self.doOverwrite`` is True.
        allowErrors : `bool`
            Allow processing errors to be non-fatal?
        """
        command = [
            "ingestPfsCalibs.py",
            dataDir,
            f"--output={calib}",
            f"--validity={self.validity}",
            "--longlog=1",
            f"--mode={copyMode}",
        ]

        if not allowErrors:
            command += ["--doraise"]

        if overwrite or self.doOverwrite:
            command += ["--config", "clobber=True"]

        filedir = os.path.join(dataDir, "rerun", rerun, self.outputSubdir)

        print(f"{shellCommand(command)} -- {shlex.quote(filedir)}/*.fits", file=fout)

    def clean(self, fout: TextIO, dataDir: str, rerun: str):
        """Put to ``fout`` commands to remove byproducts.

        Parameters
        ----------
        fout : `TextIO`
            Output file where to write the command.
        dataDir : `str`
            Root of data repository.
        rerun : `str`
            Name of rerun.
        """
        command = ["rm", "-r", "-f", os.path.join(dataDir, "rerun", rerun)]
        print(shellCommand(command), file=fout)

    @property
    def outputSubdir(self) -> str:
        """Name of subdirectory where calibs are output (`str`, read-only)

        Output files are expected to be under
        ``rerun/RERUNNAME/{self.outputSubdir}``.
        """
        return self.typeName.upper()

    @property
    def doOverwrite(self) -> bool:
        """Always overwrite old calibs? (`bool`, read-only)

        ``self.ingest()`` ignores its `overwrite` argument if this is True.
        """
        return False


@export
class BiasSource(CalibSource, typeName="bias", commandName="constructPfsBias.py"):
    pass


@export
class DarkSource(CalibSource, typeName="dark", commandName="constructPfsDark.py"):
    pass


@export
class FlatSource(CalibSource, typeName="flat", commandName="constructFiberFlat.py"):
    pass


@export
@dataclasses.dataclass
class BootstrapSourceSubgroup:
    """Subgroup of BootstrapSource.
    ``bootstrapDetectorMap.py`` is called for each subgroup.

    Parameters
    ----------
    config : `CommandConfig`
        Configurations used in constructing this calib.
    flatSource : `SourceFilter`
        SourceFilter for a single flat at zero dither.
    arcSource : `SourceFilter`
        SourceFilter for a single arc.
    """

    config: CommandConfig
    flatSource: SourceFilter
    arcSource: SourceFilter


@export
class BootstrapSource(
    CalibSource, typeName="bootstrap", commandName="bootstrapDetectorMap.py"
):
    """Sources for ``bootstrapDetectorMap.py``

    This process does not always need running.
    YAML structure for this process is different from those for others.

    See the docstring of ``fromYaml()`` for details.

    Parameters
    ----------
    groups : `Iterable[BootstrapSourceSubgroup]`
        List of subgroups.
        ``bootstrapDetectorMap.py`` is called for each of the subgroups.
    validity : `int`
        Valid days of the resulting calib.
    """

    __slots__ = ["groups"]

    def __init__(self, groups: Iterable[BootstrapSourceSubgroup], validity: int):
        super().__init__(CommandConfig(), SourceFilter(), validity)
        self.groups = list(groups)

    @classmethod
    def fromYaml(cls, yamlBlock: Mapping[str, Any]) -> "BootstrapSource":
        """Construct ``BootstrapSource`` from a YAML block.

        Parameters
        ----------
        yamlBlock : `Mapping[str, Any]`
            A block of a YAML data structure:

            ``"group"``
                List of Mapping[str, Any]`.
                ``bootstrapDetectorMap.py`` is called for each group.
                Contents of each group are:

                ``"config"``
                    A config string, or a list of config strings.
                ``"configfile"``
                    Path to a configuration file
                ``"flatId"``
                    A string like ``"field=FLAT"`` or a list of such strings
                    to select one flat at zero dither.
                ``"arcId"``
                    A string like ``"field=ARC"`` or a list of such strings
                    to select arc of a single flavor.

            ``"validity"``
                Valid days for the resulting calib
                before and after the date of the calib.

        Returns
        -------
        bootstrapSource : `BootstrapSource`
        """
        yamlBlock = dict(yamlBlock)

        groups = []
        for block in ensureInstance(yamlBlock.pop("group", []), list):
            block = ensureInstance(block, dict)
            config = CommandConfig.fromYaml(block, remove=True)
            flatSource = SourceFilter.fromYaml(block, key="flatId", remove=True)
            arcSource = SourceFilter.fromYaml(block, key="arcId", remove=True)
            if block:
                raise RuntimeError(
                    f'Invalid keys for {cls.__name__}["group"]: {list(block.keys())}'
                )
            groups.append(
                BootstrapSourceSubgroup(
                    config=config, flatSource=flatSource, arcSource=arcSource
                )
            )

        validity = int(yamlBlock.pop("validity", DEFAULT_CALIB_VALIDITY))

        if yamlBlock:
            raise RuntimeError(
                f"Invalid keys for {cls.__name__}: {list(yamlBlock.keys())}"
            )

        return cls(groups, validity)

    def execute(
        self,
        fout: TextIO,
        dataDir: str,
        calib: str,
        rerun: str,
        *,
        processes: int = 1,
        devel: bool = False,
        allowErrors: bool = False,
    ):
        """Put to ``fout`` commands to construct this calib from its source.

        Parameters
        ----------
        fout : `TextIO`
            Output file where to write the command.
        dataDir : `str`
            Root of data repository.
        calib : `str`
            Name of output calibration directory.
        rerun : `str`
            Name of rerun.
        processes : `int`
            Number of processes to use.
        devel : `bool`
            Run commands in the development mode (no versioning).
        allowErrors : `bool`
            Allow processing errors to be non-fatal?
        """
        for g in self.groups:
            command = [
                self.commandName,
                dataDir,
                f"--calib={calib}",
                f"--rerun={rerun}",
                "--longlog=1",
                f"-j{processes}",
            ]

            if not allowErrors:
                command += ["--doraise"]

            command += getDevelopmentOptions() if devel else []
            command += g.flatSource.getCommandLine(key="flatId")
            command += g.arcSource.getCommandLine(key="arcId")
            command += g.config.getCommandLine()

            print(f"{shellCommand(command)}", file=fout)

    @property
    def outputSubdir(self) -> str:
        """Name of subdirectory where calibs are output (`str`, read-only)

        Output files are expected to be under
        ``rerun/RERUNNAME/{self.outputSubdir}``.
        """
        return "DETECTORMAP"

    @property
    def doOverwrite(self) -> bool:
        """Always overwrite old calibs? (`bool`, read-only)

        ``self.ingest()`` ignores its `overwrite` argument if this is True.
        """
        return True


@export
class FiberProfilesSource(
    CalibSource,
    typeName="fiberProfiles",
    commandName="reduceProfiles.py",
    isBatchPoolTask=False,
):
    """Sources to construct a type of calib.
    The concrete type of the calib is defined by subclasses.

    Parameters
    ----------
    config : `CommandConfig`
        Configurations used in constructing this calib.
    source : `SourceFilter`
        Sources for this calib.
    validity : `int`
        Valid days of the resulting calib.
    normSource: `SourceFilter`
        Sources passed to `--normId`.
    """

    __slots__ = ["normSource"]

    def __init__(
        self,
        config: CommandConfig,
        source: SourceFilter,
        validity: int,
        normSource: SourceFilter,
    ):
        super().__init__(config, source, validity)
        self.normSource = normSource

    @classmethod
    def _fromYamlAdditionalFields(cls, yamlBlock: Mapping[str, Any]) -> Dict[str, Any]:
        """Construct additional members of ``FiberProfilesSource`` from a YAML block.

        Parameters
        ----------
        yamlBlock : `Mapping[str, Any]`
            A block of a YAML data structure. It must have this member:

            ``"normId"``
                A string like ``"field=FLAT"``, or
                a list of str like ``["field=FLAT", "dateObs=2000-01-01"]``

        Returns
        -------
        members : `Dict[str, Any]`
            Additional members of ``FiberProfilesSource``.
        """
        return {
            "normSource": SourceFilter.fromYaml(yamlBlock, remove=True, key="normId")
        }

    def _getAdditionalCommandLineArgs(self) -> List[str]:
        """Get additional command line arguments.

        Returns
        -------
        args : `List[str]`
            Additional command line arguments.
        """
        return self.normSource.getCommandLine(key="normId")


@export
class DetectorMapSource(
    CalibSource, typeName="detectorMap", commandName="reduceArc.py"
):
    def execute(
        self,
        fout: TextIO,
        dataDir: str,
        calib: str,
        rerun: str,
        *,
        processes: int = 1,
        devel: bool = False,
        allowErrors: bool = False,
    ):
        """Put to ``fout`` commands to construct this calib from its source.

        Parameters
        ----------
        fout : `TextIO`
            Output file where to write the command.
        dataDir : `str`
            Root of data repository.
        calib : `str`
            Name of output calibration directory.
        rerun : `str`
            Name of rerun.
        processes : `int`
            Number of processes to use.
        devel : `bool`
            Run commands in the development mode (no versioning).
        allowErrors : `bool`
            Allow processing errors to be non-fatal?
        """
        command = [
            self.commandName,
            dataDir,
            f"--calib={calib}",
            f"--rerun={rerun}",
            "--longlog=1",
            f"-j{processes}",
        ]

        if not allowErrors:
            command += ["--doraise"]

        command += getDevelopmentOptions() if devel else []
        command += self.source.getCommandLine()
        command += self.config.getCommandLine()

        print(f"{shellCommand(command)}", file=fout)

    @property
    def doOverwrite(self) -> bool:
        """Always overwrite old calibs? (`bool`, read-only)

        ``self.ingest()`` ignores its `overwrite` argument if this is True.
        """
        return True


@export
class CalibBlock:
    """A collection of CalibSources.

    Parameters
    ----------
    name : `str`
        Name of this block.
    sources : `Mapping[str, CalibSource]`
        Mapping from calib types to CalibSources.
        For each (key, value), key should be ``value.typeName``.
    """

    # This class member defines the order of execution.
    # It may be able to be generated from CalibSource.__subclasses,
    # but the order of subclass definitions would be significant
    # if it were to be autogenerated.
    calibTypes = ["bias", "dark", "flat", "bootstrap", "fiberProfiles", "detectorMap"]

    def __init__(self, name: str, sources: Mapping[str, CalibSource]):
        self.name = name
        self.sources = dict(sources)

    @classmethod
    def fromYaml(cls, yamlBlock: Mapping[str, Any]) -> "CalibBlock":
        """Construct ``CalibBlock`` from a YAML block.

        Parameters
        ----------
        yamlBlock : `Mapping[str, Any]`
            A block of a YAML data structure:
            This has to be a mapping from calib types to CalibSources
            with a special key "name", which defines the name of this block.
            For example:
                name: "myblock"
                bias:
                    id: "visit=0..4"
                    config: ["key=value", "key=value"]
                dark:
                    id: ["field=DARK", "dateObs=2000-01-01"]
                    configfile: "config.py"

        Returns
        -------
        calibBlock : `CalibBlock`
            Constructed ``CalibBlock`` instance.
        """
        yamlBlock = dict(yamlBlock)

        name = yamlBlock.pop("name", None)
        if name is None:
            raise RuntimeError(f'{cls.__name__} must have "name" key.')

        try:
            sources = {
                typeName: CalibSource.getSubclass(typeName).fromYaml(
                    ensureInstance(block, dict)
                )
                for typeName, block in yamlBlock.items()
                if typeName != "name"
            }
        except Exception as e:
            exceptionAddInfo(e, f"context: {cls.__name__}:{name}")
            raise

        return cls(name, sources)

    def execute(
        self,
        logger: lsst.log.Log,
        fout: TextIO,
        dataDir: str,
        calib: str,
        rerun: str,
        copyMode: str,
        calibTypes: Iterable[str] = [],
        *,
        processes: int = 1,
        clean: bool = False,
        devel: bool = False,
        overwrite: bool = False,
        allowErrors: bool = False,
    ):
        """Put to ``fout`` commands to construct and ingest calibs.

        Parameters
        ----------
        logger : `lsst.log.Log`
            Logger.
        fout : `TextIO`
            Output file where to write the command.
        dataDir : `str`
            Root of data repository.
        calib : `str`
            Name of output calibration directory.
        rerun : `str`
            Name of rerun to use.
        copyMode : `str`
            How to move files into calibration directory.
        calibTypes : `Iterable[str]`
            Types of calibs to process.
            If this is empty, all calibs are processed.
        processes : `int`
            Number of processes to use.
        clean : `bool`
            Clean up byproducts after ingesting calibs.
        devel : `bool`
            Run commands in the development mode (no versioning).
        overwrite : `bool`
            Overwrite old calibs on ingestion.
        allowErrors : `bool`
            Allow processing errors to be non-fatal?
        """
        calibTypes = set(calibTypes)
        if calibTypes:
            # sort calibTypes according to self.calibTypes
            calibTypes = [
                typeName for typeName in self.calibTypes if typeName in calibTypes
            ]
        else:
            calibTypes = self.calibTypes

        logger.info("Processing calib block '%s'", self.name)
        for typeName in calibTypes:
            if typeName in self.sources:
                self.sources[typeName].execute(
                    fout,
                    dataDir,
                    calib,
                    f"{rerun}/{self.name}/{typeName}",
                    processes=processes,
                    devel=devel,
                    allowErrors=allowErrors,
                )
                self.sources[typeName].ingest(
                    fout,
                    dataDir,
                    calib,
                    f"{rerun}/{self.name}/{typeName}",
                    copyMode,
                    overwrite=overwrite,
                )
                if clean:
                    self.sources[typeName].clean(
                        fout, dataDir, f"{rerun}/{self.name}/{typeName}"
                    )


@export
class ScienceStep:
    """A step of analysis pipeline.
    The concrete command for the step is defined by subclasses.

    Parameters
    ----------
    config : `CommandConfig`
        Configurations used in running this step.

    Notes
    -----
    To make a subclass, ``typeName``` and ``commandName`` are required:

        class ReduceExposureStep(
                ScienceStep,
                typeName="reduceExposure",
                commandName="reduceExposure.py"):
            pass

    ``typeName``
        Name of the science step. This is the name used in YAML files.
    ``commandName``
        Name of the command that is actually called.
    """

    __slots__ = ["config"]

    # This property may be replaced by __subclasses__() once it is documented.
    __subclasses: Dict[str, type] = {}

    def __init__(self, config: CommandConfig):
        self.config = config

    def __init_subclass__(cls, *, typeName: str, commandName: str, **kwargs):
        super().__init_subclass__(**kwargs)
        ScienceStep.__subclasses[typeName] = cls
        cls.typeName = typeName
        cls.commandName = commandName

    @classmethod
    def fromYaml(cls, yamlBlock: Mapping[str, Any]) -> "ScienceStep":
        """Construct ``ScienceStep`` from a YAML block.

        Parameters
        ----------
        yamlBlock : `Mapping[str, Any]`
            A block of a YAML data structure:

            ``"config"``
                A config string, or a list of config strings.
            ``"configfile"``
                Path to a configuration file

        Returns
        -------
        scienceStep : `ScienceStep`
        """
        yamlBlock = dict(yamlBlock)

        config = CommandConfig.fromYaml(yamlBlock, remove=True)

        if yamlBlock:
            raise RuntimeError(
                f"Invalid keys for {cls.__name__}: {list(yamlBlock.keys())}"
            )

        return cls(config)

    @staticmethod
    def getSubclass(typeName: str) -> Type["ScienceStep"]:
        """Get a subclass by ``typeName``.

        Parameters
        ----------
        typeName : `str`
            ``typeName`` of the subclass.

        Returns
        -------
        subclass : type
            The class object of the subclass.
        """
        return ScienceStep.__subclasses[typeName]

    def execute(
        self,
        fout: TextIO,
        source: SourceFilter,
        dataDir: str,
        calib: str,
        rerun: str,
        *,
        processes: int = 1,
        devel: bool = False,
        allowErrors: bool = False,
    ):
        """Put to ``fout`` commands for this step.

        Parameters
        ----------
        fout : `TextIO`
            Output file where to write the command.
        source : `SourceFilter`
            Sources that go through the pipeline.
        dataDir : `str`
            Root of data repository.
        calib : `str`
            Name of output calibration directory.
        rerun : `str`
            Name of rerun.
        processes : `int`
            Number of processes to use.
        devel : `bool`
            Run commands in the development mode (no versioning).
        allowErrors : `bool`
            Allow processing errors to be non-fatal?
        """
        command = [
            self.commandName,
            dataDir,
            f"--calib={calib}",
            f"--rerun={rerun}",
            "--longlog=1",
            f"-j{processes}",
        ]

        if not allowErrors:
            command += ["--doraise"]

        command += getDevelopmentOptions() if devel else []
        command += source.getCommandLine()
        command += self.config.getCommandLine()

        print(f"{shellCommand(command)}", file=fout)


@export
class ReduceExposureStep(
    ScienceStep, typeName="reduceExposure", commandName="reduceExposure.py"
):
    pass


@export
class MergeArmsStep(ScienceStep, typeName="mergeArms", commandName="mergeArms.py"):
    pass


@export
class CalculateReferenceFluxStep(
    ScienceStep,
    typeName="calculateReferenceFlux",
    commandName="calculateReferenceFlux.py",
):
    pass


@export
class FluxCalibrateStep(
    ScienceStep, typeName="fluxCalibrate", commandName="fluxCalibrate.py"
):
    pass


@export
class CoaddSpectraStep(
    ScienceStep, typeName="coaddSpectra", commandName="coaddSpectra.py"
):
    pass


@export
class ScienceBlock:
    """A collection of science analyses,
    consisting of input data and a sequence of analysis steps
    applied to the input data.

    Parameters
    ----------
    name : `str`
        Name of this block.
    source : `SourceFilter`
        Sources that go through the pipeline.
    policies : `Mapping[str, ScienceStep]`
        Configurations for analysis steps.
        For each (key, value), key should be ``value.typeName``.
        Steps not found in this mapping will be executed
        with the default config (which means this argument can be ``{}``.)
    """

    # This class member defines the order of execution.
    # It may be able to be generated from ScienceStep.__subclasses
    # but the order of subclass definitions would be significant
    # if it were to be autogenerated.
    steps = [
        "reduceExposure",
        "mergeArms",
        "calculateReferenceFlux",
        "fluxCalibrate",
        "coaddSpectra",
    ]

    def __init__(
        self, name: str, source: SourceFilter, policies: Mapping[str, ScienceStep]
    ):
        self.name = name
        self.source = source

        self.policies = {}
        for step in self.steps:
            policy = policies.get(step)
            if policy is None:
                policy = ScienceStep.getSubclass(step).fromYaml({})
            self.policies[step] = policy

    @classmethod
    def fromYaml(cls, yamlBlock: Mapping[str, Any]) -> "ScienceBlock":
        """Construct ``ScienceBlock`` from a YAML block.

        Parameters
        ----------
        yamlBlock : `Mapping[str, Any]`
            A block of a YAML data structure:

            ``"name"``
                The name of this block.
            ``"id"``
                A string like ``"visit=1..100"``, or
                a list of str like ``["field=OBJECT", "dateObs=2000-01-01"]``
            ``"policy"``
                Configurations for analysis steps.
                This field, if exists, has to be
                a mapping from step names to configs. For example:

                    policy:
                        reduceExposure:
                            config: ["key=value", "key=value"]
                        mergeArms:
                            configfile: "config.py"

                Available keys for the configs are:

                ``"config"``
                    A config string, or a list of config strings.
                ``"configfile"``
                    Path to a configuration file

        Returns
        -------
        scienceBlock : `ScienceBlock`
            Constructed ``ScienceBlock`` instance.
        """
        yamlBlock = dict(yamlBlock)

        name = yamlBlock.pop("name", None)
        if name is None:
            raise RuntimeError(f'{cls.__name__} must have "name" key.')

        try:
            source = SourceFilter.fromYaml(yamlBlock, remove=True)
            policies = {
                step: ScienceStep.getSubclass(step).fromYaml(
                    ensureInstance(block, dict)
                )
                for step, block in ensureInstance(
                    yamlBlock.pop("policy", {}), dict
                ).items()
            }

            if yamlBlock:
                raise RuntimeError(
                    f"Invalid keys for {cls.__name__}: {list(yamlBlock.keys())}"
                )
        except Exception as e:
            exceptionAddInfo(e, f"context: {cls.__name__}:{name}")
            raise

        return cls(name, source, policies)

    def execute(
        self,
        logger: lsst.log.Log,
        fout: TextIO,
        dataDir: str,
        calib: str,
        rerun: str,
        steps: Iterable[str] = [],
        *,
        processes: int = 1,
        devel: bool = False,
        allowErrors: bool = False,
    ):
        """Put to ``fout`` commands to execute this block.

        Parameters
        ----------
        logger : `lsst.log.Log`
            Logger.
        fout : `TextIO`
            Output file where to write the command.
        dataDir : `str`
            Root of data repository.
        calib : `str`
            Name of output calibration directory.
        rerun : `str`
            Name of rerun.
        steps : `Iterable[str]`
            Steps to execute. (e.g. ["reduceExposure", "mergeArms", ...])
            If this is empty, all steps are executed.
        processes : `int`
            Number of processes to use.
        devel : `bool`
            Run commands in the development mode (no versioning).
        allowErrors : `bool`
            Allow processing errors to be non-fatal?
        """
        steps = set(steps)
        if steps:
            # sort steps according to self.steps
            steps = [step for step in self.steps if step in steps]
        else:
            steps = self.steps

        logger.info("Processing science block '%s'", self.name)

        for step in steps:
            self.policies[step].execute(
                fout,
                self.source,
                dataDir,
                calib,
                f"{rerun}/pipeline",
                processes=processes,
                devel=devel,
                allowErrors=allowErrors,
            )


def getDevelopmentOptions() -> List[str]:
    """Get command line options for the development mode (no versioning).

    Returns
    -------
    options : `List[str]`
    """
    return ["--no-versions", "--clobber-config"]


@export
def processYaml(
    yamlFile: str,
) -> Tuple[InitSource, Dict[str, CalibBlock], Dict[str, ScienceBlock]]:
    """Process a YAML file defining a data processing.

    Parameters
    ----------
    yamlFile : `str`
        Path to a YAML file.

    Returns
    -------
    initSource : `InitSource`
        Initial calibs.
    calibBlocks : `Dict[str, CalibBlock]`
        Mapping from block names to CalibBlock.
    scienceBlocks : `Dict[str, ScienceBlock]`
        Mapping from block names to ScienceBlock.
    """
    with open(yamlFile) as fd:
        content = ensureInstance(yaml.load(fd, Loader=yaml.CSafeLoader), dict)

    init = content.pop("init", None)
    if init is None:
        initSource = None
    else:
        initSource = InitSource.fromYaml(ensureInstance(init, dict))

    calibBlocks = {}
    for yamlBlock in ensureInstance(content.pop("calibBlock", []), list):
        block = CalibBlock.fromYaml(ensureInstance(yamlBlock, dict))
        calibBlocks[block.name] = block

    scienceBlocks = {}
    for yamlBlock in ensureInstance(content.pop("scienceBlock", []), list):
        block = ScienceBlock.fromYaml(ensureInstance(yamlBlock, dict))
        scienceBlocks[block.name] = block

    if content:
        raise RuntimeError(f"Invalid global keys in {yamlFile}: {list(content.keys())}")

    return initSource, calibBlocks, scienceBlocks


def shellCommand(argv: Iterable[Any]) -> str:
    """Create a command line string.

    Each element of ``argv`` will be converted to str,
    quoted if necessary,
    and concatenated by a space.

    Parameters
    ----------
    argv : `Iterable[Any]`
        List of arguments for a command, including the command itself.

    Returns
    -------
    commandline : `str`
    """
    return " ".join(shlex.quote(str(x)) for x in argv)


def unique(seq: Iterable[Any]) -> List[Any]:
    """Remove duplicate elements in ``seq`` .

    This is almost equivalent to ``list(set(seq))`` ,
    but the order of the elements will be retained.

    Parameters
    ----------
    seq : `Iterable[Any]`
        Any sequence.

    Returns
    -------
    list : `List[Any]`
        ``seq`` with duplicate elements removed.
    """
    ret = []
    found = set()

    for x in seq:
        if x not in found:
            ret.append(x)
            found.add(x)

    return ret


def ensureInstance(instance: Any, types: Union[type, Collection[type]]) -> Any:
    """Ensure that ``instance`` is an instance of one of ``types``.

    Parameters
    ----------
    instance : `Any`
        An instance to test.
    types : `Union[type, Collection[type]]`
        A type or a list of types.

    Raises
    ------
    TypeError
        Raised if ``instance`` is not an instance of one of ``types``.

    Returns
    -------
    instance : `Any`
        The same object as the argument.
    """
    if not isinstance(instance, types):
        if isinstance(types, collections.abc.Collection):
            typename = f"one of {', '.join(f'`{t.__name__}`' for t in types)}"
        else:
            typename = f"`{types.__name__}`"

        value = str(instance)
        if len(value) > 50:
            value = value[:47] + "..."

        raise TypeError(
            f"illegal type (must be {typename}): `{type(instance).__name__}` (value: '{value}')"
        )

    return instance


def ensureKeyEqValue(s: str) -> str:
    """Ensure that ``s`` is in ``key=value`` format.
    If not, raise ValueError.

    This function is intended to be used for checking arguments of
    a command line option that takes multiple arguments,
    such as ``field=BIAS`` of ``--id field=BIAS``.
    So, a key that starts with a dash (like ``-key=value``) is not permitted
    because it would be interpreted as another option.

    Parameters
    ----------
    s : `str`
        A string to test.

    Raises
    ------
    ValueError
        Raised if ``s`` does not match ``key=value``.

    Returns
    -------
    s : `str`
        The same string as is given.
    """
    if not re.match(r"^[^=\-][^=]*=", s):
        raise ValueError(f"illegal string that has to be 'key=value': '{s}'")

    return s


def exceptionAddInfo(exception: Exception, info: str):
    """Add information to an exception object.

    The information is appended to the first argument of the exception object
    if the argument is a string. Otherwise, the information is appended to
    the argument list of the exception object.

    Parameters
    ----------
    exception : `Exception`
        Exception object to modify.
    info : `str`
        Information to add to `exception`
    """
    if exception.args and isinstance(exception.args[0], str):
        exception.args = (f"{exception.args[0]} [{info}]",) + exception.args[1:]
    else:
        exception.args += (info,)


@contextlib.contextmanager
def makeFileobj(name: Union[str, TextIO], *args, **kwargs):
    """Open a file if ``name`` is not a file object.

    This context manager opens a file if ``name`` is not a file object.
    Otherwise, it just returns ``name`` (which is already a file object).
    On the context being exitted, the file object is closed if it has been
    opened by this context manager. Otherwise, it is not closed.

    Parameters
    ----------
    name : `Union[str, TextIO]`
        name of a file, or a file object.
    args : `List`
        passed to `open()`
    kwargs : `Dict`
        passed to `open()`

    Returns
    -------
    contextManager
    """
    needsOpening = not (hasattr(name, "read") or hasattr(name, "write"))
    if needsOpening:
        fileobj = open(name, *args, **kwargs)
    else:
        fileobj = name

    try:
        yield fileobj
    finally:
        if needsOpening:
            fileobj.close()


@export
def generateCommands(
    *,
    logger: lsst.log.Log,
    dataDir: str,
    specFile: str,
    init: bool = False,
    blocks: Iterable[str] = [],
    calib: Optional[str] = None,
    calibTypes: Iterable[str] = [],
    clean: bool = False,
    devel: bool = False,
    copyMode: str = "copy",
    force: bool = False,
    processes: int = 1,
    output: Union[str, TextIO] = "a.sh",
    overwriteCalib: bool = False,
    rerun: str = "noname",
    scienceSteps: Iterable[str] = [],
    allowErrors: bool = False,
):
    """Generate shell commands according to ``specFile``

    Parameters
    ----------
    logger : `lsst.log.Log`
        Logger.
    dataDir : `str`
        Root of data repository.
    specFile : `str`
        Name of file specifying the work.
    init : `bool`
        Install initial calibs.
    blocks : `Iterable[str]`
        Blocks to execute.
        If this is empty, all blocks are executed.
    calib : `Optional[str]`
        Name of output calibration directory. (default: ``dataDir``/CALIB)
    calibTypes : `Iterable[str]`
        Types of calibs to process.
        If this is empty, all calibs are processed.
    clean : `bool`
        Clean up byproducts after ingesting calibs.
    copyMode : `str`
        How to move files into calibration directory.
    devel : `bool`
        Run commands in the development mode (no versioning).
    force : `bool`
        Continue in the face of problems.
    processes : `int`
        Number of processes to use.
    output : `Union[str, TextIO]`
        Path to output file.
    overwriteCalib : `bool`
        Overwrite old calibs on ingestion.
    rerun : `str`
        Name of rerun to use.
    scienceSteps : `Iterable[str]`
        pipeline steps to execute.
        If this is empty, all steps are executed.
    allowErrors : `bool`, optional
        Allow processing errors to be non-fatal?
    """
    if clean and copyMode == "link":
        raise ValueError("When `copyMode`=link, `clean` must not be True.")

    logger = logger.getChild("generateCommands")

    dataDir = os.path.abspath(dataDir)
    if not os.path.exists(dataDir):
        if force:
            logger.warning("'%s' doesn't exist", dataDir)
        else:
            raise RuntimeError(f"'{dataDir}' doesn't exist")

    if calib is None:
        calib = os.path.join(dataDir, "CALIB")
    else:
        calib = os.path.abspath(calib)

    if not init and not os.path.exists(calib):
        if force:
            logger.warning(
                "'%s' doesn't exist"
                " (To start without this directory, use `init` option)",
                calib,
            )
        else:
            raise RuntimeError(
                f"'{calib}' doesn't exist"
                " (To start without this directory, use `init` option)"
            )

    initSource, calibBlocks, scienceBlocks = processYaml(specFile)
    possibleBlocks = unique(list(calibBlocks.keys()) + list(scienceBlocks.keys()))
    if blocks is None:
        blocks = possibleBlocks

    unrecognisedBlocks = set(blocks) - set(possibleBlocks)
    if unrecognisedBlocks:
        if force:
            logger.warning("Unrecognised blocks: %s", str(list(unrecognisedBlocks)))
        logger.info(
            "Some blocks are not recognised. Possible blocks are %s",
            str(list(possibleBlocks)),
        )
        if not force:
            raise RuntimeError(f"Unrecognised blocks: '{list(unrecognisedBlocks)}'")

    with makeFileobj(output, "w") as fout:
        logger.info(
            "Start writing shell commands on '%s'", getattr(fout, "name", "(fileobj)")
        )

        print("#!/bin/sh", file=fout)
        setopts = "ux"
        if not allowErrors:
            setopts += "e"
        print(f"set -{setopts}", file=fout)

        if init:
            if initSource is None:
                raise RuntimeError("No 'init' block to execute")
            initSource.execute(logger, fout, dataDir, calib, allowErrors=allowErrors)

        for blockName in blocks:
            if blockName in calibBlocks:
                calibBlocks[blockName].execute(
                    logger,
                    fout,
                    dataDir,
                    calib,
                    rerun,
                    copyMode,
                    calibTypes=calibTypes,
                    processes=processes,
                    clean=clean,
                    devel=devel,
                    overwrite=overwriteCalib,
                    allowErrors=allowErrors,
                )

        for blockName in blocks:
            if blockName in scienceBlocks:
                scienceBlocks[blockName].execute(
                    logger,
                    fout,
                    dataDir,
                    calib,
                    rerun,
                    steps=scienceSteps,
                    processes=processes,
                    devel=devel,
                    allowErrors=allowErrors,
                )

        logger.info(
            "End writing shell commands on '%s'", getattr(fout, "name", "(fileobj)")
        )

    os.chmod(output, os.stat(output).st_mode | stat.S_IXUSR | stat.S_IXGRP)
