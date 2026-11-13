#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Create and verify immutable SVM LTP release payloads."""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import struct
import tarfile
import tempfile


ARCHITECTURES = ("x86_64", "arm")
SCHEMA = 1
SYSCALLS_SHA256 = "4fea279e0f356321b4dd8e53b1de7b912b7d86397532742ed769624cb215ece3"
SYSCALL_LABELS = 1552


def arm_extra_tests():
    plan = Path(__file__).with_name("svm-arm-extra-tests")
    rows = []
    for line in plan.read_text().splitlines():
        directory, target, selection = line.split("|", 2)
        rows.append((directory, target, selection))
    if len(rows) != 9 or len({row[1] for row in rows}) != 9:
        raise RuntimeError("invalid ARM supplemental binary plan")
    return tuple(rows)


ARM_EXTRA_TESTS = arm_extra_tests()
ARM_EXTRA_BINARIES = tuple(f"testcases/bin/{target}"
                           for _, target, _ in ARM_EXTRA_TESTS)
ARM_EXTRA_RUNFILE = "".join(selection + "\n"
                            for _, _, selection in ARM_EXTRA_TESTS)

SVM_ABI = {
    "x86_64": {"elf_class": 2, "machine": 62, "era": 2, "abi": 208,
               "interpreter": b"/svm-loader.so\0"},
    "arm": {"elf_class": 1, "machine": 40, "era": 2, "abi": 48,
            "interpreter": b"/lib/ld-uClibc.so.0\0"},
}


def is_hex_digest(value, length):
    return (isinstance(value, str) and len(value) == length and
            set(value) <= set("0123456789abcdef"))


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def release_mode(mode, directory=False):
    if directory or mode & 0o111:
        return 0o755
    return 0o644


def inventory(root, normalize_modes=False):
    result = {}
    resolved_root = root.resolve()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            result[relative] = {"type": "directory"}
        elif stat.S_ISREG(mode):
            value = release_mode(mode) if normalize_modes else stat.S_IMODE(mode)
            result[relative] = {"type": "file", "mode": value,
                                "size": path.stat().st_size, "sha256": digest(path)}
        elif stat.S_ISLNK(mode):
            target = os.readlink(path)
            if os.path.isabs(target):
                raise RuntimeError(f"absolute payload symlink: {relative}")
            try:
                destination = path.resolve(strict=True)
            except (OSError, RuntimeError) as error:
                raise RuntimeError(f"invalid payload symlink: {relative}") from error
            if not destination.is_relative_to(resolved_root):
                raise RuntimeError(f"escaping payload symlink: {relative}")
            result[relative] = {"type": "link", "target": target}
        else:
            raise RuntimeError(f"unsupported payload entry: {relative}")
    if not result or not any(row["type"] == "file" for row in result.values()):
        raise RuntimeError("empty payload inventory")
    return result


def verify_svm_elf(path, architecture):
    """Require the integrated loader ABI and interpreter for every target ELF."""
    expected = SVM_ABI[architecture]
    with path.open("rb") as stream:
        header = stream.read(64)
        if (len(header) < 20 or header[:4] != b"\x7fELF" or header[5] != 1 or
                header[6] != 1 or header[4] != expected["elf_class"]):
            raise RuntimeError(f"ELF class/encoding mismatch: {path.name}")
        if struct.unpack_from("<H", header, 16)[0] not in (2, 3):
            raise RuntimeError(f"ELF type mismatch: {path.name}")
        if struct.unpack_from("<H", header, 18)[0] != expected["machine"]:
            raise RuntimeError(f"ELF machine mismatch: {path.name}")
        if expected["elf_class"] == 2:
            phoff = struct.unpack_from("<Q", header, 32)[0]
            phentsize, phnum = struct.unpack_from("<HH", header, 54)
            phdr_format, min_header = "<IIQQQQQQ", 64
        else:
            phoff = struct.unpack_from("<I", header, 28)[0]
            phentsize, phnum = struct.unpack_from("<HH", header, 42)
            phdr_format, min_header = "<IIIIIIII", 52
        size = path.stat().st_size
        if (len(header) < min_header or phentsize != struct.calcsize(phdr_format) or
                not 0 < phnum <= 128 or phoff < min_header or
                phoff + phentsize * phnum > size):
            raise RuntimeError(f"Invalid ELF program headers: {path.name}")
        stream.seek(phoff)
        program_headers = stream.read(phentsize * phnum)
        notes, interpreters = [], []
        for index in range(phnum):
            values = struct.unpack_from(phdr_format, program_headers,
                                        index * phentsize)
            if expected["elf_class"] == 2:
                kind, offset, length = values[0], values[2], values[5]
            else:
                kind, offset, length = values[0], values[1], values[4]
            if kind not in (3, 4):
                continue
            if length > 1 << 20 or offset + length > size:
                raise RuntimeError(f"Invalid ELF segment: {path.name}")
            stream.seek(offset)
            data = stream.read(length)
            if kind == 3:
                interpreters.append(data)
                continue
            position = 0
            while position + 12 <= len(data):
                name_size, desc_size, note_type = struct.unpack_from("<III", data, position)
                name_start = position + 12
                desc_start = (name_start + name_size + 3) & ~3
                end = desc_start + desc_size
                if end > len(data):
                    raise RuntimeError(f"Invalid ELF note: {path.name}")
                if data[name_start:name_start + name_size] == b"SVM\0" and note_type == 1:
                    notes.append(data[desc_start:end])
                position = (end + 3) & ~3
        abi_note = struct.pack("<II", expected["era"], expected["abi"])
        if notes != [abi_note] or interpreters != [expected["interpreter"]]:
            raise RuntimeError(f"SVM ABI/interpreter mismatch: {path.name}")


