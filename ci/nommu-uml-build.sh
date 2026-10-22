#!/bin/sh -eux
# SPDX-License-Identifier: GPL-2.0-or-later

prefix=${1:?usage: nommu-uml-build.sh INSTALL_PREFIX}

apk update
apk add \
	acl-dev \
	autoconf \
	automake \
	clang \
	curl \
	e2fsprogs-extra \
	gcc \
	git \
	jq \
	keyutils-dev \
	libaio-dev \
	libcap-dev \
	libselinux-dev \
	libsepol-dev \
	libtirpc-dev \
	linux-headers \
	make \
	musl-dev \
	numactl-dev \
	openssl-dev \
	patch \
	pkgconfig

# Match ci/alpine.sh: these tests use sigevent fields that musl does not
# expose. Keep the source tree portable and omit the unsupported tests from
# this Alpine build.
rm -f \
	testcases/kernel/syscalls/timer_create/timer_create01.c \
	testcases/kernel/syscalls/timer_create/timer_create03.c

./build.sh -r autotools
./build.sh -r configure -p "$prefix"
./build.sh -r build
./build.sh -r install -i

# Kirk's LTP framework uses a restricted environment for testcase commands.
# Keep the library path for optional libraries staged in the install tree.
patch -d "$prefix" -p1 < ci/kirk-forward-ld-library-path.txt

# The prebuilt NOMMU UML image has a smaller runtime than this Alpine build
# environment. Ship the optional libraries used by dynamically linked LTP
# tests alongside the test installation.
mkdir -p "$prefix/lib"
cp -a /usr/lib/libaio.so* /usr/lib/libcap.so* /usr/lib/libnuma.so* "$prefix/lib/"

mkdir -p "$prefix/tmp"
chmod 777 "$prefix/tmp"
truncate -s 512M "$prefix/tmp/ltp-loop.img"
chmod 666 "$prefix/tmp/ltp-loop.img"
