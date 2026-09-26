"""Base entity for the Omada ER605 (SSH) integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import OmadaCoordinator


class OmadaEntity(CoordinatorEntity[OmadaCoordinator]):
    """Entity attached to the router device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: OmadaCoordinator, key: str) -> None:
        super().__init__(coordinator)
        router_id = coordinator.config_entry.unique_id
        self._attr_unique_id = f"{router_id}_{key}"
        self._attr_translation_key = key
        system = coordinator.data.router.system
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, router_id)},
            connections={(CONNECTION_NETWORK_MAC, system.mac)} if system.mac else set(),
            manufacturer="TP-Link",
            model=system.name or "ER605",
            hw_version=system.hardware_version,
            sw_version=system.firmware_version,
            name=system.name or "ER605",
            configuration_url=f"http://{coordinator.client.host}",
        )
