# SVM LTP release producer

The manual `SVM LTP release producer` workflow builds x86_64 and ARM payloads
on the private self-hosted runner. Its outputs stay under
`/nvme/svm/work/ltp-release/<run>-<attempt>` and it does not use Actions
artifacts. A push to the isolated `hajime/svm-arm-extras` validation branch
exports only its ARM candidate files as a one-day artifact for guest validation;
that validation build does not publish or replace release assets. x86_64 reuses
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
container image must use a registry digest (`name@sha256:...`) or a local
content ID (`sha256:...`); mutable tags are rejected. The runner overrides the
image entrypoint with `sh`, so a preloaded self-hosted-runner image cannot
start its registration process during the payload build.
The build entrypoint supports Alpine (`apk`) and Ubuntu/Debian (`apt-get`)
images, then drops to the invoking host UID/GID before compiling. This permits
the glibc-hosted ARM Buildroot compiler to run without weakening the existing
non-root output and cache boundary.

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
identity, deterministic file inventory and archive integrity. It also requires
the exact integrated 1,552-label syscall selection and checks every ELF for the
architecture-specific SVM ABI note and interpreter (x86_64 era 2/ABI 208;
ARM era 2/ABI 48). T20 also needs a source-free consumer run and
PASS/SKIP/CONF-only runtime results with zero failed, broken or warning results.
Release creation alone does not complete T20.

## ARM supplemental binaries

The ARM payload also includes these nine maintained binaries, which are outside
`runtest/syscalls`:
`fptest01`, `mem02`, `page01`, `page02`, `pth_str01`, `pth_str02`, `shmt02`,
`stack_space`, and `utsname01`. The `runtest/arm-extra` selection lists only
these binaries for supplemental ARM guest checks. The packager requires all
nine paths under `testcases/bin`, checks the exact selection, and checks their
ARM SVM ABI along with the syscall payload.
The removed `kill07`, `munmap02`, and `symlink01` tests are intentionally not
restored: upstream removed or consolidated those cases.
