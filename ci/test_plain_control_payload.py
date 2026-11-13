#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Regression tests for the plain-control payload verifier."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import plain_control_payload as payload
import svm_release_payload as common


class PlainControlPayloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiler = shutil.which("gcc")
        if not cls.compiler:
            raise unittest.SkipTest("gcc is required for ELF verifier tests")
        cls.temp = tempfile.TemporaryDirectory(prefix="plain-control-tests-")
        cls.work = Path(cls.temp.name)
        cls.source = cls.work / "probe.c"
        cls.source.write_text("int main(void) { return 0; }\n")
        cls.static_pie = cls.work / "static-pie"
        cls.dynamic_pie = cls.work / "dynamic-pie"
        cls.svm_pie = cls.work / "svm-pie"
        cls.static_exec = cls.work / "static-exec"
        subprocess.run([cls.compiler, "-static-pie", str(cls.source), "-o",
                        str(cls.static_pie)], check=True)
        subprocess.run([cls.compiler, "-fPIE", "-pie", str(cls.source), "-o",
                        str(cls.dynamic_pie)], check=True)
        subprocess.run([cls.compiler, "-static", "-no-pie", str(cls.source), "-o",
                        str(cls.static_exec)], check=True)
        note = cls.work / "svm-note.S"
        note.write_text(
            '.section .note.SVM,"a",@note\n'
            '.align 4\n.long 4,8,1\n.asciz "SVM"\n.align 4\n'
            '.long 2,0\n'
        )
        subprocess.run([cls.compiler, "-static-pie", str(cls.source), str(note),
                        "-o", str(cls.svm_pie)], check=True)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "temp"):
            cls.temp.cleanup()

    def populate_control_helpers(self, root):
        nommu = root / "libexec/plain-control/brk/nommu"
        mmu = root / "libexec/plain-control/brk/mmu"
        nommu.mkdir(parents=True)
        mmu.mkdir(parents=True)
        for test in ("brk01", "brk02"):
            shutil.copy2(self.static_exec, root / f"testcases/bin/{test}")
            shutil.copy2(self.static_pie, nommu / test)
            shutil.copy2(self.static_exec, mmu / test)
        setup = root / "plain-control-setup.sh"
        setup.write_text("#!/bin/sh\nexit 0\n")
        setup.chmod(0o755)

    def test_static_pie_without_svm_note_is_accepted(self):
        payload.verify_plain_elf(self.static_pie)

    def test_dynamic_pie_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "interpreter"):
            payload.verify_plain_elf(self.dynamic_pie)

    def test_static_non_pie_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "PIE"):
            payload.verify_plain_elf(self.static_exec)

    def test_svm_note_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "SVM-marked"):
            payload.verify_plain_elf(self.svm_pie)

    def test_clean_payload_and_tampering(self):
        root = self.work / "root"
        (root / "runtest").mkdir(parents=True)
        (root / "testcases/bin").mkdir(parents=True)
        shutil.copy2(Path(__file__).resolve().parents[1] / "runtest/syscalls",
                     root / "runtest/syscalls")
        shutil.copy2(self.static_pie, root / "testcases/bin/probe")
        self.populate_control_helpers(root)
        output = self.work / "release"
        args = argparse.Namespace(
            root=root, output=output,
            variant="control",
            source_commit="04d4de72361eb757133e5ecc735e6f4d1f45da9e",
            source_manifest=Path(__file__).resolve().parents[1] / "ci/svm-release-source.json",
            compiler="test gcc", libc_sha256="0" * 64, uapi_sha256="1" * 64,
        )
        result = payload.create(args)
        archive = output / result["archive"]["name"]
        manifest = output / f"{archive.name}.manifest.json"
        self.assertEqual(result["runtime_skip_pattern"], payload.RUNTIME_SKIP_PATTERN)
        payload.verify(archive, manifest)

        archive.write_bytes(archive.read_bytes() + b"tampered")
        with self.assertRaisesRegex(RuntimeError, "invalid plain-control release manifest"):
            payload.verify(archive, manifest)

    def test_control_variant_requires_non_pie_brk(self):
        root = self.work / "control-root"
        (root / "runtest").mkdir(parents=True)
        (root / "testcases/bin").mkdir(parents=True)
        shutil.copy2(Path(__file__).resolve().parents[1] / "runtest/syscalls",
                     root / "runtest/syscalls")
        shutil.copy2(self.static_pie, root / "testcases/bin/probe")
        self.populate_control_helpers(root)
        output = self.work / "release-control"
        args = argparse.Namespace(
            root=root, output=output, variant="control",
            source_commit="04d4de72361eb757133e5ecc735e6f4d1f45da9e",
            source_manifest=Path(__file__).resolve().parents[1] / "ci/svm-release-source.json",
            compiler="test gcc", libc_sha256="0" * 64, uapi_sha256="1" * 64,
        )
        result = payload.create(args)
        archive = output / result["archive"]["name"]
        manifest = output / f"{archive.name}.manifest.json"
        payload.verify(archive, manifest)
        self.assertEqual(result["supported_runtime_profiles"],
                         ["uml-nommu-plain", "uml-mmu-plain", "native-x86_64"])

    def test_changed_selection_is_rejected(self):
        root = self.work / "bad-selection"
        (root / "runtest").mkdir(parents=True)
        shutil.copy2(Path(__file__).resolve().parents[1] / "runtest/syscalls",
                     root / "runtest/syscalls")
        selection = root / "runtest/syscalls"
        selection.write_text(selection.read_text() + "# modified\n")
        with self.assertRaisesRegex(RuntimeError, "selection checksum"):
            payload.verify_runtime_contract(root)


if __name__ == "__main__":
    unittest.main(verbosity=2)
