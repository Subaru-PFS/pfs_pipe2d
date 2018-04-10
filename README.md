# pfs_pipe2d

A package to build and test the 2D pipeline for the Subaru Prime Focus Spectrograph.


Building
--------

The PFS 2D pipeline is built on top of the LSST software stack, and so the LSST software stack must be installed.

To install the full LSST software stack as well as the PFS 2D pipeline, use `install_pfs.sh /path/for/install`.

If you have already installed and `setup` the LSST software stack, you can use `build_pfs.sh` to build and install just the PFS 2D pipeline.


Docker
------

If you would like a Docker image containing the PFS 2D pipeline, you can build it using one of the two provided `Dockerfile`s:

- `Dockerfile.fromLSST`: builds the PFS 2D pipeline on top of the LSST software stack image provided by LSST. This option is the fastest.
- `Dockerfile.ours`: installs the LSST software stack and then builds the PFS 2D pipeline. This uses our `install_pfs.sh` script.


Bumping the LSST version
------------------------

We hope that the LSST version will be fairly static moving forward, but it sometimes needs to be updated in order to get new features and bugfixes that impact PFS development.
To update the version that we use in builds, changes should be made in two places:

- bin/install_pfs.sh : adjust the `LSST_VERSION`
- Dockerfile.fromLsst : adjust the `ARG LSST_VERSION`
