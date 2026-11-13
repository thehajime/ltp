#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Create and verify an ARM NOMMU/FDPIC plain LTP release payload."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import os
import stat
import struct
import tarfile
import tempfile

SYSCALLS_SHA256 = "4fea279e0f356321b4dd8e53b1de7b912b7d86397532742ed769624cb215ece3"
EXTRA = ("fptest01", "mem02", "page01", "page02", "pth_str01",
         "pth_str02", "shmt02", "stack_space", "utsname01")
SKIP_PATTERNS = tuple(line for line in Path(__file__).with_name(
    "plain-arm-nommu-fork-skip").read_text().splitlines()
                      if line and not line.startswith("#"))


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def inventory(root):
    result = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            result[rel] = {"type": "directory"}
        elif stat.S_ISREG(mode):
            h = hashlib.sha256(path.read_bytes()).hexdigest()
            result[rel] = {"type": "file", "mode": 0o755 if mode & 0o111 else 0o644,
                           "size": path.stat().st_size, "sha256": h}
        elif stat.S_ISLNK(mode):
            target = os.readlink(path)
            if os.path.isabs(target) or not path.resolve().is_relative_to(root.resolve()):
                raise ValueError(f"unsafe payload symlink: {rel}")
            result[rel] = {"type": "link", "target": target}
        else:
            raise ValueError(f"unsupported payload entry: {rel}")
    return result


def verify_elf(path):
    data = path.read_bytes()
    if (len(data) < 52 or data[:4] != b"\x7fELF" or data[4:7] != b"\x01\x01\x01" or
            struct.unpack_from("<H", data, 18)[0] != 40 or
            struct.unpack_from("<H", data, 16)[0] != 3):
        raise ValueError(f"not an ARM32 ET_DYN FDPIC executable: {path}")
    phoff = struct.unpack_from("<I", data, 28)[0]
    entsize, count = struct.unpack_from("<HH", data, 42)
    if entsize != 32 or not count or count > 128 or phoff + entsize * count > len(data):
        raise ValueError(f"bad ARM program headers: {path}")
    interpreters, svm_notes = [], []
    for i in range(count):
        off = phoff + i * entsize
        kind, p_offset, _, _, filesz = struct.unpack_from("<IIIII", data, off)
        if p_offset + filesz > len(data):
            raise ValueError(f"bad segment bounds: {path}")
        if kind == 3:
            interpreters.append(data[p_offset:p_offset + filesz])
        elif kind == 4:
            notes = data[p_offset:p_offset + filesz]
            pos = 0
            while pos + 12 <= len(notes):
                namesz, descsz, ntype = struct.unpack_from("<III", notes, pos)
                name = pos + 12
                desc = (name + namesz + 3) & ~3
                end = desc + descsz
                if end > len(notes):
                    raise ValueError(f"bad ELF note: {path}")
                if notes[name:name + namesz] == b"SVM\0" and ntype == 1:
                    svm_notes.append(notes[desc:end])
                pos = (end + 3) & ~3
    if interpreters != [b"/lib/ld-uClibc.so.0\0"] or svm_notes:
        raise ValueError(f"wrong interpreter or SVM note present: {path}")


