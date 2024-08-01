import argparse
import dataclasses
import difflib
import glob
import os
import re
import shlex
import string
import sys
import textwrap


from collections.abc import Callable, Sequence
from typing import (
    Any,
    Generic,
    Literal,
    Protocol,
    Type,
    TypedDict,
    TypeVar,
    cast,
    get_args,
)

import yaml


__all__ = ["main"]


class ConstructibleFromStr(Protocol):
    """Class with a constructor that takes a string."""

    def __init__(self, s: str) -> None:
        ...


TConstructibleFromStr = TypeVar("TConstructibleFromStr", bound=ConstructibleFromStr)
UConstructibleFromStr = TypeVar("UConstructibleFromStr", bound=ConstructibleFromStr)


class CommaSeparatedListArgParseAction(argparse.Action):
    """Subclass of `argparse.Action` that deals with a comma-separated list.

    ``--option a,b --option c`` will result in ``args.option = ["a", "b", "c"]``.

    Parameters
    ----------
    option_strings : `list` [ `str` ]
        Options strings.
    dest : `str`
        Destination variable name.
    elemType : `Callable` [[ `str` ], `Any` ]
        Element type.
    elemMetaVar : `str`
        Metavar for a single element.
    separator : `str`
        Separator (default: ",")
    **kwargs
        Other arguments passed to ``parser.add_argument()``
    """

    def __init__(
        self,
        option_strings: list[str],
        dest: str,
        elemType: Callable[[str], Any] = str,
        elemMetaVar: str = "",
        separator: str = ",",
        **kwargs,
    ) -> None:
        if not elemMetaVar:
            elemMetaVar = dest.upper()
        kwargs.setdefault("metavar", f"{elemMetaVar}[{separator}...]")
        kwargs.setdefault("default", [])
        super().__init__(option_strings, dest, **kwargs)

        self.elemType = elemType
        self.separator = separator

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: str | Sequence[Any] | None,
        option_string: str | None = None,
    ) -> None:
        """Handle an option.

        Parameters
        ----------
        parser : `argparse.ArgumentParser`
            Argument parser that owns this action.
        namespace : `argparse.Namespace`
            Namespace in which variables are stored.
        values : `str` | `Sequence` [ `Any` ] | `None`
            Argument of this option.
        option_string : `str` | `None`
            Option name.
        """
        valuelist = [self.elemType(x) for x in cast(str, values).split(self.separator)]
        dest = getattr(namespace, self.dest, None)
        if dest is not None:
            dest.extend(valuelist)
        else:
            setattr(namespace, self.dest, valuelist)


class Pipe2DConfigDict(TypedDict):
    """Configurations of ``pipe2d`` command.

    Parameters
    ----------
    butler_config : `str`
        Default value of --butler-config
    pipelines : `list` [ `str` ]
        Paths to pipelines with wildcards
    inputs : `list` [ `str` ]
        Collections appended to user-given inputs
    rerun : `str`
        Default output collection (of RUN-type)
    options : `list` [ `str` ]
        Other options passed to ``pipetask``
    """

    butler_config: str
    pipelines: list[str]
    inputs: list[str]
    rerun: str
    options: list[str]


SpecialCommand = Literal[
    ":install-config",
    ":show-config-path",
    ":show-pipelines",
    ":show-commands",  # alias for :show-pipelines
]


specialCommandDocs: dict[SpecialCommand, str] = {
    ":install-config": "Install a config file in the home directory.",
    ":show-config-path": "Show the path to the config file.",
    ":show-pipelines": "Show pipelines and commands.",
    ":show-commands": "Show pipelines and commands. (Alias for :show-pipelines)",
}


