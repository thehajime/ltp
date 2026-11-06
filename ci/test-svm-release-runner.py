#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Test the host input contract for the SVM LTP Release producer."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location(
    "svm_release_runner", Path(__file__).with_name("svm_release_runner.py"))
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


class ContractTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in ("compiler", "libc.so", "version.h", "plugin.so"):
            (self.root / name).write_text(name)
        (self.root / "compiler").chmod(0o755)
        self.contract = {
            "schema": 1, "architecture": "x86_64",
            "container_image": "alpine@sha256:" + "a" * 64,
            "host": "x86_64-alpine-linux-musl", "compiler": "compiler",
            "libc": "libc.so", "uapi": "version.h", "plugin": "plugin.so",
            "cppflags": ["-I/input/uapi/include"],
            "toolchain_root": ".", "toolchain_mount": "/work/sysroot",
        }
        self.save()

    def save(self):
        (self.root / "contract.json").write_text(json.dumps(self.contract))

    def test_valid_contract(self):
        data, files = runner.load_contract(self.root, "x86_64")
        self.assertEqual(data, self.contract)
        self.assertEqual(set(files), {"compiler", "libc", "uapi", "plugin",
                                      "toolchain_root"})

    def test_valid_local_content_digest(self):
        self.contract["container_image"] = "sha256:" + "b" * 64
        self.save()
        data, _ = runner.load_contract(self.root, "x86_64")
        self.assertEqual(data["container_image"], "sha256:" + "b" * 64)

    def test_compiler_symlink_keeps_invocation_name(self):
        wrapper = self.root / "toolchain-wrapper"
        wrapper.write_text("wrapper")
        wrapper.chmod(0o755)
        compiler = self.root / "target-gcc"
        compiler.symlink_to("toolchain-wrapper")
        self.contract["compiler"] = "target-gcc"
        self.save()
        _, files = runner.load_contract(self.root, "x86_64")
        self.assertEqual(files["compiler"], compiler)

    def test_architecture_and_image_are_fail_closed(self):
        with self.assertRaisesRegex(RuntimeError, "architecture"):
            runner.load_contract(self.root, "arm")
        self.contract["container_image"] = "alpine:latest"
        self.save()
        with self.assertRaisesRegex(RuntimeError, "pinned"):
            runner.load_contract(self.root, "x86_64")

    def test_path_escape_and_shell_text_are_rejected(self):
        self.contract["libc"] = "../outside"
        self.save()
        with self.assertRaises((RuntimeError, FileNotFoundError)):
            runner.load_contract(self.root, "x86_64")
        self.contract["libc"] = "libc.so"
        self.contract["cppflags"] = ["-I/input/uapi;id"]
        self.save()
        with self.assertRaisesRegex(RuntimeError, "cppflags"):
            runner.load_contract(self.root, "x86_64")

    def test_reserved_toolchain_mount_is_rejected(self):
        for mount in ("relative", "/", "/input", "/output/sdk"):
            with self.subTest(mount=mount):
                self.contract["toolchain_mount"] = mount
                self.save()
                with self.assertRaisesRegex(RuntimeError, "toolchain mount"):
                    runner.load_contract(self.root, "x86_64")


if __name__ == "__main__":
    unittest.main()
