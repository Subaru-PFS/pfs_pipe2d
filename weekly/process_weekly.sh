#!/usr/bin/env bash

DATADIR="/projects/HSC/PFS/weekly/weekly-20230925"
RERUN="weekly"
CORES=10
DEVELOPER=false
usage() {
    echo "Exercise the PFS 2D pipeline code" 1>&2
    echo "" 1>&2
    echo "Usage: $0 [-d DATADIR] [-r <RERUN>] [-c CORES] [-n] [-D] WORKDIR" 1>&2
    echo "" 1>&2
    echo "    -d <DATADIR> : path to raw data (default: ${DATADIR})" 1>&2
    echo "    -r <RERUN> : rerun name to use (default: ${RERUN})" 1>&2
    echo "    -c <CORES> : number of cores to use (default: ${CORES})" 1>&2
    echo "    WORKDIR : directory to use for work"
    echo "" 1>&2
    exit 1
}

while getopts "c:d:r:h" opt; do
    case "${opt}" in
        c)
            CORES=${OPTARG}
            ;;
        d)
            DATADIR=${OPTARG}
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

# Prepare the data
mkdir -p $WORKDIR/raw
cp $DATADIR/PFF[AB]*.fits $WORKDIR/raw
cp $DATADIR/pfsConfig-*.fits $WORKDIR/raw
chmod -R u+w $WORKDIR/raw
checkPfsRawHeaders.py --fix $WORKDIR/raw/PFF[AB]*.fits
checkPfsConfigHeaders.py --fix $WORKDIR/raw/pfsConfig-*.fits

# Setup the data repo
DATASTORE=$WORKDIR/repo
butler create $DATASTORE --seed-config $OBS_PFS_DIR/gen3/butler.yaml --dimension-config $OBS_PFS_DIR/gen3/dimensions.yaml --override
butler register-instrument $DATASTORE lsst.obs.pfs.PfsSimulator
butler register-skymap $DATASTORE -C $OBS_PFS_DIR/gen3/skymap_rings.py -c name=skymap
butler ingest-raws $DATASTORE $WORKDIR/raw/PFF[AB]*.fits --ingest-task lsst.obs.pfs.gen3.PfsRawIngestTask --transfer link --fail-fast
ingestPfsConfig.py $DATASTORE lsst.obs.pfs.PfsSimulator PFS-F/raw/pfsConfig skymap $WORKDIR/raw/pfsConfig*.fits --transfer link
makePfsDefects --lam
butler write-curated-calibrations $DATASTORE lsst.obs.pfs.PfsSimulator

# Calibs
pipetask run --register-dataset-types -j $CORES -b $DATASTORE --instrument lsst.obs.pfs.PfsSimulator -i PFS-F/raw/all,PFS-F/calib -o "$RERUN"/bias -p $DRP_STELLA_DIR/pipelines/bias.yaml -d "instrument='PFS-F' AND exposure.target_name = 'BIAS' AND arm IN ('b', 'r', 'm')" --fail-fast -c isr:doCrosstalk=False
butler certify-calibrations $DATASTORE "$RERUN"/bias PFS-F/calib bias --begin-date 2000-01-01T00:00:00 --end-date 2050-12-31T23:59:59

pipetask run --register-dataset-types -j $CORES -b $DATASTORE --instrument lsst.obs.pfs.PfsSimulator -i PFS-F/raw/all,PFS-F/calib -o "$RERUN"/dark -p '$DRP_STELLA_DIR/pipelines/dark.yaml' -d "instrument='PFS-F' AND exposure.target_name = 'DARK'" --fail-fast -c isr:doCrosstalk=False
butler certify-calibrations $DATASTORE "$RERUN"/dark PFS-F/calib dark --begin-date 2000-01-01T00:00:00 --end-date 2050-12-31T23:59:59

pipetask run --register-dataset-types -j $CORES -b $DATASTORE --instrument lsst.obs.pfs.PfsSimulator -i PFS-F/raw/all,PFS-F/calib -o "$RERUN"/flat -p '$DRP_STELLA_DIR/pipelines/flat.yaml' -d "instrument='PFS-F' AND exposure.target_name = 'FLAT' AND arm != 'm'" --fail-fast -c isr:doCrosstalk=False
butler certify-calibrations $DATASTORE "$RERUN"/flat PFS-F/calib fiberFlat --begin-date 2000-01-01T00:00:00 --end-date 2050-12-31T23:59:59

