#!/bin/bash

WORKDIR=/scratch/pprice/jenkins/weekly/$(date --iso-8601)
CORES=10
HERE=$(unset CDPATH && cd "$(dirname "$0")/.." && pwd)/
[ -z "$TAG" ] && TAG=$(date +'w.%Y.%U')
[ -z "$BRANCH" ] && BRANCH=master

if [[ $TAG =~ "_" ]]; then
    echo "Underscores are not permitted in the tag name ($TAG) due to eups munging."
    exit 1
fi

echo "Running weekly with TAG=$TAG BRANCH=$BRANCH"

# Ensure the environment is clean
( type eups && unsetup eups ) || echo "No eups in environment."
unset CONDA_DEFAULT_ENV CONDA_EXE CONDA_PREFIX CONDA_PROMPT_MODIFIER CONDA_PYTHON_EXE CONDA_SHLVL

# Need these on tiger to get the right environment
. /etc/profile  # Get "module"
module load rh/devtoolset/6  # Get modern compiler
module load git  # For git-lfs
module load anaconda3  # For python3 with 'requests', for release_pipe2d.py

set -ev

# Build the pipeline
mkdir -p $WORKDIR/build
export SCONSFLAGS="-j $CORES"
$HERE/jenkins/release_pipe2d.py -m "Automated weekly build" -b $BRANCH $TAG  # Create release
$HERE/bin/install_pfs.sh -b $TAG -t current $WORKDIR/build  # Test install_pfs, make installation for test
. $WORKDIR/build/loadLSST.bash
setup pfs_pipe2d

# Run the weekly production test
$HERE/weekly/process_weekly.sh -r weekly -c $CORES $WORKDIR/process
$HERE/weekly/process_science.sh -r science -c $CORES $WORKDIR/process

# Ensure the rerun is writeable, so everyone can play with the results
chmod g+w $WORKDIR/process/rerun
