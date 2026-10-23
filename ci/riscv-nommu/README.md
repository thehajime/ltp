# RISC-V NOMMU fork validation

The `RISC-V NOMMU syscall execution (fork)` workflow builds a minimal Buildroot
system and runs every entry in `runtest/syscalls` through host-side Kirk and QEMU
TCG. It runs on pushes to `hajime/riscv-nommu-upstream`. Use GitHub Actions'
re-run control to repeat an existing run. Manual dispatch is also available
once the workflow exists on the repository's default branch. The job is
restricted to `thehajime/ltp`.

Buildroot, Linux and Kirk revisions are pinned in the configuration and scripts.
Linux is the 7.2.0-rc5 source used for the local validation. The Buildroot
configuration contains the toolchain, BusyBox, kernel and QEMU; LTP is compiled
from the checked-out repository after the toolchain build. Downloaded source
archives are cached, while compiled LTP binaries are rebuilt for each revision.
Reused dependency checkouts must match the pinned revisions. A repeated build
uses a fresh installation directory and verifies that the Kirk patch is applied.
The target compiler detects uClibc during configure; no UCLIBC make override
is needed.

The patches under this directory are validation dependencies:

* `patches/uclibc/` corrects the RV64 SysV IPC structure padding in uClibc 1.0.59.
* `kirk-qemu.patch` permits TCG and reads LTP's text suite and metadata files
  through the first UART. This patch is suitable for this validation fixture;
  its text-only file transfer is not a general binary transport implementation.

The guest uses 2 GiB of RAM and a disposable copy of a 2 GiB ext4 root filesystem.
The base image is preserved between runs, and the previous JSON report is
removed before starting a new run. An init script initializes the clock from
the build host to avoid the 1970 epoch restore
failure in clock tests. `LTP_TIMEOUT_MUL=1` is used. `LTP_SINGLE_FS_TYPE` and
`LTP_VIRT_OVERRIDE` are unset, and no external skip file is used. Missing kernel
features and filesystem tools may produce LTP `TCONF` results.

`check-report.py` requires a result for every syscall suite entry, rejects
duplicate or unexpected entries, and fails on FAIL/BROK/WARN. A missing or empty
report also fails the job. Logs, configuration and the JSON report are uploaded
even when the build or test step fails.

To reproduce on an x86-64 Linux host, install the dependencies listed in the
workflow, use Python 3.14, and run from the repository root:

```sh
JOBS=4 bash ci/riscv-nommu/build.sh
bash ci/riscv-nommu/run.sh
```

Use `NOMMU_WORK=/absolute/path` to select the build directory. A clean Buildroot
build needs substantially more space and time than the final guest image.
The workflow permits up to 350 minutes for the build and full test execution.
Only source downloads are reused between CI jobs.

These runtime workflow and environment files are for fork validation. The
upstream proposal keeps the existing build CI scope.
