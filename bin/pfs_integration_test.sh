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
    echo "Usage: $0 [-b <BRANCH>] [-r <RERUN>] [-d DIRNAME] [-c CORES] <PREFIX>" 1>&2
    echo "" 1>&2
    echo "    -b <BRANCH> : branch of drp_stella_data to use" 1>&2
    echo "    -r <RERUN> : rerun name to use (default: 'integration')" 1>&2
    echo "    -d <DIRNAME> : directory name to give data repo (default: 'INTEGRATION')" 1>&2
    echo "    -c <CORES> : number of cores to use (default: 1)" 1>&2
    echo "    -G : don't clone or update from git" 1>&2
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
while getopts ":b:c:d:Gr:" opt; do
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

eups list -s fluxmodeldata || ( echo "fluxmodeldata package is not setup" && exit 1 )

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

DATASTORE=${TARGET}
rm -rf $DATASTORE

# Preparation
checkPfsRawHeaders.py --fix $drp_stella_data/raw/PFFA*.fits
checkPfsConfigHeaders.py --fix $drp_stella_data/raw/pfsConfig-*.fits

# Setup
butler create $DATASTORE --seed-config $OBS_PFS_DIR/gen3/butler.yaml --dimension-config $OBS_PFS_DIR/gen3/dimensions.yaml --override
butler register-instrument $DATASTORE lsst.obs.pfs.PfsSimulator
butler ingest-raws $DATASTORE $drp_stella_data/raw/PFFA*.fits --ingest-task lsst.obs.pfs.gen3.PfsRawIngestTask --transfer link --fail-fast
ingestPfsConfig.py $DATASTORE lsst.obs.pfs.PfsSimulator PFS-F/raw/pfsConfig simulator $drp_stella_data/raw/pfsConfig*.fits --transfer link
makePfsDefects --lam
butler write-curated-calibrations $DATASTORE lsst.obs.pfs.PfsSimulator --collection PFS-F/calib

defineCombination.py $DATASTORE PFS-F object --where "visit.target_name = 'OBJECT'" --collection PFS-F/raw/pfsConfig --max-group-size 3
defineCombination.py $DATASTORE PFS-F quartz --where "visit.target_name = 'FLAT' AND dither = 0" --collection PFS-F/raw/pfsConfig

# Calibs
pipetask run --register-dataset-types -j $CORES -b $DATASTORE --instrument lsst.obs.pfs.PfsSimulator -i PFS-F/raw/sps,PFS-F/calib -o "$RERUN"/bias -p $DRP_STELLA_DIR/pipelines/bias.yaml -d "instrument='PFS-F' AND visit.target_name = 'BIAS'" --fail-fast -c isr:doCrosstalk=False
butler certify-calibrations $DATASTORE "$RERUN"/bias PFS-F/calib bias --begin-date 2000-01-01T00:00:00 --end-date 2050-12-31T23:59:59

pipetask run --register-dataset-types -j $CORES -b $DATASTORE --instrument lsst.obs.pfs.PfsSimulator -i PFS-F/raw/sps,PFS-F/calib -o "$RERUN"/dark -p '$DRP_STELLA_DIR/pipelines/dark.yaml' -d "instrument='PFS-F' AND visit.target_name = 'DARK'" --fail-fast -c isr:doCrosstalk=False
butler certify-calibrations $DATASTORE "$RERUN"/dark PFS-F/calib dark --begin-date 2000-01-01T00:00:00 --end-date 2050-12-31T23:59:59

pipetask run --register-dataset-types -j $CORES -b $DATASTORE --instrument lsst.obs.pfs.PfsSimulator -i PFS-F/raw/sps,PFS-F/calib -o "$RERUN"/flat -p '$DRP_STELLA_DIR/pipelines/flat.yaml' -d "instrument='PFS-F' AND visit.target_name = 'FLAT'" --fail-fast -c isr:doCrosstalk=False
butler certify-calibrations $DATASTORE "$RERUN"/flat PFS-F/calib fiberFlat --begin-date 2000-01-01T00:00:00 --end-date 2050-12-31T23:59:59

pipetask run --register-dataset-types -j $CORES -b $DATASTORE --instrument lsst.obs.pfs.PfsSimulator -i PFS-F/raw/sps,PFS-F/raw/pfsConfig,PFS-F/calib -o "$RERUN"/bootstrap -p '$DRP_STELLA_DIR/pipelines/bootstrap.yaml' -d "instrument='PFS-F' AND visit IN (11, 22)" --fail-fast -c isr:doCrosstalk=False
butler certify-calibrations $DATASTORE "$RERUN"/bootstrap PFS-F/bootstrap detectorMap_bootstrap --begin-date 2000-01-01T00:00:00 --end-date 2050-12-31T23:59:59

pipetask run --register-dataset-types -j $CORES -b $DATASTORE --instrument lsst.obs.pfs.PfsSimulator -i PFS-F/raw/sps,PFS-F/raw/pfsConfig,PFS-F/bootstrap,PFS-F/calib -o "$RERUN"/detectorMap -p '$DRP_STELLA_DIR/pipelines/detectorMap.yaml' -d "instrument='PFS-F' AND visit.target_name = 'ARC'" -c isr:doCrosstalk=False -c measureCentroids:connections.calibDetectorMap=detectorMap_bootstrap -c gatherSlitOffsets:connections.slitOffsets=detectorMap_bootstrap.slitOffsets --fail-fast
certifyDetectorMaps.py INTEGRATION $RERUN/detectorMap PFS-F/calib --instrument PFS-F --begin-date 2000-01-01T00:00:00 --end-date 2050-12-31T23:59:59