def verify_runtime_contract(root, architecture):
    selection = root / "runtest/syscalls"
    if (not selection.is_file() or digest(selection) != SYSCALLS_SHA256):
        raise RuntimeError("SVM syscall selection checksum mismatch")
    rows = [line for line in selection.read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#")]
    if len(rows) != SYSCALL_LABELS:
        raise RuntimeError("SVM syscall selection count mismatch")
    if architecture == "arm":
        missing = [name for name in ARM_EXTRA_BINARIES
                   if not (root / name).is_file() or (root / name).is_symlink()
                   or not (stat.S_IMODE((root / name).lstat().st_mode) & 0o111)]
        if missing:
            raise RuntimeError("required ARM binaries are missing: " +
                               ", ".join(missing))
        extra_selection = root / "runtest/arm-extra"
        if (not extra_selection.is_file() or
                extra_selection.read_text() != ARM_EXTRA_RUNFILE):
            raise RuntimeError("ARM supplemental test selection mismatch")
    elf_count = 0
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        with path.open("rb") as stream:
            if stream.read(4) != b"\x7fELF":
                continue
        verify_svm_elf(path, architecture)
        elf_count += 1
    if not elf_count:
        raise RuntimeError("SVM ELF executables are missing")
    return elf_count


def deterministic_archive(root, output, compresslevel=9):
    with output.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0,
                           compresslevel=compresslevel) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
                def normalize(info):
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    info.mtime = 0
                    if info.isdir():
                        info.mode = release_mode(info.mode, directory=True)
                    elif info.isfile():
                        info.mode = release_mode(info.mode)
                    return info

                archive.add(root, arcname="ltp", recursive=True, filter=normalize)


def source_contract(source_manifest):
    data = json.loads(source_manifest.read_text())
    integration_patches = data.get("integration_patch_decisions", [])
    if (data.get("schema_version") != 1 or
            data.get("base", {}).get("commit") !=
            "1bb350a1cd55501173e33f1836a674494f2cb48b" or
            len(data.get("fix_nommu_decisions", [])) != 8 or
            len(integration_patches) != 7 or
            {row.get("name") for row in integration_patches} != {
                "ltp-nommu-full-syscall-validation.patch",
                "ltp-madvise11-void-ptrs.patch",
                "ltp-nommu-config-results.patch",
                "ltp-musl-syscall-errors.patch",
                "sigevent-thread-id.patch",
                "kernel-7.4-test-compat.patch",
                "kconfig-constant-length.patch",
            } or
            any(row.get("decision") not in {"selected", "already_present"}
                or not is_hex_digest(row.get("sha256"), 64)
                or not row.get("result_commits")
                or not all(is_hex_digest(commit, 40)
                           for commit in row["result_commits"])
                for row in integration_patches)):
        raise RuntimeError("unexpected source composition manifest")
    return {"manifest_sha256": digest(source_manifest),
            "base_commit": data["base"]["commit"],
            "selected_commits": [row["result_commit"] for row in
                                 data["fix_nommu_decisions"]
                                 if row["decision"] == "selected"],
            "integration_commits": [commit for row in integration_patches
                                    for commit in row["result_commits"]]}


