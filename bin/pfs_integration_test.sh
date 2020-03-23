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

usage() {
    echo "Exercise the PFS 2D pipeline code" 1>&2
    echo "" 1>&2
    echo "Usage: $0 [-b <BRANCH>] [-r <RERUN>] [-d DIRNAME] [-c CORES] [-n] [-C] <PREFIX>" 1>&2
    echo "" 1>&2
    echo "    -b <BRANCH> : branch of drp_stella_data to use" 1>&2
    echo "    -r <RERUN> : rerun name to use (default: 'integration')" 1>&2
    echo "    -d <DIRNAME> : directory name to give data repo (default: 'INTEGRATION')" 1>&2
    echo "    -c <CORES> : number of cores to use (default: 1)" 1>&2
    echo "    -G : don't clone or update from git" 1>&2
    echo "    -n : don't cleanup temporary products" 1>&2
    echo "    -C : don't create calibs" 1>&2
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
BUILD_CALIBS=true  # Build calibs?
while getopts ":b:c:Cd:Gnr:" opt; do
    case "${opt}" in
        b)
            BRANCH=${OPTARG}
            ;;
        c)
            CORES=${OPTARG}
            ;;
        C)
            BUILD_CALIBS=false
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

set -evx

mkdir -p $PREFIX
cd $PREFIX
TARGET="$(pwd)/$TARGET"

if $USE_GIT; then
    # Setting lfs.batch=true enables passwordless downloads with git-lfs.
    if [ -e drp_stella_data ]; then
        pushd drp_stella_data
        git fetch --all --force --prune --tags
        if [ -n $BRANCH ]; then
            git -c lfs.batch=true checkout $BRANCH || echo "Can't checkout $BRANCH"
        fi
        popd
    else
        if [ -n $BRANCH ]; then
            ( git -c lfs.batch=true clone --branch=$BRANCH --single-branch https://github.com/Subaru-PFS/drp_stella_data || git -c lfs.batch=true clone --branch=master --single-branch https://github.com/Subaru-PFS/drp_stella_data )
        else
            git -c lfs.batch=true clone --branch=master --single-branch https://github.com/Subaru-PFS/drp_stella_data
        fi
    fi
else
    if [ -n $BRANCH ]; then
    echo "Ignoring branch $BRANCH as you chose -G" >&2
    fi
fi

if [ $CORES = 1 ]; then
    batchArgs="--batch-type=none --doraise"
    runArgs="--doraise"
else
    batchArgs="--batch-type=smp --cores $CORES --doraise"
    runArgs="-j $CORES --doraise"
fi

export OMP_NUM_THREADS=1
drp_stella_data=${DRP_STELLA_DATA_DIR:-drp_stella_data}

if ( $BUILD_CALIBS ); then
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
    if ( ! $CLEANUP ); then
        calibsArgs="-n"
    fi
    pfs_build_calibs.sh -r integration -c $CORES $calibsArgs \
        -b "field=BIAS" \
        -d "field=DARK" \
        -f "field=FLAT" \
        -F "field=FLAT_ODD" -F "field=FLAT_EVEN" \
        -a "field=ARC" \
        $TARGET
fi

# Detrend only
detrend.py $TARGET --calib $TARGET/CALIB --rerun $RERUN/detrend --id visit=25 $runArgs || exit 1

# End-to-end pipeline
reduceExposure.py $TARGET --calib $TARGET/CALIB --rerun $RERUN/pipeline --id field=OBJECT $runArgs || exit 1
mergeArms.py $TARGET --calib $TARGET/CALIB --rerun $RERUN/pipeline --id field=OBJECT $runArgs || exit 1
calculateReferenceFlux.py $TARGET --calib $TARGET/CALIB --rerun $RERUN/pipeline --id field=OBJECT $runArgs || exit 1
fluxCalibrate.py $TARGET --calib $TARGET/CALIB --rerun $RERUN/pipeline --id field=OBJECT $runArgs || exit 1
coaddSpectra.py $TARGET --calib $TARGET/CALIB --rerun $RERUN/pipeline --id field=OBJECT $runArgs || exit 1

python -c "
import matplotlib
matplotlib.use('Agg')
from lsst.daf.persistence import Butler
from pfs.datamodel.utils import calculatePfsVisitHash
butler = Butler(\"${TARGET}/rerun/${RERUN}/pipeline\")
visits = [24, 25]
spectrum = butler.get(\"pfsObject\", catId=1, tract=0, patch=\"0,0\", objId=2019, nVisit=len(visits), pfsVisitHash=calculatePfsVisitHash(visits))
print(spectrum.flux[spectrum.mask == 0].sum())
spectrum.plot()
" || exit 1

echo "Done."
