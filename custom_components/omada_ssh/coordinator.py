"""Data update coordinator for the Omada ER605 (SSH) integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .client import OmadaAuthError, OmadaError, OmadaSSHClient, RouterData
from .const import (
    CONF_PING_TARGET,
    DEFAULT_PING_TARGET,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    UPTIME_TOLERANCE,
)
from .parsers import ArpEntry

_LOGGER = logging.getLogger(__name__)

type OmadaConfigEntry = ConfigEntry[OmadaCoordinator]


@dataclass
class OmadaData:
    """Data exposed to the entities."""

    router: RouterData
    boot_time: datetime | None
    lan_clients: dict[str, ArpEntry] = field(default_factory=dict)
    hostnames: dict[str, str] = field(default_factory=dict)
    wan_entries: list[ArpEntry] = field(default_factory=list)


class OmadaCoordinator(DataUpdateCoordinator[OmadaData]):
    """Poll the router over SSH."""

    config_entry: OmadaConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: OmadaConfigEntry, client: OmadaSSHClient
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )
        self.client = client
        # MAC -> last time it was seen in the ARP table.
        self.last_seen: dict[str, datetime] = {}
        # MAC -> host name from the DHCP leases, kept after the lease expires.
        self.hostnames: dict[str, str] = {}
        self._boot_time: datetime | None = None

    async def _async_update_data(self) -> OmadaData:
        ping_target = self.config_entry.options.get(
            CONF_PING_TARGET, DEFAULT_PING_TARGET
        )
        try:
            router = await self.client.async_fetch(ping_target or None)
        except OmadaAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except OmadaError as err:
            raise UpdateFailed(str(err)) from err

        for lease in router.dhcp or ():
            if lease.hostname:
                self.hostnames[lease.mac] = lease.hostname

        now = dt_util.utcnow()
        lan: dict[str, ArpEntry] = {}
        wan: list[ArpEntry] = []
        for entry in router.arp:
            if entry.is_wan:
                wan.append(entry)
            else:
                lan[entry.mac] = entry
                self.last_seen[entry.mac] = now

        if router.system.uptime_seconds is not None:
            boot = now - timedelta(seconds=router.system.uptime_seconds)
            # Keep the value stable across polls, only move it after a reboot.
            if (
                self._boot_time is None
                or abs(boot - self._boot_time) > UPTIME_TOLERANCE
            ):
                self._boot_time = boot.replace(microsecond=0)

        return OmadaData(
            router=router,
            boot_time=self._boot_time,
            lan_clients=lan,
            hostnames=dict(self.hostnames),
            wan_entries=wan,
        )
