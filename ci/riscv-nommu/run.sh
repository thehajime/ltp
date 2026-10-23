#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-or-later
set -euo pipefail
src=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
work=$(realpath "${NOMMU_WORK:-$src/.riscv-nommu}")
export PATH="$work/buildroot/output/host/bin:$PATH"
export PYTHONPATH="$work/kirk"
export LTP_TIMEOUT_MUL=1
unset LTP_SINGLE_FS_TYPE LTP_VIRT_OVERRIDE
mkdir -p "$work/results"
report=$work/results/syscalls.json
rm -f -- "$report"

for input in "$work/buildroot/output/images/Image" "$work/rootfs.ext4" "$work/kirk/kirk"; do
	if [ ! -s "$input" ]; then
		printf 'Missing build input: %s\n' "$input" >&2
		exit 1
	fi
done
run_image=$(mktemp "$work/rootfs-run.XXXXXX.ext4")
trap 'rm -f -- "$run_image"' EXIT
cp --reflink=auto --sparse=always "$work/rootfs.ext4" "$run_image"

# Keep the guest image writable and disposable. No skip file is supplied.
python3 "$work/kirk/kirk" --verbose \
	--json-report "$report" \
	--com "qemu:system=riscv64:user=root:prompt=#:ram=2G:smp=1:options=-accel tcg -M virt -bios none -cpu rv64,mmu=off -kernel $work/buildroot/output/images/Image -append \"rootwait root=/dev/vda rw console=ttyS0\" -drive file=$run_image,format=raw,id=hd0,if=none -device virtio-blk-device,drive=hd0 -netdev user,id=net0 -device virtio-net-device,netdev=net0" \
	--sut default:com=qemu --run-suite syscalls \
	--suite-timeout 4h --exec-timeout 10m
python3 "$src/ci/riscv-nommu/check-report.py" \
	"$src/runtest/syscalls" "$report"
