"""Parsers for the TP-Link Omada ER605 CLI output.

This module has no Home Assistant dependency so it can be unit tested alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re

_UPTIME_PART = re.compile(r"(\d+)\s*(day|hour|min|sec)", re.IGNORECASE)
_UPTIME_FACTORS = {"day": 86400, "hour": 3600, "min": 60, "sec": 1}

_ARP_LINE = re.compile(
    r"^\s*(?P<interface>\S+)\s+"
    r"(?P<ip>\d{1,3}(?:\.\d{1,3}){3})\s+"
    r"(?P<mac>[0-9A-Fa-f]{2}(?:[-:][0-9A-Fa-f]{2}){5})\s+"
    r"(?P<type>\S+)"
    r"(?:\s+(?P<age>\S+))?"
)

_PING_LOSS = re.compile(r"(\d+(?:\.\d+)?)\s*%\s*(?:packet\s*)?loss", re.IGNORECASE)
_PING_SENT_RECV = re.compile(
    r"(\d+)\s+packets?\s+transmitted,\s*(\d+)\s+(?:packets?\s+)?received",
    re.IGNORECASE,
)
_PING_TIME = re.compile(r"time\s*[=<]\s*(\d+(?:\.\d+)?)\s*ms", re.IGNORECASE)

# The ER605 marks its WAN ports with high internal VLAN ids (4094, 4093, ...).
WAN_INTERFACE_PREFIX = "vlan409"


@dataclass
class SystemInfo:
    """Output of `show system-info`."""

    description: str | None = None
    name: str | None = None
    hardware_version: str | None = None
    firmware_version: str | None = None
    mac: str | None = None
    system_time: str | None = None
    uptime_seconds: int | None = None
    raw: dict[str, str] = field(default_factory=dict)


@dataclass
class ArpEntry:
    """One line of `show arp`."""

    interface: str
    ip: str
    mac: str
    type: str
    age: str | None

    @property
    def is_wan(self) -> bool:
        """Return True when the entry was learnt on a WAN interface."""
        return self.interface.lower().startswith(WAN_INTERFACE_PREFIX)


@dataclass
class PingResult:
    """Summary of a `ping` run."""

    sent: int | None
    received: int | None
    loss_percent: float | None
    avg_ms: float | None

    @property
    def success(self) -> bool:
        """Return True when at least one reply came back."""
        if self.received is not None:
            return self.received > 0
        if self.loss_percent is not None:
            return self.loss_percent < 100
        return self.avg_ms is not None


def normalize_mac(mac: str) -> str:
    """Return a MAC address as lower case, colon separated."""
    return mac.replace("-", ":").lower()


def parse_uptime(text: str) -> int | None:
    """Parse `28 day - 5 hour - 12 min - 3 sec` into seconds."""
    parts = _UPTIME_PART.findall(text)
    if not parts:
        return None
    return sum(int(value) * _UPTIME_FACTORS[unit.lower()] for value, unit in parts)


def parse_system_info(output: str) -> SystemInfo:
    """Parse the output of `show system-info`."""
    raw: dict[str, str] = {}
    for line in output.splitlines():
        if " - " not in line:
            continue
        key, _, value = line.partition(" - ")
        key = key.strip()
        if key:
            raw[key] = value.strip()

    info = SystemInfo(raw=raw)
    info.description = raw.get("System Description")
    info.name = raw.get("System Name")
    info.hardware_version = raw.get("Hardware Version")
    info.firmware_version = raw.get("Firmware Version")
    if mac := raw.get("Mac Address"):
        info.mac = normalize_mac(mac)
    info.system_time = raw.get("System Time")
    if running := raw.get("Running Time"):
        info.uptime_seconds = parse_uptime(running)
    return info


def parse_arp(output: str) -> list[ArpEntry]:
    """Parse the output of `show arp`."""
    entries: list[ArpEntry] = []
    for line in output.splitlines():
        match = _ARP_LINE.match(line)
        if not match:
            continue
        age = match.group("age")
        entries.append(
            ArpEntry(
                interface=match.group("interface"),
                ip=match.group("ip"),
                mac=normalize_mac(match.group("mac")),
                type=match.group("type"),
                age=None if age in (None, "N/A") else age,
            )
        )
    return entries


def parse_key_values(output: str) -> dict[str, str]:
    """Parse `key: value` style output (show snmp-server, show ssh configuration)."""
    result: dict[str, str] = {}
    for line in output.splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip():
            result[key.strip()] = value.strip()
    return result


def parse_ping(output: str) -> PingResult:
    """Parse ping output, tolerant to the Linux and Windows style summaries."""
    sent = received = None
    if match := _PING_SENT_RECV.search(output):
        sent, received = int(match.group(1)), int(match.group(2))

    loss = None
    if match := _PING_LOSS.search(output):
        loss = float(match.group(1))
    elif sent:
        loss = round(100 * (sent - (received or 0)) / sent, 1)

    times = [float(t) for t in _PING_TIME.findall(output)]
    avg = round(sum(times) / len(times), 2) if times else None
    if received is None and times:
        received = len(times)

    return PingResult(sent=sent, received=received, loss_percent=loss, avg_ms=avg)
