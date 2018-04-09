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
    echo "    -e : install bleeding-edge LSST" 1>&2
    echo "    -l : limited install (w/o drp_stella, pfs_pipe2d)" 1>&2
    echo "    -L <VERSION> : version of LSST to install" 1>&2
    echo "    -t : tag name to apply" 1>&2
    echo "    <PREFIX> : directory in which to install" 1>&2
    echo "" 1>&2
    exit 1
}

install_lsst () {
    # Following the instructions at https://pipelines.lsst.io/install/newinstall.html
    set -ev
    local version=$1  # Should be "-t XXX" or nothing at all
    unset EUPS_DIR EUPS_PATH EUPS_PKGROOT EUPS_SHELL SETUP_EUPS
    curl -OL https://raw.githubusercontent.com/lsst/lsst/master/scripts/newinstall.sh
    bash newinstall.sh -bct
    source loadLSST.bash
    install_args=
    [ -n "$version" ] && install_args+=" -t $version"
    eups distrib install lsst_distrib $install_args --no-server-tags
    curl -sSL https://raw.githubusercontent.com/lsst/shebangtron/master/shebangtron | python
}


# Parse command-line arguments
BRANCH=
LIMITED=false
LSST_VERSION=w_2018_13
TAG=
while getopts ":b:ehlL:t:" opt; do
    case "${opt}" in
        b)
            BRANCH=${OPTARG}
            ;;
        e)
            LSST_VERSION=
            ;;
        l)
            LIMITED=true
            ;;
        L)
            LSST_VERSION=${OPTARG}
            ;;
        t)
            TAG=${OPTARG}
            ;;
        h | *)
            usage
            ;;
    esac
done
shift $((OPTIND-1))

PREFIX=$1
if [ -z "$PREFIX" ] || [ -n "$2" ]; then
    usage
fi

set -ev

mkdir -p $PREFIX
cd $PREFIX
install_lsst $LSST_VERSION
setup_args=""
[ -n "$LSST_VERSION" ] && setup_args+="-t $LSST_VERSION"
setup lsst_distrib ${setup_args}
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