def create(args):
    root = args.root.resolve()
    output = args.output.resolve()
    if root.is_symlink() or not root.is_dir() or output.exists():
        raise RuntimeError("use a real install root and fresh output directory")
    if not is_hex_digest(args.source_commit, 40):
        raise RuntimeError("source commit must be a full hexadecimal object name")
    if not all(is_hex_digest(value, 64)
               for value in (args.libc_sha256, args.uapi_sha256)):
        raise RuntimeError("libc and UAPI digests must be SHA-256 values")
    profile = getattr(args, "profile", None)
    runner_source_sha256 = getattr(args, "runner_source_sha256", None)
    if profile:
        if (profile != "arm-svm-private-fork" or args.arch != "arm" or
                not is_hex_digest(runner_source_sha256, 64)):
            raise RuntimeError("invalid ARM SVM private-fork runner provenance")
    output.mkdir(parents=True)
    name = f"ltp-svm-{args.arch}.tar.gz"
    archive = output / name
    deterministic_archive(root, archive)
    manifest = {
        "schema": SCHEMA, "status": "PASS", "architecture": args.arch,
        "source_commit": args.source_commit,
        "source": source_contract(args.source_manifest.resolve()),
        "compiler": args.compiler, "libc_sha256": args.libc_sha256,
        "uapi_sha256": args.uapi_sha256,
        "files": inventory(root, normalize_modes=True),
        "archive": {"name": name, "sha256": digest(archive)},
    }
    if profile:
        probe = root / "testcases/bin/svm-fork-waitpid"
        if not probe.is_file() or probe.is_symlink() or not (probe.stat().st_mode & 0o111):
            raise RuntimeError("ARM SVM private-fork ABI probe is missing")
        manifest["profile"] = profile
        manifest["runner_source_sha256"] = runner_source_sha256
    manifest_path = output / f"{name}.manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    (output / f"{name}.sha256").write_text(
        f"{manifest['archive']['sha256']}  {name}\n")
    verify(archive, manifest_path)
    return manifest


def safe_extract(archive, destination):
    with tarfile.open(archive, "r:gz") as stream:
        members = stream.getmembers()
        if (not members or members[0].name != "ltp" or
                any(member.name.startswith("/") or ".." in Path(member.name).parts
                    for member in members)):
            raise RuntimeError("unsafe archive member")
        stream.extractall(destination, filter="data")


def verify(archive, manifest_path):
    manifest = json.loads(manifest_path.read_text())
    source = manifest.get("source", {})
    base_keys = {"schema", "status", "architecture", "source_commit", "source",
                 "compiler", "libc_sha256", "uapi_sha256", "files", "archive"}
    profile_keys = {"profile", "runner_source_sha256"}
    args_profile = manifest.get("profile")
    expected_keys = base_keys | (profile_keys if args_profile else set())
    if (set(manifest) != expected_keys or
            manifest["schema"] != SCHEMA or manifest["status"] != "PASS" or
            manifest["architecture"] not in ARCHITECTURES or
            not is_hex_digest(manifest["source_commit"], 40) or
            set(source) != {"manifest_sha256", "base_commit",
                            "selected_commits", "integration_commits"} or
            not is_hex_digest(source.get("manifest_sha256"), 64) or
            not is_hex_digest(source.get("base_commit"), 40) or
            not source.get("selected_commits") or
            not source.get("integration_commits") or
            not all(is_hex_digest(commit, 40) for commit in
                    source.get("selected_commits", []) +
                    source.get("integration_commits", [])) or
            manifest["archive"] != {"name": archive.name, "sha256": digest(archive)} or
            not manifest["compiler"] or
            not all(is_hex_digest(manifest[name], 64)
                    for name in ("libc_sha256", "uapi_sha256")) or
            (args_profile is not None and
             (args_profile != "arm-svm-private-fork" or
              manifest["architecture"] != "arm" or
              not is_hex_digest(manifest.get("runner_source_sha256"), 64)))):
        raise RuntimeError("invalid release manifest")
    with tempfile.TemporaryDirectory(prefix="svm-ltp-payload-") as directory:
        destination = Path(directory)
        safe_extract(archive, destination)
        root = destination / "ltp"
        if root.is_symlink() or not root.is_dir() or inventory(root) != manifest["files"]:
            raise RuntimeError("release payload inventory mismatch")
        verify_runtime_contract(root, manifest["architecture"])
        if args_profile == "arm-svm-private-fork":
            probe = root / "testcases/bin/svm-fork-waitpid"
            if not probe.is_file() or probe.is_symlink() or not (probe.stat().st_mode & 0o111):
                raise RuntimeError("ARM SVM private-fork ABI probe is missing")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    builder = subparsers.add_parser("create")
    builder.add_argument("--root", type=Path, required=True)
    builder.add_argument("--output", type=Path, required=True)
    builder.add_argument("--arch", choices=ARCHITECTURES, required=True)
    builder.add_argument("--source-commit", required=True)
    builder.add_argument("--source-manifest", type=Path, required=True)
    builder.add_argument("--compiler", required=True)
    builder.add_argument("--libc-sha256", required=True)
    builder.add_argument("--uapi-sha256", required=True)
    builder.add_argument("--profile", choices=("arm-svm-private-fork",))
    builder.add_argument("--runner-source-sha256")
    checker = subparsers.add_parser("verify")
    checker.add_argument("--archive", type=Path, required=True)
    checker.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    result = create(args) if args.operation == "create" else verify(
        args.archive.resolve(), args.manifest.resolve())
    print(json.dumps({"status": "PASS", "architecture": result["architecture"],
                      "files": len(result["files"])}, sort_keys=True))


if __name__ == "__main__":
    main()
