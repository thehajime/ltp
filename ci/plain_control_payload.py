#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Create and verify the plain x86_64 UML/native LTP control payload."""

import argparse
import json
from pathlib import Path
import subprocess
import tarfile
import struct
import tempfile

import svm_release_payload as common


ARCH = "x86_64"
SELECTION_SHA256 = "4fea279e0f356321b4dd8e53b1de7b912b7d86397532742ed769624cb215ece3"
SELECTION_LABELS = 1552
VARIANTS = {
    "control": {
        "name": "plain-x86_64-control",
        "archive": "ltp-plain-x86_64.tar.gz",
        "profiles": ["uml-nommu-plain", "uml-mmu-plain", "native-x86_64"],
        "et_exec_files": ["testcases/bin/brk01", "testcases/bin/brk02"],
        "build_flags": {
            "compile": ["-O2", "-g", "-static-pie"],
            "link": ["-static-pie"],
            "overrides": {
                "testcases/bin/brk01": {
                    "compile": ["-fno-pie"], "link": ["-static", "-no-pie"]},
                "testcases/bin/brk02": {
                    "compile": ["-fno-pie"], "link": ["-static", "-no-pie"]},
            },
        },
        "elf_types": {"ET_DYN", "ET_EXEC"},
    },
}
RUNTIME_SKIP_PATTERN = "^(fmtmsg01|timer_create01|timer_create03)$"
EXCLUSIONS = [
    {"test": "fmtmsg01", "file": "testcases/kernel/syscalls/fmtmsg/fmtmsg01.c",
     "reason": "Alpine CI excludes this test because musl lacks fmtmsg()"},
    {"test": "timer_create01", "file": "testcases/kernel/syscalls/timer_create/timer_create01.c",
     "reason": "Alpine CI excludes this test because musl does not expose the required sigevent fields"},
    {"test": "timer_create03", "file": "testcases/kernel/syscalls/timer_create/timer_create03.c",
     "reason": "Alpine CI excludes this test because musl does not expose the required sigevent fields"},
]


def deterministic_archive(root, output):
    """Create a deterministic tar.gz using parallel gzip level 9."""
    try:
        raw = output.open("wb")
        compressor = subprocess.Popen(["pigz", "-9", "-n", "-c"],
                                      stdin=subprocess.PIPE, stdout=raw)
    except OSError as error:
        raise RuntimeError("pigz is required to package the plain payload") from error

    try:
        with tarfile.open(fileobj=compressor.stdin, mode="w|",
                          format=tarfile.PAX_FORMAT) as archive:
            def normalize(info):
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                info.mtime = 0
                if info.isdir():
                    info.mode = common.release_mode(info.mode, directory=True)
                elif info.isfile():
                    info.mode = common.release_mode(info.mode)
                return info

            archive.add(root, arcname="ltp", recursive=True, filter=normalize)
        compressor.stdin.close()
        status = compressor.wait()
        raw.close()
        if status:
            raise RuntimeError(f"pigz exited with status {status}")
    except BaseException:
        if compressor.poll() is None:
            compressor.kill()
            compressor.wait()
        raw.close()
        output.unlink(missing_ok=True)
        raise


def verify_plain_elf(path, allow_static_exec=False):
    """Require a static x86_64 ELF and reject SVM notes/interpreters."""
    with path.open("rb") as stream:
        header = stream.read(64)
        elf_type = struct.unpack_from("<H", header, 16)[0] if len(header) >= 64 else 0
        if (len(header) < 64 or header[:4] != b"\x7fELF" or
                header[4:7] != b"\x02\x01\x01" or
                (elf_type != 3 and not (allow_static_exec and elf_type == 2)) or
                struct.unpack_from("<H", header, 18)[0] != 62):
            raise RuntimeError(f"ELF is not an allowed x86_64 PIE/non-PIE type: {path}")
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
        return "ET_EXEC" if elf_type == 2 else "ET_DYN"


