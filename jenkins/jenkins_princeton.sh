#!/bin/bash

# Configuration parameters
HERE=$(pwd)  # Starting directory (where the package is checked out)
WORKDIR=/scratch/pprice/jenkins  # Working directory
STACK=/tigress/HSC/PFS/stack/current  # Stack directory
DISTRIB=/tigress/HSC/PFS/distrib  # Distribution directory
export SCONSFLAGS="-j 4"  # SCons build flags

# Need these on tiger to get the right environment
. /etc/profile  # Get "module"
module load rh/devtoolset/6  # Get modern compiler

set -ev

# Set parameters from Jenkins envvars
GIT_TAG=$(git describe --tags --always)  # Tag to build
VERSION=$(echo "$GIT_TAG" | sed 's|[/ ]|_|g')  # Version to call it
BUILD=$WORKDIR/build/$VERSION/$(date '+%Y%m%dT%H%M%S')  # Build directory
env

mkdir -p $BUILD
pushd $BUILD

# Build the stack
. $STACK/loadLSST.bash
"$HERE"/bin/build_pfs.sh -b "$GIT_TAG" -t current

# Build the distribution
eups distrib create --server-dir=$DISTRIB/src -S REPOSITORY_PATH='git://github.com/Subaru-PFS/$PRODUCT.git' -f generic -d eupspkg pfs_pipe2d $VERSION
eups distrib create --server-dir=$DISTRIB/Linux64 -d tarball pfs_pipe2d $VERSION

# Clean up
popd
rm -rf $BUILD
