"""SSH client driving the interactive CLI of the TP-Link Omada ER605.

The ER605 does not run commands passed on the SSH command line: it only offers
an interactive CLI (`>` prompt, then `enable` for the `#` prompt). This client
opens a shell, waits for the prompt, and sends commands one by one.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import re

import asyncssh

from .parsers import (
    ArpEntry,
    PingResult,
    SystemInfo,
    parse_arp,
    parse_ping,
    parse_system_info,
)

_LOGGER = logging.getLogger(__name__)

_PROMPT = re.compile(r"(?:^|[\r\n])[^\r\n]*?([>#])[ \t]*$")
_PAGER = re.compile(r"(--\s*more\s*--|press any key)", re.IGNORECASE)
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

LOGIN_TIMEOUT = 20
COMMAND_TIMEOUT = 20
PING_TIMEOUT = 30

# Some TP-Link firmwares only offer this legacy key exchange; append it to the
# defaults so modern algorithms are still preferred when available.
_KEX_ALGS = "+diffie-hellman-group14-sha1"


class OmadaError(Exception):
    """Base error."""


class OmadaConnectionError(OmadaError):
    """The router could not be reached or the session broke."""


class OmadaAuthError(OmadaError):
    """The credentials were refused."""


class OmadaCommandError(OmadaError):
    """The CLI answered a command with an error."""


@dataclass
class RouterData:
    """Everything collected during one poll."""

    system: SystemInfo
    arp: list[ArpEntry]
    ping: PingResult | None


class OmadaSSHClient:
    """Minimal client for the ER605 CLI."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self._conn: asyncssh.SSHClientConnection | None = None
        self._process: asyncssh.SSHClientProcess | None = None
        self._lock = asyncio.Lock()
        self._ping_broken = False

    async def _connect(self) -> None:
        try:
            self._conn = await asyncio.wait_for(
                asyncssh.connect(
                    self.host,
                    port=self.port,
                    username=self.username,
                    password=self.password,
                    known_hosts=None,
                    client_keys=None,
                    agent_path=None,
                    kex_algs=_KEX_ALGS,
                ),
                LOGIN_TIMEOUT,
            )
        except asyncssh.PermissionDenied as err:
            raise OmadaAuthError(str(err)) from err
        except (TimeoutError, OSError, asyncssh.Error) as err:
            raise OmadaConnectionError(f"{type(err).__name__}: {err}") from err

        try:
            self._process = await self._conn.create_process(
                term_type="vt100",
                term_size=(200, 1000),
                encoding="utf-8",
                errors="replace",
            )
            prompt = (await self._read_until_prompt(LOGIN_TIMEOUT))[1]
            if prompt == ">":
                await self._send("enable")
                _, prompt = await self._read_until_prompt(COMMAND_TIMEOUT)
            if prompt != "#":
                raise OmadaAuthError("Could not enter privileged mode (enable)")
        except BaseException:
            await self._close()
            raise

    async def _send(self, command: str) -> None:
        assert self._process is not None
        self._process.stdin.write(command + "\n")

    async def _read_until_prompt(self, timeout: float) -> tuple[str, str]:
        """Read output until a `>` or `#` prompt. Return (output, prompt char)."""
        assert self._process is not None
        buffer = ""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise OmadaConnectionError(
                    f"Timed out waiting for the CLI prompt, got: {buffer[-200:]!r}"
                )
            try:
                chunk = await asyncio.wait_for(
                    self._process.stdout.read(4096), remaining
                )
            except TimeoutError as err:
                raise OmadaConnectionError(
                    f"Timed out waiting for the CLI prompt, got: {buffer[-200:]!r}"
                ) from err
            except (OSError, asyncssh.Error) as err:
                raise OmadaConnectionError(str(err)) from err
            if not chunk:
                raise OmadaConnectionError("SSH session closed by the router")
            buffer += _ANSI.sub("", chunk)
            if _PAGER.search(buffer[-80:]):
                buffer = _PAGER.sub("", buffer)
                self._process.stdin.write(" ")
                continue
            if match := _PROMPT.search(buffer):
                return buffer[: match.start()], match.group(1)

    async def _run(self, command: str, timeout: float = COMMAND_TIMEOUT) -> str:
        await self._send(command)
        output, prompt = await self._read_until_prompt(timeout)
        # Drop the echoed command line.
        lines = output.replace("\r", "").split("\n")
        if lines and lines[0].strip() == command:
            lines = lines[1:]
        text = "\n".join(lines).strip("\n")
        if prompt != "#":
            raise OmadaCommandError(f"Left privileged mode after {command!r}")
        for line in lines:
            if line.strip().startswith("Error:"):
                raise OmadaCommandError(f"{command!r}: {line.strip()}")
        return text

    async def _close(self) -> None:
        if self._process is not None:
            try:
                self._process.stdin.write("exit\n")
            except Exception:
                pass
            self._process.close()
            self._process = None
        if self._conn is not None:
            self._conn.close()
            try:
                await asyncio.wait_for(self._conn.wait_closed(), 5)
            except (TimeoutError, OSError, asyncssh.Error):
                pass
            self._conn = None

    async def async_close(self) -> None:
        """Close the SSH session."""
        async with self._lock:
            await self._close()

    async def async_run_commands(self, commands: list[str]) -> dict[str, str]:
        """Run several commands in one session and return their outputs.

        The session is kept open between calls and reopened if it broke.
        """
        async with self._lock:
            for attempt in (1, 2):
                if self._process is None:
                    await self._connect()
                try:
                    return {cmd: await self._run(cmd) for cmd in commands}
                except OmadaConnectionError:
                    await self._close()
                    if attempt == 2:
                        raise
                    _LOGGER.debug("SSH session lost, reconnecting")
        raise AssertionError("unreachable")

    async def async_get_system_info(self) -> SystemInfo:
        """Return the parsed `show system-info`."""
        out = await self.async_run_commands(["show system-info"])
        return parse_system_info(out["show system-info"])

    async def async_ping(self, target: str) -> PingResult | None:
        """Ping a target from the router. Return None when ping is unusable.

        The ping output format of the ER605 CLI is not documented, so any
        failure only disables the ping sensors instead of failing the update.
        """
        if self._ping_broken:
            return None
        async with self._lock:
            try:
                if self._process is None:
                    await self._connect()
                output = await self._run(f"ping {target}", PING_TIMEOUT)
            except OmadaCommandError as err:
                _LOGGER.warning("Ping from the router is not usable: %s", err)
                self._ping_broken = True
                return None
            except OmadaConnectionError as err:
                _LOGGER.warning(
                    "Ping from the router did not finish (%s); disabling ping", err
                )
                self._ping_broken = True
                await self._close()
                return None
        _LOGGER.debug("Ping output: %r", output)
        return parse_ping(output)

    async def async_fetch(self, ping_target: str | None) -> RouterData:
        """Collect everything needed by the integration."""
        out = await self.async_run_commands(["show system-info", "show arp"])
        ping = await self.async_ping(ping_target) if ping_target else None
        return RouterData(
            system=parse_system_info(out["show system-info"]),
            arp=parse_arp(out["show arp"]),
            ping=ping,
        )
