#!/bin/bash

#
# Execute the Continuous Integration under Travis-CI
#

[ "$TRAVIS" = "true" ] || ( echo "This script is solely intended for running under Travis-CI" && exit 1 )

# Important envvars set under Travis:
# * TRAVIS_BRANCH: For builds not triggered by a pull request this is the name of the branch currently being
#   built; whereas for builds triggered by a pull request this is the name of the branch targeted by the pull
#   request (in many cases this will be master).
# * TRAVIS_PULL_REQUEST_BRANCH: If the current job is a pull request, the name of the branch from which the
#   PR originated. "" if the current job is a push build.

cd $HOME
BUILD_BRANCH=XXX
if [ -n "$TRAVIS_PULL_REQUEST_BRANCH" ]; then
    BUILD_BRANCH=$TRAVIS_PULL_REQUEST_BRANCH
else
    BUILD_BRANCH=$TRAVIS_BRANCH
fi
echo "Building branch $BUILD_BRANCH ..."

set -ev

# This is the main business
cd $HOME/pfs_pipe2d/docker
make PFS_BRANCH=$BUILD_BRANCH CORES=3 test
