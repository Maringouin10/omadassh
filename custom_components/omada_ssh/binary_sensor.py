"""Binary sensors for the Omada ER605 (SSH) integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import OmadaConfigEntry
from .entity import OmadaEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OmadaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the binary sensors."""
    async_add_entities([OmadaInternetSensor(entry.runtime_data, "internet")])


class OmadaInternetSensor(OmadaEntity, BinarySensorEntity):
    """Internet connectivity, based on a ping run by the router itself."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    @property
    def available(self) -> bool:
        """Unavailable when the router cannot run the ping."""
        return super().available and self.coordinator.data.router.ping is not None

    @property
    def is_on(self) -> bool | None:
        """Return True when the ping target answered."""
        ping = self.coordinator.data.router.ping
        return ping.success if ping else None
