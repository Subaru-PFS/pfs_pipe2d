#!/bin/bash

usage() {
    # Display usage and quit
    echo "Install the PFS 2D pipeline." 1>&2
    echo "" 1>&2
    echo "Requires that the LSST pipeline has already been installed and setup." 1>&2
    echo "" 1>&2
    echo "Usage: $0 [-b <BRANCH>] [-l] [-t TAG]" 1>&2
    echo "" 1>&2
    echo "    -b <BRANCH> : name of branch on PFS to install" 1>&2
    echo "    -l : limited install (w/o drp_stella, pfs_pipe2d)" 1>&2
    echo "    -t : tag name to apply" 1>&2
    echo "" 1>&2
    exit 1
}

git_version () {
    [ -e ".git" ] || ( echo "Not a git repo" && exit 1 )
    [ -z $(git status --porcelain --untracked-files=no) ] || ( echo "Git repo not clean" && exit 1 )
    git describe --tags --always | sed 's|/|_|g'
}

build_package () {
    # Build a package from git, optionally checking out a particular version
    local repo=$1  # Repository on GitHub (without the leading "git://github.com/")
    local commit=$2  # Commit/branch to checkout
    local tag=$3  # Tag to apply
    local repoName=$(basename $repo)

    local repoDir=$(basename $repo)
    ( git clone --branch=$commit --single-branch https://github.com/$repo $repoDir || git clone --branch=master --single-branch https://github.com/$repo $repoDir )
    pushd ${repoDir}

    version=$(git_version)
    if [ $(eups list $repoName $version) ]; then
        local build=1
        while $(eups list $repoName ${version}+$build); do build=$((build+1)); done
        version="${version}+$build"
    fi
    echo Building version ${version}...

    setup -k -r .
    [ -n "$tag" ] && scons_args+=" --tag=$tag"
    scons install declare ${scons_args}

    popd
    setup ${repoName} ${version}
    rm -rf ${repoDir}
}

# Parse command-line arguments
BRANCH="master"
LIMITED=false
TAG=
VERSION=
while getopts ":b:hlt:v:" opt; do
    case "${opt}" in
        b)
            BRANCH=${OPTARG}
            ;;
        l)
            LIMITED=true
            ;;
        t)
            TAG=${OPTARG}
            ;;
        v)
            VERSION=${OPTARG}
            ;;
        h | *)
            usage
            ;;
    esac
done
shift $((OPTIND-1))

set -ev

# OSX SIP workaround
[ -z "$DYLD_LIBRARY_PATH" ] && [ -n "$LSST_LIBRARY_PATH" ] && export DYLD_LIBRARY_PATH=$LSST_LIBRARY_PATH

# The 'setup' function may not make it down to this child process
eval $("$EUPS_DIR/bin/eups_setup" "DYLD_LIBRARY_PATH=${DYLD_LIBRARY_PATH}" eups -r "$EUPS_DIR")

setup sconsUtils

build_package Subaru-PFS/datamodel $BRANCH "$TAG"
build_package Subaru-PFS/obs_pfs $BRANCH "$TAG"

if [ "$LIMITED" = false ]; then
    build_package Subaru-PFS/drp_stella $BRANCH "$TAG"
    build_package Subaru-PFS/pfs_pipe2d $BRANCH "$TAG"
fi