class SourceSelector(Generic[TConstructibleFromStr]):
    """Source selector.

    This class parses strings like ``0..4:2``. (start..stop:step)
    ``step`` may exist only when the dimension type is `int`.

    Parameters
    ----------
    parsee : `str`
        String to be parsed.
    name : `str`
        Dimension name.
    dimtype : `Type` [ `TConstructibleFromStr` ]
        Dimension type.
    """

    name: str
    dimtype: Type[TConstructibleFromStr]
    start: TConstructibleFromStr
    stop: TConstructibleFromStr | None
    step: int | None

    def __init__(
        self, parsee: str, name: str, dimtype: Type[TConstructibleFromStr]
    ) -> None:
        if not re.fullmatch(
            r"[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*", name
        ):
            raise ValueError(f"Invalid name of an identifier: '{name}'")

        if issubclass(dimtype, int):
            regex = r"""
            (?P<start>([^.:]+|\.[^.:])*+\.?)
            (
                \.\.
                (?P<stop>([^.:]+|\.[^.:])*+\.?)
                (
                    :
                    (?P<step>([^.:]+|\.[^.:])*+\.?)
                )?
            )?
            """
            syntax = r"start[..stop[:step]]"
        else:
            regex = r"""
            (?P<start>([^.:]+|\.[^.:])*+\.?)
            (
                \.\.
                (?P<stop>([^.:]+|\.[^.:])*+\.?)
            )?
            """
            syntax = r"start[..stop]"

        m = re.fullmatch(regex, parsee, flags=re.VERBOSE)
        if not m:
            raise ValueError(f"'{parsee}' does not match '{syntax}'")

        groups = m.groupdict()

        start = dimtype(groups["start"])

        stop_s = groups.get("stop")
        if stop_s is not None:
            stop = dimtype(stop_s)
        else:
            stop = None

        step_s = groups.get("step")
        if step_s is not None:
            step = int(step_s)
            if not step:
                raise ValueError(f"Step must not be zero: '{parsee}'")
        else:
            step = None

        self.name = name
        self.dimtype = dimtype
        self.start = start
        self.stop = stop
        self.step = step

    def __str__(self) -> str:
        """Stringify the selector.

        This function returns an SQL expression.

        Returns
        -------
        expression : `str`
            SQL expression corresponding to the selector.
        """
        if self.step is not None:  # implies `self.dimtype is int`
            if self.step == 1:
                return f"{self.start} <= {self.name} AND {self.name} <= {self.stop}"
            elif self.step == -1:
                return f"{self.stop} <= {self.name} AND {self.name} <= {self.start}"
            else:
                onePast = 1 if self.step >= 0 else -1
                seq = ",".join(
                    f"{x}"
                    for x in range(
                        cast(int, self.start),
                        onePast + cast(int, self.stop),
                        cast(int, self.step),
                    )
                )
                return f"{self.name} IN ({seq})"

        if self.stop is not None:
            if issubclass(self.dimtype, str):
                return (
                    f"{sqlQuoteLiteral(cast(str, self.start))} <= {self.name}"
                    f" AND {self.name} <= {sqlQuoteLiteral(cast(str, self.stop))}"
                )
            else:
                return f"{self.start} <= {self.name} AND {self.name} <= {self.stop}"
        else:
            if issubclass(self.dimtype, str):
                return f"{self.name} = {sqlQuoteLiteral(cast(str, self.start))}"
            else:
                return f"{self.name} = {self.start}"

    def __repr__(self) -> str:
        return self.__str__()

    @staticmethod
    def getConvertingConstructor(
        name: str, dimtype: Type[UConstructibleFromStr]
    ) -> Callable[[str], "SourceSelector[UConstructibleFromStr]"]:
        """Get a converting constructor that takes only ``parsee: str``
        as its argument.

        Parameters
        ----------
        name : `str`
            Dimension name.
        dimtype : `Type` [ `UConstructibleFromStr` ]
            Dimension type.

        Returns
        -------
        ctr : `Callable` [[ `str` ], `SourceSelector` [ `UConstructibleFromStr` ]]
            Constructor that takes only ``parsee: str`` as its argument.
        """
        return lambda parsee: SourceSelector[UConstructibleFromStr](
            parsee, name, dimtype
        )


