"""Test weather of AccuWeather integration."""

from datetime import timedelta
from unittest.mock import PropertyMock, patch

from freezegun.api import FrozenDateTimeFactory
import pytest
from syrupy.assertion import SnapshotAssertion

from homeassistant.components.accuweather.const import (
    ATTRIBUTION,
    UPDATE_INTERVAL_DAILY_FORECAST,
)
from homeassistant.components.weather import (
    ATTR_FORECAST_CONDITION,
    ATTR_WEATHER_APPARENT_TEMPERATURE,
    ATTR_WEATHER_CLOUD_COVERAGE,
    ATTR_WEATHER_DEW_POINT,
    ATTR_WEATHER_HUMIDITY,
    ATTR_WEATHER_PRESSURE,
    ATTR_WEATHER_TEMPERATURE,
    ATTR_WEATHER_UV_INDEX,
    ATTR_WEATHER_VISIBILITY,
    ATTR_WEATHER_WIND_BEARING,
    ATTR_WEATHER_WIND_GUST_SPEED,
    ATTR_WEATHER_WIND_SPEED,
    DOMAIN as WEATHER_DOMAIN,
    LEGACY_SERVICE_GET_FORECAST,
    SERVICE_GET_FORECASTS,
    WeatherEntityFeature,
)
from homeassistant.const import (
    ATTR_ATTRIBUTION,
    ATTR_ENTITY_ID,
    ATTR_SUPPORTED_FEATURES,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from homeassistant.util.dt import utcnow

from . import init_integration

from tests.common import (
    async_fire_time_changed,
    load_json_array_fixture,
    load_json_object_fixture,
)
from tests.typing import WebSocketGenerator


async def test_weather(hass: HomeAssistant, entity_registry: er.EntityRegistry) -> None:
    """Test states of the weather without forecast."""
    await init_integration(hass)

    state = hass.states.get("weather.home")
    assert state
    assert state.state == "sunny"
    assert state.attributes.get(ATTR_WEATHER_HUMIDITY) == 67
    assert state.attributes.get(ATTR_WEATHER_PRESSURE) == 1012.0
    assert state.attributes.get(ATTR_WEATHER_TEMPERATURE) == 22.6
    assert state.attributes.get(ATTR_WEATHER_VISIBILITY) == 16.1
    assert state.attributes.get(ATTR_WEATHER_WIND_BEARING) == 180
    assert state.attributes.get(ATTR_WEATHER_WIND_SPEED) == 14.5  # 4.03 m/s -> km/h
    assert state.attributes.get(ATTR_WEATHER_APPARENT_TEMPERATURE) == 22.8
    assert state.attributes.get(ATTR_WEATHER_DEW_POINT) == 16.2
    assert state.attributes.get(ATTR_WEATHER_CLOUD_COVERAGE) == 10
    assert state.attributes.get(ATTR_WEATHER_WIND_GUST_SPEED) == 20.3
    assert state.attributes.get(ATTR_WEATHER_UV_INDEX) == 6
    assert state.attributes.get(ATTR_ATTRIBUTION) == ATTRIBUTION
    assert (
        state.attributes.get(ATTR_SUPPORTED_FEATURES)
        is WeatherEntityFeature.FORECAST_DAILY
    )

    entry = entity_registry.async_get("weather.home")
    assert entry
    assert entry.unique_id == "0123456"


async def test_availability(hass: HomeAssistant) -> None:
    """Ensure that we mark the entities unavailable correctly when service is offline."""
    await init_integration(hass)

    state = hass.states.get("weather.home")
    assert state
    assert state.state != STATE_UNAVAILABLE
    assert state.state == "sunny"

    future = utcnow() + timedelta(minutes=60)
    with patch(
        "homeassistant.components.accuweather.AccuWeather._async_get_data",
        side_effect=ConnectionError(),
    ):
        async_fire_time_changed(hass, future)
        await hass.async_block_till_done()

        state = hass.states.get("weather.home")
        assert state
        assert state.state == STATE_UNAVAILABLE

    future = utcnow() + timedelta(minutes=120)
    with (
        patch(
            "homeassistant.components.accuweather.AccuWeather.async_get_current_conditions",
            return_value=load_json_object_fixture(
                "accuweather/current_conditions_data.json"
            ),
        ),
        patch(
            "homeassistant.components.accuweather.AccuWeather.requests_remaining",
            new_callable=PropertyMock,
            return_value=10,
        ),
    ):
        async_fire_time_changed(hass, future)
        await hass.async_block_till_done()

        state = hass.states.get("weather.home")
        assert state
        assert state.state != STATE_UNAVAILABLE
        assert state.state == "sunny"


async def test_manual_update_entity(hass: HomeAssistant) -> None:
    """Test manual update entity via service homeassistant/update_entity."""
    await init_integration(hass)

    await async_setup_component(hass, "homeassistant", {})

    current = load_json_object_fixture("accuweather/current_conditions_data.json")

    with (
        patch(
            "homeassistant.components.accuweather.AccuWeather.async_get_current_conditions",
            return_value=current,
        ) as mock_current,
        patch(
            "homeassistant.components.accuweather.AccuWeather.requests_remaining",
            new_callable=PropertyMock,
            return_value=10,
        ),
    ):
        await hass.services.async_call(
            "homeassistant",
            "update_entity",
            {ATTR_ENTITY_ID: ["weather.home"]},
            blocking=True,
        )
    assert mock_current.call_count == 1


async def test_unsupported_condition_icon_data(hass: HomeAssistant) -> None:
    """Test with unsupported condition icon data."""
    await init_integration(hass, unsupported_icon=True)

    state = hass.states.get("weather.home")
    assert state.attributes.get(ATTR_FORECAST_CONDITION) is None


@pytest.mark.parametrize(
    ("service"),
    [
        SERVICE_GET_FORECASTS,
        LEGACY_SERVICE_GET_FORECAST,
    ],
)
async def test_forecast_service(
    hass: HomeAssistant,
    snapshot: SnapshotAssertion,
    service: str,
) -> None:
    """Test multiple forecast."""
    await init_integration(hass)

    response = await hass.services.async_call(
        WEATHER_DOMAIN,
        service,
        {
            "entity_id": "weather.home",
            "type": "daily",
        },
        blocking=True,
        return_response=True,
    )
    assert response == snapshot


async def test_forecast_subscription(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    freezer: FrozenDateTimeFactory,
    snapshot: SnapshotAssertion,
) -> None:
    """Test multiple forecast."""
    client = await hass_ws_client(hass)

    await init_integration(hass)

    await client.send_json_auto_id(
        {
            "type": "weather/subscribe_forecast",
            "forecast_type": "daily",
            "entity_id": "weather.home",
        }
    )
    msg = await client.receive_json()
    assert msg["success"]
    assert msg["result"] is None
    subscription_id = msg["id"]

    msg = await client.receive_json()
    assert msg["id"] == subscription_id
    assert msg["type"] == "event"
    forecast1 = msg["event"]["forecast"]

    assert forecast1 != []
    assert forecast1 == snapshot

    current = load_json_object_fixture("accuweather/current_conditions_data.json")
    forecast = load_json_array_fixture("accuweather/forecast_data.json")

    with (
        patch(
            "homeassistant.components.accuweather.AccuWeather.async_get_current_conditions",
            return_value=current,
        ),
        patch(
            "homeassistant.components.accuweather.AccuWeather.async_get_daily_forecast",
            return_value=forecast,
        ),
        patch(
            "homeassistant.components.accuweather.AccuWeather.requests_remaining",
            new_callable=PropertyMock,
            return_value=10,
        ),
    ):
        freezer.tick(UPDATE_INTERVAL_DAILY_FORECAST + timedelta(seconds=1))
        await hass.async_block_till_done()
        msg = await client.receive_json()

    assert msg["id"] == subscription_id
    assert msg["type"] == "event"
    forecast2 = msg["event"]["forecast"]

    assert forecast2 != []
    assert forecast2 == snapshot
