#!/bin/bash

#
# Install the PFS 2D pipeline code.
#
# The PFS 2D pipeline is based on the LSST software stack, which is itself
# based on Anaconda so there's a lot to install. When it's done you should
# source <PREFIX>/pfs_setups.sh to set up your environment.
#

set -ev

# Configuration
CONDA_VERSION=4.2.12  # Version of Conda to install
GIT_LFS_VERSION=1.4.4  # Version of git-lfs to install
LSST_SOURCE=http://conda.lsst.codes/stack/0.12.1  # Source of LSST stack
LSST_VERSION=lsst-v12_1  # Version of LSST stack to install
CONDA_FLAVOR=  # Flavor (e.g., Linux vs Mac) of Conda to install
CONDA_MD5=  # Expected MD5 of Conda installation tarball
GIT_LFS_FLAVOR=  # Flavor (e.g., Linux vs Mac) of git-lfs to install
case $(uname -s) in
    Darwin)
        CONDA_FLAVOR=MacOSX-x86_64
        CONDA_MD5=ff3d7b69e32e1e4246176fb90f8480c8
        GIT_LFS_FLAVOR=darwin-amd64
        ;;
    Linux)
        CONDA_FLAVOR=Linux-x86_64
        CONDA_MD5=c8b836baaa4ff89192947e4b1a70b07e
        GIT_LFS_FLAVOR=linux-amd64
        ;;
    *)
        echo "Unrecognised system name: $(uname -s)"
        exit 1
esac

usage() {
    # Display usage and quit
    echo "Install the PFS 2D pipeline." 1>&2
    echo "" 1>&2
    echo "Usage: $0 [-b <BRANCH>] <PREFIX>" 1>&2
    echo "" 1>&2
    echo "    -b <BRANCH> : name of branch on PFS to install" 1>&2
    echo "    <PREFIX> : directory in which to install" 1>&2
    echo "" 1>&2
    exit 1
}

build_package () {
    set -ev
    # Build a package from git, optionally checking out a particular version
    local repo=$1  # Repository
    local commit=$2  # Commit/branch to checkout
    local required=${3:-false}  # Commit/branch is required?
    rm -rf $(basename $repo)
    git clone $repo
    pushd $(basename $repo)
    if [ -n "$commit" ]; then
        git checkout $commit || ( echo "Cannot checkout $commit" && ! $required )
    fi
    setup -k -r .
    [ -e SConstruct ] && scons
    find . -name "*.os" -exec rm {} \;
    popd
}

path_prepend () {
    # Prepend paths to a variable, making sure we're not duplicating anything.
    local target=$1  # Target variable name (e.g., PATH)
    local pathlist=$2  # Paths to add (colon-delimited)
    local add=""  # Paths to add
    local new  # New path to include
    local IFS=':'
    for new in $pathlist ; do
        unset IFS
        if [[ ! "${!target}" =~ "(^|:)$new($|:)" ]] ; then
            local IFS=':'
            add=${add:+$add:}$new
        fi
    done
    local IFS=':'
    export $target="${add}${!target:+:${!target}}"
}

# Parse command-line arguments
BRANCH=
while getopts ":b:s" opt; do
    case "${opt}" in
        b)
            BRANCH=${OPTARG}
            ;;
        *)
            usage
            ;;
    esac
done
shift $((OPTIND-1))

PREFIX=$1
if [ -z "$PREFIX" ] || [ -n "$2" ]; then
    usage
fi

HERE=$(unset CDPATH && cd "$(dirname "$0")"/.. && pwd)
SETUPS_BASE=$PREFIX/pfs_setups.sh
SETUPS_LSST=$PREFIX/lsst/setups_lsst.sh
SETUPS_PFS=$PREFIX/pfs/setups_pfs.sh
mkdir -p $PREFIX
cd $PREFIX

# Install Conda
if [ ! -e "$PREFIX/conda" ] || [ ! -e "$PREFIX/conda/bin/conda" ]; then
    [ -e "$PREFIX/conda" ] && rm -rf "$PREFIX/conda"
    CONDA_INSTALLER=Miniconda2-${CONDA_VERSION}-${CONDA_FLAVOR}.sh
    wget https://repo.continuum.io/miniconda/${CONDA_INSTALLER}
    if [ "$(md5sum ${CONDA_INSTALLER})" != "$CONDA_MD5  $CONDA_INSTALLER" ]; then
        echo "MD5 mismatch for ${CONDA_INSTALLER}"
        exit 1
    fi
    chmod u+x $CONDA_INSTALLER
    ./$CONDA_INSTALLER -b -p $PREFIX/conda