@dataclasses.dataclass
class QueryDimension:
    """Dimension available in data-querying.

    Parameters
    ----------
    name : `str`
        Name of the dimension. "instrument", "detector", "visit", etc.
    dimtype : `type`
        Type of the dimension. int, str, etc.
    doc : `str`
        Document text for the dimension.
    """

    name: str
    dimtype: type
    doc: str

    @staticmethod
    def getList() -> list["QueryDimension"]:
        """Get all available dimensions.

        Returns
        -------
        dimensions : `list` [ `QueryDimension` ]
        """
        # The body of this function is the output of this command:
        # python3 -c "from pfs.pipe2d.pipe2d import QueryDimension as D; \
        #   D.printBodyOfGetListMethod('$REPO/gen3.sqlite3')"

        return [
            QueryDimension(
                name="arm",
                dimtype=str,
                doc=r"""
                An arm within a particular PFS instrument [brnm] Note that this
                does not include the spectrograph, which is included separately.
                """,
            ),
            QueryDimension(
                name="detector",
                dimtype=int,
                doc=r"""
                A detector associated with a particular instrument (not an
                observation of that detector; that requires specifying an
                exposure or visit as well).
                """,
            ),
            QueryDimension(
                name="detector.full_name",
                dimtype=str,
                doc=r"""
                Another key for --detector.
                """,
            ),
            QueryDimension(
                name="detector.name_in_raft",
                dimtype=str,
                doc=r"""
                """,
            ),
            QueryDimension(
                name="detector.purpose",
                dimtype=str,
                doc=r"""
                Role of the detector; typically one of "SCIENCE", "WAVEFRONT",
                or "GUIDE", though instruments may define additional values.
                """,
            ),
            QueryDimension(
                name="detector.raft",
                dimtype=str,
                doc=r"""
                A string name for a group of detectors with an instrument-
                dependent interpretation.
                """,
            ),
            QueryDimension(
                name="dither",
                dimtype=float,
                doc=r"""
                A slit offset in the spatial dimension. Used in fiberFlat
                construction, where we want to iterate over exposures with the
                same dither setting.
                """,
            ),
            QueryDimension(
                name="exposure",
                dimtype=int,
                doc=r"""
                An observation associated with a particular instrument.  All
                direct observations are identified with an exposure, but derived
                datasets that may be based on more than one exposure (e.g.
                multiple snaps) are typically identified with visits instead,
                even for instruments that don't have multiple exposures per
                visit.  As a result, instruments that don't have multiple
                exposures per visit will typically have visit entries that are
                essentially duplicates of their exposure entries. The exposure
                table contains metadata entries that are relevant for
                calibration exposures, and does not duplicate entries in visit
                that would be the same for all exposures within a visit with the
                exception of the exposure.group entry.
                """,
            ),
            QueryDimension(
                name="exposure.obs_id",
                dimtype=str,
                doc=r"""
                Another key for --exposure.
                """,
            ),
            QueryDimension(
                name="exposure.dark_time",
                dimtype=float,
                doc=r"""
                Duration of the exposure with shutter closed (seconds).
                """,
            ),
            QueryDimension(
                name="exposure.day_obs",
                dimtype=int,
                doc=r"""
                Day of observation as defined by the observatory (YYYYMMDD
                format).
                """,
            ),
            QueryDimension(
                name="exposure.exposure_time",
                dimtype=float,
                doc=r"""
                Duration of the exposure with shutter open (seconds).
                """,
            ),
            QueryDimension(
                name="exposure.group_id",
                dimtype=int,
                doc=r"""
                Integer group identifier associated with this exposure by the
                acquisition system.
                """,
            ),
            QueryDimension(
                name="exposure.group_name",
                dimtype=str,
                doc=r"""
                String group identifier associated with this exposure by the
                acquisition system.
                """,
            ),
            QueryDimension(
                name="exposure.observation_reason",
                dimtype=str,
                doc=r"""
                The reason this observation was taken. (e.g. science, filter
                scan, unknown).
                """,
            ),
            QueryDimension(
                name="exposure.observation_type",
                dimtype=str,
                doc=r"""
                The observation type of this exposure (e.g. dark, bias,
                science).
                """,
            ),
            QueryDimension(
                name="exposure.science_program",
                dimtype=str,
                doc=r"""
                Observing program (survey, proposal, engineering project)
                identifier.
                """,
            ),
            QueryDimension(
                name="exposure.seq_num",
                dimtype=int,
                doc=r"""
                Counter for the observation within a larger sequence. Context of
                the sequence number is observatory specific. Can be a global
                counter or counter within day_obs.
                """,
            ),
            QueryDimension(
                name="exposure.sky_angle",
                dimtype=float,
                doc=r"""
                Angle of the instrument focal plane on the sky in degrees. Can
                be NULL for observations that are not on sky, or for
                observations where the sky angle changes during the observation.
                """,
            ),
            QueryDimension(
                name="exposure.target_name",
                dimtype=str,
                doc=r"""
                Object of interest for this observation or survey field name.
                """,
            ),
            QueryDimension(
                name="exposure.tracking_dec",
                dimtype=float,
                doc=r"""
                Tracking ICRS Declination of boresight in degrees. Can be NULL
                for observations that are not on sky.
                """,
            ),
            QueryDimension(
                name="exposure.tracking_ra",
                dimtype=float,
                doc=r"""
                Tracking ICRS Right Ascension of boresight in degrees. Can be
                NULL for observations that are not on sky.
                """,
            ),
            QueryDimension(
                name="exposure.zenith_angle",
                dimtype=float,
                doc=r"""
                Angle in degrees from the zenith at the start of the exposure.
                """,
            ),
            QueryDimension(
                name="instrument",
                dimtype=str,
                doc=r"""
                An entity that produces observations.  An instrument defines a
                set of physical_filters and detectors and a numbering system for
                the exposures and visits that represent observations with it.
                """,
            ),
            QueryDimension(
                name="patch",
                dimtype=int,
                doc=r"""
                A rectangular region within a tract.
                """,
            ),
            QueryDimension(
                name="patch.cell_x",
                dimtype=int,
                doc=r"""
                Which column this patch occupies in the tract's grid of patches.
                """,
            ),
            QueryDimension(
                name="patch.cell_y",
                dimtype=int,
                doc=r"""
                Which row this patch occupies in the tract's grid of patches.
                """,
            ),
            QueryDimension(
                name="pfs_design_id",
                dimtype=int,
                doc=r"""
                Configuration of the top-end, mapping fibers to targets.
                """,
            ),
            QueryDimension(
                name="skymap",
                dimtype=str,
                doc=r"""
                A set of tracts and patches that subdivide the sky into
                rectangular regions with simple projections and intentional
                overlaps.
                """,
            ),
            QueryDimension(
                name="skymap.hash",
                dimtype=str,
                doc=r"""
                Another key for --skymap.
                """,
            ),
            QueryDimension(
                name="spectrograph",
                dimtype=int,
                doc=r"""
                A PFS spectrograph module within a particular instrument [1-4]
                """,
            ),
            QueryDimension(
                name="tract",
                dimtype=int,
                doc=r"""
                A large rectangular region mapped to the sky with a single map
                projection, associated with a particular skymap.
                """,
            ),
            QueryDimension(
                name="visit",
                dimtype=int,
                doc=r"""
                A sequence of observations processed together, comprised of one
                or more exposures from the same instrument with the same
                pointing and physical_filter. The visit table contains metadata
                that is both meaningful only for science exposures and the same
                for all exposures in a visit.
                """,
            ),
            QueryDimension(
                name="visit.name",
                dimtype=str,
                doc=r"""
                Another key for --visit.
                """,
            ),
            QueryDimension(
                name="visit.day_obs",
                dimtype=int,
                doc=r"""
                Day of observation as defined by the observatory (YYYYMMDD
                format). If a visit crosses multiple days this entry will be the
                earliest day of any of the exposures that make up the visit.
                """,
            ),
            QueryDimension(
                name="visit.exposure_time",
                dimtype=float,
                doc=r"""
                The total exposure time of the visit in seconds.  This should be
                equal to the sum of the exposure_time values for all constituent
                exposures (i.e. it should not include time between exposures).
                """,
            ),
            QueryDimension(
                name="visit.observation_reason",
                dimtype=str,
                doc=r"""
                The reason this visit was taken. (e.g. science, filter scan,
                unknown, various).
                """,
            ),
            QueryDimension(
                name="visit.science_program",
                dimtype=str,
                doc=r"""
                Observing program (survey or proposal) identifier.
                """,
            ),
            QueryDimension(
                name="visit.target_name",
                dimtype=str,
                doc=r"""
                Object of interest for this visit or survey field name.
                """,
            ),
            QueryDimension(
                name="visit.zenith_angle",
                dimtype=float,
                doc=r"""
                Approximate zenith angle in degrees during the visit. Can only
                be approximate since it is continuously changing during and
                observation and multiple visits can be combined from a
                relatively long period.
                """,
            ),
            QueryDimension(
                name="visit_system",
                dimtype=int,
                doc=r"""
                A system of self-consistent visit definitions, within which each
                exposure should appear at most once.
                """,
            ),
            QueryDimension(
                name="visit_system.name",
                dimtype=str,
                doc=r"""
                Another key for --visit-system.
                """,
            ),
        ]

    @staticmethod
    def printBodyOfGetListMethod(
        gen3_sqlite3: str, pipe2d_py: str | None = None
    ) -> None:
        """Print the body of getList() method.

        This method is never called by main() function even indirectly.
        Instead, code maintainers can call this method to get a text that
        should be copied to getList()'s body.

        e.g. python3 -c "from pfs.pipe2d.pipe2d import QueryDimension as D; \
            D.printBodyOfGetListMethod('$REPO/gen3.sqlite3', '$PWD/pipe2d_py')"

        This method requires that the backend database is SQLite,
        as the function parameter implies. (This restriction is the reason why
        this method is never called by main().)

        Parameters
        ----------
        gen3_sqlite3 : `str`
            Path to ``gen3.sqlite3``, which is to be read.
        pipe2d_py : `str` | `None`
            Path to ``pipe2d.py``, which is to be overwritten.
            If this is not given, the function body will be printed to ``stdout``.
        """
        import io
        import json
        import sqlite3

        indent = 4  # number of spaces per indent
        bodyDepth = 2  # indent depth of the printed function body
        lineWidth = 80  # number of letters per line
        docWidth = lineWidth - indent * (2 + bodyDepth)  # line width of documents.

        # Dimensions listed here won't be made command line options.
        unwantedDimensions: list[re.Pattern[str]] = [
            re.compile(regex)
            for regex in [
                r"band(?:\..*)?",
                r"physical_filter(?:\..*)?",
                r"subfilter(?:\..*)?",
                r"instrument\.class_name",
                r"instrument\.detector_max",
                r"instrument\.exposure_max",
                r"instrument\.visit_max",
                r"skymap\.patch_nx_max",
                r"skymap\.patch_ny_max",
                r"skymap\.tract_max",
            ]
        ]

        dimTypes = {
            "float": "float",
            "hash": "str",
            "int": "int",
            "string": "str",
        }

        conn = sqlite3.connect(gen3_sqlite3)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT value from butler_attributes WHERE name = 'config:dimensions.json'"
        )
        [(dimensions_s,)] = cursor

        dimensions = json.loads(dimensions_s)

        # list of (name, type, doc)
        fields: list[tuple[str, str, str]] = []

        for name, property in sorted(dimensions["elements"].items()):
            keys = property.get("keys")
            if not keys:
                continue

            fields.append((name, keys[0]["type"], property.get("doc", "")))

            for key in sorted(keys[1:], key=lambda key: key["name"]):
                fields.append(
                    (
                        f'{name}.{key["name"]}',
                        key["type"],
                        f'Another key for --{name.replace("_", "-")}.',
                    )
                )

            for metadata in sorted(
                property.get("metadata", []), key=lambda dic: dic["name"]
            ):
                fields.append(
                    (
                        f'{name}.{metadata["name"]}',
                        metadata["type"],
                        metadata.get("doc", ""),
                    )
                )

        fields = [
            (name, type, doc)
            for name, type, doc in fields
            if not any(r.fullmatch(name) for r in unwantedDimensions)
        ]

        tempFile = io.StringIO()

        def printLine(line: str, *, depth: int) -> None:
            """Print a line to ``tempFile`` (non-local variable).

            Parameters
            ----------
            line : str
                A line of text.
            depth : int
                indent depth (not including ``bodyDepth``).
            """
            spaces = " " * (indent * (bodyDepth + depth))
            print(spaces + line, file=tempFile)

        printLine("return [", depth=0)

        for fieldname, type, doc in fields:
            docLines = textwrap.wrap(doc.strip(), width=docWidth)

            printLine("QueryDimension(", depth=1)
            printLine(f'name="{fieldname}",', depth=2)
            printLine(f"dimtype={dimTypes[type]},", depth=2)
            printLine('doc=r"""', depth=2)
            for line in docLines:
                printLine(line, depth=2)
            printLine('""",', depth=2)
            printLine("),", depth=1)

        printLine("]", depth=0)

        bodyText = tempFile.getvalue()

        if pipe2d_py is None:
            print(bodyText, end="")
            return

        with open(pipe2d_py, "r") as f:
            entireText = f.read()

        space = r"\ "
        matches = list(
            re.finditer(
                rf'''
                ^{space * (indent * bodyDepth)}return\ \[
                    [\ \n]* QueryDimension\(
                    [\ \n]*     name="[^"\n]*+",
                    [\ \n]*     dimtype=[a-zA-Z_][a-zA-Z0-9_]*+,
                    [\ \n]*     doc=r"""(?:[^"]++|"[^"]++|""[^"]++)*""",?
                    [\ \n]* \)
                    (?:,
                        [\ \n]* QueryDimension\(
                        [\ \n]*     name="[^"\n]*+",
                        [\ \n]*     dimtype=[a-zA-Z_][a-zA-Z0-9_]*+,
                        [\ \n]*     doc=r"""(?:[^"]++|"[^"]++|""[^"]++)*""",?
                        [\ \n]* \)
                    )*
                    ,?
                    [\ \n]*
                \]\n
                ''',
                entireText,
                flags=re.VERBOSE | re.MULTILINE,
            )
        )

        if not matches:
            raise RuntimeError(f"Failed to find a text to replace in '{pipe2d_py}'")

        match = max(matches, key=lambda m: m.end() - m.start())
        entireText = entireText[:match.start()] + bodyText + entireText[match.end():]

        with open(pipe2d_py + "~", "w") as f:
            f.write(entireText)

        os.replace(pipe2d_py + "~", pipe2d_py)


