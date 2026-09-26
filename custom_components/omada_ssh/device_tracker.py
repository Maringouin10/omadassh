"""Device trackers for clients seen in the ER605 ARP table."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.components.device_tracker import ScannerEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import CONF_CONSIDER_HOME, DEFAULT_CONSIDER_HOME, DOMAIN
from .coordinator import OmadaConfigEntry, OmadaCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OmadaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one tracker per client MAC address."""
    coordinator = entry.runtime_data
    tracked: set[str] = set()

    # Recreate the trackers known from a previous run, so devices that are
    # away when Home Assistant starts show as away instead of disappearing.
    registry = er.async_get(hass)
    for reg_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if reg_entry.domain == "device_tracker" and reg_entry.unique_id:
            tracked.add(reg_entry.unique_id)

    @callback
    def _async_add_new() -> None:
        new = set(coordinator.data.lan_clients) - tracked
        if new:
            tracked.update(new)
            async_add_entities(OmadaClientTracker(coordinator, mac) for mac in new)

    async_add_entities(OmadaClientTracker(coordinator, mac) for mac in tracked)
    _async_add_new()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new))


class OmadaClientTracker(CoordinatorEntity[OmadaCoordinator], ScannerEntity):
    """A client of the router, home when seen recently in the ARP table."""

    def __init__(self, coordinator: OmadaCoordinator, mac: str) -> None:
        super().__init__(coordinator)
        self._mac = mac
        self._attr_unique_id = mac
        self._consider_home = timedelta(
            seconds=coordinator.config_entry.options.get(
                CONF_CONSIDER_HOME, DEFAULT_CONSIDER_HOME
            )
        )
        self._last_ip: str | None = None

    @property
    def entity_registry_enabled_default(self) -> bool:
        """Enable every tracker, not only those matching a known device."""
        return True

    @property
    def name(self) -> str:
        """Return the DHCP host name, or the MAC address when unknown."""
        return self.hostname or f"{DOMAIN} {self._mac}"

    @property
    def hostname(self) -> str | None:
        """Return the host name announced to the DHCP server."""
        return self.coordinator.hostnames.get(self._mac)

    @property
    def mac_address(self) -> str:
        """Return the MAC address."""
        return self._mac

    @property
    def ip_address(self) -> str | None:
        """Return the last known IP address."""
        if client := self.coordinator.data.lan_clients.get(self._mac):
            self._last_ip = client.ip
        return self._last_ip

    @property
    def is_connected(self) -> bool:
        """Return True when seen within the consider home delay."""
        last_seen = self.coordinator.last_seen.get(self._mac)
        if last_seen is None:
            return False
        return dt_util.utcnow() - last_seen < self._consider_home

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Return when the client was last seen."""
        last_seen = self.coordinator.last_seen.get(self._mac)
        return {"last_seen": last_seen.isoformat()} if last_seen else {}