fi
path_prepend PATH $PREFIX/conda/bin

# Install LSST stack
if [ ! -e $PREFIX/conda/envs/$LSST_VERSION ]; then
    conda config --add channels $LSST_SOURCE
    conda create --name $LSST_VERSION python=2 --yes
    conda install -n $LSST_VERSION anaconda --yes
    conda install -n $LSST_VERSION lsst-distrib --yes
    conda install -n $LSST_VERSION future --yes
    if [ $(uname -s) = "Linux" ]; then
        conda install -n $LSST_VERSION libgcc isl=0.12.2 --yes
        conda install -n $LSST_VERSION -c msarahan gcc-5 --yes
    fi

    # Delete some large files that we don't need
    rm -rf conda/pkgs/lsst-mariadb-*/opt/lsst/mariadb/mysql-test
    rm -f conda/pkgs/lsst-activemqcpp-*/opt/lsst/activemqcpp/lib/*.a
    conda clean --tarballs --source-cache --yes
fi

# Install git-lfs
command -v git-lfs > /dev/null 2>&1 || {
    GIT_LFS_INSTALLER=https://github.com/git-lfs/git-lfs/releases/download/v${GIT_LFS_VERSION}/git-lfs-${GIT_LFS_FLAVOR}-${GIT_LFS_VERSION}.tar.gz
    wget $GIT_LFS_INSTALLER
    tar xvzf $(basename $GIT_LFS_INSTALLER)
    install git-lfs-${GIT_LFS_VERSION}/git-lfs $PREFIX/conda/bin
    git lfs install
}

mkdir -p $PREFIX/lsst
touch $SETUPS_LSST
[ -e $PREFIX/pfs ] && rm -rf $PREFIX/pfs  # Want to regenerate PFS-specific packages every time
mkdir -p $PREFIX/pfs
touch $SETUPS_PFS

# Create a script you can source to get everything.
# This is quick to regenerate every time; saves the trouble of checking nothing's changed.
[ -e $SETUPS_BASE ] && rm $SETUPS_BASE
echo export PATH=$PREFIX/conda/bin:$PATH >> $SETUPS_BASE
echo export PYTHONPATH=$PREFIX/conda/envs/${LSST_VERSION}/lib/python2.7/site-packages:$PYTHONPATH >> $SETUPS_BASE
echo . activate $LSST_VERSION >> $SETUPS_BASE
echo export OPAL_PREFIX=$PREFIX/conda/envs/$LSST_VERSION >> $SETUPS_BASE
echo . $PREFIX/conda/envs/$LSST_VERSION/bin/eups-setups.sh >> $SETUPS_BASE
echo setup lsst_distrib >> $SETUPS_BASE
echo . $SETUPS_LSST >> $SETUPS_BASE
echo . $SETUPS_PFS >> $SETUPS_BASE

. $SETUPS_BASE

# Install LSST overrides
cd $PREFIX/lsst
if [ ! -e $PREFIX/lsst/lsst_overrides.txt ] || cmp --quiet $PREFIX/lsst/lsst_overrides.txt $HERE/lsst_overrides.txt ; then
    sed -e 's/#.*$//' -e '/^$/d' $HERE/lsst_overrides.txt | while read REPO COMMIT; do
        build_package $REPO $COMMIT true
        echo setup -j -r $PREFIX/lsst/$(basename $REPO) >> $SETUPS_LSST
    done
    cp $HERE/lsst_overrides.txt $PREFIX/lsst/
fi

# Install PFS packages
cd $PREFIX/pfs
sed -e 's/#.*$//' -e '/^$/d' $HERE/pfs_packages.txt | while read REPO; do
    build_package $REPO $BRANCH
    echo setup -j -r $PREFIX/pfs/$(basename $REPO) >> $SETUPS_PFS
done

# Check that it's working
cd $HERE
. $SETUPS_BASE
python -c 'import pfs.drp.stella'

echo "All done."
echo ""
echo "To use the PFS software, do:"
echo ""
echo "    source $SETUPS_BASE"
echo ""
