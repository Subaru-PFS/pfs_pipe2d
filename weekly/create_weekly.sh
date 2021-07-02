#!/usr/bin/env bash

usage() {
    # Display usage and quit
    echo "Create simulated images for the weekly." 1>&2
    echo "" 1>&2
    echo "Usage: $0 [-f FIBERS] [-j NUMCORES] [-n] OBJ_SPECTRA_DIR" 1>&2
    echo "" 1>&2
    echo "    -f <FIBERS> : fibers to activate (all,lam,...)" 1>&2
    echo "    -j <NUMCORES> : number of cores to use" 1>&2
    echo "    -n : don't actually run the simulator" 1>&2
    echo "    OBJ_SPECTRA_DIR : location of object spectra" 1>&2
    echo "" 1>&2
    exit 1
}

if [[ -z "${OBJ_SPECTRA_DIR}" ]]; then
    echo "ERROR: Environment variable OBJ_SPECTRA_DIR is undefined."
    echo " This is needed to simulate astrophysical objects"
    exit 1
fi

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
        h | *)
            usage
            ;;
    esac
done
shift $((OPTIND-1))
OBJ_SPECTRA_DIR=$1; shift
if [ -z "$OBJ_SPECTRA_DIR" ] || [ -n "$1" ]; then
    usage
fi

set -e

# Make PfsDesign
# 1: Base design: 20% sky, 10% fluxstd, rest galaxies
# 2: Shuffled w.r.t. 1
# 3: Odd fibers of 1
# 4: Even fibers of 1
( $DRYRUN ) || makePfsDesign --fibers "$FIBERS" --spectrograph 1 --pfsDesignId 1 --scienceCatId 1 --scienceObjId "18 55 71 76 93 94 105 112 115 120 125 139 140 146 148 160 177 178 185 212 215 218 234 242 249 253 277 292 294 304 308 314 329 331 336 342 343 346 358 359 382 387 391 392 396 398 406 416 427 428 429 431 439 440 446 447 449 452 456 462 469 474 476 481 488 492 496 497 499 506 508 534 537 560 565 566 567 571 580 585 586 591 592 596 605 606 607 613 614 615 619 623 624 626 628 632 633 637 645 647 654 674 685 689 700 702 704 724 725 726 727 733 737 741 762 764 765 766 775 783 791 792 797 798 804 809 814 820 823 824 832 833 835 838 849 852 866 867 868 869 879 893 906 939 954 959 961 962 967 975 976 978 983 991 997 1002 1010 1022 1027 1029 1034 1035 1065 1070 1071 1075 1077 1078 1084 1086 1103 1104 1109 1113 1118 1120 1127 1146 1155 1165 1167 1171 1178 1181 1186 1192 1194 1195 1200 1201 1202 1207 1212 1215 1217 1219 1225 1227 1228 1243 1245 1246 1279 1289 1290 1294 1299 1301 1313 1314 1319 1323 1324 1328 1336 1341 1342 1344 1345 1348 1351 1352 1354 1355 1357 1360 1371 1373 1387 1392 1396 1400 1405 1410 1411 1415 1423 1424 1427 1430 1431 1440 1441 1453 1455 1456 1459 1466 1474 1475 1483 1489 1492 1494 1496 1501 1502 1505 1511 1517 1518 1528 1536 1551 1552 1571 1574 1593 1601 1605 1608 1621 1632 1636 1639 1643 1648 1653 1655 1659 1660 1665 1667 1668 1675 1676 1680 1692 1695 1715 1741 1743 1762 1764 1765 1766 1767 1770 1772 1783 1784 1788 1798 1822 1824 1849 1862 1865 1905 1908 1914 1919 1921 1922 1928 1935 1941 1944 1947 1948 1950 1953 1955 1962 1964 1965 1968 1970 1972 1973 1975 1976 1980 1981 1982 1986 1999 2005 2012 2015 2019 2035 2040 2044 2047 2055 2071 2074 2076 2082 2097 2104 2106 2111 2114 2120 2127 2131 2132 2133 2135 2136 2143 2149 2155 2157 2158 2162 2164 2177 2181 2184 2188 2189 2201 2210 2217 2238 2242 2244 2251 2257 2258 2262 2263 2271 2274 2285 2291 2296 2299 2307 2311 2312 2336 2343 2344 2348 2354 2358 2375 2376 2377 2378 2380 2382 2383 2385 2403 2405 2416 2417 2423 2427 2439 2446 2451 2452 2453 2458"
( $DRYRUN ) || transmutePfsDesign 1 shuffle 2
( $DRYRUN ) || transmutePfsDesign 1 odd 3
( $DRYRUN ) || transmutePfsDesign 1 even 4

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

COUNTER=0
COMMANDS=()
# Biases
make_brn 10 --pfsDesignId 1 --exptime 0 --type bias
# Darks
make_brn 10 --pfsDesignId 1 --exptime 1800 --type dark
# Dithered flats
make_brn 3 --pfsDesignId 1 --exptime 30 --type flat --xoffset 0
make_brn 3 --pfsDesignId 1 --exptime 30 --type flat --xoffset 2000
make_brn 3 --pfsDesignId 1 --exptime 30 --type flat --xoffset 4000
make_brn 3 --pfsDesignId 1 --exptime 30 --type flat --xoffset -2000
make_brn 3 --pfsDesignId 1 --exptime 30 --type flat --xoffset -4000
# Fiber trace
make_brmn 1 --pfsDesignId 3 --exptime 30 --type flat --imagetyp flat_odd
make_brmn 1 --pfsDesignId 4 --exptime 30 --type flat --imagetyp flat_even
# Arcs
make_brmn 1 --pfsDesignId 1 --exptime 2 --type arc --lamps NE
make_brmn 1 --pfsDesignId 1 --exptime 5 --type arc --lamps HG
make_brmn 1 --pfsDesignId 1 --exptime 1 --type arc --lamps XE
make_brmn 1 --pfsDesignId 1 --exptime 1 --type arc --lamps KR
# Objects
make_brmn 3 --pfsDesignId 1 --exptime 1800 --type object --objSpectraDir $OBJ_SPECTRA_DIR
make_brmn 2 --pfsDesignId 2 --exptime 1800 --type object --objSpectraDir $OBJ_SPECTRA_DIR
make_brmn 1 --pfsDesignId 1 --exptime 300 --type object --objSpectraDir $OBJ_SPECTRA_DIR

IFS=$'\n' printf '%s\n' "${COMMANDS[@]}" | xargs -d $'\n' -n 1 -P $NUMCORES $( ( ! $DRYRUN ) && echo "--verbose") sh -c
