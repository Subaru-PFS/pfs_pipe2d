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
"""Components to implement a program ``generateReductionSpec.py``.
"""

import dateutil.parser
import psycopg2
import yaml

import argparse
import dataclasses
import datetime
import getpass
import itertools
import math
import os
import re

from typing import Any, Dict, Iterable, List, Optional, Tuple


all_arms = ["b", "r", "n", "m"]
"""List of all arms
"""


@dataclasses.dataclass
class FileId:
    """A set of keys that uniquely identifies a raw FITS file.
    """

    visit: int
    arm: str
    spectrograph: int


@dataclasses.dataclass(order=True)
class BeamConfig:
    """A set of keys that uniquely identifies a beam config.
    """

    beam_config_date: float
    pfs_design_id: int


@dataclasses.dataclass
class SelectionCriteria:
    """Selection criteria used in queries to opDB.
    """

    date_start: Optional[datetime.datetime] = None
    date_end: Optional[datetime.datetime] = None
    visit_start: Optional[int] = None
    visit_end: Optional[int] = None

    @classmethod
    def fromNamespace(cls, args: argparse.Namespace, *, remove: bool = False) -> "SelectionCriteria":
        """Construct SelectionCriteria from argparse.Namespace object.

        Parameters
        ----------
        args : `argparse.Namespace`
            A return value of ``argparse.ArgumentParser().parse_args()``.
        remove : `bool`
            Remove from ``args`` those members that are used by this function.

        Returns
        -------
        criteria : `SelectionCriteria`
            Constructed SelectionCriteria instance.
        """
        criteria = SelectionCriteria()
        criteria.updateFromNamespace(args, remove=remove)
        return criteria

    def updateFromNamespace(self, args: argparse.Namespace, *, remove: bool = False):
        """Update self using members in argparse.Namespace object.

        Parameters
        ----------
        args : `argparse.Namespace`
            A return value of ``argparse.ArgumentParser().parse_args()``.
        remove : `bool`
            Remove from ``args`` those members that are used by this function.
        """
        undefined = object()

        for field in dataclasses.fields(self):
            # In case a user wants to overwrite a field with None,
            # we use not None but `undefined` as the default value
            member = getattr(args, field.name, undefined)
            if member is undefined:
                continue
            setattr(self, field.name, member)
            if remove:
                delattr(args, field.name)

    def asSQL(self) -> str:
        """Get SQL expression for queries to opDB.

        Returns
        -------
        expression : `str`
            SQL expression.
        """
        # To modify this method, pay attentin to SQL injection.
        # For example, if `self.x` is assumed to be integer
        # but is not guaranteed to be,
        # `:d` must always be specified in format strings:
        #     `expressions.append(f"x > {self.x:d}")`
        expressions = []
        if self.date_start is not None:
            if self.date_start.tzinfo is None:
                datestr = self.date_start.isoformat()
            else:
                datestr = self.date_start.astimezone(datetime.timezone.utc).replace(tzinfo=None).isoformat()
            expressions.append(f"pfs_visit.issued_at >= '{datestr}'")
        if self.date_end is not None:
            if self.date_end.tzinfo is None:
                datestr = self.date_end.isoformat()
            else:
                datestr = self.date_end.astimezone(datetime.timezone.utc).replace(tzinfo=None).isoformat()
            expressions.append(f"pfs_visit.issued_at < '{datestr}'")
        if self.visit_start is not None:
            expressions.append(f"pfs_visit.pfs_visit_id >= '{self.visit_start:d}'")
        if self.visit_end is not None:
            expressions.append(f"pfs_visit.pfs_visit_id < '{self.visit_end:d}'")

        if expressions:
            return "(" + " AND ".join(expressions) + ")"
        else:
            return "TRUE"