# Make a fake flat for arm=m, because we don't have the data to create one properly
mkdir -p $WORKDIR/flats
makeFakeFlat.py $WORKDIR/flats
cat <<EOF > $WORKDIR/flats/flats.ecsv
# %ECSV 1.0
# ---
# datatype:
# - {name: filename, datatype: string}
# - {name: instrument, datatype: string}
# - {name: arm, datatype: string}
# - {name: spectrograph, datatype: int64}
# - {name: detector, datatype: int64}
# schema: astropy-2.0
filename instrument arm spectrograph detector
$WORKDIR/flats/pfsFakeFlat-m1.fits PFS-F m 1 -1
EOF
butler ingest-files $DATASTORE fiberFlat PFS-F/flat $WORKDIR/flats/flats.ecsv --transfer copy
butler certify-calibrations $DATASTORE PFS-F/flat PFS-F/calib fiberFlat --begin-date 2000-01-01T00:00:00 --end-date 2050-12-31T23:59:59

pipetask --log-level .=INFO run --register-dataset-types -j $CORES -b $DATASTORE --instrument lsst.obs.pfs.PfsSimulator -i PFS-F/raw/all,PFS-F/raw/pfsConfig,PFS-F/calib -o "$RERUN"/bootstrap -p '$DRP_STELLA_DIR/pipelines/bootstrap.yaml' -d "instrument='PFS-F' AND (exposure IN (20, 42) OR (arm = 'm' AND exposure IN (23, 43)))" --fail-fast -c isr:doCrosstalk=False -c bootstrap:profiles.associationDepth=70 -c bootstrap:profiles.findThreshold=5000 -c bootstrap:profiles.profileRadius=2 -c bootstrap:profiles.profileSwath=2500 -c bootstrap:profiles.profileOversample=3
butler certify-calibrations $DATASTORE "$RERUN"/bootstrap PFS-F/detectorMap/bootstrap detectorMap_bootstrap --begin-date 2000-01-01T00:00:00 --end-date 2050-12-31T23:59:59

pipetask run --register-dataset-types -j $CORES -b $DATASTORE --instrument lsst.obs.pfs.PfsSimulator -i PFS-F/raw/all,PFS-F/raw/pfsConfig,PFS-F/detectorMap/bootstrap,PFS-F/calib -o "$RERUN"/detectorMap -p '$DRP_STELLA_DIR/pipelines/detectorMap.yaml' -d "instrument='PFS-F' AND exposure.target_name = 'ARC'" -c fitDetectorMap:fitDetectorMap.doSlitOffsets=True -c isr:doCrosstalk=False -c measureCentroids:connections.calibDetectorMap=detectorMap_bootstrap --fail-fast
certifyDetectorMaps.py $DATASTORE "$RERUN"/detectorMap PFS-F/calib --instrument PFS-F --begin-date 2000-01-01T00:00:00 --end-date 2050-12-31T23:59:59

pipetask run --register-dataset-types -j $CORES -b $DATASTORE --instrument lsst.obs.pfs.PfsSimulator -i PFS-F/raw/all,PFS-F/raw/pfsConfig,PFS-F/calib -o "$RERUN"/fiberProfiles -p '$DRP_STELLA_DIR/pipelines/fiberProfiles.yaml' -d "instrument='PFS-F' AND exposure.target_name IN ('FLAT_ODD', 'FLAT_EVEN')" -c isr:doCrosstalk=False --fail-fast
butler certify-calibrations $DATASTORE "$RERUN"/fiberProfiles PFS-F/calib fiberProfiles --begin-date 2000-01-01T00:00:00 --end-date 2050-12-31T23:59:59

# Single exposure pipeline
pipetask run --register-dataset-types -j $CORES -b $DATASTORE --instrument lsst.obs.pfs.PfsSimulator -i PFS-F/raw/all,PFS-F/raw/pfsConfig,PFS-F/calib -o "$RERUN"/reduceExposure -p '$DRP_STELLA_DIR/pipelines/reduceExposure.yaml' -d "instrument='PFS-F' AND exposure.target_name = 'OBJECT'" --fail-fast -c isr:doCrosstalk=False -c mergeArms:doApplyFiberNorms=False

# Science pipeline
pipetask run --register-dataset-types -j $CORES -b $DATASTORE --instrument lsst.obs.pfs.PfsSimulator -i PFS-F/raw/all,PFS-F/raw/pfsConfig,PFS-F/calib,skymaps,"$RERUN"/reduceExposure --skip-existing-in "$RERUN"/reduceExposure -o "$RERUN"/science -p '$DRP_STELLA_DIR/pipelines/science.yaml' -d "instrument='PFS-F' AND exposure.target_name = 'OBJECT'" --fail-fast -c isr:doCrosstalk=False -c fitFluxCal:fitFocalPlane.polyOrder=0 -c mergeArms:doApplyFiberNorms=False -c coaddSpectra:doApplyFiberNorms=False

# Exports products
exportPfsProducts.py -b $DATASTORE -i PFS-F/raw/pfsConfig,"$RERUN"/reduceExposure,"$RERUN"/science -o export

# Disable test until it's converted to use Gen3.
if false; then
    $HERE/test_weekly.py --raw=$DATADIR --rerun=$WORKDIR/rerun/$RERUN
fi