def main() -> None:
    """Entrypoint of the executable ``pipe2d``

    This function might not return.
    If it returns, the caller should exit immediately with EXIT_SUCCESS.
    """
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=textwrap.dedent(
            """\
            This program is a wrapper for `pipetask` command.

            Run `%(prog)s :show-pipelines` to see available pipelines.
            Options not listed below are silently passed to `pipetask`
            (but see `--pass` option.)
            """
        ),
        epilog=textwrap.dedent(
            """\
            environment variables:
              PIPE2D_CONFIG         Path to the config file (`--pipe2d-config`)
            """
        ),
    )
    parser.add_argument(
        "pipeline",
        help="Pipeline name."
        " This argument may be a special command starting with ':', such as ':show-pipelines'",
    )
    parser.add_argument(
        "-b",
        "--butler-config",
        metavar="PATH",
        type=str,
        help="Path to the butler config file",
    )
    parser.add_argument(
        "-d",
        "--data-query",
        metavar="QUERY",
        type=str,
        help="Data selection expression. (Appended to the other query expressions with 'AND' operator.)",
    )
    parser.add_argument(
        "--developer", action="store_true", help="Enable options useful for developers"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Do not actually execute `pipetask`."
    )
    parser.add_argument(
        "-i",
        "--input",
        action=CommaSeparatedListArgParseAction,
        elemMetaVar="COLLECTION",
        help="Input run names, comma-separated.",
    )
    parser.add_argument(
        "--no-default-inputs",
        action="store_true",
        help="Do not append default input collections to the list given by `--input`",
    )
    parser.add_argument(
        "--no-default-options",
        action="store_true",
        help="Do not pass default options (described in the config file) to `pipetask`.",
    )
    parser.add_argument(
        "--pass",
        metavar="ARG",
        dest="passed_args",
        type=str,
        action="append",
        default=[],
        help="Pass ARG to `pipetask`. Use this option to pass pipetask options"
        " hidden by this program: `--pass=--instrument=lsst.obs.pfs.PfsSimulator` for example."
        " (No need to prefix `--pass=` to pipetask options if they are not hidden.)",
    )
    parser.add_argument(
        "--pipe2d-config", metavar="PATH", type=str, help="Path to the config file."
    )
    parser.add_argument(
        "--rerun", metavar="COLLECTION", type=str, help="Output run name."
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Make `pipetask` verbose."
    )

    queryDimensions = QueryDimension.getList()
    for dimension in queryDimensions:
        elemMetaVar = dimension.dimtype.__name__.upper()
        if issubclass(dimension.dimtype, int):
            rangeMetaVar = f"{elemMetaVar}[..{elemMetaVar}[:INT]]"
        else:
            rangeMetaVar = f"{elemMetaVar}[..{elemMetaVar}]"

        parser.add_argument(
            f"--{re.sub('[._]', '-', dimension.name)}",
            action=CommaSeparatedListArgParseAction,
            dest=dimension.name,
            elemType=SourceSelector.getConvertingConstructor(
                dimension.name, dimension.dimtype
            ),
            elemMetaVar=rangeMetaVar,
            separator="^",
            help=dimension.doc,
        )

    args, unknownArgs = parser.parse_known_args()
    if args.pipe2d_config is None:
        # "or None" makes sure that `args.pipe2d_config` won't be "".
        args.pipe2d_config = os.environ.get("PIPE2D_CONFIG") or None

    config = loadConfig(args.pipe2d_config)

    args.pipeline = canonicalizePipelineName(args.pipeline, config["pipelines"])

    if args.pipeline in get_args(SpecialCommand):
        specialCommand = cast(SpecialCommand, args.pipeline)
        if specialCommand == ":install-config":
            return onInstallConfig(args.pipe2d_config)

        if specialCommand == ":show-config-path":
            return onShowConfigPath(args.pipe2d_config)

        if specialCommand == ":show-pipelines" or specialCommand == ":show-commands":
            return onShowPipelines(config["pipelines"])

        print(f"Command '{specialCommand}' is not implemented.")
        sys.exit(1)

    if args.butler_config is None:
        args.butler_config = config["butler_config"]

    if not args.no_default_inputs:
        args.input.extend(config["inputs"])

    if args.rerun is None:
        args.rerun = expandVars(
            config["rerun"], extraVars={"PIPELINE": getBaseFileNameStem(args.pipeline)}
        )

    command = ["pipetask", "run"]

    if not args.no_default_options:
        command.extend(config["options"])

    command += [
        f"--butler-config={args.butler_config}",
        f"--pipeline={args.pipeline}",
        f"--input={','.join(args.input)}",
        f"--output-run={args.rerun}",
    ]

    queries: list[str] = []
    for dimension in queryDimensions:
        selectors = getattr(args, dimension.name)
        if selectors:
            queries.append(sqlAny(selectors))

    if args.data_query is not None:
        queries.append(args.data_query)

    if queries:
        command += [
            f"--data-query={sqlAll(queries)}",
        ]

    if args.developer:
        command += [
            "--pdb",
            "--fail-fast",
            "--clobber-outputs",
            f"--skip-existing-in={args.rerun}",
        ]

    if args.verbose:
        command += [
            "--long-log",
            "--log-level=.=TRACE",
        ]

    command.extend(args.passed_args)
    command.extend(unknownArgs)

    command = reorderPipetaskCommand(command)
    print(f"+ {shlex.join(command)}")

    if args.dry_run:
        return

    sys.stdout.flush()
    sys.stderr.flush()
    os.execvp(command[0], command)


