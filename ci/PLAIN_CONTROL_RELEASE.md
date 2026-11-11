# Plain x86_64 UML control payload

This producer creates a separate plain x86_64 payload for the native baseline
and plain MMU/NOMMU UML controls. It is independent of the SVM ABI payloads.
The binaries are Alpine/musl static PIE: ELF64 x86_64 `ET_DYN`, with no
`PT_INTERP` and no SVM ELF note. The packager checks those properties for every
ELF file and binds the 1,552-label `runtest/syscalls` inventory to the archive.

Build from a clean checkout of the reconciled source using Alpine 3.20.3. The
source archive must have a top-level `ltp/` directory. Set
`PLAIN_SOURCE_COMMIT`, `PLAIN_LIBC_SHA256` (SHA-256 of `/usr/lib/libc.a`), and
`PLAIN_UAPI_SHA256` (SHA-256 of `/usr/include/linux/version.h`), then run:

```sh
ci/plain_control_release_build.sh /path/to/ltp-source.tar /path/to/output
```

The builder stages a 512 MiB loop image at `opt/ltp/tmp/ltp-loop.img` so the
filesystem tests can probe all guest-supported filesystems. It preserves all
syscall selection labels. The three source files excluded by the existing
Alpine CI rule (`fmtmsg01`, `timer_create01`, and `timer_create03`) remain in the
selection and have their musl-specific reason recorded in the manifest.

The manifest declares support for `native-x86_64`, `uml-mmu-plain`, and
`uml-nommu-plain`. This declaration is a compatibility contract; publication
requires runtime validation for each profile, with no FAIL, BROK, or WARN
results. The verifier also checks every payload file's content/mode/link
inventory, archive hash, syscall selection, and ELF ABI. It rejects SVM-marked,
dynamically interpreted, non-PIE, wrong-architecture, or modified payloads.

The SVM Release remains the artifact for SVM profiles and ARM. This plain
payload is only the x86_64 control artifact.
