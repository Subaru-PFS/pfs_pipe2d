#!/usr/bin/env bash

DATADIR="/projects/HSC/PFS/weekly-20210819"
RERUN="weekly"
CORES=10
CLEANUP=true
DEVELOPER=false
usage() {
    echo "Exercise the PFS 2D pipeline code" 1>&2
    echo "" 1>&2
    echo "Usage: $0 [-d DATADIR] [-r <RERUN>] [-c CORES] [-n] [-D] WORKDIR" 1>&2
    echo "" 1>&2
    echo "    -d <DATADIR> : path to raw data (default: ${DATADIR})" 1>&2
    echo "    -r <RERUN> : rerun name to use (default: ${RERUN})" 1>&2
    echo "    -c <CORES> : number of cores to use (default: ${CORES})" 1>&2
    echo "    -n : don't cleanup temporary products" 1>&2
    echo "    -D : developer mode (--clobber-config --no-versions)" 1>&2
    echo "    WORKDIR : directory to use for work"
    echo "" 1>&2
    exit 1
}

while getopts "c:d:Dnr:" opt; do
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
        n)
            CLEANUP=false
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
if [ ! -d "$DATADIR" ]; then
    echo "Error: DATADIR directory $DATADIR does not exist."
    usage
fi
HERE=$(unset CDPATH && cd "$(dirname "$0")" && pwd)

set -evx

# Set up the data repo and ingest all data
mkdir -p $WORKDIR
mkdir -p $WORKDIR/CALIB
echo "lsst.obs.pfs.PfsMapper" > $WORKDIR/_mapper
ingestPfsImages.py $WORKDIR $DATADIR/PFFA*.fits

# Ingest defects
ingestCuratedCalibs.py $WORKDIR --calib $WORKDIR/CALIB $DRP_PFS_DATA_DIR/curated/pfs/defects

# Build calibs
develFlag=""
cleanFlag=""
( $DEVELOPER ) && develFlag="--devel"
( $CLEANUP ) && cleanFlag="--clean"

# Calibs for brn
generateCommands.py $WORKDIR \
    $HERE/../examples/weekly.yaml \
    $WORKDIR/calibs_for_brn.sh \
    --rerun=$RERUN/calib/brn \
    --init --blocks=calibs_for_brn \
    -j $CORES $develFlag $cleanFlag

sh $WORKDIR/calibs_for_brn.sh

# Calibs for m
generateCommands.py $WORKDIR \
    $HERE/../examples/weekly.yaml \
    $WORKDIR/calibs_for_m.sh \
    --rerun=$RERUN/calib/m \
    --blocks=calibs_for_m \
    -j $CORES $develFlag $cleanFlag

sh $WORKDIR/calibs_for_m.sh

# Run calibs over again just with for the arcs: we want to preserve their outputs so we can test the results
generateCommands.py $WORKDIR \
    $HERE/../examples/weekly.yaml \
    $WORKDIR/arc_brn.sh \
    --rerun=$RERUN/calib/brn \
    --blocks=arc_brn \
    -j $CORES $develFlag

sh $WORKDIR/arc_brn.sh

generateCommands.py $WORKDIR \
    $HERE/../examples/weekly.yaml \
    $WORKDIR/arc_m.sh \
    --rerun=$RERUN/calib/m \
    --blocks=arc_m \
    -j $CORES $develFlag

sh $WORKDIR/arc_m.sh

# Run the pipeline on brn
generateCommands.py $WORKDIR \
    $HERE/../examples/weekly.yaml \
    $WORKDIR/pipeline_on_brn.sh \
    --rerun=$RERUN/pipeline/brn \
    --blocks=pipeline_on_brn \
    -j $CORES $develFlag

sh $WORKDIR/pipeline_on_brn.sh

# Run the pipeline on bmn
generateCommands.py $WORKDIR \
    $HERE/../examples/weekly.yaml \
    $WORKDIR/pipeline_on_bmn.sh \
    --rerun=$RERUN/pipeline/bmn \
    --blocks=pipeline_on_bmn \
    -j $CORES $develFlag

sh $WORKDIR/pipeline_on_bmn.sh

$HERE/test_weekly.py --raw=$DATADIR --rerun=$WORKDIR/rerun/$RERUN
