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
butler ingest-files $DATASTORE detectorMap_bootstrap PFS-F/detectorMap/bootstrap --prefix $DRP_PFS_DATA_DIR/detectorMap $DRP_PFS_DATA_DIR/detectorMap/detectorMap-PFS-F.ecsv --transfer copy
makePfsDefects --lam
butler write-curated-calibrations $DATASTORE lsst.obs.pfs.PfsSimulator

# Setup pipe2d
export PIPE2D_CONFIG=$WORKDIR/pipe2d_config.yaml
cat <<EOF > $PIPE2D_CONFIG
butler_config: "$DATASTORE"
options:
- "--register-dataset-types"
- "--log-level=.=INFO"
- "--instrument=lsst.obs.pfs.PfsSimulator"
EOF

# Calibs
pipe2d bias -j $CORES -i PFS-F/raw/all,PFS-F/calib -o "$RERUN"/bias --instrument='PFS-F' --exposure-target-name='BIAS' --arm='b^r^m' --fail-fast -c isr:doCrosstalk=False
butler certify-calibrations $DATASTORE "$RERUN"/bias PFS-F/calib bias --begin-date 2000-01-01T00:00:00 --end-date 2050-12-31T23:59:59

pipe2d dark -j $CORES -i PFS-F/raw/all,PFS-F/calib -o "$RERUN"/dark --instrument='PFS-F' --exposure-target-name='DARK' --fail-fast -c isr:doCrosstalk=False
butler certify-calibrations $DATASTORE "$RERUN"/dark PFS-F/calib dark --begin-date 2000-01-01T00:00:00 --end-date 2050-12-31T23:59:59

pipe2d flat -j $CORES -i PFS-F/raw/all,PFS-F/calib -o "$RERUN"/flat --instrument='PFS-F' --exposure-target-name='FLAT' -d "arm != 'm'" --fail-fast -c isr:doCrosstalk=False
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

pipe2d fiberProfiles -j $CORES -i PFS-F/raw/all,PFS-F/raw/pfsConfig,PFS-F/detectorMap/bootstrap,PFS-F/calib -o "$RERUN"/fiberProfiles --instrument='PFS-F' --exposure-target-name='FLAT_ODD^FLAT_EVEN' -c measureDetectorMap:useBootstrapDetectorMap=True -c isr:doCrosstalk=False --fail-fast
butler certify-calibrations $DATASTORE "$RERUN"/fiberProfiles PFS-F/calib fiberProfiles --begin-date 2000-01-01T00:00:00 --end-date 2050-12-31T23:59:59

pipe2d detectorMap -j $CORES -i PFS-F/raw/all,PFS-F/raw/pfsConfig,PFS-F/detectorMap/bootstrap,PFS-F/calib -o "$RERUN"/detectorMap --instrument='PFS-F' --exposure-target-name='ARC' -c measureCentroids:useBootstrapDetectorMap=True -c fitDetectorMap:useBootstrapDetectorMap=True -c fitDetectorMap:fitDetectorMap.doSlitOffsets=True -c isr:doCrosstalk=False --fail-fast
butler certify-calibrations $DATASTORE "$RERUN"/detectorMap PFS-F/calib detectorMap_calib --begin-date 2000-01-01T00:00:00 --end-date 2050-12-31T23:59:59

# Single exposure pipeline
pipe2d reduceExposure -j $CORES -i PFS-F/raw/all,PFS-F/raw/pfsConfig,PFS-F/calib -o "$RERUN"/reduceExposure --instrument='PFS-F' --exposure-target-name='OBJECT' --fail-fast -c isr:doCrosstalk=False -c mergeArms:doApplyFiberNorms=False

# Science pipeline
pipe2d science -j $CORES -i PFS-F/raw/all,PFS-F/raw/pfsConfig,PFS-F/calib,skymaps,"$RERUN"/reduceExposure --skip-existing-in "$RERUN"/reduceExposure -o "$RERUN"/science --instrument='PFS-F' --exposure-target-name='OBJECT' --fail-fast -c isr:doCrosstalk=False -c fitFluxCal:fitFocalPlane.polyOrder=0 -c mergeArms:doApplyFiberNorms=False -c coaddSpectra:doApplyFiberNorms=False

# Exports products
exportPfsProducts.py -b $DATASTORE -i PFS-F/raw/pfsConfig,"$RERUN"/reduceExposure,"$RERUN"/science -o export

# Disable test until it's converted to use Gen3.
if false; then
    $HERE/test_weekly.py --raw=$DATADIR --rerun=$WORKDIR/rerun/$RERUN
fi
