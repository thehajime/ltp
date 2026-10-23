#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-or-later
set -euo pipefail

src=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
ci_dir=$src/ci/riscv-nommu
work=${NOMMU_WORK:-$src/.riscv-nommu}
jobs=${JOBS:-$(nproc)}
mkdir -p "$work"
work=$(realpath "$work")

prepare_checkout()
{
	local path=$1 url=$2 revision=$3 current
	if [ ! -d "$path/.git" ]; then
		git init "$path"
		git -C "$path" remote add origin "$url"
	fi
	current=$(git -C "$path" rev-parse --verify HEAD 2>/dev/null || :)
	if [ -z "$current" ]; then
		git -C "$path" fetch --depth=1 "$url" "$revision"
		git -C "$path" checkout --detach FETCH_HEAD
	elif [ "$current" != "$revision" ]; then
		printf 'Unexpected dependency revision in %s: %s (expected %s)\n' \
			"$path" "$current" "$revision" >&2
		return 1
	fi
}

prepare_checkout "$work/buildroot" https://github.com/buildroot/buildroot.git \
	93e8f75c559a6efd6d4b503123e4755bb2a49576
sed "s|@CI_DIR@|$ci_dir|g" "$ci_dir/buildroot.config" > "$work/buildroot.config"
make -C "$work/buildroot" BR2_DEFCONFIG="$work/buildroot.config" defconfig
make -C "$work/buildroot" -j"$jobs"

export PATH="$work/buildroot/output/host/bin:$PATH"
# Host utilities must not inherit the target's elf2flt linker flags.
export HOST_CFLAGS=-O2 HOST_LDFLAGS=-Wl,--as-needed
cd "$src"
make autotools
CC=riscv64-buildroot-linux-uclibc-gcc \
CFLAGS='-O2 -g -fPIC' LDFLAGS='-Wl,-elf2flt=-r -static' \
	./configure --host=riscv64-buildroot-linux-uclibc --prefix=/opt/ltp
make -j"$jobs" -C include
make -j"$jobs" -C libs
make -j"$jobs" -C lib

stage=$(mktemp -d "$work/root.XXXXXX")
trap 'rm -rf -- "$stage"' EXIT
cp -a "$work/buildroot/output/target/." "$stage/"
for dir in testcases/kernel/syscalls tools/apicmds \
	testcases/kernel/security/dirtyc0w \
	testcases/kernel/security/dirtyc0w_shmem \
	testcases/kernel/security/dirtypipe \
	testcases/kernel/security/prot_hsymlinks; do
	make -j"$jobs" -C "$dir"
	make -C "$dir" DESTDIR="$stage" install
	# elf2flt retains large ELF intermediates, which are not used at runtime.
	find "$dir" -name '*.gdb' -delete
done
mkdir -p "$stage/opt/ltp/runtest" "$stage/opt/ltp/metadata"
cp runtest/syscalls "$stage/opt/ltp/runtest/"
make -C metadata
cp metadata/ltp.json "$stage/opt/ltp/metadata/"
install -d "$stage/etc/init.d"
cat > "$stage/etc/init.d/S00ltpclock" <<EOF
#!/bin/sh
date -u -s '$(date -u '+%Y-%m-%d %H:%M:%S')'
EOF
chmod +x "$stage/etc/init.d/S00ltpclock"

# Use the matching Buildroot fakeroot and e2fsprogs. Its fakeroot prepends
# host/lib to LD_LIBRARY_PATH, which is incompatible with the runner's mke2fs.
export stage work
"$work/buildroot/output/host/bin/fakeroot" -- sh -eu -c '
	chown -R 0:0 "$stage"
	truncate -s 2G "$work/rootfs.ext4"
	"$work/buildroot/output/host/sbin/mkfs.ext4" -q -F -O ^has_journal -E root_owner=0:0 -d "$stage" "$work/rootfs.ext4"
'

prepare_checkout "$work/kirk" https://github.com/linux-test-project/kirk.git \
	fc28d0b526047b6fd54b931a7aa6e369ed4bc1fb
if git -C "$work/kirk" apply --check "$ci_dir/kirk-qemu.patch" 2>/dev/null; then
	git -C "$work/kirk" apply "$ci_dir/kirk-qemu.patch"
else
	# A reused checkout must already contain precisely the required changes.
	git -C "$work/kirk" apply --reverse --check "$ci_dir/kirk-qemu.patch"
fi
