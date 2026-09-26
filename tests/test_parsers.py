"""Tests for the CLI output parsers, using real ER605 v2.30 output."""

from conftest import fixture, parsers


def test_system_info():
    info = parsers.parse_system_info(fixture("show_system_info.txt"))
    assert info.name == "ER605"
    assert info.hardware_version == "ER605 v2.30"
    assert info.firmware_version == "2.4.5 Build 20260721 Rel.81048"
    assert info.mac == "d4:d6:df:53:48:f3"
    assert info.system_time == "2026-09-25 22:34:40"
    assert info.uptime_seconds == 28 * 86400 + 5 * 3600 + 12 * 60 + 3


def test_uptime_variants():
    assert parsers.parse_uptime("0 day - 0 hour - 1 min - 5 sec") == 65
    assert parsers.parse_uptime("2 days - 1 hour") == 2 * 86400 + 3600
    assert parsers.parse_uptime("garbage") is None


def test_arp():
    entries = parsers.parse_arp(fixture("show_arp.txt"))
    assert len(entries) == 16
    first = entries[0]
    assert first.interface == "vlan1"
    assert first.ip == "192.168.0.139"
    assert first.mac == "70:b3:06:33:04:30"
    assert first.type == "Dynamic"
    assert first.age is None
    assert not first.is_wan

    wan = [e for e in entries if e.is_wan]
    assert len(wan) == 1
    assert wan[0].ip == "205.173.162.2"
    assert wan[0].interface == "vlan4094"


def test_arp_empty():
    assert parsers.parse_arp("") == []


def test_key_values():
    out = "SNMPv1-v2c:          off\t\nSNMPv3:              off\t\n"
    assert parsers.parse_key_values(out) == {"SNMPv1-v2c": "off", "SNMPv3": "off"}


def test_ping_linux_style():
    out = """PING 8.8.8.8 (8.8.8.8): 56 data bytes
64 bytes from 8.8.8.8: seq=0 ttl=117 time=12.1 ms
64 bytes from 8.8.8.8: seq=1 ttl=117 time=11.9 ms

--- 8.8.8.8 ping statistics ---
4 packets transmitted, 2 packets received, 50% packet loss
round-trip min/avg/max = 11.9/12.0/12.1 ms"""
    result = parsers.parse_ping(out)
    assert result.sent == 4
    assert result.received == 2
    assert result.loss_percent == 50
    assert result.avg_ms == 12.0
    assert result.success


def test_ping_windows_style():
    out = """Reply from 8.8.8.8: bytes=32 time=10ms TTL=117
Reply from 8.8.8.8: bytes=32 time<1ms TTL=117
    Packets: Sent = 2, Received = 2, Lost = 0 (0% loss),"""
    result = parsers.parse_ping(out)
    assert result.loss_percent == 0
    assert result.received == 2
    assert result.success


def test_ping_timeout():
    out = "Request timed out.\nRequest timed out.\n2 packets transmitted, 0 received, 100% packet loss"
    result = parsers.parse_ping(out)
    assert result.received == 0
    assert not result.success


def test_dhcp_clients():
    leases = parsers.parse_dhcp_clients(fixture("show_dhcp_client_list.txt"))
    assert [lease.mac for lease in leases] == [
        "70:b3:06:33:04:30",
        "d8:3a:dd:c9:69:9b",
        "00:22:4d:7a:ad:e2",
    ]
    assert leases[0].hostname == "iPhone-de-Marin"
    assert leases[0].ip == "192.168.0.139"
    assert leases[0].lease == "01:52:10"
    assert not leases[0].reserved
    assert leases[1].reserved
    assert leases[2].hostname is None


def test_dhcp_clients_space_aligned():
    out = """Client Name : laptop
MAC Address : 7C:2C:67:8E:52:5C
IP Address  : 192.168.0.117
Lease Time  : 1:00:00
"""
    (lease,) = parsers.parse_dhcp_clients(out)
    assert lease.hostname == "laptop"
    assert lease.mac == "7c:2c:67:8e:52:5c"
    assert lease.ip == "192.168.0.117"
