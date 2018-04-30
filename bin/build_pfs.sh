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
    git describe --tags --always
}

build_package () {
    # Build a package from git, optionally checking out a particular version
    set -ev
    local repo=$1  # Repository on GitHub (without the leading "git://github.com/")
    local commit=$2  # Commit/branch to checkout
    local tag=$3  # Tag to apply
    local repoName=$(basename $repo)

    ( curl -Lf https://api.github.com/repos/$repo/tarball/$commit || curl -Lf https://api.github.com/repos/$repo/tarball/master ) > ${repoName}.tar.gz
    tar xvzf ${repoName}.tar.gz
    local repoDir=$(tar -tzf ${repoName}.tar.gz | head -1 | cut -f1 -d"/")
    pushd ${repoDir}

    setup -k -r .
    scons
    version=$(curl --fail --header "Accept: application/vnd.github.VERSION.sha" https://api.github.com/repos/$repo/commits/$commit || curl --fail --header "Accept: application/vnd.github.VERSION.sha" https://api.github.com/repos/$repo/commits/master)
    scons_args=" version=${version}"
    [ -n "$tag" ] && scons_args+=" --tag=$tag"
    scons install declare ${scons_args}

    popd
    setup ${repoName} $version
    rm -rf ${repoDir}
}

# Parse command-line arguments
BRANCH="master"
LIMITED=false
TAG=
while getopts ":b:hlt:" opt; do
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

build_package Subaru-PFS/datamodel $BRANCH $TAG
build_package Subaru-PFS/obs_pfs $BRANCH $TAG

if [ "$LIMITED" = false ]; then
    build_package Subaru-PFS/drp_stella $BRANCH $TAG
    build_package Subaru-PFS/pfs_pipe2d $BRANCH $TAG
fi
