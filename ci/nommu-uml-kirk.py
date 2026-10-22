# SPDX-License-Identifier: GPL-2.0-or-later
"""Kirk communication plugin for running an UML NOMMU guest via Docker."""

import asyncio
import os
import shlex
import shutil
import time
import uuid
from typing import Any, Dict, Optional

from libkirk.com import ComChannel, IOBuffer
from libkirk.errors import CommunicationError


class NommuUmlChannel(ComChannel):
    _name = "nommu-uml"
    _guest_root = "/opt/ltp"
    _prompt = b"__KIRK_PROMPT__ "

    def __init__(self) -> None:
        self._ltp_root = ""
        self._init_script = ""
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._rx = bytearray()
        self._lock = asyncio.Lock()

    @staticmethod
    def _trace(message: str) -> None:
        trace_path = os.environ.get("NOMMU_KIRK_TRACE")
        if trace_path:
            with open(trace_path, "a", encoding="utf-8") as trace:
                trace.write(f"{time.monotonic():.3f} {message}\n")

    def setup(self, **kwargs: Dict[str, Any]) -> None:
        self._ltp_root = os.path.abspath(kwargs.get("ltp_root", ""))
        self._init_script = os.path.abspath(kwargs.get("init_script", ""))
        if not os.path.isdir(self._ltp_root):
            raise CommunicationError(f"LTP install directory not found: {self._ltp_root}")
        if not os.path.isfile(self._init_script):
            raise CommunicationError(f"UML init script not found: {self._init_script}")
        if not shutil.which("docker"):
            raise CommunicationError("docker command not found")

    @property
    def config_help(self) -> Dict[str, str]:
        return {
            "ltp_root": "Host path to the installed LTP tree mounted at /opt/ltp",
            "init_script": "Host path to the guest init shell script",
        }

    @property
    def parallel_execution(self) -> bool:
        return False

    async def active(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    async def communicate(self, iobuffer: Optional[IOBuffer] = None) -> None:
        if await self.active():
            raise CommunicationError("NOMMU UML is already running")

        image = "ghcr.io/thehajime/alpine:3.20.3-um-nommu"
        cmd = [
            "docker", "run", "--rm", "-i", "--privileged",
            # UML stores guest RAM in a shared-memory file. Keep this limit
            # above the configured 2 GiB guest RAM or the guest stalls once
            # it faults in more than the tmpfs quota.
            "--tmpfs", "/dev/shm:rw,exec,nosuid,nodev,size=3g",
            "-v", f"{self._ltp_root}:/opt/ltp",
            "-v", f"{self._init_script}:/nommu-uml-init:ro",
            "--entrypoint", "/root/vmlinux", image,
            "con0=fd:0,fd:1", "console=tty",
            "vec0:transport=raw,ifname=eth0,depth=128,gro=1",
            "root=/dev/root", "rootflags=/", "rootfstype=hostfs", "rw",
            "mem=2048m", "loglevel=0", "init=/nommu-uml-init",
        ]

        self._proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        self._rx.clear()

        try:
            await self._read_until(self._prompt, 180, iobuffer)
            await self._send("echo __KIRK_READY__\n")
            await self._read_until(b"__KIRK_READY__", 20, iobuffer)
            await self._read_until(self._prompt, 20, iobuffer)
        except Exception as err:
            await self.stop(iobuffer)
            raise CommunicationError(f"NOMMU UML guest did not become ready: {err}") from err

    async def stop(self, iobuffer: Optional[IOBuffer] = None) -> None:
        proc = self._proc
        if proc is None:
            return

        if proc.returncode is None:
            try:
                await self._send("poweroff -f\n")
                await asyncio.wait_for(proc.wait(), timeout=20)
            except (asyncio.TimeoutError, OSError):
                proc.kill()
                await proc.wait()

        self._proc = None
        if proc.stdin:
            proc.stdin.close()
        self._rx.clear()

    async def restart(self, iobuffer: Optional[IOBuffer] = None) -> None:
        await self.stop(iobuffer)
        await self.communicate(iobuffer)

    async def ping(self) -> float:
        start = time.monotonic()
        ret = await self.run_command("true")
        if not ret or ret["returncode"]:
            raise CommunicationError("NOMMU UML ping failed")
        return time.monotonic() - start

    async def run_command(
        self,
        command: str,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        iobuffer: Optional[IOBuffer] = None,
    ) -> Optional[Dict[str, Any]]:
        if not command:
            raise ValueError("command is empty")
        if not await self.active():
            raise CommunicationError("NOMMU UML is not running")

        # Kirk keeps its LTPROOT path on the host and passes it to the
        # communication channel. The guest sees the same tree at /opt/ltp.
        command = command.replace(self._ltp_root, self._guest_root)
        if cwd:
            cwd = cwd.replace(self._ltp_root, self._guest_root)
        if env:
            env = {
                key: value.replace(self._ltp_root, self._guest_root)
                for key, value in env.items()
            }

        prefix = []
        if cwd:
            prefix.append(f"cd {shlex.quote(cwd)}")
        if env:
            prefix.extend(f"export {key}={shlex.quote(value)}" for key, value in env.items())

        token = f"__KIRK_RC_{uuid.uuid4().hex}__"
        script = "; ".join(prefix + [command])
        script += f"; __kirk_rc=$?; printf '\\n{token}:%s\\n' \"$__kirk_rc\"\n"

        async with self._lock:
            start = time.monotonic()
            self._trace(f"SEND cwd={cwd!r} env={env!r} command={command!r}")
            await self._send(script)
            try:
                output = await self._read_until(token.encode() + b":", 3600, iobuffer)
            except asyncio.CancelledError:
                # Kirk cancels this coroutine when --exec-timeout expires.
                # Interrupt the foreground guest command so the interactive
                # shell can accept the next test instead of remaining wedged.
                try:
                    await self._send("\x03")
                    await asyncio.wait_for(
                        self._read_until(token.encode() + b":", 10, iobuffer),
                        timeout=10,
                    )
                    await asyncio.wait_for(
                        self._read_until(b"\n", 5, iobuffer), timeout=5
                    )
                except (asyncio.TimeoutError, CommunicationError, OSError):
                    pass
                raise
            marker = output.rfind(token.encode())
            status = await self._read_until(b"\n", 5, iobuffer)
            try:
                retcode = int(status.decode(errors="replace").strip())
            except ValueError as err:
                raise CommunicationError(f"Invalid command status marker: {status!r}") from err
            # Wait until the interactive shell has returned to its prompt
            # before sending another command. The completion marker is printed
            # just before the shell finishes the current input line; without
            # prompt synchronization, a fast follow-up write can be lost.
            await self._read_until(self._prompt, 20, iobuffer)

        stdout = output[:marker].decode(errors="replace").strip("\r\n")
        self._trace(
            f"DONE rc={retcode} duration={time.monotonic() - start:.3f}s "
            f"output_bytes={len(stdout)} tail={stdout[-160:]!r}"
        )
        return {
            "command": command,
            "returncode": retcode,
            "stdout": stdout,
            "exec_time": time.monotonic() - start,
        }

    async def fetch_file(self, target_path: str) -> bytes:
        prefixes = (self._ltp_root, self._guest_root)
        prefix = next(
            (
                root
                for root in prefixes
                if target_path == root or target_path.startswith(root + "/")
            ),
            None,
        )
        if not prefix:
            raise CommunicationError(f"Unsupported guest file path: {target_path}")
        relative = os.path.normpath(target_path[len(prefix):].lstrip("/"))
        if relative == ".." or relative.startswith("../"):
            raise CommunicationError(f"Invalid guest file path: {target_path}")
        host_path = os.path.join(self._ltp_root, relative)
        try:
            with open(host_path, "rb") as source:
                return source.read()
        except OSError as err:
            raise CommunicationError(f"Cannot read LTP file {host_path}: {err}") from err

    async def _send(self, data: str) -> None:
        if not self._proc or not self._proc.stdin:
            raise CommunicationError("UML console is closed")
        self._proc.stdin.write(data.encode())
        await self._proc.stdin.drain()

    async def _read_until(
        self,
        marker: bytes,
        timeout: float,
        iobuffer: Optional[IOBuffer] = None,
    ) -> bytes:
        end = time.monotonic() + timeout
        while True:
            pos = self._rx.find(marker)
            if pos >= 0:
                end_pos = pos + len(marker)
                out = bytes(self._rx[:end_pos])
                del self._rx[:end_pos]
                return out

            if time.monotonic() >= end:
                raise asyncio.TimeoutError(f"Timed out waiting for {marker!r}")

            if not self._proc or not self._proc.stdout:
                raise CommunicationError("UML console is closed")
            try:
                chunk = await asyncio.wait_for(
                    self._proc.stdout.read(65536), end - time.monotonic()
                )
            except asyncio.TimeoutError:
                raise
            except OSError as err:
                raise CommunicationError(f"Cannot read UML console: {err}") from err
            if not chunk:
                raise CommunicationError("UML console closed")

            self._rx.extend(chunk)
            # BusyBox ash may ask for the cursor position. The pipe-based UML
            # console has no terminal emulator, so answer that query here.
            while b"\x1b[6n" in self._rx:
                query = self._rx.index(b"\x1b[6n")
                del self._rx[query:query + len(b"\x1b[6n")]
                await self._send("\x1b[1;1R")
            if os.environ.get("NOMMU_KIRK_TRACE_RX"):
                self._trace(f"RECV bytes={len(chunk)} tail={chunk[-240:]!r}")
            if iobuffer:
                await iobuffer.write(chunk.decode(errors="replace"))
