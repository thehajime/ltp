#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-or-later
# Build an ARM NOMMU/FDPIC LTP payload with the noSVM uClibc toolchain.
set -eu

source_archive=${1:?LTP source archive required}
output=${2:?output directory required}
: "${PLAIN_ARM_CC:?ARM NOMMU/FDPIC compiler required}"
: "${PLAIN_ARM_SOURCE_COMMIT:?full LTP source commit required}"
: "${PLAIN_ARM_LIBC_SHA256:?uClibc shared library SHA-256 required}"
: "${PLAIN_ARM_UAPI_SHA256:?UAPI SHA-256 required}"
: "${PLAIN_ARM_BUILD_JOBS:=2}"

mkdir -p "$output/source" "$output/install" "$output/logs"
tar -C "$output/source" -xf "$source_archive"
source_dir=$(cd "$output/source" && pwd)
root=$(cd "$output/install" && pwd)/opt/ltp
fork_wrapper=$(cd "$(dirname "$0")" && pwd)/plain_arm_nommu_fork.c
wrapper_obj="$output/plain_arm_nommu_fork.o"
"$PLAIN_ARM_CC" -O2 -fPIE -c "$fork_wrapper" -o "$wrapper_obj"

cd "$source_dir"
make autotools > "$output/logs/autotools.log" 2>&1
export CC="$PLAIN_ARM_CC" HOSTCC=gcc CFLAGS='-O2 -g -fPIE'
export LDFLAGS="$wrapper_obj -L$source_dir/lib"
./configure --build=x86_64-pc-linux-gnu --host=arm-buildroot-uclinuxfdpiceabi \
	--prefix=/opt/ltp > "$output/logs/configure.log" 2>&1
make -C lib -j"$PLAIN_ARM_BUILD_JOBS" \
	> "$output/logs/lib-build.log" 2>&1
make -C libs/ujson -j"$PLAIN_ARM_BUILD_JOBS" \
	> "$output/logs/ujson-build.log" 2>&1
make -C testcases/lib -j"$PLAIN_ARM_BUILD_JOBS" \
	> "$output/logs/helpers-build.log" 2>&1
make -C tools/apicmds -j"$PLAIN_ARM_BUILD_JOBS" HOSTCC=gcc \
	> "$output/logs/apicmds-build.log" 2>&1
make -C tools/apicmds install DESTDIR="$output/install" HOSTCC=gcc \
	> "$output/logs/apicmds-install.log" 2>&1
make -C testcases/kernel/syscalls -j"$PLAIN_ARM_BUILD_JOBS" \
	> "$output/logs/syscalls-build.log" 2>&1
make -C testcases/lib install DESTDIR="$output/install" \
	> "$output/logs/helpers-install.log" 2>&1
make -C testcases/kernel/syscalls install DESTDIR="$output/install" \
	> "$output/logs/syscalls-install.log" 2>&1

make -C libs/newipc -j"$PLAIN_ARM_BUILD_JOBS" \
	> "$output/logs/newipc-build.log" 2>&1
while IFS='|' read -r directory target selection; do
	[ -n "$directory" ] || continue
	log=$(printf '%s' "$target" | tr / -)
	make -C "testcases/$directory" MAKE_TARGETS="$target" \
		-j"$PLAIN_ARM_BUILD_JOBS" \
		> "$output/logs/extra-$log-build.log" 2>&1
	make -C "testcases/$directory" MAKE_TARGETS="$target" install \
		DESTDIR="$output/install" \
		> "$output/logs/extra-$log-install.log" 2>&1
done < ci/svm-arm-extra-tests
install -D -m 0644 runtest/syscalls "$root/runtest/syscalls"
 : > "$root/runtest/arm-extra"
while IFS='|' read -r directory target selection; do
	[ -n "$directory" ] || continue
	printf '%s\n' "$selection" >> "$root/runtest/arm-extra"
done < ci/svm-arm-extra-tests
install -m 0644 ci/plain-arm-nommu-fork-skip "$root/runtest/plain-arm-nommu-fork-skip"
install -D -m 0644 ci/plain_arm_nommu_fork.c \
	"$root/share/plain-arm-nommu-fork-wrapper.c"

python3 ci/plain_arm_nommu_payload.py create \
	--root "$root" --output "$output/release" \
	--source-commit "$PLAIN_ARM_SOURCE_COMMIT" \
	--compiler "$($PLAIN_ARM_CC --version | sed -n '1p')" \
	--libc-sha256 "$PLAIN_ARM_LIBC_SHA256" \
	--uapi-sha256 "$PLAIN_ARM_UAPI_SHA256"
