#!/bin/bash

#
# Process PFS calibs from Subaru
#

HERE=$(unset CDPATH && cd "$(dirname "$0")"/.. && pwd)

REPO=
DATES=
CALIB=
DATABASE="dbname=opdb user=pfs host=localhost port=5432"
RERUN=calibs
CONFIGDIR=
CORES=10
CLOBBER=false
DEVMODE=false
DRYRUN=false

usage() {
    # Display usage and quit
    echo "Process PFS calibs from Subaru" 1>&2
    echo "" 1>&2
    echo "Usage: $0 [OPTIONS] <REPO> <DATE> [<DATE> ...]" 1>&2
    echo "" 1>&2
    echo "    -c <CALIBS> : calibs repo directory (default: <REPO>/CALIB)" 1>&2
    echo "    -r <RERUN> : rerun name to use (default: $RERUN)" 1>&2
    echo "    -d <DATABASE> : database connection details (default: $DATABASE)" 1>&2
    echo "    -C <CONFIG_DIR> : directory with configuration overrides" 1>&2
    echo "    -j <CORES> : number of cores to use for processing (default: $CORES)" 1>&2
    echo "    -D : developer mode (activates --no-versions --clobber-config)" 1>&2
    echo "    -n : dry run (don't execute generated script)" 1>&2
    echo "    <REPO> : data repo directory" 1>&2
    echo "    <DATE> : date(s) to process" 1>&2
    echo "" 1>&2
    exit 1
}


# Parse command-line arguments
while getopts ":hc:r:d:C:j:Dn" opt; do
    case "${opt}" in
        c)
            CALIB=${OPTARG}
            ;;
        r)
            RERUN=${OPTARG}
            ;;
        d)
            DATABASE=${OPTARG}
            ;;
        C)
            CONFIGDIR=${OPTARG}
            ;;
        j)
            CORES=${OPTARG}
            ;;
        D)
            DEVMODE=true
            ;;
        n)
            DRYRUN=true
            ;;
        h | *)
            usage
            ;;
    esac
done
shift $((OPTIND-1))
if [ -z "$1" ] || [ -z "$2" ]; then
    usage
fi
REPO=$1; shift;
[ -n "$CALIB" ] || CALIB=$REPO/CALIB
DATES=$@

set -eux

for startDate in "$DATES"; do
    # Use python to do date arithmetic because the GNU 'date' command is a bit funny about timezones
    endDate=$(python -c "import datetime, dateutil.parser; print((dateutil.parser.parse(\"$startDate\") + datetime.timedelta(days=1)).isoformat())")

    obsFilename="obs_${startDate}.yaml"
    scriptFilename="obs_${startDate}.sh"
    generateReductionSpec.py --dbname="$DATABASE" --date-start="$startDate" --date-end="$endDate" "$obsFilename" $([ -n "$CONFIGDIR" ] && echo "--config $CONFIGDIR")
    generateCommands.py "$REPO" "$obsFilename" "$scriptFilename" --calib=$CALIB --rerun="$RERUN" $(( $DEVMODE ) && echo "--devel") --processes=$CORES --allowErrors

    if ! $DRYRUN ; then
        "./$scriptFilename" 2>&1 | tee "obs_${startDate}.log" || echo "Failed while executing $scriptFilename"
    fi
done
