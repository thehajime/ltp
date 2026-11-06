#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-or-later
# Build an immutable SVM LTP payload from an already composed public source.
set -eu

svm_source=${1:?source archive required}
svm_output=${2:?output directory required}
: "${SVM_ARCH:?x86_64 or arm required}"
: "${SVM_CC:?target compiler command required}"
: "${SVM_HOST:?configure host tuple required}"
: "${SVM_SOURCE_COMMIT:?full source commit required}"
: "${SVM_LIBC_SHA256:?libc SHA-256 required}"
: "${SVM_UAPI_SHA256:?UAPI SHA-256 required}"
: "${SVM_BUILD_JOBS:=2}"
: "${CCACHE_DIR:=/ccache}"

case "$SVM_ARCH" in
	x86_64|arm) ;;
	*) echo "unsupported architecture: $SVM_ARCH" >&2; exit 2 ;;
esac
case "$SVM_SOURCE_COMMIT:$SVM_LIBC_SHA256:$SVM_UAPI_SHA256" in
	*[!0-9a-f:]*) echo "source and dependency digests must be lowercase hexadecimal" >&2; exit 2 ;;
esac
[ "${#SVM_SOURCE_COMMIT}" -eq 40 ]
[ "${#SVM_LIBC_SHA256}" -eq 64 ]
[ "${#SVM_UAPI_SHA256}" -eq 64 ]

if [ "$(id -u)" -eq 0 ]; then
	: "${SVM_BUILD_UID:?non-root output UID required}"
	: "${SVM_BUILD_GID:?non-root output GID required}"
	if command -v apk >/dev/null 2>&1; then
		apk add --no-cache alpine-sdk ccache autoconf automake m4 bison flex \
			findutils linux-headers perl python3 > "$svm_output/dependencies.log" 2>&1
		group=$(awk -F: -v gid="$SVM_BUILD_GID" '$3 == gid {print $1; exit}' /etc/group)
		[ -n "$group" ] || { addgroup -g "$SVM_BUILD_GID" svm-ltp; group=svm-ltp; }
		user=$(awk -F: -v uid="$SVM_BUILD_UID" '$3 == uid {print $1; exit}' /etc/passwd)
		[ -n "$user" ] || { adduser -D -H -u "$SVM_BUILD_UID" -G "$group" svm-ltp; user=svm-ltp; }
	else
		command -v apt-get >/dev/null 2>&1 || {
			echo "supported package manager not found" >&2; exit 2;
		}
		apt-get update > "$svm_output/dependencies.log" 2>&1
		apt-get install -y --no-install-recommends build-essential ccache \
			autoconf automake m4 bison flex findutils linux-libc-dev perl python3 \
			>> "$svm_output/dependencies.log" 2>&1
		group=$(getent group "$SVM_BUILD_GID" | cut -d: -f1)
		[ -n "$group" ] || { groupadd -g "$SVM_BUILD_GID" svm-ltp; group=svm-ltp; }
		user=$(getent passwd "$SVM_BUILD_UID" | cut -d: -f1)
		[ -n "$user" ] || {
			useradd -M -u "$SVM_BUILD_UID" -g "$group" -s /bin/sh svm-ltp
			user=svm-ltp
		}
	fi
	cache_gid=$(stat -c %g "$CCACHE_DIR")
	cache_group=$(awk -F: -v gid="$cache_gid" '$3 == gid {print $1; exit}' /etc/group)
	if [ -z "$cache_group" ]; then
		if command -v apk >/dev/null 2>&1; then addgroup -g "$cache_gid" svm-cache;
		else groupadd -g "$cache_gid" svm-cache; fi
		cache_group=svm-cache
	fi
	if command -v apk >/dev/null 2>&1; then addgroup "$user" "$cache_group";
	else usermod -a -G "$cache_group" "$user"; fi
	export SVM_RELEASE_BUILDER=$0
	exec su -s /bin/sh "$user" -c \
		'exec sh "$SVM_RELEASE_BUILDER" "$1" "$2"' sh "$svm_source" "$svm_output"
fi

mkdir -p "$CCACHE_DIR" "$svm_output/source" "$svm_output/install"
ccache --set-config max_size=10G
ccache --set-config compiler_check=content
export CCACHE_DIR CCACHE_BASEDIR=/ CCACHE_COMPILERCHECK=content CCACHE_UMASK=002

tar -C "$svm_output/source" --strip-components=1 -xf "$svm_source"
cd "$svm_output/source"
make autotools > "$svm_output/autotools.log" 2>&1
compiler=$(sh -c "$SVM_CC --version" | sed -n '1p')
printf '%s\n' "$compiler" > "$svm_output/compiler.log"
export CC="ccache $SVM_CC" CFLAGS='-O2 -g'
export CPPFLAGS="${SVM_CPPFLAGS:-}"
export SVM_PLUGIN="${SVM_PLUGIN:-}"
./configure --build=x86_64-pc-linux-gnu --host="$SVM_HOST" --prefix=/opt/ltp \
	> "$svm_output/configure.log" 2>&1
grep -Fq 'checking whether we are cross compiling... yes' "$svm_output/configure.log"

make -C lib -j"$SVM_BUILD_JOBS" HOSTCC='ccache gcc' > "$svm_output/lib-build.log" 2>&1
make -C testcases/lib -j"$SVM_BUILD_JOBS" HOSTCC='ccache gcc' > "$svm_output/helpers-build.log" 2>&1
make -C tools/apicmds -j"$SVM_BUILD_JOBS" HOSTCC='ccache gcc' > "$svm_output/apicmds-build.log" 2>&1
make -C tools/apicmds install DESTDIR="$svm_output/install" HOSTCC='ccache gcc' \
	> "$svm_output/apicmds-install.log" 2>&1
make -C testcases/kernel/syscalls -j"$SVM_BUILD_JOBS" HOSTCC='ccache gcc' \
	> "$svm_output/syscalls-build.log" 2>&1
for extra in ipc/msgstress ipc/pipeio security/prot_hsymlinks \
	security/dirtyc0w security/dirtyc0w_shmem security/dirtypipe; do
	log=$(printf '%s' "$extra" | tr / -)
	make -C "testcases/kernel/$extra" -j"$SVM_BUILD_JOBS" HOSTCC='ccache gcc' \
		> "$svm_output/$log-build.log" 2>&1
	make -C "testcases/kernel/$extra" install DESTDIR="$svm_output/install" \
		HOSTCC='ccache gcc' > "$svm_output/$log-install.log" 2>&1
done
make -C testcases/lib install DESTDIR="$svm_output/install" HOSTCC='ccache gcc' \
	> "$svm_output/helpers-install.log" 2>&1
make -C testcases/kernel/syscalls install DESTDIR="$svm_output/install" \
	HOSTCC='ccache gcc' > "$svm_output/syscalls-install.log" 2>&1
mkdir -p "$svm_output/install/opt/ltp/runtest"
cp runtest/syscalls "$svm_output/install/opt/ltp/runtest/syscalls"

python3 ci/svm_release_payload.py create \
	--root "$svm_output/install/opt/ltp" --output "$svm_output/release" \
	--arch "$SVM_ARCH" --source-commit "$SVM_SOURCE_COMMIT" \
	--source-manifest ci/svm-release-source.json --compiler "$compiler" \
	--libc-sha256 "$SVM_LIBC_SHA256" --uapi-sha256 "$SVM_UAPI_SHA256" \
	> "$svm_output/payload.log"
printf '%s\n' '{"status":"PASS","scope":"syscalls-release-build"}' \
	> "$svm_output/build-summary.json"
