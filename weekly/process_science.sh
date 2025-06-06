#!/usr/bin/env bash

DATADIR="/projects/HSC/PFS/scienceSims/scienceSims-20230808"
RERUN="science"
CORES=10
DEVELOPER=false
usage() {
    echo "Run the PFS 2D pipeline code on the science exposures" 1>&2
    echo "" 1>&2
    echo "Usage: $0 [-d DATADIR] [-r <RERUN>] [-c CORES] [-D] WORKDIR" 1>&2
    echo "" 1>&2
    echo "    -d <DATADIR> : path to raw data (default: ${DATADIR})" 1>&2
    echo "    -r <RERUN> : rerun name to use (default: ${RERUN})" 1>&2
    echo "    -c <CORES> : number of cores to use (default: ${CORES})" 1>&2
    echo "    -D : developer mode (--clobber-config --no-versions)" 1>&2
    echo "    WORKDIR : directory to use for work (contains existing 'repo')" 1>&2
    echo "" 1>&2
    exit 1
}

while getopts "c:d:Dr:" opt; do
    case "${opt}" in
        c)
            CORES=${OPTARG}
            ;;
        d)
            DATADIR=${OPTARG}
            ;;
        D)
            DEVELOPER=true
            ;;
        r)
            RERUN=${OPTARG}
            ;;
        h | *)
            usage
            ;;
    esac
done
shift $((OPTIND-1))
WORKDIR=$1; shift
if [ -z "$WORKDIR" ] || [ -n "$1" ]; then
    usage
fi
DATASTORE=$WORKDIR/repo
if [ ! -e "$DATASTORE/gen3.sqlite3" ]; then
    echo "Working directory $WORKDIR doesn't appear to be a data repository (no gen3.sqlite3 file)"
    usage
fi
if [ ! -d "$DATADIR" ]; then
    echo "Error: DATADIR directory $DATADIR does not exist."
    usage
fi
HERE=$(unset CDPATH && cd "$(dirname "$0")" && pwd)

develFlag=""
( $DEVELOPER ) && develFlag="--devel"

set -evx

# Ingest the science data
mkdir -p $WORKDIR/rawScience
cp $DATADIR/PFF[AB]*.fits $WORKDIR/rawScience
cp $DATADIR/pfsConfig-*.fits $WORKDIR/rawScience
chmod -R u+w $WORKDIR/rawScience

checkPfsRawHeaders.py --fix --nir $WORKDIR/rawScience/PFF[AB]*.fits
checkPfsConfigHeaders.py --fix $WORKDIR/rawScience/pfsConfig-*.fits
butler ingest-raws $DATASTORE $WORKDIR/rawScience/PFF[AB]*.fits --ingest-task lsst.obs.pfs.gen3.PfsRawIngestTask --transfer copy --fail-fast
ingestPfsConfig.py $DATASTORE lsst.obs.pfs.PfsSimulator PFS-F/raw/pfsConfig $WORKDIR/rawScience/pfsConfig*.fits --transfer link

# Run the pipeline
defineCombination.py $DATASTORE PFS-F science 1000 1001 1002 1003 1004 1005 1006 1007 --collection PFS-F/raw/pfsConfig --max-group-size 100

pipetask run --register-dataset-types -j $CORES -b $DATASTORE --instrument lsst.obs.pfs.PfsSimulator -i PFS-F/raw/sps,PFS-F/raw/pfsConfig,PFS-F/calib,PFS-F/objectGroups -o "$RERUN" -p '$DRP_STELLA_DIR/pipelines/science.yaml' -d "combination = 'science'" --fail-fast -c isr:doCrosstalk=False -c isr:h4.quickCDS=True -c isr:h4.doIPC=False -c isr:h4.useDarkCube=False -c reduceExposure:doApplyScreenResponse=False -c reduceExposure:doBlackSpotCorrection=False -c fitFluxCal:fitFocalPlane.polyOrder=0 -c cosmicray:grouping=manual -c 'cosmicray:groups={1000: 1, 1001: 1, 1002: 2, 1003: 2, 1004: 3, 1005: 3, 1006: 4, 1007: 4}'

exportPfsProducts.py -b $DATASTORE -i PFS-F/raw/pfsConfig,"$RERUN" -o $WORKDIR/export --visits "combination = 'science'"
