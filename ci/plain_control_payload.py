#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Create and verify the plain x86_64 UML/native LTP control payload."""

import argparse
import json
from pathlib import Path
import struct
import tempfile

import svm_release_payload as common


ARCH = "x86_64"
SELECTION_SHA256 = "4fea279e0f356321b4dd8e53b1de7b912b7d86397532742ed769624cb215ece3"
SELECTION_LABELS = 1552
PROFILES = ["native-x86_64", "uml-mmu-plain", "uml-nommu-plain"]
RUNTIME_SKIP_PATTERN = "^(fmtmsg01|timer_create01|timer_create03)$"
EXCLUSIONS = [
    {"test": "fmtmsg01", "file": "testcases/kernel/syscalls/fmtmsg/fmtmsg01.c",
     "reason": "Alpine CI excludes this test because musl lacks fmtmsg()"},
    {"test": "timer_create01", "file": "testcases/kernel/syscalls/timer_create/timer_create01.c",
     "reason": "Alpine CI excludes this test because musl does not expose the required sigevent fields"},
    {"test": "timer_create03", "file": "testcases/kernel/syscalls/timer_create/timer_create03.c",
     "reason": "Alpine CI excludes this test because musl does not expose the required sigevent fields"},
]


def verify_plain_elf(path):
    """Require x86_64 static PIE and reject SVM notes/interpreters."""
    with path.open("rb") as stream:
        header = stream.read(64)
        if (len(header) < 64 or header[:4] != b"\x7fELF" or
                header[4:7] != b"\x02\x01\x01" or
                struct.unpack_from("<H", header, 16)[0] != 3 or
                struct.unpack_from("<H", header, 18)[0] != 62):
            raise RuntimeError(f"ELF is not x86_64 PIE: {path}")
        phoff = struct.unpack_from("<Q", header, 32)[0]
        phentsize, phnum = struct.unpack_from("<HH", header, 54)
        phfmt = "<IIQQQQQQ"
        if (phentsize != struct.calcsize(phfmt) or not 0 < phnum <= 128 or
                phoff + phentsize * phnum > path.stat().st_size):
            raise RuntimeError(f"invalid ELF program headers: {path}")
        stream.seek(phoff)
        phdrs = stream.read(phentsize * phnum)
        for index in range(phnum):
            values = struct.unpack_from(phfmt, phdrs, index * phentsize)
            kind, offset, length = values[0], values[2], values[5]
            if kind == 3:
                raise RuntimeError(f"dynamic interpreter in plain payload: {path}")
            if kind != 4:
                continue
            if length > 1 << 20 or offset + length > path.stat().st_size:
                raise RuntimeError(f"invalid ELF note segment: {path}")
            stream.seek(offset)
            data = stream.read(length)
            position = 0
            while position + 12 <= len(data):
                namesz, descsz, note_type = struct.unpack_from("<III", data, position)
                name_start = position + 12
                desc_start = (name_start + namesz + 3) & ~3
                end = desc_start + descsz
                if end > len(data):
                    raise RuntimeError(f"invalid ELF note: {path}")
                if data[name_start:name_start + namesz] == b"SVM\0":
                    raise RuntimeError(f"SVM-marked ELF in plain payload: {path}")
                position = (end + 3) & ~3


def verify_runtime_contract(root):
    selection = root / "runtest/syscalls"
    if not selection.is_file() or common.digest(selection) != SELECTION_SHA256:
        raise RuntimeError("plain-control syscall selection checksum mismatch")
    labels = [line.split()[0] for line in selection.read_text().splitlines()
              if line.strip() and not line.lstrip().startswith("#")]
    if len(labels) != SELECTION_LABELS:
        raise RuntimeError("plain-control syscall selection count mismatch")
    if not {row["test"] for row in EXCLUSIONS} <= set(labels):
        raise RuntimeError("a documented musl exclusion is absent from selection")

    elf_count = 0
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        with path.open("rb") as stream:
            if stream.read(4) != b"\x7fELF":
                continue
        verify_plain_elf(path)
        elf_count += 1
    if not elf_count:
        raise RuntimeError("plain-control ELF executables are missing")
    return labels, elf_count


