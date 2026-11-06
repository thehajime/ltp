#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Test immutable SVM LTP release payload handling."""

import argparse
import copy
import json
from pathlib import Path
import tempfile
import unittest

import svm_release_payload as payload


class PayloadTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.root = self.directory / "root"
        (self.root / "testcases/bin").mkdir(parents=True)
        self.binary = self.root / "testcases/bin/getpid01"
        self.binary.write_bytes(b"fixture")
        self.binary.chmod(0o755)
        (self.root / "bin").mkdir()
        (self.root / "bin/getpid01").symlink_to("../testcases/bin/getpid01")
        self.output = self.directory / "output"
        source = Path(__file__).with_name("svm-release-source.json")
        args = argparse.Namespace(
            root=self.root, output=self.output, arch="x86_64",
            source_commit="b" * 40, source_manifest=source,
            compiler="fixture gcc", libc_sha256="c" * 64,
            uapi_sha256="d" * 64)
        self.manifest = payload.create(args)
        self.archive = self.output / self.manifest["archive"]["name"]
        self.manifest_path = self.archive.with_name(self.archive.name + ".manifest.json")

    def save(self, value):
        self.manifest_path.write_text(json.dumps(value))

    def test_round_trip_and_deterministic_archive(self):
        self.assertEqual(payload.verify(self.archive, self.manifest_path), self.manifest)
        other = self.directory / "other.tar.gz"
        payload.deterministic_archive(self.root, other)
        self.assertEqual(payload.digest(self.archive), payload.digest(other))

    def test_content_and_mode_changes_are_rejected(self):
        for field, value in (("sha256", "0" * 64), ("mode", 0o644)):
            with self.subTest(field=field):
                changed = copy.deepcopy(self.manifest)
                changed["files"]["testcases/bin/getpid01"][field] = value
                self.save(changed)
                with self.assertRaisesRegex(RuntimeError, "inventory mismatch"):
                    payload.verify(self.archive, self.manifest_path)

    def test_archive_manifest_and_architecture_changes_are_rejected(self):
        changed = copy.deepcopy(self.manifest)
        changed["archive"]["sha256"] = "0" * 64
        self.save(changed)
        with self.assertRaisesRegex(RuntimeError, "invalid release manifest"):
            payload.verify(self.archive, self.manifest_path)

    def test_source_compiler_libc_and_uapi_changes_are_rejected(self):
        for field, value in (("source_commit", "short"), ("compiler", ""),
                             ("libc_sha256", "0"), ("uapi_sha256", "0")):
            with self.subTest(field=field):
                changed = copy.deepcopy(self.manifest)
                changed[field] = value
                self.save(changed)
                with self.assertRaisesRegex(RuntimeError, "invalid release manifest"):
                    payload.verify(self.archive, self.manifest_path)
        source = self.directory / "source.json"
        source.write_text("{}")
        with self.assertRaisesRegex(RuntimeError, "source composition"):
            payload.source_contract(source)
        changed = copy.deepcopy(self.manifest)
        changed["architecture"] = "riscv64"
        self.save(changed)
        with self.assertRaisesRegex(RuntimeError, "invalid release manifest"):
            payload.verify(self.archive, self.manifest_path)
        for field, value in (("manifest_sha256", "0"),
                             ("integration_commits", [])):
            with self.subTest(source_field=field):
                changed = copy.deepcopy(self.manifest)
                changed["source"][field] = value
                self.save(changed)
                with self.assertRaisesRegex(RuntimeError,
                                            "invalid release manifest"):
                    payload.verify(self.archive, self.manifest_path)

    def test_absolute_or_escaping_symlink_is_rejected(self):
        link = self.root / "bad-link"
        for target in ("/etc/passwd", "../../outside"):
            with self.subTest(target=target):
                link.symlink_to(target)
                with self.assertRaisesRegex(RuntimeError, "symlink"):
                    payload.inventory(self.root)
                link.unlink()


if __name__ == "__main__":
    unittest.main()
