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
import tarfile
import tempfile


ARCHITECTURES = ("x86_64", "arm")
SCHEMA = 1


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


def deterministic_archive(root, output):
    with output.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
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
            len(data.get("fix_nommu_decisions", [])) != 7 or
            len(integration_patches) != 6 or
            {row.get("name") for row in integration_patches} != {
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
    if (set(manifest) != {"schema", "status", "architecture", "source_commit",
                          "source", "compiler", "libc_sha256", "uapi_sha256",
                          "files", "archive"} or
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
                    for name in ("libc_sha256", "uapi_sha256"))):
        raise RuntimeError("invalid release manifest")
    with tempfile.TemporaryDirectory(prefix="svm-ltp-payload-") as directory:
        destination = Path(directory)
        safe_extract(archive, destination)
        root = destination / "ltp"
        if root.is_symlink() or not root.is_dir() or inventory(root) != manifest["files"]:
            raise RuntimeError("release payload inventory mismatch")
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