def create(args):
    root, output = args.root.resolve(), args.output.resolve()
    if root.is_symlink() or not root.is_dir() or output.exists():
        raise RuntimeError("use a real install root and fresh output directory")
    if not common.is_hex_digest(args.source_commit, 40):
        raise RuntimeError("source commit must be a full hexadecimal object name")
    if not all(common.is_hex_digest(value, 64)
               for value in (args.libc_sha256, args.uapi_sha256)):
        raise RuntimeError("libc and UAPI digests must be SHA-256 values")
    labels, elf_count = verify_runtime_contract(root)
    output.mkdir(parents=True)
    name = "ltp-plain-x86_64-control.tar.gz"
    archive = output / name
    common.deterministic_archive(root, archive, compresslevel=1)
    manifest = {
        "schema": 1,
        "status": "PASS",
        "variant": "plain-x86_64-control",
        "architecture": ARCH,
        "source_commit": args.source_commit,
        "source": common.source_contract(args.source_manifest.resolve()),
        "selection": {"path": "runtest/syscalls", "labels": len(labels),
                      "sha256": SELECTION_SHA256},
        "compiler": args.compiler,
        "libc": {"name": "musl", "static_archive_sha256": args.libc_sha256},
        "uapi_sha256": args.uapi_sha256,
        "build_flags": {"compile": ["-O2", "-g", "-static-pie"],
                        "link": ["-static-pie"]},
        "elf_abi": {"class": "ELF64", "machine": "x86_64",
                    "type": "ET_DYN", "static_pie": True,
                    "interpreter": None, "svm_note": False,
                    "checked_elf_files": elf_count},
        "supported_runtime_profiles": PROFILES,
        "justified_musl_exclusions": EXCLUSIONS,
        "runtime_skip_pattern": RUNTIME_SKIP_PATTERN,
        "files": common.inventory(root, normalize_modes=True),
        "archive": {"name": name, "sha256": common.digest(archive)},
    }
    manifest_path = output / f"{name}.manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    (output / f"{name}.sha256").write_text(
        f"{manifest['archive']['sha256']}  {name}\n")
    verify(archive, manifest_path)
    return manifest


def verify(archive, manifest_path):
    manifest = json.loads(manifest_path.read_text())
    expected = {"schema", "status", "variant", "architecture", "source_commit",
                "source", "selection", "compiler", "libc", "uapi_sha256",
                "build_flags", "elf_abi", "supported_runtime_profiles",
                "justified_musl_exclusions", "runtime_skip_pattern",
                "files", "archive"}
    source = manifest.get("source", {})
    elf_abi = manifest.get("elf_abi", {})
    libc = manifest.get("libc", {})
    selection = manifest.get("selection", {})
    if (set(manifest) != expected or manifest["schema"] != 1 or
            manifest["status"] != "PASS" or
            manifest["variant"] != "plain-x86_64-control" or
            manifest["architecture"] != ARCH or
            not common.is_hex_digest(manifest["source_commit"], 40) or
            set(source) != {"manifest_sha256", "base_commit", "selected_commits",
                            "integration_commits"} or
            not common.is_hex_digest(source.get("manifest_sha256"), 64) or
            not common.is_hex_digest(source.get("base_commit"), 40) or
            not source.get("selected_commits") or
            not source.get("integration_commits") or
            not all(common.is_hex_digest(commit, 40) for commit in
                    source.get("selected_commits", []) +
                    source.get("integration_commits", [])) or
            selection != {"path": "runtest/syscalls", "labels": SELECTION_LABELS,
                          "sha256": SELECTION_SHA256} or
            manifest["compiler"] == "" or
            libc.get("name") != "musl" or
            set(libc) != {"name", "static_archive_sha256"} or
            not common.is_hex_digest(libc.get("static_archive_sha256"), 64) or
            not common.is_hex_digest(manifest["uapi_sha256"], 64) or
            manifest["build_flags"] != {"compile": ["-O2", "-g", "-static-pie"],
                                        "link": ["-static-pie"]} or
            manifest["supported_runtime_profiles"] != PROFILES or
            manifest["justified_musl_exclusions"] != EXCLUSIONS or
            manifest["runtime_skip_pattern"] != RUNTIME_SKIP_PATTERN or
            set(elf_abi) != {"class", "machine", "type", "static_pie",
                             "interpreter", "svm_note", "checked_elf_files"} or
            elf_abi.get("class") != "ELF64" or
            elf_abi.get("machine") != "x86_64" or
            elf_abi.get("type") != "ET_DYN" or
            elf_abi.get("static_pie") is not True or
            elf_abi.get("interpreter") is not None or
            elf_abi.get("svm_note") is not False or
            not isinstance(elf_abi.get("checked_elf_files"), int) or
            elf_abi.get("checked_elf_files", 0) < 1 or
            manifest["archive"] != {"name": archive.name,
                                    "sha256": common.digest(archive)}):
        raise RuntimeError("invalid plain-control release manifest")
    with tempfile.TemporaryDirectory(prefix="ltp-plain-control-") as temp:
        destination = Path(temp)
        common.safe_extract(archive, destination)
        root = destination / "ltp"
        if root.is_symlink() or not root.is_dir() or common.inventory(root) != manifest["files"]:
            raise RuntimeError("plain-control payload inventory mismatch")
        verify_runtime_contract(root)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    builder = subparsers.add_parser("create")
    builder.add_argument("--root", type=Path, required=True)
    builder.add_argument("--output", type=Path, required=True)
    builder.add_argument("--source-commit", required=True)
    builder.add_argument("--source-manifest", type=Path, required=True)
    builder.add_argument("--compiler", required=True)
    builder.add_argument("--libc-sha256", required=True)
    builder.add_argument("--uapi-sha256", required=True)
    checker = subparsers.add_parser("verify")
    checker.add_argument("--archive", type=Path, required=True)
    checker.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    result = create(args) if args.operation == "create" else verify(
        args.archive.resolve(), args.manifest.resolve())
    print(json.dumps({"status": "PASS", "architecture": ARCH,
                      "files": len(result["files"])}, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        raise SystemExit(f"plain-control payload failed: {error}")
