#!/usr/bin/env bash

#
# Script for running 2D simuator
# against simulated science spectra provided by S Johnson, U. Michigan
#
# Based on create_weekly.sh by P Price.
#
# FIXME: move bash functions from create_weekly to pfs_utils
#

# Default location of simulated object spectra
OBJ_SPECTRA_DIR="/projects/HSC/PFS/simulator/"

usage() {
    # Display usage and quit
    echo "Create simulated science images" 1>&2
    echo "" 1>&2
    echo "Usage: $0 [-f FIBERS] [-j NUMCORES] [-n] [-d OBJ_SPECTRA_DIR]" 1>&2
    echo "" 1>&2
    echo "    -f <FIBERS> : fibers to activate (all,lam,...)" 1>&2
    echo "    -j <NUMCORES> : number of cores to use" 1>&2
    echo "    -n : don't actually run the simulator" 1>&2
    echo "    -d OBJ_SPECTRA_DIR : location of object spectra" 1>&2
    echo "" 1>&2
    exit 1
}

# Parse command-line arguments
NUMCORES=1
DRYRUN=false
FIBERS=all
while getopts "hf:j:d:n" opt; do
    case "${opt}" in
        f)
            FIBERS=${OPTARG}
            ;;
        j)
            NUMCORES=${OPTARG}
            ;;
        n)
            DRYRUN=true
            ;;
        d)
            OBJ_SPECTRA_DIR=${OPTARG}
            ;;
        h | *)
            usage
            ;;
    esac
done
shift $((OPTIND-1))

# Check that $OBJECT_SPECTRA_DIR
# is specified, the directory exists
# and includes the YAML file.
if [ -z "$OBJ_SPECTRA_DIR" ] || [ -n "$1" ]; then
    usage
fi

if [ -d "$OBJ_SPECTRA_DIR" ]; then
    echo "Reading object spectra from $OBJ_SPECTRA_DIR .."
else
    echo "$OBJ_SPECTRA_DIR does not exist."
    exit 1
fi

catConfig=$OBJ_SPECTRA_DIR/catalog_config.yaml
if [ -f "$catConfig" ]; then
    echo "Reading catalog config from $catConfig .."
else
    echo "$catConfig does not exist."
    exit 1
fi

set -e

get_visits() {
    local start=$1
    local num=$2
    local stop=$((start + num))
    local visits=""
    local ii
    for ((ii=start; ii < stop ; ii++)); do
        visits+=" --visit $ii"
    done
    echo $visits
}
get_filename() {
    local visit=$1
    local arm=$2
    case $arm in
        b)
            arm=1
            ;;
        r)
            arm=2
            ;;
        m)
            arm=4
            ;;
        n)
            arm=3
            ;;
        *)
            exit 1
    esac
    echo $(printf "PFFA%06d1%1d.fits" $visit $arm)
}

make_brn() {
    local num=$1; shift;
    local visits=$(get_visits $COUNTER $num)
    (( COUNTER+=num ))
    for detector in b1 r1 n1; do
        COMMANDS+=("$( ( $DRYRUN ) && echo "echo " )makeSim $visits --detector $detector $([ $detector = "r1" ] && echo "--pfsConfig") $(echo "$@" | sed "s|@DETECTOR@|$detector|g")")
    done
}
make_m() {
    local num=$1; shift;
    local visits=$(get_visits $COUNTER $num)
    (( COUNTER+=num ))
    COMMANDS+=("$( ( $DRYRUN ) && echo "echo " )makeSim $visits --detector m1 --pfsConfig $(echo "$@" | sed "s|@DETECTOR@|m1|g")")
}
make_brmn() {
    local num=$1
    local startBR=$COUNTER
    make_brn "$@"
    local startMM=$COUNTER
    make_m "$@"
    # Link bn for bmn
    # We can get away with this because during ingestion, "visit" comes from the filename, not the header.
    local ii
    local bn
    local mm
    for ((ii=0, bn=startBR, mm=startMM; ii < num; ii++, bn++, mm++)); do
        $( ( $DRYRUN ) && echo "echo " )ln -s $(get_filename $bn b) $(get_filename $mm b)
        $( ( $DRYRUN ) && echo "echo " )ln -s $(get_filename $bn n) $(get_filename $mm n)
    done
}

COUNTER=1000 # Keep visit namespace separate to that for core weekly data
COMMANDS=()
# Objects
for pfsDesignId in 9 10; do
    # create a symlink to the relevant pfsDesign file to that makeSim can access it
    $( ( $DRYRUN ) && echo "echo " )ln -s $(printf "$OBJ_SPECTRA_DIR/pfsDesign/pfsDesign-0x%016x.fits" $pfsDesignId) .
    make_brmn 2 --pfsDesignId $pfsDesignId --exptime 1800 --type object --objSpectraDir $OBJ_SPECTRA_DIR
done
IFS=$'\n' printf '%s\n' "${COMMANDS[@]}" | xargs -d $'\n' -n 1 -P $NUMCORES $( ( ! $DRYRUN ) && echo "--verbose") sh -c