def main():
    """The main function for generateReductionSpec.py
    """
    parser = argparse.ArgumentParser(description="""
        Generate a spec file (in YAML) for processing, by reading opDB.
        The spec file can be input to generateCommands.py
        to generate actual commands.
    """)
    parser.add_argument("--detectorMapDir", type=str, help="""
        Directory that contains initial detector maps.
        If you want to inscribe environment variables as environment variables
        in the output file, escape the $ sign when calling this program.
    """)
    parser.add_argument("output", type=str, help="""
        Output file name. Should usually end with ".yaml".
    """)
    parser.add_argument("-d", "--dbname", type=str, help="""
        Database name of opDB. For example, -d "dbname=opdb host=example.com".
    """)
    parser.add_argument("--maxarcs", type=int, default=10, help="""
        Max number of arc visits to use for making one detectorMap.
    """)
    # options for SelectionCriteria follow.
    parser.add_argument("--date-start", type=dateutil.parser.parse, help="""
        Choose only those records with `pfs_visit.issued_at >= date_start`.
    """)
    parser.add_argument("--date-end", type=dateutil.parser.parse, help="""
        Choose only those records with `pfs_visit.issued_at < date_end`.
    """)
    parser.add_argument("--visit-start", type=int, help="""
        Choose only those records with `pfs_visit.pfs_visit_id >= visit_start`.
    """)
    parser.add_argument("--visit-end", type=int, help="""
        Choose only those records with `pfs_visit.pfs_visit_id < visit_end`.
    """)
    args = parser.parse_args()
    args.criteria = SelectionCriteria.fromNamespace(args, remove=True)

    if args.dbname is None:
        args.dbname = getDefaultDBName()

    generateReductionSpec(**vars(args))


def getDefaultDBName() -> str:
    """Get default database name for the current user.

    Returns
    -------
    dbname : `str`
        Something like "dbname=username"
    """
    return f"dbname={getpass.getuser()}"


def generateReductionSpec(
        output: str, dbname: str,
        criteria: SelectionCriteria = SelectionCriteria(),
        *, maxarcs: int = 10, detectorMapDir: str = None):
    """Read opDB and generate a YAML file that specifies data reduction.

    Parameters
    ----------
    output : `str`
        Output file name.
    dbname : `str`
        String to pass to psycopg2.connect() for database connection.
    criteria : `SelectionCriteria`
        Selection criteria used in queries to opDB.
    maxarcs : `int`
        Max number of arc visits to use for making one detectorMap.
    detectorMapDir : `str`, optional
        Directory that contains initial detector maps.
        Environment variable like ``$env`` can be used.
    """
    yamlObject = {}
    if detectorMapDir is not None:
        yamlObject["init"] = getSpecInitSpec(detectorMapDir)

    calibBlocks = []
    calibBlocks += getBiasDarkSpecs(dbname, "biasdark_", criteria=criteria)
    calibBlocks += getFlatSpecs(dbname, "flat_", criteria=criteria)
    calibBlocks += getFiberProfilesSpecs(dbname, "fiberProfiles_", criteria=criteria)
    calibBlocks += getDetectorMapSpecs(dbname, "detectorMap_", criteria=criteria, maxarcs=maxarcs)
    yamlObject["calibBlock"] = calibBlocks

    with open(output, "w") as f:
        yaml.dump(yamlObject, f, sort_keys=False)


def getSpecInitSpec(dirName: str) -> Dict[str, Any]:
    """Get ``init`` section in the YAML spec file.

    Parameters
    ----------
    dirName : `str`
        Directory that contains initial detector maps.
        Environment variable like ``$env`` can be used.

    Returns
    -------
    block : `Dict[str, Any]`
    """
    detectorMapFmt = "detectorMap-sim-{arm}.fits"

    files = os.listdir(os.path.expandvars(dirName))

    baseNameRe = "^" + re.escape(detectorMapFmt.format(arm="/")).replace("/", "(.*)") + "$"
    arms = []
    for name in files:
        match = re.match(baseNameRe, name)
        if match is not None:
            arms.append(match.group(1))

    if not arms:
        raise RuntimeError(f"No detectorMap files found in '{dirName}'")

    return {
        "dirName": dirName,
        "detectorMapFmt": detectorMapFmt,
        "arms": arms,
    }


