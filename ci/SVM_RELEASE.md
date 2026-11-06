# SVM LTP release producer

The manual `SVM LTP release producer` workflow builds x86_64 and ARM payloads
on the private self-hosted runner. It does not use Actions artifacts. Build
outputs stay under `/nvme/svm/work/ltp-release/<run>-<attempt>`. x86_64 reuses
`/home/tazaki/.ccache/svm/alpine-userspace`; ARM reuses
`/home/tazaki/.ccache/svm/arm-sdk`. Both caches retain the 10 GiB limit.

The workflow is dispatch-only and accepts `publish=false` for a build-only
validation. With `publish=true`, it creates one draft Release only after both
matrix entries pass, verifies both archives again, uploads their archive,
manifest and checksum files, and then publishes the draft.

## Private runner input contract

Create one input directory for each architecture:

```
/nvme/svm/inputs/ltp-release/x86_64/contract.json
/nvme/svm/inputs/ltp-release/arm/contract.json
```

Every referenced path is relative to its architecture directory. Symlinks are
accepted only when their resolved target remains inside that directory. The
container image must use a digest; mutable tags are rejected.

```json
{
  "schema": 1,
  "architecture": "x86_64",
  "container_image": "alpine@sha256:<64 lowercase hexadecimal digits>",
  "host": "x86_64-alpine-linux-musl",
  "compiler": "sysroot/usr/bin/svm-gcc",
  "libc": "sysroot/lib/ld-musl-x86_64.so.1",
  "uapi": "uapi/include/linux/version.h",
  "cppflags": ["-I/input/uapi/include"],
  "plugin": "plugin/svm_plugin.so",
  "toolchain_root": "sysroot",
  "toolchain_mount": "/work/sysroot"
}
```

The ARM contract uses `"architecture": "arm"`, the exact ARM configure host
tuple, compiler, libc and UAPI paths from the tested ARM SDK. The workflow
fails before building if a file is missing, escapes the input directory, the
compiler is not executable, the architecture differs, or the image is not
digest-pinned. `toolchain_mount` records absolute paths embedded in the tested
compiler specs; the runner rejects its own reserved mount points. The contract
must not contain credentials or private source.

## Acceptance boundary

A successful producer run proves source composition, toolchain/libc/UAPI
identity, deterministic file inventory and archive integrity. T20 also needs a
source-free consumer run and PASS/SKIP/CONF-only runtime results with zero
failed, broken or warning results. Release creation alone does not complete
T20.
