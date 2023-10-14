#!/bin/bash

#
# Install the LSST components required by the PFS pipeline
#

HERE=$(unset CDPATH && cd "$(dirname "$0")"/.. && pwd)


usage() {
    # Display usage and quit
    echo "Install the PFS 2D pipeline in the current directory." 1>&2
    echo "" 1>&2
    echo "Usage: $0 [-e] [-L <VERSION>] [-p PACKAGES]" 1>&2
    echo "" 1>&2
    echo "    -e : install bleeding-edge LSST" 1>&2
    echo "    -L <VERSION> : version of LSST to install" 1>&2
    echo "    -p <PACKAGES> : space-delimited list of LSST packages to install" 1>&2
    echo "    -S : install from source (use for non-Redhat distros)" 1>&2
    echo "" 1>&2
    exit 1
}


install_lsst () {
    # Following the instructions at https://pipelines.lsst.io/install/newinstall.html
    set -ev
    local version=$1  # LSST version to install
    local packages=$2  # Space-delimited list of packages
    local fromSource=$3  # Want tarball distribution?
    echo $version
    echo $packages
    echo $fromSource
    unset EUPS_DIR EUPS_PATH EUPS_PKGROOT EUPS_SHELL SETUP_EUPS
    unset CONDA_DEFAULT_ENV CONDA_EXE CONDA_PREFIX CONDA_PROMPT_MODIFIER CONDA_PYTHON_EXE CONDA_SHLVL
    # Using a version of newinstall subsequent to 23.0.0 because of much-reduced installation time (DM-33305).
    # This may result in messages about a version mismatch, but that shouldn't be a real concern.
    curl -OL https://raw.githubusercontent.com/lsst/lsst/${version}/scripts/newinstall.sh

    # Patch newinstall.sh to include mkl. This makes things like FFTs go faster.
    # Also include a few extras we want for PFS.
    patch -p0 <<EOF
--- newinstall.sh	2022-02-17 18:12:04.000000000 -0500
+++ newinstall.sh	2022-02-17 18:12:17.000000000 -0500
@@ -506,6 +506,9 @@
 	(
 		set -Eeo pipefail

+        echo "conda==22.11.1" >> conda/current/conda-meta/pinned
+        conda update -n base -c conda-forge -y conda
+
 		# install mamba to speed up environment creation
 		$cmd conda install -c conda-forge -y mamba

@@ -529,6 +532,7 @@
 		else
 			args+=("rubin-env=${ref}")
 		fi
+		args+=("mkl" "jupyter" "notebook<7" "ipython" "ipympl" "ipywidgets" "jupyter_contrib_nbextensions" "astroplan" "ipyevents" "ginga" "mypy" "black" "isort" "pygithub" "pyopenssl=22.0.0" "cryptography=37.0.4" "cffi=1.15.1" "matplotlib=3.6" "pydantic=1.10.10" "astrowidgets" "pybind11=2.10.4" "zstd=1.5.2")

 		$cmd mamba "${args[@]}"
EOF

    local newinstallOptions="-bc"  # Batch mode; continue previous failed install
    if ( ! $fromSource ); then
        newinstallOptions+=" -t"
    fi
    bash newinstall.sh $newinstallOptions
    source loadLSST.bash

    install_args=
    [ -n "$version" ] && install_args+=" -t $(echo $version | sed 's/\./_/g')"
    for pp in $packages ; do
        echo Installing package $pp: eups distrib install $pp $install_args --no-server-tags
        eups distrib install $pp $install_args --no-server-tags
    done
    curl -sSL https://raw.githubusercontent.com/lsst/shebangtron/master/shebangtron | python
}


# Parse command-line arguments
BRANCH=
LIMITED=false
LSST_VERSION=w.2022.17
# On next upgrade, add display_astrowidgets to PACKAGES
PACKAGES="pipe_drivers display_ds9 display_matplotlib ctrl_mpexec cp_pipe"
FROM_SOURCE=false
while getopts ":e:hL:p:S" opt; do
    case "${opt}" in
        e)
            LSST_VERSION=
            ;;
        L)
            LSST_VERSION=${OPTARG}
            ;;
        p)
            PACKAGES=${OPTARG}
            ;;
        S)
            FROM_SOURCE=true
            ;;
        h | *)
            usage
            ;;
    esac
done
shift $((OPTIND-1))
if [ -n "$1" ]; then
    usage
fi

set -ev
install_lsst $LSST_VERSION "$PACKAGES" $FROM_SOURCE
