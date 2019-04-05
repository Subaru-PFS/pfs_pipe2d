#!/bin/bash

#
# Exercise the PFS 2D pipeline code.
#
# We run through the an example reduction to make sure everything's working.
#
if [ $(uname -s) = Darwin ]; then
    if [ -z $DYLD_LIBRARY_PATH ]; then
        export DYLD_LIBRARY_PATH=$LSST_LIBRARY_PATH
    fi
fi

set -evx

usage() {
    echo "Exercise the PFS 2D pipeline code" 1>&2
    echo "" 1>&2
    echo "Usage: $0 [-b <BRANCH>] [-r <RERUN>] [-d DIRNAME] [-c CORES] [-n] <PREFIX>" 1>&2
    echo "" 1>&2
    echo "    -b <BRANCH> : branch of drp_stella_data to use" 1>&2
    echo "    -r <RERUN> : rerun name to use (default: 'integration')" 1>&2
    echo "    -d <DIRNAME> : directory name to give data repo (default: 'INTEGRATION')" 1>&2
    echo "    -c <CORES> : number of cores to use (default: 1)" 1>&2
    echo "    -G : don't clone or update from git" 1>&2
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
USE_GIT=true # checkout/update from git
CLEANUP=true  # Clean temporary products?
while getopts ":b:c:d:Gnr:" opt; do
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
        G)
            USE_GIT=false
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
TARGET="$(pwd)/$TARGET"

if $USE_GIT; then
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
else
    if [ -n $BRANCH ]; then
	echo "Ignoring branch $BRANCH as you chose -G" >&2
    fi
fi

if [ $CORES = 1 ]; then
    batchArgs="--batch-type=none --doraise"
else
    batchArgs="--batch-type=smp --cores $CORES --doraise"
fi

export OMP_NUM_THREADS=1

#
# Look for the data files
#
if [ -d drp_stella_data ]; then
    drp_stella_data=drp_stella_data
else
    drp_stella_data=$(find . -name PFLA00583012.fits | xargs dirname | xargs dirname)
fi

# Construct repo
rm -rf $TARGET
mkdir -p $TARGET
mkdir -p $TARGET/CALIB
[ -e $TARGET/_mapper ] || echo "lsst.obs.pfs.PfsMapper" > $TARGET/_mapper

# Ingest images into repo
ingestPfsImages.py $TARGET --mode=link \
    $drp_stella_data/raw/PFFA*.fits \
    -c clobber=True register.ignore=True

ingestCalibs.py $TARGET --calib $TARGET/CALIB --validity 1800 \
		$drp_stella_data/raw/detectorMap-sim-*.fits --mode=copy || exit 1

# Build calibs
calibsArgs=
( ! $CLEANUP && calibsArgs="-n" ) || true
pfs_build_calibs.sh -r integration -c $CORES $calibsArgs \
    -b "field=BIAS" \
    -d "field=DARK" \
    -f "field=FLAT" \
    -F "visit=20" \
    -a "field=ARC" \
    $TARGET

# Detrend only
detrend.py $TARGET --calib $TARGET/CALIB --rerun $RERUN/detrend --id visit=33 || exit 1

# End-to-end pipeline
reduceExposure.py $TARGET --calib $TARGET/CALIB --rerun $RERUN/pipeline --id field=OBJECT || exit 1
mergeArms.py $TARGET --calib $TARGET/CALIB --rerun $RERUN/pipeline --id field=OBJECT || exit 1
calculateReferenceFlux.py $TARGET --calib $TARGET/CALIB --rerun $RERUN/pipeline --id field=OBJECT || exit 1
fluxCalibrate.py $TARGET --calib $TARGET/CALIB --rerun $RERUN/pipeline --id field=OBJECT || exit 1
coaddSpectra.py $TARGET --calib $TARGET/CALIB --rerun $RERUN/pipeline --id field=OBJECT || exit 1

python -c "
from lsst.daf.persistence import Butler
butler = Butler(\"${TARGET}/rerun/${RERUN}/pipeline\")
spectrum = butler.get(\"pfsCoadd\", catId=1, tract=0, patch=\"0,0\", objId=0x12, numExp=4, expHash=0x1eab2e92)
print(spectrum.flux[spectrum.mask == 0].sum())
" || exit 1

echo "Done."
