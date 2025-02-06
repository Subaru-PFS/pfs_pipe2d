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
    echo "    -L <VERSION> : version of LSST to install" 1>&2
    echo "    -p <PACKAGES> : space-delimited list of LSST packages to install" 1>&2
    echo "    -S : install from source (use for non-Redhat distros)" 1>&2
    echo "" 1>&2
    exit 1
}


install_lsst () {
    # Following the instructions at https://pipelines.lsst.io/install/newinstall.html
    set -ev
    local version=$1  # LSST version to install
    local packages=$2  # Space-delimited list of packages
    local fromSource=$3  # Want tarball distribution?
    echo $version
    echo $packages
    echo $fromSource
    unset EUPS_DIR EUPS_PATH EUPS_PKGROOT EUPS_SHELL SETUP_EUPS
    unset CONDA_DEFAULT_ENV CONDA_EXE CONDA_PREFIX CONDA_PROMPT_MODIFIER CONDA_PYTHON_EXE CONDA_SHLVL

    # Install LSST base conda environment
    curl -OL https://ls.st/lsstinstall
    chmod u+x lsstinstall
    ./lsstinstall -T $version
    source loadLSST.bash

    # Install additional conda packages for PFS
    mamba install -y --no-update-deps mkl jupyter notebook ipython ipympl ipywidgets jupyter_contrib_nbextensions astroplan ipyevents ginga mypy black isort pygithub pyopenssl astrowidgets

    # Install LSST packages
    install_args=
    [ -n "$version" ] && install_args+=" -t $(echo $version | sed 's/\./_/g')"
    for pp in $packages ; do
        echo Installing package $pp: eups distrib install $pp $install_args --no-server-tags
        eups distrib install $pp $install_args --no-server-tags
    done
    curl -sSL https://raw.githubusercontent.com/lsst/shebangtron/main/shebangtron | python
}


# Parse command-line arguments
BRANCH=
LSST_VERSION=v28_0_1
PACKAGES="cp_pipe ctrl_bps ctrl_bps_parsl display_ds9 display_matplotlib display_astrowidgets"
FROM_SOURCE=false
while getopts ":hL:p:S" opt; do
    case "${opt}" in
        L)
            LSST_VERSION=${OPTARG}
            ;;
        p)
            PACKAGES=${OPTARG}
            ;;
        S)
            FROM_SOURCE=true
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
install_lsst $LSST_VERSION "$PACKAGES" $FROM_SOURCE
