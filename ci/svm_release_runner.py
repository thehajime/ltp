#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Run the sealed SVM LTP producer from a validated host input contract."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys


ARCHITECTURES = ("x86_64", "arm")
SAFE_VALUE = re.compile(r"[A-Za-z0-9_+.,:/=@%-]+")
IMAGE = re.compile(
    r"(?:[a-z0-9][a-z0-9._/-]*@)?sha256:[0-9a-f]{64}")
CONTAINER_PATH = re.compile(r"/[A-Za-z0-9_.+/-]+")
RESERVED_MOUNTS = ("/input", "/source", "/output", "/repository", "/ccache")


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def contained_file(root, relative, *, executable=False):
    if not isinstance(relative, str) or not relative or relative.startswith("/"):
        raise RuntimeError("contract paths must be non-empty and relative")
    path = (root / relative).resolve(strict=True)
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise RuntimeError(f"contract path escapes input root: {relative}")
    if executable and not os.access(path, os.X_OK):
        raise RuntimeError(f"contract compiler is not executable: {relative}")
    return path


def contained_directory(root, relative):
    if not isinstance(relative, str) or not relative or relative.startswith("/"):
        raise RuntimeError("contract paths must be non-empty and relative")
    path = (root / relative).resolve(strict=True)
    if not path.is_relative_to(root.resolve()) or not path.is_dir():
        raise RuntimeError(f"contract directory escapes input root: {relative}")
    return path


def load_contract(root, architecture):
    path = root / "contract.json"
    data = json.loads(path.read_text())
    required = {"schema", "architecture", "container_image", "host",
                "compiler", "libc", "uapi", "cppflags", "plugin",
                "toolchain_root", "toolchain_mount"}
    if set(data) != required or data["schema"] != 1:
        raise RuntimeError("unexpected producer contract schema")
    if data["architecture"] != architecture or architecture not in ARCHITECTURES:
        raise RuntimeError("producer contract architecture mismatch")
    if not isinstance(data["container_image"], str) or not IMAGE.fullmatch(
            data["container_image"]):
        raise RuntimeError("container image must be pinned by SHA-256 digest")
    if not isinstance(data["host"], str) or not SAFE_VALUE.fullmatch(data["host"]):
        raise RuntimeError("invalid configure host tuple")
    if (not isinstance(data["cppflags"], list) or
            not all(isinstance(item, str) and SAFE_VALUE.fullmatch(item)
                    for item in data["cppflags"])):
        raise RuntimeError("cppflags must be a list of safe single arguments")
    mount = data["toolchain_mount"]
    if (not isinstance(mount, str) or not CONTAINER_PATH.fullmatch(mount) or
            mount == "/" or any(mount == item or mount.startswith(item + "/")
                                for item in RESERVED_MOUNTS)):
        raise RuntimeError("invalid or reserved toolchain mount")
    files = {
        "compiler": contained_file(root, data["compiler"], executable=True),
        "libc": contained_file(root, data["libc"]),
        "uapi": contained_file(root, data["uapi"]),
        "plugin": contained_file(root, data["plugin"]),
    }
    files["toolchain_root"] = contained_directory(root, data["toolchain_root"])
    return data, files


def run(args):
    source = args.source.resolve(strict=True)
    root = args.input_root.resolve(strict=True)
    output = args.output.resolve()
    cache = args.ccache_dir.resolve()
    if not source.is_file() or output.exists():
        raise RuntimeError("source must be a file and output must be fresh")
    data, files = load_contract(root, args.architecture)
    output.mkdir(parents=True)
    cache.mkdir(parents=True, exist_ok=True)
    source_commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=args.repository, text=True).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise RuntimeError("repository HEAD is not a full Git object name")
    container_paths = {name: "/input/" + path.relative_to(root).as_posix()
                       for name, path in files.items()}
    command = [
        "docker", "run", "--rm", "--network", "bridge",
        "--entrypoint", "sh",
        "--volume", f"{root}:/input:ro",
        "--volume", f"{source.parent}:/source:ro",
        "--volume", f"{output}:/output",
        "--volume", f"{cache}:/ccache",
        "--volume", f"{files['toolchain_root']}:{data['toolchain_mount']}:ro",
    ]
    environment = {
        "SVM_ARCH": args.architecture,
        "SVM_CC": container_paths["compiler"],
        "SVM_HOST": data["host"],
        "SVM_SOURCE_COMMIT": source_commit,
        "SVM_LIBC_SHA256": digest(files["libc"]),
        "SVM_UAPI_SHA256": digest(files["uapi"]),
        "SVM_CPPFLAGS": " ".join(data["cppflags"]),
        "SVM_PLUGIN": container_paths["plugin"],
        "SVM_BUILD_UID": str(os.getuid()),
        "SVM_BUILD_GID": str(os.getgid()),
        "SVM_BUILD_JOBS": str(args.jobs),
        "CCACHE_DIR": "/ccache",
    }
    for name, value in environment.items():
        command.extend(["--env", f"{name}={value}"])
    # The mounted source is a tar archive. Invoke the builder from the checked
    # out repository through a separate read-only mount.
    command.extend([
        "--volume", f"{args.repository.resolve()}:/repository:ro",
        data["container_image"], "/repository/ci/svm_release_build.sh",
        "/source/" + source.name, "/output",
    ])
    subprocess.run(command, check=True)
    summary = json.loads((output / "build-summary.json").read_text())
    if summary != {"status": "PASS", "scope": "syscalls-release-build"}:
        raise RuntimeError("producer did not emit the accepted build summary")
    return {"status": "PASS", "architecture": args.architecture,
            "source_commit": source_commit, "output": str(output),
            "container_image": data["container_image"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--architecture", choices=ARCHITECTURES, required=True)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ccache-dir", type=Path, required=True)
    parser.add_argument("--jobs", type=int, default=2)
    args = parser.parse_args()
    if not 1 <= args.jobs <= 64:
        parser.error("jobs must be between one and 64")
    print(json.dumps(run(args), sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"SVM release runner failed: {error}", file=sys.stderr)
        sys.exit(1)
