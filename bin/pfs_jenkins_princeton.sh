#!/bin/bash

HERE=$(pwd)  # Starting directory (where the package is checked out)
WORKDIR=/scratch/pprice/jenkins  # Working directory
STACK=$WORKDIR/stack  # Stack directory
DISTRIB=$WORKDIR/distrib  # Distribution directory
export SCONSFLAGS="-j 4"

. /etc/profile
module load rh/devtoolset/6

set -ev

GIT_TAG=$(echo "$GIT_BRANCH" | sed 's|^.*/tags/||')  # Tag to build
VERSION=$(echo "$GIT_TAG" | sed 's|[/ ]|_|g')  # Version to call it
BUILD=$WORKDIR/build/$VERSION/$(date '+%Y%m%dT%H%M%S')  # Build directory

echo GIT_TAG=$GIT_TAG
echo VERSION=$VERSION
echo BUILD=$BUILD

env

mkdir -p $BUILD
pushd $BUILD

. $STACK/loadLSST.bash
"$HERE"/bin/build_pfs.sh -b "$GIT_TAG" -v "$VERSION" -t current
eups distrib create --server-dir=$DISTRIB -S REPOSITORY_PATH='git://github.com/Subaru-PFS/$PRODUCT.git' -f generic -d eupspkg pfs_pipe2d $VERSION
eups distrib create --server-dir=$DISTRIB -d tarball pfs_pipe2d $VERSION

popd
rm -rf $BUILD
