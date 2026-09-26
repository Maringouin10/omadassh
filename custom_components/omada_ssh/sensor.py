"""Sensors for the Omada ER605 (SSH) integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import OmadaConfigEntry, OmadaCoordinator, OmadaData
from .entity import OmadaEntity


@dataclass(frozen=True, kw_only=True)
class OmadaSensorDescription(SensorEntityDescription):
    """Describe an Omada sensor."""

    value_fn: Callable[[OmadaData], Any]
    attrs_fn: Callable[[OmadaData], dict[str, Any]] | None = None
    ping: bool = False


def _wan_gateway(data: OmadaData) -> str | None:
    return data.wan_entries[0].ip if data.wan_entries else None


SENSORS: tuple[OmadaSensorDescription, ...] = (
    OmadaSensorDescription(
        key="last_boot",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.boot_time,
    ),
    OmadaSensorDescription(
        key="firmware",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.router.system.firmware_version,
    ),
    OmadaSensorDescription(
        key="hardware",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.router.system.hardware_version,
    ),
    OmadaSensorDescription(
        key="connected_clients",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: len(data.lan_clients),
        attrs_fn=lambda data: {
            "clients": [
                {"ip": c.ip, "mac": c.mac, "interface": c.interface}
                for c in sorted(
                    data.lan_clients.values(),
                    key=lambda c: tuple(int(p) for p in c.ip.split(".")),
                )
            ]
        },
    ),
    OmadaSensorDescription(
        key="wan_gateway",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_wan_gateway,
        attrs_fn=lambda data: {
            "mac": data.wan_entries[0].mac if data.wan_entries else None,
            "interface": data.wan_entries[0].interface if data.wan_entries else None,
        },
    ),
    OmadaSensorDescription(
        key="ping_latency",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        ping=True,
        value_fn=lambda data: data.router.ping.avg_ms if data.router.ping else None,
    ),
    OmadaSensorDescription(
        key="ping_loss",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        ping=True,
        value_fn=lambda data: (
            data.router.ping.loss_percent if data.router.ping else None
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OmadaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensors."""
    coordinator = entry.runtime_data
    async_add_entities(OmadaSensor(coordinator, desc) for desc in SENSORS)


class OmadaSensor(OmadaEntity, SensorEntity):
    """Sensor reading one value from the coordinator data."""

    entity_description: OmadaSensorDescription

    def __init__(
        self, coordinator: OmadaCoordinator, description: OmadaSensorDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        """Ping sensors are unavailable when the router cannot ping."""
        if self.entity_description.ping and self.coordinator.data.router.ping is None:
            return False
        return super().available

    @property
    def native_value(self) -> Any:
        """Return the sensor value."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes."""
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.coordinator.data)
