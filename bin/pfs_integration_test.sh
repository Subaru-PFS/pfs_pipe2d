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
    echo "Usage: $0 [-b <BRANCH>] [-r <RERUN>] [-d DIRNAME] [-c CORES] [-n] [-C] [-2] [-3] <PREFIX>" 1>&2
    echo "" 1>&2
    echo "    -b <BRANCH> : branch of drp_stella_data to use" 1>&2
    echo "    -r <RERUN> : rerun name to use (default: 'integration')" 1>&2
    echo "    -d <DIRNAME> : directory name to give data repo (default: 'INTEGRATION')" 1>&2
    echo "    -c <CORES> : number of cores to use (default: 1)" 1>&2
    echo "    -G : don't clone or update from git" 1>&2
    echo "    -n : don't cleanup temporary products" 1>&2
    echo "    -C : don't create calibs" 1>&2
    echo "    -2 : run Gen2 only" 1>&2
    echo "    -3 : run Gen3 only" 1>&2
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
RUN_GEN2=true  # run Gen2 tests?
RUN_GEN3=true  # run Gen3 tests?
while getopts ":b:c:Cd:Gnr:23" opt; do
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
        2)
            RUN_GEN2=true
            RUN_GEN3=false
            ;;
        3)
            RUN_GEN2=false
            RUN_GEN3=true
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

    setup -jr drp_stella_data
else
    if [ -n $BRANCH ]; then
    echo "Ignoring branch $BRANCH as you chose -G" >&2
    fi
fi

export OMP_NUM_THREADS=1
drp_stella_data=${DRP_STELLA_DATA_DIR:-drp_stella_data}

if $RUN_GEN2; then

    if [ $CORES = 1 ]; then
        batchArgs="--batch-type=none --doraise"
        runArgs="--doraise"
    else
        batchArgs="--batch-type=smp --cores $CORES --doraise"
        runArgs="-j $CORES --doraise"
    fi

    if ( $CLEANUP ); then
        cleanFlag="--clean"
    else
        cleanFlag=""
    fi

    export PYTHONWARNINGS="ignore:Gen2 Butler has been deprecated:FutureWarning:"

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

        makePfsDefects --lam
        ingestCuratedCalibs.py "$TARGET" --calib "$TARGET"/CALIB "$DRP_PFS_DATA_DIR"/curated/pfs/defects

        # Build calibs
        generateCommands.py "$TARGET" \
            "$PFS_PIPE2D_DIR"/examples/integration_test.yaml \
            calib.sh \
            --rerun="$RERUN" --init --blocks=test_calib \
            -j "$CORES" $cleanFlag

        sh calib.sh
    fi

    # Detrend only
    detrend.py $TARGET --calib $TARGET/CALIB --rerun $RERUN/detrend --id visit=25 $runArgs || exit 1

    # End-to-end pipeline
    generateCommands.py "$TARGET" \
        "$PFS_PIPE2D_DIR"/examples/integration_test.yaml \
        science.sh \
        --rerun="$RERUN" --blocks=test_science \
        -j "$CORES" $cleanFlag

    sh science.sh

    python -c "