def getBiasDarkSpecs(dbname: str, nameprefix: str, criteria: SelectionCriteria) -> List[Dict[str, Any]]:
    """Read opDB and return a list of YAML blocks
    that specify how to create bias and dark.

    Parameters
    ----------
    dbname : `str`
        String to pass to psycopg2.connect() for database connection.
    nameprefix : `str`
        Prefix of the names of the generated blocks.
    criteria : `SelectionCriteria`
        Selection criteria used in queries to opDB.

    Returns
    -------
    blocks : `List[Dict[str, Any]]`
        Elements of ``calibBlock`` list in the YAML spec file.
        Each element is a mapping from ``calibType`` ("bias", "dark")
        to the description of its source,
        with a special key "name" whose value is the name of the element.
    """
    # For bias and darks, arm 'm' is not distinguished from 'r'.
    arms = [arm for arm in all_arms if arm != "m"]
    calibTypes = [
        ("bias", "masterBiases"),
        ("dark", "masterDarks"),
    ]

    blocks = []
    for arm in arms:
        calibBlock: Dict[str, Any] = {}
        for calibType, sequenceType in calibTypes:
            sources = getSourcesFromDB(sequenceType, arm, dbname, criteria)
            if arm == "r":
                sources += getSourcesFromDB(sequenceType, "m", dbname, criteria)
            if sources:
                calibBlock[calibType] = {
                    "id": getSourceFilterFromListOfFileId(sources)
                }

        if calibBlock:
            blocks.append(nameYamlMapping(f"{nameprefix}{arm}", calibBlock))

    return mergeCalibBlocks(blocks)


def getFlatSpecs(dbname: str, nameprefix: str, criteria: SelectionCriteria) -> List[Dict[str, Any]]:
    """Read opDB and return a list of YAML blocks
    that specify how to create flat.

    Parameters
    ----------
    dbname : `str`
        String to pass to psycopg2.connect() for database connection.
    nameprefix : `str`
        Prefix of the names of the generated blocks.
    criteria : `SelectionCriteria`
        Selection criteria used in queries to opDB.

    Returns
    -------
    blocks : `List[Dict[str, Any]]`
        Elements of ``calibBlock`` list in the YAML spec file.
        Each element is a mapping from ``calibType`` ("flat")
        to the description of its source,
        with a special key "name" whose value is the name of the element.
    """
    calibTypes = [
        ("flat", "ditheredFlats"),
    ]

    blocks = []
    for arm in all_arms:
        calibBlock: Dict[str, Any] = {}
        for calibType, sequenceType in calibTypes:
            sources = getSourcesFromDB(sequenceType, arm, dbname, criteria)
            if sources:
                calibBlock["flat"] = {
                    "id": getSourceFilterFromListOfFileId(sources)
                }

        if calibBlock:
            blocks.append(nameYamlMapping(f"{nameprefix}{arm}", calibBlock))

    return mergeCalibBlocks(blocks)


def getFiberProfilesSpecs(dbname: str, nameprefix: str, criteria: SelectionCriteria) -> List[Dict[str, Any]]:
    """Read opDB and return a list of YAML blocks
    that specify how to create fiberProfiles.

    Parameters
    ----------
    dbname : `str`
        String to pass to psycopg2.connect() for database connection.
    nameprefix : `str`
        Prefix of the names of the generated blocks.
    criteria : `SelectionCriteria`
        Selection criteria used in queries to opDB.

    Returns
    -------
    blocks : `List[Dict[str, Any]]`
        Elements of ``calibBlock`` list in the YAML spec file.
        Each element is a mapping from ``calibType``
        ("fiberProfiles") to the description of its source,
        with a special key "name" whose value is the name of the element.
    """
    blocks = []
    for beamConfig in sorted(getBeamConfigs(["scienceTrace"], dbname, criteria)):
        for arm in all_arms:
            calibBlock: Dict[str, Any] = {}

            # There may be two groups (flat_odd, flat_even) in future,
            # but all sources belong to one group for now.
            sourceGroups = [
                getSourcesFromDB("scienceTrace", arm, dbname, criteria, beamConfig=beamConfig)
            ]
            sourceGroups = [group for group in sourceGroups if group]
            if sourceGroups:
                calibBlock["fiberProfiles"] = {
                    "group": [
                        {"id": getSourceFilterFromListOfFileId(group)} for group in sourceGroups
                    ]
                }

            if calibBlock:
                # This name is not unique
                # but a serial number will be added to it
                # after a merge process.
                blocks.append(nameYamlMapping(f"{nameprefix}{arm}", calibBlock))

    return addSerialNumbersToNames(mergeCalibBlocks(blocks))