def verify_runtime_contract(root, variant="control"):
    config = VARIANTS[variant]
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
    types = {"ET_DYN": 0, "ET_EXEC": 0}
    seen_exec = set()
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        with path.open("rb") as stream:
            if stream.read(4) != b"\x7fELF":
                continue
        relative = path.relative_to(root).as_posix()
        elf_type = verify_plain_elf(path, allow_static_exec=True)
        if elf_type not in config["elf_types"]:
            raise RuntimeError(f"ELF type {elf_type} is not allowed for {variant}: {path}")
        if (elf_type == "ET_EXEC") != (relative in config["et_exec_files"]):
            raise RuntimeError(f"unexpected non-PIE ELF type for {relative}")
        if elf_type == "ET_EXEC":
            seen_exec.add(relative)
        types[elf_type] += 1
        elf_count += 1
    if not elf_count:
        raise RuntimeError("plain-control ELF executables are missing")
    if seen_exec != set(config["et_exec_files"]):
        raise RuntimeError(f"required static ET_EXEC files missing for {variant}")
    return labels, elf_count, types


def create(args):
    root, output = args.root.resolve(), args.output.resolve()
    if (root.is_symlink() or not root.is_dir() or
            (output.exists() and not output.is_dir())):
        raise RuntimeError("use a real install root and output directory")
    if not common.is_hex_digest(args.source_commit, 40):
        raise RuntimeError("source commit must be a full hexadecimal object name")
    if not all(common.is_hex_digest(value, 64)
               for value in (args.libc_sha256, args.uapi_sha256)):
        raise RuntimeError("libc and UAPI digests must be SHA-256 values")
    config = VARIANTS[args.variant]
    labels, elf_count, elf_types = verify_runtime_contract(root, args.variant)
    name = config["archive"]
    output.mkdir(parents=True, exist_ok=True)
    archive = output / name
    if archive.exists() or (output / f"{name}.manifest.json").exists():
        raise RuntimeError(f"refusing to overwrite existing variant {name}")
    deterministic_archive(root, archive)
    manifest = {
        "schema": 1,
        "status": "PASS",
        "variant": config["name"],
        "architecture": ARCH,
        "source_commit": args.source_commit,
        "source": common.source_contract(args.source_manifest.resolve()),
        "selection": {"path": "runtest/syscalls", "labels": len(labels),
                      "sha256": SELECTION_SHA256},
        "compiler": args.compiler,
        "libc": {"name": "musl", "static_archive_sha256": args.libc_sha256},
        "uapi_sha256": args.uapi_sha256,
        "build_flags": config["build_flags"],
        "elf_abi": {"class": "ELF64", "machine": "x86_64",
                    "type_counts": elf_types,
                    "static_pie": False,
                    "static_non_pie_files": config["et_exec_files"],
                    "interpreter": None, "svm_note": False,
                    "checked_elf_files": elf_count},
        "supported_runtime_profiles": config["profiles"],
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
    variant = next((key for key, value in VARIANTS.items()
                    if value["name"] == manifest.get("variant")), None)
    config = VARIANTS.get(variant)
    if (set(manifest) != expected or manifest["schema"] != 1 or
            manifest["status"] != "PASS" or
            config is None or
            archive.name != config["archive"] or
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
            manifest["build_flags"] != config["build_flags"] or
            manifest["supported_runtime_profiles"] != config["profiles"] or
            manifest["justified_musl_exclusions"] != EXCLUSIONS or
            manifest["runtime_skip_pattern"] != RUNTIME_SKIP_PATTERN or
            set(elf_abi) != {"class", "machine", "type_counts", "static_pie",
                             "static_non_pie_files", "interpreter", "svm_note",
                             "checked_elf_files"} or
            elf_abi.get("class") != "ELF64" or
            elf_abi.get("machine") != "x86_64" or
            not isinstance(elf_abi.get("type_counts"), dict) or
            elf_abi.get("static_pie") is not False or
            elf_abi.get("static_non_pie_files") != config["et_exec_files"] or
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
        _, _, types = verify_runtime_contract(root, variant)
        if elf_abi["type_counts"] != types:
            raise RuntimeError("plain-control ELF type inventory mismatch")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    builder = subparsers.add_parser("create")
    builder.add_argument("--root", type=Path, required=True)
    builder.add_argument("--output", type=Path, required=True)
    builder.add_argument("--variant", choices=VARIANTS, default="control")
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
