#!/bin/bash

WORKDIR=/scratch/pprice/jenkins/weekly/$(date --iso-8601)
RAWDATA=/projects/HSC/PFS/weekly
CORES=10
HERE=$(unset CDPATH && cd "$(dirname "$0")" && pwd)

# Ensure the environment is clean
( [ -n "$(which eups)" ] && unsetup eups ) || echo "No eups in environment."
unset CONDA_DEFAULT_ENV CONDA_EXE CONDA_PREFIX CONDA_PROMPT_MODIFIER CONDA_PYTHON_EXE CONDA_SHLVL

# Need these on tiger to get the right environment
. /etc/profile  # Get "module"
module load rh/devtoolset/6  # Get modern compiler
module load git  # For git-lfs

set -ev

# Build the pipeline
$HERE/bin/install_pfs.sh -t current $WORKDIR/build
. $WORKDIR/build/loadLSST.bash
setup pfs_pipe2d

# Run the weekly production test
$HERE/weekly/process_weekly.sh -d $RAWDATA -r weekly -c $CORES $WORKDIR/process
$HERE/test_weekly.py --raw=$RAWDATA --rerun=$WORKDIR/process/rerun/weekly