def onInstallConfig(configpath: str | None) -> None:
    """Special command ``:install-config``
    which installs a config file in user's home directory (by default).

    This function is a part of main function. Calling it may result in sys.exit().

    Parameters
    ----------
    configpath : `str` | `None`
        Path to the config file.
    """
    if configpath is None:
        configpath = getDefaultConfigPath()

    configpath = cast(str, configpath)

    try:
        with open(configpath, "x") as f:
            yaml.dump(getDefaultConfig(), f)
    except FileExistsError as e:
        print(f"Config file already exists.: '{e.filename}'")
        print("This program won't overwrite this file.")
        print("If you really want to replace it, remove the file for yourself")
        print("before calling this program.")
        sys.exit(1)

    print(f"Config file was installed: {configpath}")


def onShowConfigPath(configpath: str | None) -> None:
    """Special command ``:show-config-path``
    which prints the path to the config file.

    This function is a part of main function. Calling it may result in sys.exit().

    Parameters
    ----------
    configpath : `str` | `None`
        Path to the config file.
    """
    print(configpath if configpath is not None else getDefaultConfigPath())


def onShowPipelines(candidates: list[str]) -> None:
    """Special command ``:show-pipelines``
    which prints pipelines and special commands.

    This function is a part of main function. Calling it may result in sys.exit().

    Parameters
    ----------
    candidates : `str` | `None`
        Candidates of pipeline. This is a list of paths,
        each possibly including wildcards and environment variables.
    """
    for template in candidates:
        for path in glob.iglob(os.path.expandvars(template)):
            basename = getBaseFileNameStem(path)
            with open(path) as f:
                doc = yaml.load(f, Loader=yaml.SafeLoader).get("description", "")
            print(basename)
            print("=" * len(basename))
            print(doc)
            print()

    for command in get_args(SpecialCommand):
        doc = specialCommandDocs.get(command, "")
        print(command)
        print("=" * len(command))
        print(doc)
        print()


