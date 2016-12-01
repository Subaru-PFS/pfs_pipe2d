#!/bin/bash

#
# Execute the Continuous Integration under Travis-CI
#

set -ev

[ "$TRAVIS" = "true" ] || ( echo "This script is solely intended for running under Travis-CI" && exit 1 )

# Work around log length limitation (4 MB) by trapping all output.
# In the event of an error, we'll dump the last 100 lines.
# This code from http://stackoverflow.com/a/26082445/834250
export PING_SLEEP=30s
export WORKDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
export BUILD_OUTPUT=$WORKDIR/build.out
touch $BUILD_OUTPUT
dump_output() {
   echo The last 100 lines of output:
   tail -100 $BUILD_OUTPUT  
}
error_handler() {
  echo ERROR: An error was encountered with the build.
  dump_output
  exit 1
}
# If an error occurs, run our error handler to output a tail of the build
trap 'error_handler' ERR

# Set up a repeating loop to send some output to Travis so it doesn't time out.
bash -c "while true; do echo \$(date) - building ...; sleep $PING_SLEEP; done" &
PING_LOOP_PID=$!

# Important envvars set under Travis:
# * TRAVIS_BRANCH: For builds not triggered by a pull request this is the name of the branch currently being
#   built; whereas for builds triggered by a pull request this is the name of the branch targeted by the pull
#   request (in many cases this will be master).
# * TRAVIS_PULL_REQUEST_BRANCH: If the current job is a pull request, the name of the branch from which the
#   PR originated. "" if the current job is a push build.

HERE=$(unset CDPATH && cd "$(dirname "$0")"/.. && pwd)
cd $HOME
BUILD_BRANCH=XXX
if [ -n "$TRAVIS_PULL_REQUEST_BRANCH" ]; then
    BUILD_BRANCH=$TRAVIS_PULL_REQUEST_BRANCH
else
    BUILD_BRANCH=$TRAVIS_BRANCH
fi
echo "Building branch $BUILD_BRANCH ..."

# This is the main business
$HERE/bin/install_pfs.sh -b $BUILD_BRANCH $HOME/pfs >> $BUILD_OUTPUT 2>&1
. $HOME/pfs/pfs_setups.sh >> $BUILD_OUTPUT 2>&1
git lfs install  # May not have been done if using cache
$HERE/bin/pfs_integration_test.sh -b $BUILD_BRANCH -c 2 $HOME/pfs/integration_test >> $BUILD_OUTPUT 2>&1

# The build finished without returning an error so dump a tail of the output
dump_output

# nicely terminate the ping output loop
kill $PING_LOOP_PID
