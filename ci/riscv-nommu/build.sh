#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-or-later
set -euo pipefail

src=$(git rev-parse --show-toplevel)
ci_dir=$src/ci/riscv-nommu
work=${NOMMU_WORK:-$src/.riscv-nommu}
jobs=${JOBS:-$(nproc)}
mkdir -p "$work"
work=$(realpath "$work")

if [ ! -d "$work/buildroot/.git" ]; then
	git init "$work/buildroot"
	git -C "$work/buildroot" remote add origin https://github.com/buildroot/buildroot.git
	git -C "$work/buildroot" fetch --depth=1 origin 93e8f75c559a6efd6d4b503123e4755bb2a49576
	git -C "$work/buildroot" checkout --detach FETCH_HEAD
fi
sed "s|@CI_DIR@|$ci_dir|g" "$ci_dir/buildroot.config" > "$work/buildroot.config"
make -C "$work/buildroot" BR2_DEFCONFIG="$work/buildroot.config" defconfig
make -C "$work/buildroot" -j"$jobs"

export PATH="$work/buildroot/output/host/bin:$PATH"
cd "$src"
make autotools
CC=riscv64-buildroot-linux-uclibc-gcc \
CFLAGS='-O2 -g -fPIC' LDFLAGS='-Wl,-elf2flt=-r -static' \
	./configure --host=riscv64-buildroot-linux-uclibc --prefix=/opt/ltp
make -j"$jobs" UCLIBC=1 -C include
make -j"$jobs" UCLIBC=1 -C libs
make -j"$jobs" UCLIBC=1 -C lib

stage=$work/root
mkdir -p "$stage"
cp -a "$work/buildroot/output/target/." "$stage/"
for dir in testcases/kernel/syscalls tools/apicmds \
	testcases/kernel/security/dirtyc0w \
	testcases/kernel/security/dirtyc0w_shmem \
	testcases/kernel/security/dirtypipe \
	testcases/kernel/security/prot_hsymlinks; do
	make -j"$jobs" UCLIBC=1 -C "$dir"
	make UCLIBC=1 -C "$dir" DESTDIR="$stage" install
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

# fakeroot preserves target ownership without running tests or builds as root.
export stage work
fakeroot -- sh -eu -c '
	chown -R 0:0 "$stage"
	truncate -s 2G "$work/rootfs.ext4"
	mke2fs -q -F -t ext4 -O ^has_journal -E root_owner=0:0 -d "$stage" "$work/rootfs.ext4"
'

if [ ! -d "$work/kirk/.git" ]; then
	git init "$work/kirk"
	git -C "$work/kirk" remote add origin https://github.com/linux-test-project/kirk.git
	git -C "$work/kirk" fetch --depth=1 origin fc28d0b526047b6fd54b931a7aa6e369ed4bc1fb
	git -C "$work/kirk" checkout --detach FETCH_HEAD
	git -C "$work/kirk" apply "$ci_dir/kirk-qemu.patch"
fi