def canonicalizePipelineName(pipeline: str, candidates: list[str]) -> str:
    """Canonicalize a pipeline name.

    (1) If ``pipeline`` is case-insensitively equal to one of SpecialCommand's,
    then the command is returned.
    (2) Otherwise, ``candidates`` is searched for ``pipeline`` case-insensitively.
    (3) If ``pipeline`` is a real file path and it exists,
    then ``pipeline`` is returned.

    In case-insensitive comparison (or, except for case (3)),
    hyphens and underscores are ignored.

    Parameters
    ----------
    pipeline : `str`
        Pipeline name.
    candidates : `list` [ `str` ]
        Candidates of pipeline. This is a list of paths,
        each possibly including wildcards and environment variables.

    Returns
    -------
    pipeline : `str`
        Canonicalized pipeline name.
    """
    key = re.sub(r"[_\-]+", "", pipeline.upper())
    bestCandidates: list[str] = []
    bestScore = len(pipeline)

    for command in get_args(SpecialCommand):
        score = getEditDistance(key, re.sub(r"[_\-]+", "", command.upper()))
        if score == 0:
            return command
        elif score == bestScore:
            bestCandidates.append(command)
        elif score < bestScore:
            bestCandidates = [command]
            bestScore = score

    for template in candidates:
        for path in glob.iglob(os.path.expandvars(template)):
            basename = getBaseFileNameStem(path)
            score = getEditDistance(key, re.sub(r"[_\-]+", "", basename.upper()))
            if score == 0:
                return path
            elif score == bestScore:
                bestCandidates.append(basename)
            elif score < bestScore:
                bestCandidates = [basename]
                bestScore = score

    if os.path.exists(pipeline):
        return pipeline

    if bestCandidates:
        suggestion = " (maybe " + ", ".join(f"'{x}'" for x in bestCandidates) + ")"
    else:
        suggestion = ""

    raise ValueError(f"Pipeline or command not found: '{pipeline}'.{suggestion}")