def getDetectorMapSpecs(
        dbname: str, nameprefix: str, criteria: SelectionCriteria,
        *, maxarcs: int) -> List[Dict[str, Any]]:
    """Read opDB and return a list of YAML blocks
    that specify how to create detectorMap (arc).

    Parameters
    ----------
    dbname : `str`
        String to pass to psycopg2.connect() for database connection.
    nameprefix : `str`
        Prefix of the names of the generated blocks.
    criteria : `SelectionCriteria`
        Selection criteria used in queries to opDB.
    maxarcs : `int`
        Max number of arc visits to use for making one detectorMap.

    Returns
    -------
    blocks : `List[Dict[str, Any]]`
        Elements of ``calibBlock`` list in the YAML spec file.
        Each element is a mapping from ``calibType``
        ("detectorMap") to the description of its source,
        with a special key "name" whose value is the name of the element.
    """
    blocks = []
    for beamConfig in sorted(getBeamConfigs(["scienceArc"], dbname, criteria)):
        for arm in all_arms:
            sources = getSourcesFromDB("scienceArc", arm, dbname, criteria, beamConfig=beamConfig)
            for srcs in splitSources(sources, maxarcs):
                calibBlock: Dict[str, Any] = {}

                if sources:
                    calibBlock["detectorMap"] = {
                        "id": getSourceFilterFromListOfFileId(srcs)
                    }

                if calibBlock:
                    # This name is not unique
                    # but a serial number will be added to it
                    # after a merge process.
                    blocks.append(nameYamlMapping(f"{nameprefix}{arm}", calibBlock))

    return addSerialNumbersToNames(mergeCalibBlocks(blocks))


def getBeamConfigs(
        sequenceTypes: Iterable[str], dbname: str, criteria: SelectionCriteria) -> List[BeamConfig]:
    """Read opDB and return a list of ``BeamConfig``.

    Parameters
    ----------
    sequenceTypes : `Iterable[str]`
        List of ``sps_sequence.sequence_type``.
    dbname : `str`
        String to pass to psycopg2.connect() for database connection.
    criteria : `SelectionCriteria`
        Selection criteria used in queries to opDB.

    Returns
    -------
    beamConfigs : `List[BeamConfig]`
        List of ``BeamConfig``.
    """
    sequenceTypes = list(sequenceTypes)
    if not sequenceTypes:
        return []

    sequenceTypesFormat = ",".join(["%s"]*len(sequenceTypes))

    with psycopg2.connect(dbname) as conn:
        cursor = conn.cursor()
        cursor.execute(f"""
        SELECT
            beam_config_date, pfs_design_id
        FROM
            visit_set
            JOIN sps_sequence USING (visit_set_id)
            JOIN sps_exposure USING (pfs_visit_id)
            JOIN pfs_visit USING (pfs_visit_id)
        WHERE
            sequence_type IN ({sequenceTypesFormat})
            AND {criteria.asSQL()}
        GROUP BY
            beam_config_date, pfs_design_id
        """, sequenceTypes)

        return [
            BeamConfig(beam_config_date=beam_config_date, pfs_design_id=pfs_design_id)
            for beam_config_date, pfs_design_id in cursor
        ]


def getSourcesFromDB(
        sequenceType: str, arm: str, dbname: str, criteria: SelectionCriteria,
        beamConfig: Optional[BeamConfig] = None) -> List[FileId]:
    """Read opDB and return a list of FileId from which to create a calib.

    Parameters
    ----------
    sequenceType : `str`
        Compared with sps_sequence.sequence_type in opDB.
    arm : `str`
        Arm name ('b', 'r', 'n', 'm').
    dbname : `str`
        String to pass to psycopg2.connect() for database connection.
    criteria : `SelectionCriteria`
        Selection criteria used in queries to opDB.
    beamConfig : `BeamConfig`
        Instance of ``BeamConfig``.

    Returns
    -------
    fileIds : `List[FileId]`
    """
    if beamConfig is None:
        beam_config_date = None
        pfs_design_id = None
        sql = f"""
        SELECT
            pfs_visit_id, arm, sps_module_id
        FROM
            sps_sequence
            JOIN visit_set USING (visit_set_id)
            JOIN pfs_visit USING(pfs_visit_id)
            JOIN sps_exposure USING (pfs_visit_id)
            JOIN sps_camera USING(sps_camera_id)
            LEFT JOIN sps_annotation USING (pfs_visit_id, sps_camera_id)
        WHERE
            sps_sequence.sequence_type = %(sequenceType)s
            AND sps_camera.arm = %(arm)s
            AND (
                sps_annotation.data_flag IS NULL
                OR sps_annotation.data_flag = 0
            )
            AND {criteria.asSQL()}
        """
    else:
        beam_config_date = beamConfig.beam_config_date
        pfs_design_id = beamConfig.pfs_design_id
        sql = f"""
        SELECT
            pfs_visit_id, arm, sps_module_id
        FROM
            sps_sequence
            JOIN visit_set USING (visit_set_id)
            JOIN pfs_visit USING(pfs_visit_id)
            JOIN sps_exposure USING (pfs_visit_id)
            JOIN sps_camera USING(sps_camera_id)
            LEFT JOIN sps_annotation USING (pfs_visit_id, sps_camera_id)
        WHERE
            sps_sequence.sequence_type = %(sequenceType)s
            AND sps_camera.arm = %(arm)s
            AND beam_config_date = %(beam_config_date)s
            AND pfs_design_id = %(pfs_design_id)s
            AND (
                sps_annotation.data_flag IS NULL
                OR sps_annotation.data_flag = 0
            )
            AND {criteria.asSQL()}
        """

    with psycopg2.connect(dbname) as conn:
        cursor = conn.cursor()
        cursor.execute(sql, locals())
        return [
            FileId(visit=visit, arm=arm, spectrograph=spectrograph)
            for visit, arm, spectrograph in cursor
        ]