def verify_root(root):
    selection = root / "runtest/syscalls"
    if digest(selection) != SYSCALLS_SHA256:
        raise ValueError("syscall selection checksum mismatch")
    rows = [line for line in selection.read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#")]
    if len(rows) != 1552:
        raise ValueError("wide syscall selection must contain 1552 labels")
    missing = sorted({line.split()[1] for line in rows
                      if len(line.split()) > 1 and
                      not (root / "testcases/bin" / line.split()[1]).is_file()})
    if missing:
        raise ValueError("syscall selection commands are missing: " +
                         ", ".join(missing))
    extras = root / "runtest/arm-extra"
    labels = [line.split("|", 2)[2] for line in
              Path(__file__).with_name("svm-arm-extra-tests").read_text().splitlines()]
    if extras.read_text() != "".join(label + "\n" for label in labels):
        raise ValueError("ARM supplemental selection mismatch")
    for name in EXTRA:
        path = root / "testcases/bin" / name
        if not path.is_file() or path.is_symlink() or not os.access(path, os.X_OK):
            raise ValueError(f"missing ARM supplemental command: {name}")
    count = 0
    for path in root.rglob("*"):
        if path.is_file() and not path.is_symlink():
            with path.open("rb") as stream:
                if stream.read(4) == b"\x7fELF":
                    verify_elf(path)
                    count += 1
    if not count:
        raise ValueError("no FDPIC ELFs found")
    return rows, count


def archive_tree(root, output):
    with output.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0,
                           compresslevel=9) as zipped:
            with tarfile.open(fileobj=zipped, mode="w", format=tarfile.PAX_FORMAT) as tar:
                def normalize(info):
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    info.mtime = 0
                    if info.isdir(): info.mode = 0o755
                    elif info.isfile(): info.mode = 0o755 if info.mode & 0o111 else 0o644
                    return info
                tar.add(root, arcname="ltp", recursive=True, filter=normalize)


def create(args):
    root, output = args.root.resolve(), args.output.resolve()
    if output.exists(): raise ValueError("output directory must be fresh")
    rows, elf_count = verify_root(root)
    output.mkdir(parents=True)
    name = "ltp-plain-arm.tar.gz"
    archive = output / name
    archive_tree(root, archive)
    sha = digest(archive)
    manifest = {"schema": 1, "status": "PASS", "variant": "plain-arm-nommu-fdpic",
                "architecture": "arm", "source_commit": args.source_commit,
                "compiler": args.compiler, "libc": {"name": "uClibc",
                "sha256": args.libc_sha256}, "uapi_sha256": args.uapi_sha256,
                "selection": {"path": "runtest/syscalls", "labels": len(rows),
                              "sha256": SYSCALLS_SHA256},
                "supplemental_commands": list(EXTRA),
                "nommu_fork_skip_patterns": list(SKIP_PATTERNS),
                "elf_abi": {"class": "ELF32", "machine": "ARM", "type": "ET_DYN",
                            "interpreter": "/lib/ld-uClibc.so.0", "svm_note": False,
                            "checked_elf_files": elf_count},
                "runtime_validation": "NOT_RUN", "files": inventory(root),
                "archive": {"name": name, "sha256": sha}}
    manifest_path = output / f"{name}.manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    (output / f"{name}.sha256").write_text(f"{sha}  {name}\n")
    verify(archive, manifest_path)
    return manifest


def verify(archive, manifest_path):
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("archive") != {"name": archive.name, "sha256": digest(archive)}:
        raise ValueError("archive digest mismatch")
    with tempfile.TemporaryDirectory(prefix="plain-arm-fdpic-") as temp:
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(temp, filter="data")
        root = Path(temp) / "ltp"
        _, count = verify_root(root)
        if count != manifest["elf_abi"]["checked_elf_files"]:
            raise ValueError("ELF count mismatch")
        if inventory(root) != manifest["files"]:
            raise ValueError("payload inventory mismatch")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    build = sub.add_parser("create")
    check = sub.add_parser("verify")
    for cmd in (build,):
        cmd.add_argument("--root", type=Path, required=True)
        cmd.add_argument("--output", type=Path, required=True)
        cmd.add_argument("--source-commit", required=True)
        cmd.add_argument("--compiler", required=True)
        cmd.add_argument("--libc-sha256", required=True)
        cmd.add_argument("--uapi-sha256", required=True)
    check.add_argument("--archive", type=Path, required=True)
    check.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    if args.operation == "create": result = create(args)
    else: result = verify(args.archive, args.manifest)
    print(json.dumps({"status": "PASS", "architecture": "arm",
                      "archive": result["archive"]}, sort_keys=True))


if __name__ == "__main__":
    try: main()
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        raise SystemExit(f"plain ARM payload failed: {exc}")
