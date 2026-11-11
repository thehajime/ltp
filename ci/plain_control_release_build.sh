#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-or-later
# Build the plain x86_64 LTP control payload from the reconciled source.
set -eu

source_tar=${1:?source archive required}
output=${2:?output directory required}
: "${PLAIN_SOURCE_COMMIT:?full source commit required}"
: "${PLAIN_LIBC_SHA256:?musl libc archive SHA-256 required}"
: "${PLAIN_UAPI_SHA256:?UAPI SHA-256 required}"
: "${PLAIN_BUILD_JOBS:=2}"
: "${CCACHE_DIR:=/ccache}"

if ! command -v gcc >/dev/null 2>&1; then
	command -v apk >/dev/null 2>&1 || {
		echo "Alpine package manager or preinstalled GCC is required" >&2; exit 2;
	}
	apk add --no-cache alpine-sdk ccache autoconf automake m4 bison flex \
		findutils linux-headers perl python3 acl-dev clang curl e2fsprogs-extra \
		git jq keyutils-dev libaio-dev libcap-dev libselinux-dev libsepol-dev \
		libtirpc-dev musl-dev numactl-dev openssl-dev patch pkgconf
fi

command -v ccache >/dev/null 2>&1 || {
	echo "ccache is required" >&2; exit 2;
}

case "$PLAIN_SOURCE_COMMIT:$PLAIN_LIBC_SHA256:$PLAIN_UAPI_SHA256" in
	*[!0-9a-f:]*) echo "source and dependency digests must be lowercase hexadecimal" >&2; exit 2 ;;
esac
[ "${#PLAIN_SOURCE_COMMIT}" -eq 40 ]
[ "${#PLAIN_LIBC_SHA256}" -eq 64 ]
[ "${#PLAIN_UAPI_SHA256}" -eq 64 ]

mkdir -p "$CCACHE_DIR" "$output/source" "$output/install"
ccache --set-config max_size=10G
ccache --set-config compiler_check=content
export CCACHE_DIR CCACHE_BASEDIR=/ CCACHE_COMPILERCHECK=content CCACHE_UMASK=002

tar -C "$output/source" --strip-components=1 -xf "$source_tar"
cd "$output/source"

# Match ci/alpine.sh: musl does not expose these interfaces used by the tests.
rm -f testcases/kernel/syscalls/fmtmsg/fmtmsg01.c \
	testcases/kernel/syscalls/timer_create/timer_create01.c \
	testcases/kernel/syscalls/timer_create/timer_create03.c

make autotools > "$output/autotools.log" 2>&1
compiler=$(gcc --version | sed -n '1p')
printf '%s\n' "$compiler" > "$output/compiler.log"
export CC='ccache gcc' HOSTCC='ccache gcc'
export CFLAGS='-O2 -g -static-pie -Wformat -Werror=format-security -Werror=implicit-function-declaration -Werror=return-type -fno-common'
export LDFLAGS='-static-pie'
./configure --prefix=/opt/ltp > "$output/configure.log" 2>&1

make -C lib -j"$PLAIN_BUILD_JOBS" > "$output/lib-build.log" 2>&1
make -C testcases/lib -j"$PLAIN_BUILD_JOBS" > "$output/helpers-build.log" 2>&1
make -C tools/apicmds -j"$PLAIN_BUILD_JOBS" > "$output/apicmds-build.log" 2>&1
make -C tools/apicmds install DESTDIR="$output/install" \
	> "$output/apicmds-install.log" 2>&1
make -C testcases/kernel/syscalls -j"$PLAIN_BUILD_JOBS" \
	> "$output/syscalls-build.log" 2>&1
for extra in ipc/msgstress ipc/pipeio security/prot_hsymlinks \
	security/dirtyc0w security/dirtyc0w_shmem security/dirtypipe; do
	log=$(printf '%s' "$extra" | tr / -)
	make -C "testcases/kernel/$extra" -j"$PLAIN_BUILD_JOBS" \
		> "$output/$log-build.log" 2>&1
	make -C "testcases/kernel/$extra" install DESTDIR="$output/install" \
		> "$output/$log-install.log" 2>&1
done
make -C testcases/lib install DESTDIR="$output/install" \
	> "$output/helpers-install.log" 2>&1
make -C testcases/kernel/syscalls install DESTDIR="$output/install" \
	> "$output/syscalls-install.log" 2>&1
mkdir -p "$output/install/opt/ltp/runtest"
cp runtest/syscalls "$output/install/opt/ltp/runtest/syscalls"
mkdir -p "$output/install/opt/ltp/tmp"
chmod 777 "$output/install/opt/ltp/tmp"
truncate -s 512M "$output/install/opt/ltp/tmp/ltp-loop.img"
chmod 666 "$output/install/opt/ltp/tmp/ltp-loop.img"

python3 ci/test_plain_control_payload.py -v > "$output/payload-tests.log" 2>&1

python3 ci/plain_control_payload.py create \
	--root "$output/install/opt/ltp" --output "$output/release" \
	--source-commit "$PLAIN_SOURCE_COMMIT" \
	--source-manifest ci/svm-release-source.json --compiler "$compiler" \
	--libc-sha256 "$PLAIN_LIBC_SHA256" --uapi-sha256 "$PLAIN_UAPI_SHA256" \
	> "$output/payload.log"
printf '%s\n' '{"status":"PASS","scope":"plain-control-syscalls-release-build"}' \
	> "$output/build-summary.json"