def getSourceFilterFromListOfFileId(ids: Iterable[FileId]) -> List[str]:
    """Convert a list of FileId to a format that can be used as the arguments
    of --id option.

    Parameters
    ----------
    ids : `Iterable[FileId]`
        List of FileId.

    Returns
    -------
    sourceFilter : `List[str]`
        For example, ["visit=1..10", "arm=r", "spectrograph=1"]
    """
    ids = list(ids)
    if not ids:
        raise ValueError(f"Empty list of FileId cannot be expressed in --id format.")

    visits = set(id.visit for id in ids)
    arms = set(id.arm for id in ids)
    spectrographs = set(id.spectrograph for id in ids)

    # ids must be equal to Cartesian product: visits x arms x spectrographs
    if len(ids) != len(visits) * len(arms) * len(spectrographs):
        raise ValueError(f"List of FileId cannot be expressed in --id format: {ids}")

    return [
        f"visit={getCompactNotationFromIntegers(visits)}",
        f"arm={'^'.join(str(x) for x in sorted(arms))}",
        f"spectrograph={getCompactNotationFromIntegers(spectrographs)}",
    ]


def getCompactNotationFromIntegers(ints: Iterable[int]) -> str:
    """Convert a list of integers
    to an equivalent list of spans (first, last, stride).

    Parameters
    ----------
    ints : `Iterable[int]`
        List of integers.

    Returns
    -------
    spans : `str`
        A list of spans joined with'^'.
        Each span is a single integer, ``f"{first}:{last}"``,
        or ``f"{first}:{last}:{stride}"`` (``last`` is inclusive.)
    """
    return '^'.join(
        f"{first}" if first == last
        else f"{first}..{last}" if stride == 1
        else f"{first}..{last}:{stride}"
        for first, last, stride in getSpansFromIntegers(ints)
    )


def getSpansFromIntegers(ints: Iterable[int]) -> List[Tuple[int, int, int]]:
    """Convert a list of integers
    to an equivalent list of spans (first, last, stride).

    Parameters
    ----------
    ints : `Iterable[int]`
        List of integers.

    Returns
    -------
    spans : `List[Tuple[int, int, int]]`
        List of spans.
        Each span (``first``, ``last``, ``stride``) represents integers
        ranging from ``first`` to ``last``, inclusive, with ``stride``.
    """
    ints = sorted(set(ints))
    if len(ints) <= 2:
        return [(x, x, 1) for x in ints]

    stride = min(
        (y - x if y - x == z - y else math.inf)
        for x, y, z in zip(ints[:-2], ints[1:-1], ints[2:])
    )
    if not (stride < math.inf):
        # There are not three consecutive elements at even intervals
        return [(x, x, 1) for x in ints]

    # guard both sides with sentinels
    ints = [math.nan, math.nan] + ints + [math.nan, math.nan]

    spans = []
    for is_evenintervals, group in itertools.groupby(
        zip(ints[:-2], ints[1:-1], ints[2:]),
        key=lambda xyz: xyz[1] - xyz[0] == xyz[2] - xyz[1] == stride
    ):
        group = list(group)
        if is_evenintervals:
            first = group[0][0]
            last = group[-1][-1]
            spans.append((first, last, stride))
        else:
            spans += getSpansFromIntegers(xyz[2] for xyz in group[:-2])

    return spans


