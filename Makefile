# The Debian package. dpkg-buildpackage writes the .deb, .buildinfo and .changes to the
# checkout's parent directory and has no option to write them elsewhere, so `make deb` moves
# them into dist/. Not build/: the build's clean step (pybuild) deletes build/ at the start of
# every build.
VERSION := $(shell dpkg-parsechangelog -S Version)
ARCH := $(shell dpkg-architecture -qDEB_BUILD_ARCH)
DEB := dist/iphonebridge_$(VERSION)_all.deb

.PHONY: deb
deb:  ## Build the .deb into dist/ and run lintian on it
	dpkg-buildpackage -us -uc -b
	mkdir -p dist
	mv ../iphonebridge_$(VERSION)_all.deb ../iphonebridge_$(VERSION)_$(ARCH).buildinfo \
	  ../iphonebridge_$(VERSION)_$(ARCH).changes dist/
	lintian $(DEB)
	@echo "built $(DEB)"
