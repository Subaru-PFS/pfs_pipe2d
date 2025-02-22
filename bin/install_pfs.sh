#!/bin/bash

#
# Install the PFS 2D pipeline code.
#
# The PFS 2D pipeline is based on the LSST software stack, which we
# install first.
#

HERE=$(unset CDPATH && cd "$(dirname "$0")"/.. && pwd)

usage() {
    # Display usage and quit
    echo "Install the PFS 2D pipeline." 1>&2
    echo "" 1>&2
    echo "Usage: $0 [-b <BRANCH>] [-e] [-l] [-L <VERSION>] <PREFIX>" 1>&2
    echo "" 1>&2
    echo "    -b <BRANCH> : name of branch on PFS to install" 1>&2
    echo "    -l : limited install (w/o drp_stella, pfs_pipe2d)" 1>&2
    echo "    -L <VERSION> : version of LSST to install" 1>&2
    echo "    -t : tag name to apply" 1>&2
    echo "    -S : install LSST from source (use for non-Redhat distros)" 1>&2
    echo "    <PREFIX> : directory in which to install" 1>&2
    echo "" 1>&2
    exit 1
}


abspath() {
    # Return absolute path to file
    # $1 : relative filename
    echo "$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
}


# Parse command-line arguments
BRANCH=
LIMITED=false
LSST_VERSION=
PACKAGES=
TAG=
LSST_FROM_SOURCE=false
while getopts ":b:eh$L:p:t:S" opt; do
    case "${opt}" in
        b)
            BRANCH=${OPTARG}
            ;;
        L)
            LSST_VERSION=${OPTARG}
            ;;
        p)
            PACKAGES=${OPTARG}
            ;;
        t)
            TAG=${OPTARG}
            ;;
        S)
            LSST_FROM_SOURCE=true
            ;;
        h | *)
            usage
            ;;
    esac
done
shift $((OPTIND-1))
if [ -z "$1" ] || [ -n "$2" ]; then
    usage
fi
PREFIX=$(abspath $1)

set -ev

mkdir -p $PREFIX
cd $PREFIX

# Install LSST
lsst_args=""
[ -n "$PACKAGES" ] && lsst_args+=" -p ""$PACKAGES"""
[ -n "$LSST_VERSION" ] && lsst_args+=" -L $LSST_VERSION"
( $LSST_FROM_SOURCE ) && lsst_args+=" -S"
bash $HERE/bin/install_lsst.sh ${lsst_args}

# Setup LSST
. $PREFIX/loadLSST.bash
setup_args=""
[ -n "$LSST_VERSION" ] && setup_args+="-t $LSST_VERSION"
setup cp_pipe ${setup_args}
export -f setup

[ -e $PREFIX/pfs ] && rm -rf $PREFIX/pfs  # Want to regenerate PFS-specific packages every time
mkdir -p $PREFIX/pfs
# Install PFS packages
cd $PREFIX/pfs
build_args=""
[ -n "$BRANCH" ] && build_args+=" -b ${BRANCH}"
[ "$LIMITED" = true ] && build_args+=" -l"
[ -n "$TAG" ] && build_args+=" -t $TAG"
bash $HERE/bin/build_pfs.sh $build_args

cd $HERE

set +v

setup_args=""
if [ -n "$TAG" ]; then
    setup_args+="-t $TAG"
else
    setup_args+="<VERSION>"
fi
echo ""
echo "All done."
echo ""
echo "To use the PFS software, do:"
echo ""
echo "    source ${PREFIX}/loadLSST.bash"
echo "    setup pfs_pipe2d ${setup_args}"
echo ""