def expandVars(template: str, extraVars: dict[str, str]) -> str:
    """Expand ``${VAR}`` in ``template``.

    Environment variables plus ``extraVars`` are expanded.

    Parameters
    ----------
    template : `str`
        template string.
    extraVars : `dict` [ `str` , `str` ]
        Extra variables.

    Returns
    -------
    s : `str`
        String with variables expanded.
    """
    return string.Template(template).substitute(os.environ, **extraVars)


def getBaseFileNameStem(path: str) -> str:
    """Get the stem (extension stripped) of the base filename.

    Parameters
    ----------
    path : `str`
        Path, possibly qualified and having an extension.

    Returns
    -------
    stem : `str`
        Path, not qualified and without an extension.
    """
    stem, ext = os.path.splitext(os.path.basename(path.rstrip("/")))
    return stem


def getDefaultConfig() -> Pipe2DConfigDict:
    """Get a new instance of `Pipe2DConfigDict` with all fields set to default.

    Returns
    -------
    config : `Pipe2DConfigDict`
        Config.
    """
    return {
        "butler_config": "",
        "pipelines": ["$DRP_STELLA_DIR/pipelines/*.yaml"],
        "inputs": [],
        "rerun": "u/$USER/$PIPELINE",
        "options": ["--register-dataset-types", "--log-level=.=INFO"],
    }


