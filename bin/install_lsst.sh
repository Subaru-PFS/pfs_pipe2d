#!/bin/bash

#
# Install the LSST components required by the PFS pipeline
#

HERE=$(unset CDPATH && cd "$(dirname "$0")"/.. && pwd)


usage() {
    # Display usage and quit
    echo "Install the PFS 2D pipeline in the current directory." 1>&2
    echo "" 1>&2
    echo "Usage: $0 [-e] [-L <VERSION>] [-p PACKAGES]" 1>&2
    echo "" 1>&2
    echo "    -e : install bleeding-edge LSST" 1>&2
    echo "    -L <VERSION> : version of LSST to install" 1>&2
    echo "    -p <PACKAGES> : space-delimited list of LSST packages to install" 1>&2
    echo "" 1>&2
    exit 1
}


install_lsst () {
    # Following the instructions at https://pipelines.lsst.io/install/newinstall.html
    set -ev
    local version=$1  # LSST version to install
    local packages=$2  # Space-delimited list of packages
    unset EUPS_DIR EUPS_PATH EUPS_PKGROOT EUPS_SHELL SETUP_EUPS
    curl -OL https://raw.githubusercontent.com/lsst/lsst/16.0/scripts/newinstall.sh
    bash newinstall.sh -bct
    source loadLSST.bash

    install_args=
    [ -n "$version" ] && install_args+=" -t $version"
    for pp in $packages ; do
        echo Installing package $pp: eups distrib install $pp $install_args --no-server-tags
        eups distrib install $pp $install_args --no-server-tags
    done
    curl -sSL https://raw.githubusercontent.com/lsst/shebangtron/master/shebangtron | python
}


# Parse command-line arguments
BRANCH=
LIMITED=false
LSST_VERSION=v16_0
PACKAGES="pipe_drivers display_ds9 display_matplotlib"
TAG=
while getopts ":e:hL:p:" opt; do
    case "${opt}" in
        e)
            LSST_VERSION=
            ;;
        L)
            LSST_VERSION=${OPTARG}
            ;;
        p)
            PACKAGES=${OPTARG}
            ;;
        h | *)
            usage
            ;;
    esac
done
shift $((OPTIND-1))
if [ -n "$1" ]; then
    usage
fi

set -ev
install_lsst $LSST_VERSION "$PACKAGES"
