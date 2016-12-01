#!/bin/bash

#
# Exercise the PFS 2D pipeline code.
#
# We run through the an example reduction to make sure everything's working.
#

set -ev

usage() {
    echo "Exercise the PFS 2D pipeline code" 1>&2
    echo "" 1>&2
    echo "Usage: $0 [-b <BRANCH>] [-r <RERUN>] [-d DIRNAME] [-c CORES] [-n] <PREFIX>" 1>&2
    echo "" 1>&2
    echo "    -b <BRANCH> : branch of drp_stella_data to use" 1>&2
    echo "    -r <RERUN> : rerun name to use (default: 'integration')" 1>&2
    echo "    -d <DIRNAME> : directory name to give data repo (default: 'INTEGRATION')" 1>&2
    echo "    -c <CORES> : number of cores to use (default: 1)" 1>&2
    echo "    -n : don't cleanup temporary products" 1>&2
    echo "    <PREFIX> : directory under which to operate" 1>&2
    echo "" 1>&2
    exit 1
}

# Parse command-line arguments
BRANCH=  # Branch to build
RERUN="integration"  # Rerun name to use
TARGET="INTEGRATION"  # Directory name to give data repo
CORES=1  # Number of cores to use
CLEANUP=true  # Clean temporary products?
while getopts ":b:c:d:nr:" opt; do
    case "${opt}" in
        b)
            BRANCH=${OPTARG}
            ;;
        c)
            CORES=${OPTARG}
            ;;
        d)
            TARGET=${OPTARG}
            ;;
        n)
            CLEANUP=false
            ;;
        r)
            RERUN=${OPTARG}
            ;;
        *)
            usage
            ;;
    esac
done
shift $((OPTIND-1))

PREFIX=$1  # Directory to work in
if [ -z "$PREFIX" ] || [ -n "$2" ]; then
    usage
fi

mkdir -p $PREFIX
cd $PREFIX

# Setting lfs.batch=true enables passwordless downloads with git-lfs.
if [ -e drp_stella_data ]; then
    pushd drp_stella_data
    git fetch --all --force --prune --tags
    popd
else
    git -c lfs.batch=true clone https://github.com/Subaru-PFS/drp_stella_data
fi
if [ -n $BRANCH ]; then
    pushd drp_stella_data
    git -c lfs.batch=true checkout $BRANCH || echo "Can't checkout $BRANCH"
    popd
fi

# Construct repo
mkdir -p $TARGET
[ -e $TARGET/_mapper ] || echo "lsst.obs.pfs.PfsMapper" > $TARGET/_mapper

# Ingest images into repo
ingestImages.py $TARGET --mode=link \
    drp_stella_data/tests/data/raw/*.fits \
    -c clobber=True register.ignore=True
[ -e $TARGET/pfsState ] || cp -r drp_stella_data/tests/data/PFS/pfsState $TARGET

# Build bias
constructBias.py $TARGET --rerun $RERUN/bias \
    --id field=BIAS dateObs=2015-12-22 arm=r spectrograph=2 \
    --calibId calibVersion=bias arm=r spectrograph=2 \
    --batch-type=smp --cores $CORES
genCalibRegistry.py --root $TARGET/CALIB --validity 1000
( $CLEANUP && rm -r $TARGET/rerun/$RERUN/bias ) || true

# Build dark
constructDark.py $TARGET --rerun $RERUN/dark \
    --id field=DARK dateObs=2015-12-22 arm=r spectrograph=2 \
    --calibId calibVersion=dark arm=r spectrograph=2 \
    --batch-type=smp --cores $CORES
genCalibRegistry.py --root $TARGET/CALIB --validity 1000
( $CLEANUP && rm -r $TARGET/rerun/$RERUN/dark ) || true

# Build fiber trace
constructFiberTrace.py $TARGET --rerun $RERUN/fiber \
    --id visit=29 \
    --calibId calibVersion=fiberTrace arm=r spectrograph=2 \
    --batch-type=smp --cores $CORES
genCalibRegistry.py --root $TARGET/CALIB --validity 1000
( $CLEANUP && rm -r $TARGET/rerun/$RERUN/fiber ) || true

# Build flat
constructFiberFlat.py $TARGET --rerun $RERUN/flat \
    --id visit=29..53 \
    --calibId calibVersion=flat arm=r spectrograph=2 \
    --batch-type=smp --cores $CORES
genCalibRegistry.py --root $TARGET/CALIB --validity 1000
( $CLEANUP && rm -r $TARGET/rerun/$RERUN/flat ) || true

# Process an arc
detrend.py $TARGET --rerun $RERUN/detrend --id visit=58
reduceArc.py $TARGET --rerun $RERUN/detrend --id visit=58

echo "Done."
