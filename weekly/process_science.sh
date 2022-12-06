#!/usr/bin/env bash

DATADIR="/projects/HSC/PFS/scienceSims/scienceSims-20221201"
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
    echo "    WORKDIR : directory to use for work (contains existing data repo)" 1>&2
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
if [ ! -e "$WORKDIR/_mapper" ]; then
    echo "Working directory $WORKDIR doesn't appear to be a data repository (no _mapper file)"
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
ingestPfsImages.py $WORKDIR $DATADIR/PFF[AB]*.fits

# Run the pipeline
generateCommands.py $WORKDIR \
    $HERE/../examples/science.yaml \
    $WORKDIR/science.sh \
    --rerun=$RERUN \
    --blocks brn bmn \
    -j $CORES $develFlag

sh $WORKDIR/science.sh
