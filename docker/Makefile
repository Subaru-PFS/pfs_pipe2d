TAG=latest
PFS_BRANCH=master
CORES=4

# Need local copies of install scripts, so Docker can see them.
# Docker doesn't let us use files outside this directory.
bin/install_lsst.sh:
	mkdir -p bin/
	cp -f ../bin/install_lsst.sh bin/
bin/build_pfs.sh:
	mkdir -p bin/
	cp -f ../bin/build_pfs.sh bin/
bin/install_pfs.sh:
	mkdir -p bin/
	cp -f ../bin/install_pfs.sh bin/

# LSST packages for PFS 2D pipeline
lsst:	Dockerfile.lsst bin/install_lsst.sh
	docker build -t paprice/pfs_lsst:$(TAG) -f Dockerfile.lsst .

# PFS 2D pipeline
#
# Always fires, by virtue of .PHONY (for make) and FORCE argument (for docker)
pipe2d:	Dockerfile.pipe2d bin/build_pfs.sh
	docker build --progress=plain -t paprice/pfs_pipe2d:$(TAG) -f Dockerfile.pipe2d --build-arg INSTALL_ARGS="-b $(PFS_BRANCH)" --build-arg VERSION=$(TAG) --build-arg FORCE=$$(date +%s) .

# PFS 2D pipeline with debugging tools
pipe2d_debug: Dockerfile.pipe2d_debug
	docker build -t paprice/pfs_pipe2d_debug:$(TAG) -f Dockerfile.pipe2d_debug --build-arg VERSION=$(TAG) .

# PFS 2D pipeline with opdb
pipe2d_opdb: Dockerfile.pipe2d_opdb
	docker build -t paprice/pfs_pipe2d_opdb:$(TAG) -f Dockerfile.pipe2d_opdb --build-arg VERSION=$(TAG) .

# Run the integration test
test: pipe2d
	docker run paprice/pfs_pipe2d:$(TAG) /bin/bash -lc "\$${PFS_PIPE2D_DIR}/bin/pfs_integration_test.sh -b $(PFS_BRANCH) -c $(CORES) /opt/pfs/integration_test"

# 2D Simulator
sim2d: Dockerfile.sim2d
	docker build -t paprice/pfs_sim2d:$(TAG) -f Dockerfile.sim2d --build-arg VERSION=$(TAG) --build-arg BRANCH=$(PFS_BRANCH) .

all:	lsst pipe2d pipe2d_debug
bin:	bin/install_lsst.sh bin/build_pfs.sh bin/install_pfs.sh
.PHONY: lsst pipe2d pipe2d_debug sim2d all bin test bin/install_lsst.sh bin/build_pfs.sh bin/install_pfs.sh
.NOTPARALLEL:
