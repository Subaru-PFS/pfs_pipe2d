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

LOG_NAME=weekly_${TAG}
LOG_FILE=$WORKDIR/${LOG_NAME}.log

state="setup"
notify_on_exit () {
    # Notify originator of the result
    local flags=""
    if [[ -n $state ]]; then flags="--failed $state"; fi
    $HERE/jenkins/jenkins_notify.py $flags --workdir $WORKDIR --username pprice --description "weekly $TAG ($BRANCH)"
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

echo "Running weekly with TAG=$TAG BRANCH=$BRANCH"

# Ensure the environment is clean
( type eups && unsetup eups ) || echo "No eups in environment."
unset CONDA_DEFAULT_ENV CONDA_EXE CONDA_PREFIX CONDA_PROMPT_MODIFIER CONDA_PYTHON_EXE CONDA_SHLVL

# Need these on tiger to get the right environment
. /etc/profile  # Get "module"
module load git  # For git-lfs
module load anaconda3  # For python3 with 'requests', for release_pipe2d.py

set -ev

# Build the pipeline
state="build"
mkdir -p $WORKDIR/build
export SCONSFLAGS="-j $CORES"
export OMP_NUM_THREADS=1
export PYTHONWARNINGS="ignore:Gen2 Butler has been deprecated:FutureWarning:"
$HERE/jenkins/release_pipe2d.py -m "Automated weekly build" -b $BRANCH $TAG  # Create release
$HERE/bin/install_pfs.sh -b $TAG -t current $WORKDIR/build  # Test install_pfs, make installation for test
. $WORKDIR/build/loadLSST.bash
setup pfs_pipe2d
setup -k fluxmodeldata

# Run the weekly production test
state="test"
$HERE/weekly/process_weekly.sh -r weekly -c $CORES $WORKDIR/process
$HERE/weekly/process_science.sh -r science -c $CORES $WORKDIR/process

# Ensure the rerun is writeable, so everyone can play with the results
chmod g+w $WORKDIR/process/rerun

state=""  # Indicates success