defineFiberProfilesInputs.py $DATASTORE PFS-F integrationProfiles --bright 26 --bright 27
pipetask run --register-dataset-types -j $CORES -b $DATASTORE --instrument lsst.obs.pfs.PfsSimulator -i PFS-F/raw/sps,PFS-F/fiberProfilesInputs,PFS-F/raw/pfsConfig,PFS-F/calib -o "$RERUN"/fitFiberProfiles -p '$DRP_STELLA_DIR/pipelines/fitFiberProfiles.yaml' -d "profiles_run = 'integrationProfiles'" -c fitProfiles:profiles.profileSwath=2000 -c fitProfiles:profiles.profileOversample=3 -c fitProfiles:profiles.doScatteredLight=False --fail-fast
# Alternate method of getting fiberProfiles: test that it doesn't fail
pipetask run --register-dataset-types -j $CORES -b $DATASTORE --instrument lsst.obs.pfs.PfsSimulator -i PFS-F/raw/sps,PFS-F/raw/pfsConfig,PFS-F/calib -o "$RERUN"/measureFiberProfiles -p '$DRP_STELLA_DIR/pipelines/measureFiberProfiles.yaml' -d "instrument='PFS-F' AND visit.target_name IN ('FLAT_ODD', 'FLAT_EVEN')" -c isr:doCrosstalk=False --fail-fast
butler certify-calibrations $DATASTORE "$RERUN"/fitFiberProfiles PFS-F/calib fiberProfiles --begin-date 2000-01-01T00:00:00 --end-date 2050-12-31T23:59:59

pipetask run --register-dataset-types -j $CORES -b $DATASTORE --instrument lsst.obs.pfs.PfsSimulator -i PFS-F/raw/sps,PFS-F/raw/pfsConfig,PFS-F/calib -o "$RERUN"/fiberNorms -p '$DRP_STELLA_DIR/pipelines/fiberNorms.yaml' -d "instrument='PFS-F' AND visit.target_name = 'FLAT' AND dither = 0" -c isr:doCrosstalk=False -c reduceExposure:doApplyScreenResponse=False -c reduceExposure:doBlackSpotCorrection=False -c reduceExposure:doScatteredLight=False --fail-fast
butler certify-calibrations $DATASTORE "$RERUN"/fiberNorms PFS-F/calib fiberNorms_calib --begin-date 2000-01-01T00:00:00 --end-date 2050-12-31T23:59:59

pipetask run --register-dataset-types -j $CORES -b $DATASTORE --instrument lsst.obs.pfs.PfsSimulator -i PFS-F/raw/sps,PFS-F/raw/pfsConfig,PFS-F/calib -o "$RERUN"/skyNorms -p '$DRP_STELLA_DIR/pipelines/combineSkyNorms.yaml' -d "instrument='PFS-F' AND combination = 'object'" -c isr:doCrosstalk=False -c reduceExposure:doApplyScreenResponse=False -c reduceExposure:doBlackSpotCorrection=False -c reduceExposure:doScatteredLight=False -c reduceExposure:doApplyPfiCorrection=False -c skyNorms:fitFocalPlane.order=0 --fail-fast
butler certify-calibrations $DATASTORE "$RERUN"/skyNorms PFS-F/calib skyNorms_calib --begin-date 2000-01-01T00:00:00 --end-date 2050-12-31T23:59:59

# Single exposure pipeline for observing
pipetask run --register-dataset-types -j $CORES -b $DATASTORE --instrument lsst.obs.pfs.PfsSimulator -i PFS-F/raw/sps,PFS-F/raw/pfsConfig,PFS-F/calib -o "$RERUN"/observing -p '$DRP_STELLA_DIR/pipelines/observing.yaml' -d "combination IN ('object', 'quartz')" --fail-fast -c isr:doCrosstalk=False -c reduceExposure:doApplyScreenResponse=False -c reduceExposure:doBlackSpotCorrection=False -c reduceExposure:doScatteredLight=False -c reduceExposure:doApplyPfiCorrection=False -c 'reduceExposure:targetType=[SCIENCE, SKY, FLUXSTD]'

# Science pipeline
pipetask run --register-dataset-types -j $CORES -b $DATASTORE --instrument lsst.obs.pfs.PfsSimulator -i PFS-F/raw/sps,PFS-F/raw/pfsConfig,PFS-F/calib,PFS-F/objectGroups -o "$RERUN"/science -p '$DRP_STELLA_DIR/pipelines/science.yaml' -d "combination = 'object'" --fail-fast -c isr:doCrosstalk=False -c fitFluxCal:fitFocalPlane.polyOrder=0 -c reduceExposure:doApplyScreenResponse=False -c reduceExposure:doBlackSpotCorrection=False -c reduceExposure:doScatteredLight=False -c reduceExposure:doApplyPfiCorrection=False -c 'reduceExposure:targetType=[SCIENCE, SKY, FLUXSTD]' -c cosmicray:grouping=separate

# Exports products
exportPfsProducts.py -b $DATASTORE -i PFS-F/raw/pfsConfig,"$RERUN"/science -o ${TARGET}_export

echo "Done with integration test."
