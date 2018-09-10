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
ingestImages.py $TARGET --mode=link \
    $drp_stella_data/raw/*.fits \
    -c clobber=True register.ignore=True

ingestCalibs.py $TARGET --calib $TARGET/CALIB --validity 1800 \
		$OBS_PFS_DIR/pfs/camera/pfsDetectorMap-005833-r1.fits --mode=copy || exit 1

# Build bias
constructBias.py $TARGET --calib $TARGET/CALIB --rerun $RERUN/calib --id visit=3140..3149 $batchArgs || exit 1
ingestCalibs.py $TARGET --calib $TARGET/CALIB --validity 1000 \
		    $TARGET/rerun/$RERUN/calib/BIAS/*.fits || exit 1
( $CLEANUP && rm -r $TARGET/rerun/$RERUN/calib) || true

# Build dark
constructDark.py $TARGET --calib $TARGET/CALIB --rerun $RERUN/calib --id visit=3154..3158 $batchArgs || exit 1
ingestCalibs.py $TARGET --calib $TARGET/CALIB --validity 1000 \
		    $TARGET/rerun/$RERUN/calib/DARK/*.fits || exit 1
( $CLEANUP && rm -r $TARGET/rerun/$RERUN/calib) || true

# Build flat
constructFiberFlat.py $TARGET --calib $TARGET/CALIB --rerun $RERUN/calib \
            --id visit=5699..5753:9^5768..5813:9^5822 $batchArgs || exit 1
ingestCalibs.py $TARGET --calib $TARGET/CALIB --validity 1000 \
		    $TARGET/rerun/$RERUN/calib/FLAT/*.fits || exit 1
( $CLEANUP && rm -r $TARGET/rerun/$RERUN/calib) || true

# Build fiber trace
constructFiberTrace.py $TARGET --calib $TARGET/CALIB --rerun $RERUN/calib \
		       --id visit=5694 $batchArgs || exit 1
sqlite3 $TARGET/CALIB/calibRegistry.sqlite3 "delete from detectormap where visit0=$(echo pfsDetectorMap-005833-r1.fits | perl -ne '/pfsDetectorMap-0*([^-]+)-/; print $1');"
ingestCalibs.py $TARGET --calib $TARGET/CALIB --validity 1000 \
		    $TARGET/rerun/$RERUN/calib/{FIBERTRACE,DETECTORMAP}/*.fits || exit 1
( $CLEANUP && rm -r $TARGET/rerun/$RERUN/calib ) || true

# Process arc
reduceArc.py $TARGET --calib $TARGET/CALIB --rerun $RERUN/arc --id visit=5830^5825 -j $CORES || exit 1
# Read arc
python -c "
from lsst.daf.persistence import Butler
butler = Butler(\"${TARGET}/rerun/${RERUN}/arc\")
arc = butler.get(\"pfsArm\", visit=5825, arm=\"r\", spectrograph=1)
print(arc.lam)
print(arc.flux)
" || exit 1
( $CLEANUP && rm -r $TARGET/rerun/$RERUN/arc ) || true

# Detrend only
detrend.py $TARGET --calib $TARGET/CALIB --rerun $RERUN/detrend --id visit=5830

echo "Done."
