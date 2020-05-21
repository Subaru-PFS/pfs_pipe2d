#!/bin/bash

# Configuration parameters
HERE=$(unset CDPATH && cd "$(dirname "$0")/.." && pwd)/  # Parent directory of this script
WORKDIR=/scratch/pprice/jenkins  # Working directory
STACK=/tigress/HSC/PFS/stack/current  # Stack directory
DISTRIB=/tigress/HSC/PFS/distrib  # Distribution directory
export SCONSFLAGS="-j 4"  # SCons build flags

# Need these on tiger to get the right environment
. /etc/profile  # Get "module"
module load rh/devtoolset/6  # Get modern compiler
module load git  # For git-lfs

set -ev

# Set parameters from Jenkins envvars
[ -n "$GIT_TAG" ] || ( echo "No GIT_TAG supplied." && exit 1 )
VERSION=$(echo "$GIT_TAG" | sed 's|[/ ]|_|g')  # Version to call it
BUILD=$WORKDIR/build/$VERSION/$(date '+%Y%m%dT%H%M%S')  # Build directory
env

if [[ $GIT_TAG =~ "_" ]]; then
    echo "Underscores are not permitted in the tag name ($TAG) due to eups munging."
    exit 1
fi

mkdir -p $BUILD
pushd $BUILD

# Build the stack
. $STACK/loadLSST.bash
"$HERE"/bin/build_pfs.sh -b "$GIT_TAG" -t current

# Build the distribution
eups distrib create --server-dir=$DISTRIB/src -S REPOSITORY_PATH='git://github.com/Subaru-PFS/$PRODUCT.git' -f generic -d eupspkg pfs_pipe2d $VERSION
eups distrib create --server-dir=$DISTRIB/Linux64 -d tarball pfs_pipe2d $VERSION

# Generate a changelog
setup pfs_pipe2d
generateChangelog.py --outfile $DISTRIB/changelog/${VERSION}.html datamodel pfs_utils drp_pfs_data obs_pfs drp_stella_data drp_stella pfs_pipe2d

# Clean up
popd
rm -rf $BUILD
