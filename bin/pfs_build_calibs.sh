#!/bin/bash

#
# Build calibs, given a set of biases, darks, flats and arcs.
#
if [ $(uname -s) = Darwin ]; then
    if [ -z $DYLD_LIBRARY_PATH ]; then
        export DYLD_LIBRARY_PATH=$LSST_LIBRARY_PATH
    fi
fi

RERUN="${USER}/calibs"  # Rerun name to use
CORES=3  # Cores to use
VALIDITY=1000  # Validity period (days)

usage() {
    echo "Build calibs, given a set of biases, darks, flats and arcs" 1>&2
    echo "" 1>&2
    echo "Usage: $0 [-r <RERUN>] [-c <CORES] [-C CALIB] [-n] -b <BIASES> -d <DARKS> -f <FLATS> -F <FIBERTRACE> [-a <ARCS>] <REPO>" 1>&2
    echo "" 1>&2
    echo "    -r <RERUN> : rerun name to use (default: '${RERUN}')" 1>&2
    echo "    -c <CORES> : number of cores to use (default: ${CORES})" 1>&2
    echo "    -C <CALIB> : directory for calibs" 1>&2
    echo "    -n : don't cleanup temporary products" 1>&2
    echo "    -v <VALIDITY> : validity period (days; default: ${VALIDITY})" 1>&2
    echo "    -b <BIASES> : identifier set for biases" 1>&2
    echo "    -d <DARKS> : identifier set for darks" 1>&2
    echo "    -f <FLATS> : identifier set for flats" 1>&2
    echo "    -F <FIBERTRACE> : identifier set for fiberTrace" 1>&2
    echo "    -a <ARCS> : identifier set for arcs" 1>&2
    echo "    <REPO> : data repository directory" 1>&2
    echo "" 1>&2
    exit 1
}

# Parse command-line arguments
CLEANUP=true  # Clean temporary products?
BIASES=
DARKS=
FLATS=
FIBERTRACES=
ARCS=
while getopts ":r:c:C:nv:b:d:f:F:a:" opt; do
    case "${opt}" in
        r)
            RERUN=${OPTARG}
            ;;
        c)
            CORES=${OPTARG}
            ;;
        C)
            CALIB=${OPTARG}
            ;;
        n)
            CLEANUP=false
            ;;
        v)
            VALIDITY=${OPTARG}
            ;;
        b)
            BIASES=${OPTARG}
            ;;
        d)
            DARKS=${OPTARG}
            ;;
        f)
            FLATS=${OPTARG}
            ;;
        F)
            FIBERTRACES=${OPTARG}
            ;;
        a)
            ARCS=${OPTARG}
            ;;
        *)
            usage
            ;;
    esac
done
shift $((OPTIND-1))

REPO=$1  # Data repository directory
if [ -z "$REPO" ] || [ -n "$2" ]; then
    usage
fi
if [ -z "$BIASES" ] || [ -z "$DARKS" ] || [ -z "$FLATS" ] || [ -z "$FIBERTRACES" ]; then
    usage
fi
[ -z "$CALIB" ] && CALIB=${REPO}/CALIB

if [ $CORES = 1 ]; then
    batchArgs="--batch-type=none --doraise"
else
    batchArgs="--batch-type=smp --cores $CORES --doraise"
fi
export OMP_NUM_THREADS=1

set -evx

# Build bias
constructBias.py $REPO --calib $CALIB --rerun $RERUN/bias --id $BIASES $batchArgs || exit 1
ingestCalibs.py $REPO --calib $CALIB --validity $VALIDITY --mode=copy \
		    $REPO/rerun/$RERUN/bias/BIAS/*.fits || exit 1
( $CLEANUP && rm -r $REPO/rerun/$RERUN/bias) || true

# Build dark
constructDark.py $REPO --calib $CALIB --rerun $RERUN/dark --id $DARKS $batchArgs || exit 1
ingestCalibs.py $REPO --calib $CALIB --validity $VALIDITY --mode=copy \
		    $REPO/rerun/$RERUN/dark/DARK/*.fits || exit 1
( $CLEANUP && rm -r $REPO/rerun/$RERUN/dark) || true

# Build flat
constructFiberFlat.py $REPO --calib $CALIB --rerun $RERUN/flat \
            --id $FLATS $batchArgs || exit 1
ingestCalibs.py $REPO --calib $CALIB --validity $VALIDITY --mode=copy \
		    $REPO/rerun/$RERUN/flat/FLAT/*.fits || exit 1
( $CLEANUP && rm -r $REPO/rerun/$RERUN/flat) || true

# Build fiber trace
constructFiberTrace.py $REPO --calib $CALIB --rerun $RERUN/fiberTrace \
		       --id $FIBERTRACES $batchArgs || exit 1
ingestCalibs.py $REPO --calib $CALIB --validity $VALIDITY --mode=copy \
		    $REPO/rerun/$RERUN/fiberTrace/FIBERTRACE/*.fits || exit 1
( $CLEANUP && rm -r $REPO/rerun/$RERUN/fiberTrace ) || true

# Process arc
if [ -z "$ARCS" ]; then
    reduceArc.py $REPO --calib $CALIB --rerun $RERUN/arc --id $ARCS -j $CORES || exit 1
    ingestCalibs.py $REPO --calib $CALIB --validity $VALIDITY --mode=copy \
                $REPO/rerun/$RERUN/arc/DETECTORMAP/*.fits \
                -c clobber=True register.ignore=True || exit 1
    ( $CLEANUP && rm -r $REPO/rerun/$RERUN/arc ) || true
fi