def splitSources(sources: Iterable[FileId], chunkSize: int) -> List[List[FileId]]:
    """Split ``sources`` into chunks
    so that each chunk will have at most ``chunkSize`` items
    that have contiguous visit numbers.

    ``sources`` will be split as evenly as possible.
    For example, if chunkSize == 5, then 6 items will be split into 3+3,
    and 11 items will be split into 4+4+3.

    Parameters
    ----------
    sources : `Iterable[FileId]`
        The input list to split

    chunkSize : `int`
        Max size of a chunk.

    Returns
    -------
    chunks : `List[List[FileId]]`
        Chunks made from ``sources``.
        Each chunk has at most ``chunkSize`` items,
        and the items in a chunk have contiguous visit numbers.
    """
    if chunkSize <= 0:
        raise ValueError(f"chunkSize must be positive ({chunkSize})")

    sentinel = FileId(visit=math.nan, arm=None, spectrograph=None)
    sources = [sentinel] + sorted(sources, key=lambda x: x.visit) + [sentinel]

    # Split sources into sequences, each contiguous in terms of visits.
    contiguousSeqs = []
    for iscontiguous, group in itertools.groupby(
        zip(sources[:-1], sources[1:]),
        key=lambda pair: pair[1].visit - pair[0].visit == 1
    ):
        group = list(group)
        if iscontiguous:
            contiguousSeqs.append([pair[0] for pair in group] + [group[-1][-1]])
        else:
            contiguousSeqs.extend([pair[-1]] for pair in group[:-1])

    # Further split the contiguous sequences into small chunks
    chunks = []
    for seq in contiguousSeqs:
        n = len(seq)
        numChunks = (n + chunkSize - 1) // chunkSize
        quotient = n // numChunks
        remainder = n % numChunks
        for i in range(numChunks):
            if remainder > 0:
                remainder -= 1
                numToPop = quotient + 1
            else:
                numToPop = quotient
            chunks.append(seq[:numToPop])
            seq = seq[numToPop:]
        assert(len(seq) == 0)

    return chunks


def nameYamlMapping(name: str, mapping: Dict[str, Any]) -> Dict[str, Any]:
    """Add ``"name"`` field to a YAML mapping.

    Parameters
    ----------
    name : `str`
        name of the returned mapping.
    mapping : `Dict[str, Any]`
        YAML mapping (i.e. Python dict)

    Returns
    -------
    newMapping: `Dict[str, Any]`
        A shallow copy of the argument ``mapping``
        with ``"name"`` field added to it.
    """
    # Because we want "name" field to be the first member for aesthetic
    # reasons, we create a new dict and copy ``mapping`` to it.
    newMapping = {"name": name}
    newMapping.update((key, value) for key, value in mapping.items() if key != "name")
    return newMapping


def mergeCalibBlocks(blocks: Iterable[Any]) -> List[Any]:
    """Find mergeable calibBlocks in ``blocks`` and merge them.

    Two calibBlocks are "mergeable"
    if they are equal up to strings "arm=..." in them.

    Parameters
    ----------
    blocks : `Iterable[Any]`
        List of calibBlocks.

    Returns
    -------
    newBlocks : `List[Any]`
        Shallow copy of ``blocks``,
        except that mergeable elements have been merged.
    """
    blocks = list(blocks)

    newBlocks = []
    while blocks:
        mergeables = [0]
        for i in range(1, len(blocks)):
            if _mergeCalibBlocks_isMergeable(blocks[0], blocks[i]):
                mergeables.append(i)
        newBlocks.append(_mergeCalibBlocks_merge(blocks[i] for i in mergeables))
        for i in reversed(mergeables):
            del blocks[i]

    return newBlocks


def _mergeCalibBlocks_isMergeable(object1: Any, object2: Any) -> bool:
    """Compare two calibBlocks and return True if they are mergeable,
    which means they are equal up to strings "arm=...".
    ("name" key is also ignored in comparison.)

    Parameters
    ----------
    object1 : `Any`
        Any constituent part of a calibBlock
        (including the complete calibBlock itself).
    object2 : `Any`
        Any constituent part of a calibBlock
        (including the complete calibBlock itself).

    Returns
    -------
    isMergeable : `bool`
        True if ``object1`` and ``object2`` are mergeable
    """
    if isinstance(object1, list):
        if not isinstance(object2, list):
            return False
        if len(object1) != len(object2):
            return False
        return all(
            _mergeCalibBlocks_isMergeable(elem1, elem2)
            for elem1, elem2 in zip(object1, object2)
        )

    if isinstance(object1, dict):
        if not isinstance(object2, dict):
            return False
        if set(object1.keys()) != set(object2.keys()):
            return False
        return all(
            _mergeCalibBlocks_isMergeable(object1[key], object2[key])
            for key in object1 if key != "name"
        )

    if isinstance(object1, str):
        if not isinstance(object2, str):
            return False
        if object1.startswith("arm=") and object2.startswith("arm="):
            return True
        return object1 == object2

    return object1 == object2


