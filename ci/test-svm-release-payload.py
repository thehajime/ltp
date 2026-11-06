#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Test immutable SVM LTP release payload handling."""

import argparse
import copy
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

import svm_release_payload as payload


def note_elf(architecture, interpreter=None, abi=None):
    expected = payload.SVM_ABI[architecture]
    interpreter = interpreter or expected["interpreter"]
    abi = abi or struct.pack("<II", expected["era"], expected["abi"])
    note = struct.pack("<III", 4, len(abi), 1) + b"SVM\0" + abi
    note += b"\0" * ((-len(note)) % 4)
    phoff = 64 if expected["elf_class"] == 2 else 52
    note_offset, interp_offset = 256, 320
    size = interp_offset + len(interpreter)
    data = bytearray(size)
    data[:7] = bytes((0x7f, 0x45, 0x4c, 0x46, expected["elf_class"], 1, 1))
    if expected["elf_class"] == 2:
        struct.pack_into("<HHIQQQIHHHHHH", data, 16, 3,
                         expected["machine"], 1, 0, phoff, 0, 0, 64, 56,
                         2, 0, 0, 0)
        struct.pack_into("<IIQQQQQQ", data, phoff, 4, 4, note_offset, 0, 0,
                         len(note), len(note), 4)
        struct.pack_into("<IIQQQQQQ", data, phoff + 56, 3, 4, interp_offset,
                         0, 0, len(interpreter), len(interpreter), 1)
    else:
        struct.pack_into("<HHIIIIIHHHHHH", data, 16, 3,
                         expected["machine"], 1, 0, phoff, 0, 0, 52, 32,
                         2, 0, 0, 0)
        struct.pack_into("<IIIIIIII", data, phoff, 4, note_offset, 0, 0,
                         len(note), len(note), 4, 4)
        struct.pack_into("<IIIIIIII", data, phoff + 32, 3, interp_offset,
                         0, 0, len(interpreter), len(interpreter), 4, 1)
    data[note_offset:note_offset + len(note)] = note
    data[interp_offset:interp_offset + len(interpreter)] = interpreter
    return bytes(data)


class PayloadTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.root = self.directory / "root"
        (self.root / "testcases/bin").mkdir(parents=True)
        self.binary = self.root / "testcases/bin/getpid01"
        self.binary.write_bytes(note_elf("x86_64"))
        self.binary.chmod(0o775)
        (self.root / "testcases/bin").chmod(0o775)
        (self.root / "bin").mkdir()
        (self.root / "bin/getpid01").symlink_to("../testcases/bin/getpid01")
        selection = self.root / "runtest/syscalls"
        selection.parent.mkdir()
        selection.write_text("first getpid01\nsecond getpid01 -i 2\n")
        self._selection_patches = [
            patch.object(payload, "SYSCALLS_SHA256",
                         hashlib.sha256(selection.read_bytes()).hexdigest()),
            patch.object(payload, "SYSCALL_LABELS", 2),
        ]
        for item in self._selection_patches:
            item.start()
            self.addCleanup(item.stop)
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
        self.assertEqual(self.manifest["files"]["testcases/bin/getpid01"]["mode"],
                         0o755)
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

    def test_svm_abi_is_required_for_both_architectures(self):
        for architecture in ("x86_64", "arm"):
            path = self.directory / f"{architecture}.elf"
            path.write_bytes(note_elf(architecture))
            payload.verify_svm_elf(path, architecture)
            path.write_bytes(note_elf(architecture, abi=b"bad-note"))
            with self.assertRaisesRegex(RuntimeError, "SVM ABI"):
                payload.verify_svm_elf(path, architecture)

    def test_wrong_architecture_and_loader_are_rejected(self):
        path = self.directory / "wrong.elf"
        path.write_bytes(note_elf("arm"))
        with self.assertRaisesRegex(RuntimeError, "ELF class/encoding mismatch"):
            payload.verify_svm_elf(path, "x86_64")
        path.write_bytes(note_elf("x86_64", interpreter=b"/lib/ld.so\0"))
        with self.assertRaisesRegex(RuntimeError, "SVM ABI/interpreter"):
            payload.verify_svm_elf(path, "x86_64")

    def test_runtime_selection_hash_and_count_are_required(self):
        selection = self.root / "runtest/syscalls"
        selection.write_text("different getpid01\n")
        with self.assertRaisesRegex(RuntimeError, "selection checksum"):
            payload.verify_runtime_contract(self.root, "x86_64")


if __name__ == "__main__":
    unittest.main()
