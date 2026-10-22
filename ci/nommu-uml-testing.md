# NOMMU UML test workflow

This branch provides a reproducible Alpine/musl build and two ways to run the
LTP syscall suite on the prebuilt NOMMU UML image. The RISC-V Kirk work is not
part of this workflow.

## Requirements

- A Linux host with Docker access. The UML container needs `--privileged` and a
  3 GiB `/dev/shm` tmpfs.
- Network access to pull `alpine:3.20.3`, fetch Alpine packages, and pull
  `ghcr.io/thehajime/alpine:3.20.3-um-nommu`.
- The `tools/kirk` submodule, initialized by the recursive checkout below.

The build runs on Alpine 3.20.3 with musl. The NOMMU UML guest image is
`ghcr.io/thehajime/alpine:3.20.3-um-nommu`.

## Checkout and build

```sh
git clone --branch hajime/nommu-runtime-upstream --recurse-submodules \
  https://github.com/thehajime/ltp.git
cd ltp
mkdir -p build/nommu-install
docker run --rm \
  -v "$PWD:/ltp" \
  -v "$PWD/build/nommu-install:/ltp-install" \
  -w /ltp alpine:3.20.3 \
  /bin/sh -ec './ci/nommu-uml-build.sh /ltp-install'
```

The build script installs the Alpine build dependencies, omits
`timer_create01` and `timer_create03` as `ci/alpine.sh` does because musl does
not expose their `sigevent` fields, then runs `autotools`, `configure`, `build`,
and `install`. It stages `libaio`, `libcap`, and `libnuma` for the smaller guest
image, applies the Kirk environment-forwarding patch, and creates the loopback
image used by filesystem tests.

## Run Kirk inside the UML guest

Run the entire syscall suite:

```sh
LTPROOT="$PWD/build/nommu-install" \
  KIRK_GUEST_SUITE=syscalls \
  ./ci/nommu-uml-kirk-in-guest
```

For a quick smoke test, select a few fork/vfork cases:

```sh
LTPROOT="$PWD/build/nommu-install" \
  KIRK_GUEST_SUITE=syscalls \
  KIRK_GUEST_PATTERN='^(close01|fork01|fork13|vfork01|vfork02)$' \
  ./ci/nommu-uml-kirk-in-guest
```

The runner sets `LTP_VIRT_OVERRIDE=uml`, uses `/dev/loop0`, and leaves
`LTP_SINGLE_FS_TYPE` unset so tests can try every filesystem available in the
guest. It exits nonzero if Kirk or any LTP test reports FAIL, BROK, or WARN.

## GitHub Actions

- `NOMMU UML syscall runtime` runs the syscall suite on pushes and pull
  requests. It runs Kirk on the host and controls the UML guest through the
  `nommu-uml` communication plugin.
- `Fork validation - Kirk inside NOMMU UML` is a manual workflow. Dispatch it
  with the suite name (default `syscalls`) and, optionally, a Kirk test-name
  regular expression. It launches Kirk inside the guest.

For example, dispatch a guest smoke test with GitHub CLI:

```sh
gh workflow run ci-nommu-uml-kirk-guest.yml \
  --repo thehajime/ltp \
  --ref hajime/nommu-runtime-upstream \
  -f suite=syscalls \
  -f 'pattern=^(close01|fork01|vfork01)$'
```

Find the run with:

```sh
gh run list --repo thehajime/ltp --branch hajime/nommu-runtime-upstream
gh run watch RUN_ID --exit-status
```

## Verified locally

On 2026-10-21, the full `syscalls` run with Kirk inside NOMMU UML completed
with 855 test results marked PASS and 697 marked TCONF/SKIP. LTP reported
5,321 passed assertions and 1,120 skipped assertions, with zero FAIL, BROK, or
WARN. The host-Kirk workflow path also passed a three-test smoke run.
