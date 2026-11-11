#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-or-later
# Create the disposable loop backing file on the test system, not in the archive.
set -e

ltp_root=${LTPROOT:-/opt/ltp}
tmpdir=$ltp_root/tmp
image=$tmpdir/ltp-loop.img
image_size=2147483648
brk_dir=$ltp_root/libexec/plain-control/brk

mkdir -p "$tmpdir"
chmod 0777 "$tmpdir"

if [ ! -e "$image" ]; then
	truncate -s "$image_size" "$image"
elif [ ! -f "$image" ] || [ "$(wc -c < "$image")" -lt "$image_size" ]; then
	truncate -s "$image_size" "$image"
fi

chmod 0666 "$image"

if grep -q '^MmapCopy:' /proc/meminfo; then
	brk_variant=nommu
else
	brk_variant=mmu
fi

for test in brk01 brk02; do
	cp "$brk_dir/$brk_variant/$test" "$ltp_root/testcases/bin/$test"
done
