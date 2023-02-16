#!/usr/bin/env bash

# Default location of simulated object spectra
OBJ_SPECTRA_DIR="/projects/HSC/PFS/simulator/"

usage() {
    # Display usage and quit
    echo "Create simulated images for the weekly." 1>&2
    echo "" 1>&2
    echo "Usage: $0 [-j NUMCORES] [-n] [-d OBJ_SPECTRA_DIR] <PFS_DESIGN_ID>" 1>&2
    echo "" 1>&2
    echo "    -j <NUMCORES> : number of cores to use" 1>&2
    echo "    -n : don't actually run the simulator" 1>&2
    echo "    -d OBJ_SPECTRA_DIR : location of object spectra" 1>&2
    echo "    <PFS_DESIGN_ID> : pfsDesignId for base design" 1>&2
    echo "" 1>&2
    exit 1
}

# Parse command-line arguments
NUMCORES=1
DRYRUN=false
while getopts "hj:d:n" opt; do
    case "${opt}" in
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
PFS_DESIGN_ID=$1; shift

# Check that $OBJECT_SPECTRA_DIR is specified, the directory exists
# and includes the YAML file.
if [ -z "$OBJ_SPECTRA_DIR" ] || [ -n "$1" ] || [ -z "$PFS_DESIGN_ID" ]; then
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

# Make PfsDesign
ALT_DESIGN_ID=$((PFS_DESIGN_ID + 1))  # Alternate design: shuffled w.r.t. base
ODD_DESIGN_ID=$((PFS_DESIGN_ID + 2))  # Odd fibers of base
EVEN_DESIGN_ID=$((PFS_DESIGN_ID + 3))  # Even fibers of base
( $DRYRUN ) || transmutePfsDesign $PFS_DESIGN_ID shuffle $ALT_DESIGN_ID
( $DRYRUN ) || transmutePfsDesign $PFS_DESIGN_ID odd $ODD_DESIGN_ID
( $DRYRUN ) || transmutePfsDesign $PFS_DESIGN_ID even $EVEN_DESIGN_ID

# Build simulated images:
# * Biases: 10 brn
# * Darks: 10x1800 sec brn
# * Dithered flats: 3 at each of -4000,-2000,0,+2000,+4000 (millipixels?) in brn, nominal exposure time
# * Fiber trace: separate for odd,even fibers in brmn, nominal exposure time
# * Arcs: 1 each in Ne,HgAr,Xe,Kr in brmn, nominal exposure time
# * Objects:
#     + 3x1800 sec + 1x300 sec with constant pfsDesign, brmn
#     + 2x1800 sec with shuffled pfsDesign, brmn

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
    local category="A"
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
            category="B"
            ;;
        *)
            exit 1
    esac
    echo $(printf "PFF%s%06d1%1d.fits" $category $visit $arm)
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

COUNTER=0
COMMANDS=()
# Biases
make_brn 10 --pfsDesignId $PFS_DESIGN_ID --exptime 0 --type bias
# Darks
make_brn 10 --pfsDesignId $PFS_DESIGN_ID --exptime 1800 --type dark
# Dithered flats
make_brn 3 --pfsDesignId $PFS_DESIGN_ID --exptime 30 --type flat --xoffset 0
make_brn 3 --pfsDesignId $PFS_DESIGN_ID --exptime 30 --type flat --xoffset 2000
make_brn 3 --pfsDesignId $PFS_DESIGN_ID --exptime 30 --type flat --xoffset 4000
make_brn 3 --pfsDesignId $PFS_DESIGN_ID --exptime 30 --type flat --xoffset -2000
make_brn 3 --pfsDesignId $PFS_DESIGN_ID --exptime 30 --type flat --xoffset -4000
# Fiber trace
make_brmn 1 --pfsDesignId $ODD_DESIGN_ID --exptime 30 --type flat --imagetyp flat_odd
make_brmn 1 --pfsDesignId $EVEN_DESIGN_ID --exptime 30 --type flat --imagetyp flat_even
# Arcs
make_brmn 1 --pfsDesignId $PFS_DESIGN_ID --exptime 2 --type arc --lamps NE
make_brmn 1 --pfsDesignId $PFS_DESIGN_ID --exptime 5 --type arc --lamps HG
make_brmn 1 --pfsDesignId $PFS_DESIGN_ID --exptime 1 --type arc --lamps XE
make_brmn 1 --pfsDesignId $PFS_DESIGN_ID --exptime 1 --type arc --lamps KR
# Objects
make_brmn 3 --pfsDesignId $PFS_DESIGN_ID --exptime 1800 --type object --objSpectraDir $OBJ_SPECTRA_DIR
make_brmn 2 --pfsDesignId $ALT_DESIGN_ID --exptime 1800 --type object --objSpectraDir $OBJ_SPECTRA_DIR
make_brmn 1 --pfsDesignId $PFS_DESIGN_ID --exptime 300 --type object --objSpectraDir $OBJ_SPECTRA_DIR

IFS=$'\n' printf '%s\n' "${COMMANDS[@]}" | xargs -d $'\n' -n 1 -P $NUMCORES $( ( ! $DRYRUN ) && echo "--verbose") sh -c