def _mergeCalibBlocks_merge(objects: Iterable[Any]) -> Any:
    """Merge calibBlocks.

    Parameters
    ----------
    objects : `Iterable[Any]`
        A list, each element being any constituent part of a calibBlock.
        (including a complete calibBlock itself).
        All elements must be mergeable to each other.

    Returns
    -------
    merged : `Any`
        Merged object.
    """
    objects = list(objects)
    if not objects:
        raise ValueError("No objects to merge.")

    if any(isinstance(obj, list) for obj in objects):
        if not all(isinstance(obj, list) for obj in objects):
            raise ValueError("calibBlocks are not mergeable.")
        if not all(len(objects[0]) == len(obj) for obj in objects):
            return ValueError("calibBlocks are not mergeable.")
        return [_mergeCalibBlocks_merge(tpl) for tpl in zip(*objects)]

    if any(isinstance(obj, dict) for obj in objects):
        if not all(isinstance(obj, dict) for obj in objects):
            raise ValueError("calibBlocks are not mergeable.")
        if not all(set(objects[0].keys()) == set(obj.keys()) for obj in objects):
            return ValueError("calibBlocks are not mergeable.")
        merged = {}
        for key in objects[0]:
            if key == "name":
                merged[key] = _mergeCalibBlocks_mergeNames(obj[key] for obj in objects)
            else:
                merged[key] = _mergeCalibBlocks_merge(obj[key] for obj in objects)
        return merged

    if any(isinstance(obj, str) for obj in objects):
        if not all(isinstance(obj, str) for obj in objects):
            raise ValueError("calibBlocks are not mergeable.")
        if all(obj.startswith("arm=") for obj in objects):
            return "arm=" + "^".join(sorted(obj[len("arm="):] for obj in objects))
        if not all(objects[0] == obj for obj in objects):
            raise ValueError("calibBlocks are not mergeable.")
        return objects[0]

    if not all(objects[0] == obj for obj in objects):
        raise ValueError("calibBlocks are not mergeable.")
    return objects[0]


def _mergeCalibBlocks_mergeNames(names: Iterable[str]) -> str:
    """Merge names of calibBlocks.

    The names must be ``f"{prefix}{arm}"``,
    in which ``prefix`` is common to all names.

    Parameters
    ----------
    names : `Iterable[str]`
        Names of calibBlocks to merge.

    Returns
    -------
    mergedName : `str`
        Merge result.
    """
    names = list(names)
    if not names:
        raise ValueError("No names to merge.")

    armRe = "|".join(re.escape(arm) for arm in all_arms)
    nameRe = fr"\A(?P<prefix>.*)(?P<arm>{armRe})\Z"

    splitNames = [re.match(nameRe, name).groupdict() for name in names]
    if not all(splitNames[0]["prefix"] == name["prefix"] for name in splitNames):
        raise ValueError("names are not mergeable.")

    return splitNames[0]["prefix"] + "".join(sorted(name["arm"] for name in splitNames))


def addSerialNumbersToNames(calibBlocks: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Find elements in ``calibBlocks`` that have a name common to them,
    and add serial numbers to the name.
    Even if an element has a unique name, the name is added ``"_1"`` to.
    The order of elements in the return value
    may be different from that in the argument.

    Parameters
    ----------
    calibBlocks : `Iterable[Dict[str, Any]]`
        List of calibBlocks.

    Returns
    -------
    calibBlocks : `Iterable[Dict[str, Any]]`
        List of calibBlocks, each element is given a unique name.
    """
    calibBlocks = sorted(calibBlocks, key=lambda block: block["name"])
    for key, group in itertools.groupby(calibBlocks, key=lambda block: block["name"]):
        group = list(group)
        for i, elem in enumerate(group, start=1):
            elem["name"] += f"_{i}"

    return calibBlocks
