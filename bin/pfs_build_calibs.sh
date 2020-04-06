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
    echo "Usage: $0 [-r <RERUN>] [-c <CORES] [-C CALIB] [-n] [-b <BIASES>] [-d <DARKS>] [-f <FLATS>] [-F <FIBERTRACE>] [-a <ARCS>] <REPO>" 1>&2
    echo "" 1>&2
    echo "    -r <RERUN> : rerun name to use (default: '${RERUN}')" 1>&2
    echo "    -c <CORES> : number of cores to use (default: ${CORES})" 1>&2
    echo "    -C <CALIB> : directory for calibs" 1>&2
    echo "    -n : don't cleanup temporary products" 1>&2
    echo "    -v <VALIDITY> : validity period (days; default: ${VALIDITY})" 1>&2
    echo "    -b <BIASES> : identifier set for biases" 1>&2
    echo "    -d <DARKS> : identifier set for darks" 1>&2
    echo "    -f <FLATS> : identifier set for flats" 1>&2
    echo "    -F <FIBERTRACE> : identifier set for fiberTrace (multiple ok)" 1>&2
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
FIBERTRACES=()
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
            IFS=$'\n'
            FIBERTRACES+=(${OPTARG})
            unset IFS
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
if [ -z "$BIASES" ] && [ -z "$DARKS" ] && [ -z "$FLATS" ] && [ -z "$FIBERTRACES" ] && [ -z "$ARCS" ]; then
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
if [ -n "$BIASES" ]; then
    constructPfsBias.py $REPO --calib $CALIB --rerun $RERUN/bias --id $BIASES $batchArgs || exit 1
    ingestPfsCalibs.py $REPO --calib $CALIB --validity $VALIDITY --mode=copy \
                $REPO/rerun/$RERUN/bias/BIAS/*.fits || exit 1
    ( $CLEANUP && rm -r $REPO/rerun/$RERUN/bias) || true
fi

# Build dark
if [ -n "$DARKS" ]; then
    constructPfsDark.py $REPO --calib $CALIB --rerun $RERUN/dark --id $DARKS $batchArgs || exit 1
    ingestPfsCalibs.py $REPO --calib $CALIB --validity $VALIDITY --mode=copy \
                $REPO/rerun/$RERUN/dark/DARK/*.fits || exit 1
    ( $CLEANUP && rm -r $REPO/rerun/$RERUN/dark) || true
fi

# Build flat
if [ -n "$FLATS" ]; then
    constructFiberFlat.py $REPO --calib $CALIB --rerun $RERUN/flat \
                --id $FLATS $batchArgs || exit 1
    ingestPfsCalibs.py $REPO --calib $CALIB --validity $VALIDITY --mode=copy \
                $REPO/rerun/$RERUN/flat/FLAT/*.fits || exit 1
    ( $CLEANUP && rm -r $REPO/rerun/$RERUN/flat) || true
fi

# Build fiber traces
if (( ${#FIBERTRACES[@]} > 0 )); then
    fiberTraceIdString=""
    IFS="\n"
    for ft in "${FIBERTRACES[@]}"; do
        fiberTraceIdString+=" --id $ft"
    done
    unset IFS
    constructFiberTrace.py $REPO --calib $CALIB --rerun $RERUN/fiberTrace \
                $fiberTraceIdString $batchArgs || exit 1

    shopt -s nullglob
    for detector in b1 r1 m1 n1; do
        traces=($REPO/rerun/$RERUN/fiberTrace/FIBERTRACE/pfsFiberTrace-*-${detector}.fits)
        if (( ${#traces[@]} == 0 )); then
            echo "No traces for detector ${detector}."
            continue
        fi
        mkdir -p $REPO/rerun/$RERUN/fiberTrace-combined/
        combineFiberTraces.py $REPO/rerun/$RERUN/fiberTrace-combined/$(basename ${traces[0]}) ${traces[*]}
        ingestCalibs.py $REPO --calib $CALIB --validity $VALIDITY --mode=copy \
                $REPO/rerun/$RERUN/fiberTrace-combined/pfsFiberTrace-*-${detector}.fits || exit 1
    done
    ( $CLEANUP && rm -r $REPO/rerun/$RERUN/fiberTrace $REPO/rerun/$RERUN/fiberTrace-combined ) || true
fi

# Process arc
if [ -n "$ARCS" ]; then
    reduceArc.py $REPO --calib $CALIB --rerun $RERUN/arc --id $ARCS -j $CORES || exit 1
    ingestPfsCalibs.py $REPO --calib $CALIB --validity $VALIDITY --mode=copy \
                $REPO/rerun/$RERUN/arc/DETECTORMAP/*.fits \
                -c clobber=True register.ignore=True || exit 1
    ( $CLEANUP && rm -r $REPO/rerun/$RERUN/arc ) || true
fi
