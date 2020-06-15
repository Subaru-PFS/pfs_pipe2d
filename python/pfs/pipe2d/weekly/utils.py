from .. import generateCommands

import os
import re

__all__ = ("getIdValues", "getVisitsByBlockName", "getBrnVisits", "getBmnVisits")


def getIdValues(text):
    """Interpret a list of values

    The list of values is in the same format as they would be specified on
    the command-line, without any leading keyword (e.g., no ``visit=``).

    This code has been taken from
    ``lsst.pipe.base.argumentParser.IdValueAction``.

    Parameters
    ----------
    text : `list` of `str`
        Text with the list of visits.

    Returns
    -------
    visits : `list` of `int`
        Visit numbers.
    """
    visits = []
    for line in text:
        for vv in line.strip().split("^"):
            mat = re.search(r"^(\d+)\.\.(\d+)(?::(\d+))?$", vv)
            if mat:
                v1 = int(mat.group(1))
                v2 = int(mat.group(2))
                v3 = mat.group(3)
                v3 = int(v3) if v3 else 1
                for ii in range(v1, v2 + 1, v3):
                    visits.append(ii)
            else:
                visits.append(int(vv))
    return visits


def getVisitsByBlockName(blockName):
    """Return the list of visit numbers for ``blockName`` in the weekly.

    Parameters
    ----------
    blockName : `str`
        One of the science block names defined in ``examples/weekly.yaml``.

    Returns
    -------
    visits : `list` of `int`
        Visit numbers.
    """
    filename = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "examples", "weekly.yaml")
    initSource, calibBlocks, scienceBlocks = generateCommands.processYaml(filename)
    idList = scienceBlocks[blockName].source.id
    if not (len(idList) == 1 and idList[0].startswith("visit=")):
        raise RuntimeError(
            f"examples/weekly.yaml: 'id' field of scienceBlock '{blockName}' must be 'visit=...'")

    idStr = idList[0][len("visit="):]
    return getIdValues([idStr])


def getBrnVisits():
    """Return the list of visit numbers for BRN data in the weekly

    Returns
    -------
    visits : `list` of `int`
        Visit numbers.
    """
    return getVisitsByBlockName("pipeline_on_brn")


def getBmnVisits():
    """Return the list of visit numbers for BMN data in the weekly

    Returns
    -------
    visits : `list` of `int`
        Visit numbers.
    """
    return getVisitsByBlockName("pipeline_on_bmn")
