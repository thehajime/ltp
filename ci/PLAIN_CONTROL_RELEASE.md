# Plain x86_64 LTP control payload

This producer creates one plain x86_64 payload for native, MMU UML and NOMMU
UML. The LTP library detects NOMMU at runtime by reading `/proc/meminfo`; no
NOMMU build-time switch is needed. The payload contains static PIE executables
except `brk01` and `brk02`, which are static non-PIE (`ET_EXEC`) because they
test `brk(2)`. Both tests set `.needs_mmu = 1`, so the test harness reports
`TCONF` on NOMMU. The archive has no `PT_INTERP` or SVM ELF note and binds the
1,552-label `runtest/syscalls` selection to its manifest.

Build from a clean checkout of the reconciled source using Alpine 3.20.3. The
source archive must have a top-level `ltp/` directory. Set
`PLAIN_SOURCE_COMMIT`, `PLAIN_LIBC_SHA256` (SHA-256 of `/usr/lib/libc.a`), and
`PLAIN_UAPI_SHA256` (SHA-256 of `/usr/include/linux/version.h`), then run:

```sh
ci/plain_control_release_build.sh /path/to/ltp-source.tar /path/to/output
```

The producer emits `ltp-plain-x86_64.tar.gz`, a JSON manifest, and a SHA-256
sidecar. It uses `pigz -9`, the same gzip compression level as the SVM release
packager.
Filesystem backing storage is created on the test system rather than stored in
the archive. Run the included `plain-control-setup.sh` before filesystem tests;
it creates a 2 GiB sparse `tmp/ltp-loop.img` in the LTP root.

The three source files excluded by the existing Alpine CI rule (`fmtmsg01`,
`timer_create01`, and `timer_create03`) remain in the selection and have their
musl-specific reason recorded in the manifest. The `runtime_skip_pattern` is
exactly those three labels, because their source files are intentionally absent
under the Alpine CI rule; do not broaden it.

The manifest supports `native-x86_64`, `uml-mmu-plain`, and `uml-nommu-plain`.
These declarations are compatibility contracts; publication requires runtime
validation for all three profiles, with no FAIL, BROK, or WARN results. The
verifier checks every payload file's content/mode/link inventory, archive
hash, syscall selection, and per-file ELF ABI. It rejects SVM-marked,
dynamically interpreted, wrong-architecture, or unexpected ELF types.

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
payload is the x86_64 control artifact.
