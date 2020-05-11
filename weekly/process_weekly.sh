#!/usr/bin/env bash

DATADIR="/projects/HSC/PFS/weekly"
RERUN="weekly"
CORES=10
CLEANUP=true
DEVELOPER=false
usage() {
    echo "Exercise the PFS 2D pipeline code" 1>&2
    echo "" 1>&2
    echo "Usage: $0 [-d DATADIR] [-r <RERUN>] [-c CORES] [-n] WORKDIR" 1>&2
    echo "" 1>&2
    echo "    -d <DATADIR> : path to raw data (default: ${DATADIR})" 1>&2
    echo "    -r <RERUN> : rerun name to use (default: ${RERUN})" 1>&2
    echo "    -c <CORES> : number of cores to use (default: ${CORES})" 1>&2
    echo "    -n : don't cleanup temporary products" 1>&2
    echo "    -D : developer mode (--clobber-config --no-versions)" 1>&2
    echo "    WORKDIR : directory to use for work"
    echo "" 1>&2
    exit 1
}

while getopts "c:d:Dnr:" opt; do
    case "${opt}" in
        c)
            CORES=${OPTARG}
            ;;
        d)
            DATADIR=${OPTARG}
            ;;
        D)
            DEVELOPER=true
            ;;
        n)
            CLEANUP=false
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
HERE=$(unset CDPATH && cd "$(dirname "$0")" && pwd)

set -evx

# Set up the data repo and ingest all data
mkdir -p $WORKDIR
mkdir -p $WORKDIR/CALIB
echo "lsst.obs.pfs.PfsMapper" > $WORKDIR/_mapper
ingestPfsImages.py $WORKDIR $DATADIR/PFFA*.fits
ingestPfsCalibs.py $WORKDIR --calib $WORKDIR/CALIB --validity 1800 --mode=copy $DATADIR/detectorMap-*.fits

# Build calibs
calibsArgs=""
( $DEVELOPER ) && calibsArgs+=" -D"
( ! $CLEANUP ) && calibsArgs+=" -n"

# Calibs for brn
pfs_build_calibs.sh -r $RERUN/calib/brn -c $CORES -C $WORKDIR/CALIB $calibsArgs \
    -b "field=BIAS arm=b^r^n" \
    -d "field=DARK arm=b^r^n" \
    -f "field=FLAT arm=b^r^n" \
    -F "visit=35" -F "visit=37" \
    -a "visit=39..45:2" \
    $WORKDIR
# Calibs for m
pfs_build_calibs.sh -r $RERUN/calib/m -c $CORES -C $WORKDIR/CALIB $calibsArgs \
    -F "visit=36 arm=m" -F "visit=38 arm=m" \
    -a "visit=40..46:2 arm=m" \
    $WORKDIR

runArgs="--doraise -j $CORES"
( $DEVELOPER ) && runArgs+=" --clobber-config --no-versions"

# Run the pipeline on brn
id_brn="visit=$(cat $HERE/brn_visits.dat)"
reduceExposure.py $WORKDIR --calib $WORKDIR/CALIB --rerun $RERUN/pipeline/brn --id $id_brn $runArgs || exit 1
mergeArms.py $WORKDIR --calib $WORKDIR/CALIB --rerun $RERUN/pipeline/brn --id $id_brn $runArgs || exit 1
calculateReferenceFlux.py $WORKDIR --calib $WORKDIR/CALIB --rerun $RERUN/pipeline/brn --id $id_brn $runArgs || exit 1
fluxCalibrate.py $WORKDIR --calib $WORKDIR/CALIB --rerun $RERUN/pipeline/brn --id $id_brn $runArgs || exit 1
coaddSpectra.py $WORKDIR --calib $WORKDIR/CALIB --rerun $RERUN/pipeline/brn --id $id_brn $runArgs || exit 1

# Run the pipeline on bmn
id_bmn="visit=$(cat $HERE/bmn_visits.dat)"
reduceExposure.py $WORKDIR --calib $WORKDIR/CALIB --rerun $RERUN/pipeline/bmn --id $id_bmn $runArgs || exit 1
mergeArms.py $WORKDIR --calib $WORKDIR/CALIB --rerun $RERUN/pipeline/bmn --id $id_bmn $runArgs || exit 1
calculateReferenceFlux.py $WORKDIR --calib $WORKDIR/CALIB --rerun $RERUN/pipeline/bmn --id $id_bmn $runArgs || exit 1
fluxCalibrate.py $WORKDIR --calib $WORKDIR/CALIB --rerun $RERUN/pipeline/bmn --id $id_bmn $runArgs || exit 1
coaddSpectra.py $WORKDIR --calib $WORKDIR/CALIB --rerun $RERUN/pipeline/bmn --id $id_bmn $runArgs || exit 1

$HERE/test_weekly.py --raw=$DATADIR --rerun=$WORKDIR/rerun/$RERUN
