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

import psycopg2
import yaml

import argparse
import dataclasses
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


def main():
    """The main function for generateReductionSpec.py
    """
    parser = argparse.ArgumentParser(description="""
        Generate a spec file (in YAML) for processing, by reading opDB.
        The spec file can be input to generateCommands.py
        to generate actual commands.
    """)
    parser.add_argument("detectorMapDir", type=str, help="""
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
    args = parser.parse_args()

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


def generateReductionSpec(output: str, detectorMapDir: str, dbname: str):
    """Read opDB and generate a YAML file that specifies data reduction.

    Parameters
    ----------
    output : `str`
        Output file name.
    detectorMapDir : `str`
        Directory that contains initial detector maps.
        Environment variable like ``$env`` can be used.
    dbname : `str`
        String to pass to psycopg2.connect() for database connection.
    """
    yamlObject = {}
    yamlObject["init"] = getSpecInitSpec(detectorMapDir)

    calibBlocks = []
    calibBlocks += getBiasDarkSpecs(dbname, "biasdark_")
    calibBlocks += getFlatSpecs(dbname, "flat_")
    calibBlocks += getOtherCalibSpecs(dbname, "calib_")
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


def getBiasDarkSpecs(dbname: str, nameprefix: str) -> List[Dict[str, Any]]:
    """Read opDB and return a list of YAML blocks
    that specify how to create bias and dark.

    Parameters
    ----------
    dbname : `str`
        String to pass to psycopg2.connect() for database connection.
    nameprefix : `str`
        Prefix of the names of the generated blocks.

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
            sources = getSourcesFromDB(sequenceType, arm, dbname)
            if arm == "r":
                sources += getSourcesFromDB(sequenceType, "m", dbname)
            if sources:
                calibBlock[calibType] = {
                    "id": getSourceFilterFromListOfFileId(sources)
                }

        if calibBlock:
            blocks.append(nameYamlMapping(f"{nameprefix}{arm}", calibBlock))

    return blocks


def getFlatSpecs(dbname: str, nameprefix: str) -> List[Dict[str, Any]]:
    """Read opDB and return a list of YAML blocks
    that specify how to create flat.

    Parameters
    ----------
    dbname : `str`
        String to pass to psycopg2.connect() for database connection.
    nameprefix : `str`
        Prefix of the names of the generated blocks.

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
            sources = getSourcesFromDB(sequenceType, arm, dbname)
            if sources:
                calibBlock["flat"] = {
                    "id": getSourceFilterFromListOfFileId(sources)
                }

        if calibBlock:
            blocks.append(nameYamlMapping(f"{nameprefix}{arm}", calibBlock))

    return blocks


def getOtherCalibSpecs(dbname: str, nameprefix: str) -> List[Dict[str, Any]]:
    """Read opDB and return a list of YAML blocks
    that specify how to create fiberProfiles and detectorMap (arc).

    Parameters
    ----------
    dbname : `str`
        String to pass to psycopg2.connect() for database connection.
    nameprefix : `str`
        Prefix of the names of the generated blocks.

    Returns
    -------
    blocks : `List[Dict[str, Any]]`
        Elements of ``calibBlock`` list in the YAML spec file.
        Each element is a mapping from ``calibType``
        ("fiberProfiles", "detectorMap") to the description of its source,
        with a special key "name" whose value is the name of the element.
    """
    blocks = []
    for beamConfig in sorted(getBeamConfigs(["scienceTrace", "scienceArc"], dbname)):
        for arm in all_arms:
            calibBlock: Dict[str, Any] = {}

            # There may be two groups (flat_odd, flat_even) in future,
            # but all sources belong to one group for now.
            sourceGroups = [
                getSourcesFromDB("scienceTrace", arm, dbname, beamConfig=beamConfig)
            ]
            sourceGroups = [group for group in sourceGroups if group]
            if sourceGroups:
                calibBlock["fiberProfiles"] = {
                    "group": [
                        {"id": getSourceFilterFromListOfFileId(group)} for group in sourceGroups
                    ]
                }

            sources = getSourcesFromDB("scienceArc", arm, dbname, beamConfig=beamConfig)
            if sources:
                calibBlock["detectorMap"] = {
                    "id": getSourceFilterFromListOfFileId(sources)
                }

            if calibBlock:
                name = f"{nameprefix}{arm}_{beamConfig.beam_config_date}_{beamConfig.pfs_design_id:016x}"
                blocks.append(nameYamlMapping(name, calibBlock))

    return blocks


def getBeamConfigs(sequenceTypes: Iterable[str], dbname: str) -> List[BeamConfig]:
    """Read opDB and return a list of ``BeamConfig``.

    Parameters
    ----------
    sequenceTypes : `Iterable[str]`
        List of ``sps_sequence.sequence_type``.

    dbname : `str`
        String to pass to psycopg2.connect() for database connection.

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
        GROUP BY
            beam_config_date, pfs_design_id
        """, sequenceTypes)

        return [
            BeamConfig(beam_config_date=beam_config_date, pfs_design_id=pfs_design_id)
            for beam_config_date, pfs_design_id in cursor
        ]


def getSourcesFromDB(
        sequenceType: str, arm: str, dbname: str,
        beamConfig: Optional[BeamConfig] = None) -> List[FileId]:
    """Read opDB and return a list of FileId from which to create a calib.

    Parameters
    ----------
    sequenceType : `str`
        Compared with sps_sequence.sequence_type in opDB.
    arm : `str`
        Arm name ('b', 'r', 'n', 'm').
    beamConfig : `BeamConfig`
        Instance of ``BeamConfig``.
    dbname : `str`
        String to pass to psycopg2.connect() for database connection.

    Returns
    -------
    fileIds : `List[FileId]`
    """
    if beamConfig is None:
        beam_config_date = None
        pfs_design_id = None
        sql = """
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
        """
    else:
        beam_config_date = beamConfig.beam_config_date
        pfs_design_id = beamConfig.pfs_design_id
        sql = """
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