import matplotlib
matplotlib.use('Agg')
from lsst.daf.persistence import Butler
from pfs.datamodel.utils import calculatePfsVisitHash
butler = Butler(\"${TARGET}/rerun/${RERUN}/pipeline\")
visits = [24, 25]
spectrum = butler.get(\"pfsObject\", catId=1, tract=0, patch=\"0,0\", objId=55, nVisit=len(visits), pfsVisitHash=calculatePfsVisitHash(visits))
print(spectrum.flux[spectrum.mask == 0].sum())
spectrum.plot()
" || exit 1

    echo "Done with Gen2."
fi

if $RUN_GEN3; then

    DATASTORE=${TARGET}_Gen3
    rm -rf $DATASTORE

    # Preparation
    checkPfsRawHeaders.py --fix $drp_stella_data/raw/PFFA*.fits
    checkPfsConfigHeaders.py --fix $drp_stella_data/raw/pfsConfig-*.fits

    # Setup
    butler create $DATASTORE --seed-config $OBS_PFS_DIR/gen3/butler.yaml --dimension-config $OBS_PFS_DIR/gen3/dimensions.yaml --override
    butler register-instrument $DATASTORE lsst.obs.pfs.PfsSimulator
    butler register-skymap $DATASTORE -C $OBS_PFS_DIR/gen3/skymap_discrete.py -c name=simulator
    butler ingest-raws $DATASTORE $drp_stella_data/raw/PFFA*.fits --ingest-task lsst.obs.pfs.gen3.PfsRawIngestTask --transfer link --fail-fast
    ingestPfsConfig.py $DATASTORE lsst.obs.pfs.PfsSimulator PFS-F/raw/pfsConfig simulator $drp_stella_data/raw/pfsConfig*.fits --transfer link
    butler ingest-files $DATASTORE detectorMap_bootstrap PFS-F/detectorMap/bootstrap --prefix $DRP_PFS_DATA_DIR/detectorMap $DRP_PFS_DATA_DIR/detectorMap/detectorMap-sim.ecsv --transfer copy
    makePfsDefects --lam
    butler write-curated-calibrations $DATASTORE lsst.obs.pfs.PfsSimulator

    # Calibs
    pipetask run --register-dataset-types -j $CORES -b $DATASTORE --instrument lsst.obs.pfs.PfsSimulator -i PFS-F/raw/all,PFS-F/calib -o "$RERUN"/bias -p $DRP_STELLA_DIR/pipelines/bias.yaml -d "instrument='PFS-F' AND exposure.target_name = 'BIAS'" --fail-fast -c isr:doCrosstalk=False
    butler certify-calibrations $DATASTORE "$RERUN"/bias PFS-F/calib bias --begin-date 2000-01-01T00:00:00 --end-date 2050-12-31T23:59:59

    pipetask run --register-dataset-types -j $CORES -b $DATASTORE --instrument lsst.obs.pfs.PfsSimulator -i PFS-F/raw/all,PFS-F/calib -o "$RERUN"/dark -p '$DRP_STELLA_DIR/pipelines/dark.yaml' -d "instrument='PFS-F' AND exposure.target_name = 'DARK'" --fail-fast -c isr:doCrosstalk=False
    butler certify-calibrations $DATASTORE "$RERUN"/dark PFS-F/calib dark --begin-date 2000-01-01T00:00:00 --end-date 2050-12-31T23:59:59

    pipetask run --register-dataset-types -j $CORES -b $DATASTORE --instrument lsst.obs.pfs.PfsSimulator -i PFS-F/raw/all,PFS-F/calib -o "$RERUN"/flat -p '$DRP_STELLA_DIR/pipelines/flat.yaml' -d "instrument='PFS-F' AND exposure.target_name = 'FLAT'" --fail-fast -c isr:doCrosstalk=False
    butler certify-calibrations $DATASTORE "$RERUN"/flat PFS-F/calib fiberFlat --begin-date 2000-01-01T00:00:00 --end-date 2050-12-31T23:59:59

    pipetask run --register-dataset-types -j $CORES -b $DATASTORE --instrument lsst.obs.pfs.PfsSimulator -i PFS-F/raw/all,PFS-F/raw/pfsConfig,PFS-F/detectorMap/bootstrap,PFS-F/calib -o "$RERUN"/fiberProfiles -p '$DRP_STELLA_DIR/pipelines/fiberProfiles.yaml' -d "instrument='PFS-F' AND exposure.target_name IN ('FLAT_ODD', 'FLAT_EVEN')" -c measureDetectorMap:useBootstrapDetectorMap=True -c isr:doCrosstalk=False --fail-fast
    butler certify-calibrations $DATASTORE "$RERUN"/fiberProfiles PFS-F/calib fiberProfiles --begin-date 2000-01-01T00:00:00 --end-date 2050-12-31T23:59:59

    pipetask run --register-dataset-types -j $CORES -b $DATASTORE --instrument lsst.obs.pfs.PfsSimulator -i PFS-F/raw/all,PFS-F/raw/pfsConfig,PFS-F/detectorMap/bootstrap,PFS-F/calib -o "$RERUN"/detectorMap -p '$DRP_STELLA_DIR/pipelines/detectorMap.yaml' -d "instrument='PFS-F' AND exposure.target_name = 'ARC'" -c measureCentroids:useBootstrapDetectorMap=True -c fitDetectorMap:useBootstrapDetectorMap=True -c isr:doCrosstalk=False --fail-fast
    butler certify-calibrations $DATASTORE "$RERUN"/detectorMap PFS-F/calib detectorMap --begin-date 2000-01-01T00:00:00 --end-date 2050-12-31T23:59:59

    # Single exposure pipeline
    pipetask run --register-dataset-types -j $CORES -b $DATASTORE --instrument lsst.obs.pfs.PfsSimulator -i PFS-F/raw/all,PFS-F/raw/pfsConfig,PFS-F/calib -o "$RERUN"/reduceExposure -p '$DRP_STELLA_DIR/pipelines/reduceExposure.yaml' -d "instrument='PFS-F' AND exposure.target_name = 'OBJECT'" --fail-fast -c isr:doCrosstalk=False

    # Science pipeline
    pipetask run --register-dataset-types -j $CORES -b $DATASTORE --instrument lsst.obs.pfs.PfsSimulator -i PFS-F/raw/all,PFS-F/raw/pfsConfig,PFS-F/calib,skymaps -o "$RERUN"/science -p '$DRP_STELLA_DIR/pipelines/science.yaml' -d "instrument='PFS-F' AND exposure.target_name = 'OBJECT'" --fail-fast -c isr:doCrosstalk=False

    # Exports products
    exportPfsProducts.py -b $DATASTORE -i PFS-F/raw/pfsConfig,"$RERUN"/science -o ${TARGET}_export

    echo "Done with Gen3."
fi
