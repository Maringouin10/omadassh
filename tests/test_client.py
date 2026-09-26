"""End-to-end test of the SSH client against a fake ER605 CLI server."""

import asyncio

import asyncssh
import pytest

from conftest import client as omada_client, fixture

pytestmark = pytest.mark.usefixtures("socket_enabled")

BANNER = (
    "\r\n\r\nNote:This gateway is being managed by Controller. "
    "Some functions of CLI Server are prohibited.\r\n\r\n\r\n"
)
USER, PASSWORD = "admin", "secret"


class _Server(asyncssh.SSHServer):
    def begin_auth(self, username):
        return True

    def password_auth_supported(self):
        return True

    def validate_password(self, username, password):
        return username == USER and password == PASSWORD


def _make_handler(ping_output):
    responses = {
        "show system-info": fixture("show_system_info.txt"),
        "show arp": fixture("show_arp.txt"),
    }

    async def handle(process):
        privileged = False
        process.stdout.write(BANNER + ">")
        while True:
            line = await process.stdin.readline()
            if not line:
                break
            cmd = line.strip()
            process.stdout.write(cmd + "\r\n")  # echo, like a real terminal
            if cmd == "enable":
                privileged = True
            elif cmd == "exit":
                if not privileged:
                    break
                privileged = False
            elif privileged and cmd in responses:
                process.stdout.write(responses[cmd].replace("\n", "\r\n"))
            elif privileged and cmd.startswith("ping") and ping_output is not None:
                if ping_output == "hang":
                    await asyncio.sleep(3600)
                process.stdout.write(ping_output.replace("\n", "\r\n") + "\r\n")
            else:
                word = cmd.split()[0] if cmd else ""
                process.stdout.write(f'Error: Invalid command "{word}"\r\n')
            process.stdout.write("\r\n#" if privileged else "\r\n>")
        process.exit(0)

    return handle


@pytest.fixture
async def server(request):
    ping_output = getattr(request, "param", None)
    key = asyncssh.generate_private_key("ssh-ed25519")
    srv = await asyncssh.create_server(
        _Server,
        "127.0.0.1",
        0,
        server_host_keys=[key],
        process_factory=_make_handler(ping_output),
        encoding="utf-8",
    )
    port = srv.sockets[0].getsockname()[1]
    yield port
    srv.close()
    await srv.wait_closed()


async def test_fetch(server):
    c = omada_client.OmadaSSHClient("127.0.0.1", server, USER, PASSWORD)
    try:
        data = await c.async_fetch(None)
        assert data.system.firmware_version == "2.4.5 Build 20260721 Rel.81048"
        assert data.system.mac == "d4:d6:df:53:48:f3"
        assert len(data.arp) == 16
        assert data.ping is None
        # The session is reused for the next poll.
        again = await c.async_fetch(None)
        assert len(again.arp) == 16
    finally:
        await c.async_close()


async def test_wrong_password(server):
    c = omada_client.OmadaSSHClient("127.0.0.1", server, USER, "wrong")
    with pytest.raises(omada_client.OmadaAuthError):
        await c.async_get_system_info()
    await c.async_close()


async def test_unreachable():
    c = omada_client.OmadaSSHClient("127.0.0.1", 1, USER, PASSWORD)
    with pytest.raises(omada_client.OmadaConnectionError):
        await c.async_get_system_info()


async def test_command_error(server):
    c = omada_client.OmadaSSHClient("127.0.0.1", server, USER, PASSWORD)
    try:
        with pytest.raises(omada_client.OmadaCommandError, match="Invalid command"):
            await c.async_run_commands(["show interface"])
    finally:
        await c.async_close()


@pytest.mark.parametrize(
    "server",
    [
        "4 packets transmitted, 4 packets received, 0% packet loss\n"
        "64 bytes from 8.8.8.8: seq=0 ttl=117 time=12.0 ms"
    ],
    indirect=True,
)
async def test_ping(server):
    c = omada_client.OmadaSSHClient("127.0.0.1", server, USER, PASSWORD)
    try:
        data = await c.async_fetch("8.8.8.8")
        assert data.ping is not None
        assert data.ping.success
        assert data.ping.avg_ms == 12.0
    finally:
        await c.async_close()


async def test_ping_unsupported_is_not_fatal(server):
    # Without a ping_output the fake CLI rejects ping with "Error: ...".
    c = omada_client.OmadaSSHClient("127.0.0.1", server, USER, PASSWORD)
    try:
        data = await c.async_fetch("8.8.8.8")
        assert data.ping is None
        assert len(data.arp) == 16
    finally:
        await c.async_close()


@pytest.mark.parametrize("server", ["hang"], indirect=True)
async def test_ping_hanging_is_disabled(server, monkeypatch):
    monkeypatch.setattr(omada_client, "PING_TIMEOUT", 0.5)
    c = omada_client.OmadaSSHClient("127.0.0.1", server, USER, PASSWORD)
    try:
        data = await c.async_fetch("8.8.8.8")
        assert data.ping is None
        # Next poll reconnects and skips the ping.
        data = await c.async_fetch("8.8.8.8")
        assert data.ping is None
        assert len(data.arp) == 16
    finally:
        await c.async_close()
