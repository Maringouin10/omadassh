"""Tests for the Home Assistant side of the integration."""

from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.omada_ssh.client import (
    OmadaAuthError,
    OmadaConnectionError,
    RouterData,
)
from custom_components.omada_ssh.const import DOMAIN
from custom_components.omada_ssh.parsers import (
    PingResult,
    parse_arp,
    parse_system_info,
)

from conftest import fixture

USER_INPUT = {
    CONF_HOST: "192.168.0.1",
    CONF_PORT: 22,
    CONF_USERNAME: "admin",
    CONF_PASSWORD: "secret",
}
CLIENT = "custom_components.omada_ssh.client.OmadaSSHClient"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


PING_OK = PingResult(4, 4, 0.0, 12.3)


def _router_data(arp_text=None, ping=PING_OK):
    return RouterData(
        system=parse_system_info(fixture("show_system_info.txt")),
        arp=parse_arp(arp_text if arp_text is not None else fixture("show_arp.txt")),
        ping=ping,
    )


@pytest.fixture
def mock_client():
    with (
        patch(f"{CLIENT}.async_fetch", new_callable=AsyncMock) as fetch,
        patch(f"{CLIENT}.async_get_system_info", new_callable=AsyncMock) as info,
        patch(f"{CLIENT}.async_close", new_callable=AsyncMock),
    ):
        fetch.return_value = _router_data()
        info.return_value = parse_system_info(fixture("show_system_info.txt"))
        yield fetch, info


async def test_config_flow(hass: HomeAssistant, mock_client) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "ER605"
    assert result["result"].unique_id == "d4:d6:df:53:48:f3"


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (OmadaAuthError("no"), "invalid_auth"),
        (OmadaConnectionError("x"), "cannot_connect"),
    ],
)
async def test_config_flow_errors(hass, mock_client, error, expected) -> None:
    mock_client[1].side_effect = error
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}


async def _setup(hass) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, data=USER_INPUT, unique_id="d4:d6:df:53:48:f3", title="ER605"
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_entities(hass: HomeAssistant, mock_client) -> None:
    await _setup(hass)

    assert hass.states.get("sensor.er605_connected_clients").state == "15"
    assert hass.states.get("sensor.er605_wan_gateway").state == "205.173.162.2"
    assert hass.states.get("sensor.er605_firmware").state.startswith("2.4.5")
    assert hass.states.get("sensor.er605_internet_latency").state == "12.3"
    assert hass.states.get("binary_sensor.er605_internet").state == "on"
    assert hass.states.get("sensor.er605_last_boot").state != "unknown"

    trackers = hass.states.async_entity_ids("device_tracker")
    assert len(trackers) == 15  # the WAN gateway is not tracked
    state = hass.states.get("device_tracker.omada_ssh_70_b3_06_33_04_30")
    assert state.state == "home"
    assert state.attributes["ip"] == "192.168.0.139"


async def test_ping_unavailable(hass: HomeAssistant, mock_client) -> None:
    mock_client[0].return_value = _router_data(ping=None)
    await _setup(hass)
    assert hass.states.get("binary_sensor.er605_internet").state == "unavailable"
    assert hass.states.get("sensor.er605_internet_latency").state == "unavailable"
    assert hass.states.get("sensor.er605_connected_clients").state == "15"


async def test_client_goes_away(hass: HomeAssistant, mock_client, freezer) -> None:
    await _setup(hass)
    entity = "device_tracker.omada_ssh_70_b3_06_33_04_30"
    arp = "\n".join(
        line for line in fixture("show_arp.txt").splitlines() if "70-B3" not in line
    )
    mock_client[0].return_value = _router_data(arp_text=arp)

    # Still home within the 3 minute delay.
    freezer.tick(timedelta(seconds=60))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(entity).state == "home"

    freezer.tick(timedelta(seconds=180))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(entity).state == "not_home"


async def test_new_client_added(hass: HomeAssistant, mock_client) -> None:
    await _setup(hass)
    extra = "vlan1         192.168.0.200   AA-BB-CC-DD-EE-FF      Dynamic   N/A"
    mock_client[0].return_value = _router_data(
        arp_text=fixture("show_arp.txt") + extra + "\n"
    )
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
    await hass.async_block_till_done()
    assert hass.states.get("device_tracker.omada_ssh_aa_bb_cc_dd_ee_ff").state == "home"


async def test_auth_failure_starts_reauth(hass: HomeAssistant, mock_client) -> None:
    mock_client[0].side_effect = OmadaAuthError("refused")
    entry = MockConfigEntry(domain=DOMAIN, data=USER_INPUT, unique_id="x")
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is config_entries.ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert flows and flows[0]["context"]["source"] == "reauth"


async def test_unload(hass: HomeAssistant, mock_client) -> None:
    entry = await _setup(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is config_entries.ConfigEntryState.NOT_LOADED
