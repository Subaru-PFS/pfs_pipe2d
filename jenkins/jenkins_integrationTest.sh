#!/bin/bash

# Expect the following environment variables set by Jenkins as run parameters:
# BRANCH: Git branch to test
# USERNAME: User name of person who started the run
#
# The following environment variables are set by Jenkins for all runs:
# BUILD_NUMBER: The current build number

STACK_DIR=/scratch/gpfs/RUBIN/PFS/stack-20250303
WORKDIR=/scratch/gpfs/RUBIN/PFS/jenkins/integrationTest/${BUILD_NUMBER}
FLUXCAL=/scratch/gpfs/RUBIN/PFS/fluxCal/fluxmodeldata-ambre-20230608-small
CORES=10
HERE=$(unset CDPATH && cd "$(dirname "$0")/.." && pwd)/
LOG_NAME=integration_${BUILD_NUMBER}
LOG_FILE=$WORKDIR/${LOG_NAME}.log

mkdir -p $WORKDIR && cd $WORKDIR


die() {
    # Print a message before exiting
    echo $*
    exit 1
}


build_package () {
    # Build a package from git, optionally checking out a particular version
    local repo=$1  # Repository on GitHub (without the leading "git://github.com/")
    local commit=$2  # Commit/branch to checkout
    local repoName=$(basename $repo)

    local repoDir=$(basename $repo)
    ( git clone --branch=$commit --single-branch https://github.com/$repo $repoDir || git clone --branch=master --single-branch https://github.com/$repo $repoDir )
    pushd ${repoDir}
    setup -k -r .
    scons
    popd
}


state="setup"
notify_on_exit () {
    # Notify originator of the result
    local flags=""
    if [[ -n $state ]]; then flags="--failed $state"; fi
    $HERE/jenkins/jenkins_notify.py $flags --workdir $WORKDIR --username $USERNAME --description "integrationTest $BUILD_NUMBER ($BRANCH)"
}

################################################################################
# The following redirection of stdout+stderr comes from
# https://stackoverflow.com/a/20564208/834250

exec 3>&1 4>&2 1> >(tee -a $LOG_FILE >&3) 2> >(tee -a $LOG_FILE >&4)
trap 'cleanup' INT QUIT TERM EXIT

get_pids_of_ppid() {
    # Return PIDs of parent PID
    local ppid="$1"  # Parent PID

    RETVAL=''
    local pids=`ps x -o pid,ppid | awk "\\$2 == \\"$ppid\\" { print \\$1 }"`
    RETVAL="$pids"
}

# Needed to kill processes running in background
cleanup() {
    # Kill processes running in the background.
    # This ensures no zombies get left around (e.g., logging).
    local current_pid element
    local pids=( "$$" )

    chmod -R g+rw $WORKDIR
    notify_on_exit

    running_pids=("${pids[@]}")

    while :; do
        current_pid="${running_pids[0]}"
        [ -z "$current_pid" ] && break

        running_pids=("${running_pids[@]:1}")
        get_pids_of_ppid $current_pid
        local new_pids="$RETVAL"
        [ -z "$new_pids" ] && continue

        for element in $new_pids; do
            running_pids+=("$element")
            pids=("$element" "${pids[@]}")
        done
    done

    kill ${pids[@]} 2>/dev/null
}

################################################################################

[ -n "$BRANCH" ] || die "BRANCH not set."
[ -n "$USERNAME" ] || die "USERNAME not set."
echo "Running integration test with BRANCH=$BRANCH"

# Ensure the environment is clean
( type eups && unsetup eups ) || echo "No eups in environment."
unset CONDA_DEFAULT_ENV CONDA_EXE CONDA_PREFIX CONDA_PROMPT_MODIFIER CONDA_PYTHON_EXE CONDA_SHLVL

# Need these on tiger to get the right environment
. /etc/profile  # Get "module"
module load rh/devtoolset/6  # Get modern compiler
module load git  # For git-lfs

set -ev

# Build the pipeline
state="build"
. $STACK_DIR/loadLSST.bash
setup cp_pipe
export SCONSFLAGS="-j $CORES"
build_package Subaru-PFS/datamodel $BRANCH "$TAG"
build_package Subaru-PFS/pfs_utils $BRANCH "$TAG"
build_package Subaru-PFS/obs_pfs $BRANCH "$TAG"
build_package Subaru-PFS/drp_pfs_data $BRANCH "$TAG"
build_package Subaru-PFS/drp_stella $BRANCH "$TAG"
build_package Subaru-PFS/pfs_pipe2d $BRANCH "$TAG"
setup -jr $FLUXCAL

# Run the integration test
state="test"
pfs_integration_test.sh -b $BRANCH -c $CORES $WORKDIR
state=""  # Indicates success
