# Plain x86_64 UML control payload

This producer creates plain x86_64 payloads for the native baseline and plain
MMU/NOMMU UML controls. It is independent of the SVM ABI payloads. NOMMU uses
Alpine/musl static PIE (`ET_DYN`). MMU/native uses the same static PIE inventory
except `brk01` and `brk02`, which are static non-PIE (`ET_EXEC`) because these
tests inspect the process break. Both variants have no `PT_INTERP` or SVM ELF
note, and bind the same 1,552-label `runtest/syscalls` inventory to the archive.

Build from a clean checkout of the reconciled source using Alpine 3.20.3. The
source archive must have a top-level `ltp/` directory. Set
`PLAIN_SOURCE_COMMIT`, `PLAIN_LIBC_SHA256` (SHA-256 of `/usr/lib/libc.a`), and
`PLAIN_UAPI_SHA256` (SHA-256 of `/usr/include/linux/version.h`), then run:

```sh
ci/plain_control_release_build.sh /path/to/ltp-source.tar /path/to/output
```

The builder stages a 2 GiB loop image at `opt/ltp/tmp/ltp-loop.img` so the
filesystem tests can probe all guest-supported filesystems. It preserves all
syscall selection labels. The three source files excluded by the existing
Alpine CI rule (`fmtmsg01`, `timer_create01`, and `timer_create03`) remain in the
selection and have their musl-specific reason recorded in the manifest.
The `runtime_skip_pattern` is exactly those three labels, because their source
files are intentionally absent under the Alpine CI rule; do not broaden it.

The NOMMU manifest supports `uml-nommu-plain`; the MMU/native manifest supports
`native-x86_64` and `uml-mmu-plain`. These declarations are compatibility
contracts; publication requires runtime validation for each profile, with no
FAIL, BROK, or WARN results. The verifier checks every payload file's
content/mode/link inventory, archive hash, syscall selection, and per-file ELF
ABI. It rejects SVM-marked, dynamically interpreted, wrong-architecture, or
unexpected ELF types.

The producer emits `ltp-plain-x86_64-nommu.tar.gz` and
`ltp-plain-x86_64-mmu-native.tar.gz`, each with a JSON manifest and SHA-256
sidecar.

For UML runtime validation, set `LTP_TIMEOUT_MUL=10` and give the runner a
per-test timeout above the LTP test's own runtime limit. Some syscall tests
need several minutes on emulated CPUs. The MMU UML test kernel must enable
`CONFIG_BLK_DEV_LOOP`, `CONFIG_KEYS`, `CONFIG_PID_NS`, and `CONFIG_USER_NS`;
the loop device must be built in or installed in the guest module tree. Set
`LTP_VIRT_OVERRIDE=uml` inside both UML guests so UML-specific test limitations
are reported as TCONF; leave it unset on native x86_64. Leave
`LTP_SINGLE_FS_TYPE` unset for all three profiles so every guest-supported
filesystem is exercised.

The SVM Release remains the artifact for SVM profiles and ARM. This plain
payload is only the x86_64 control artifact.