def getDefaultConfigPath() -> str:
    """Get the path to the default config file.

    Returns
    -------
    path : `str`
        Path to the default config file.
    """
    return os.path.expanduser(os.path.join("~", ".pipe2d_config.yaml"))


def getEditDistance(old: str, new: str) -> int:
    """Get the edit distance between ``old`` and ``new``.

    The edit distance returned by this function is not necessarily minimal.

    Parameters
    ----------
    old : `str`
        Old text.
    new : `str`
        New text.

    Returns
    -------
    dist : `int`
        Edit distance.
    """
    return sum(
        1
        for line in difflib.Differ().compare(list(old), list(new))
        if line.startswith(("- ", "+ "))
    )


def loadConfig(configpath: str | None) -> Pipe2DConfigDict:
    """Load a config from a file.

    If ``configpath`` is None, and there is not a file at the default config path,
    this function returns ``getDefaultConfig()`` instead of raising `FileNotFoundError`.

    Parameters
    ----------
    configpath : `str` | `None`
        Path to the config file.

    Returns
    -------
    config : `Pipe2DConfigDict`
        Config.
    """
    config = getDefaultConfig()

    try:
        with open(
            configpath if configpath is not None else getDefaultConfigPath()
        ) as f:
            config.update(yaml.load(f, Loader=yaml.SafeLoader))
    except FileNotFoundError:
        if configpath is not None:
            raise

    return config


def reorderPipetaskCommand(command: list[str]) -> list[str]:
    """Reorder a pipetask command line.

    In a pipetask command line, some options must come before others.
    This function reorders a command line to make it a valid one.

    Parameters
    ----------
    command : `list` [ `str` ]
        Pipetask command.

    Returns
    -------
    command : `list` [ `str` ]
        Reordered pipetask command.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("command", type=str)
    parser.add_argument("--log-level", type=str, action="append", default=[])
    parser.add_argument("--long-log", action="store_true")
    parser.add_argument("--log-file", type=str, action="append", default=[])
    parser.add_argument("--log-tty", action="store_true")
    parser.add_argument("--no-log-tty", action="store_true")
    parser.add_argument("--log-label", type=str, action="append", default=[])

    precedent, rest = parser.parse_known_args(args=command[1:])

    newcommand: list[str] = [command[0]]
    for key, value in vars(precedent).items():
        if key != "command":
            if (value is None) or (isinstance(value, (bool, list)) and not value):
                continue

            option = f'--{key.replace("_", "-")}'

            if isinstance(value, bool):
                newcommand.append(option)
            elif isinstance(value, list):
                newcommand.extend(f"{option}={elem}" for elem in value)
            else:
                newcommand.append(f"{option}={value}")

    newcommand.append(precedent.command)
    newcommand.extend(rest)
    return newcommand


def sqlAll(expressions: Sequence[str | SourceSelector]) -> str:
    """Concatenate ``expressions`` with ``AND`` operator.

    Parameters
    ----------
    expressions : `Sequence` [ `str` | `SourceSelector` ]
        List of expressions.

    Returns
    -------
    allexp : `str`
        "exp0 AND exp1 AND ..."
    """
    if not expressions:
        return "TRUE"

    if len(expressions) == 1:
        return str(expressions[0])

    return " AND ".join(f"({x})" for x in expressions)


def sqlAny(expressions: Sequence[str | SourceSelector]) -> str:
    """Concatenate ``expressions`` with ``OR`` operator.

    Parameters
    ----------
    expressions : `Sequence` [ `str` | `SourceSelector` ]
        List of expressions.

    Returns
    -------
    anyexp : `str`
        "exp0 OR exp1 OR ..."
    """
    if not expressions:
        return "FALSE"

    if len(expressions) == 1:
        return str(expressions[0])

    return " OR ".join(f"({x})" for x in expressions)


def sqlQuoteLiteral(s: str) -> str:
    """Quote a literal string for SQL.

    For example, sqlQuoteLiteral("ab'c") = "'ab''c'".

    Parameters
    ----------
    s : `str`
        String to be quoted.

    Returns
    -------
    quoted : `str`
        Quoted string.
    """
    s = s.replace("'", "''")
    return f"'{s}'"


if __name__ == "__main__":
    main()
