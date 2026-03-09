"""Platform for sensor integration."""
import logging
from datetime import timedelta, datetime

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers import entity_registry as er
from homeassistant.util import slugify

from .const import DOMAIN, CONF_BASE_URL, CONF_STOP_ID, CONF_STOP_NAME, CONF_AGENCY_NAME, CONF_ROUTE_ID, CONF_ROUTE_NAME
from .api import AvailClient

_LOGGER = logging.getLogger(__name__)

# CONFIGURATION:
# Departures update frequently (1 min) to keep ETAs accurate
DEPARTURE_INTERVAL = timedelta(seconds=60)
# Alerts change rarely, so we fetch them less often (5 mins) to prevent timeouts
ALERT_INTERVAL = timedelta(minutes=5)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    base_url = entry.data[CONF_BASE_URL]
    stop_id = entry.data[CONF_STOP_ID]
    stop_name = entry.data.get(CONF_STOP_NAME, f"Stop {stop_id}")
    route_id = entry.data.get(CONF_ROUTE_ID)
    route_name = entry.data.get(CONF_ROUTE_NAME)
    agency_name = entry.data.get(CONF_AGENCY_NAME, "myStop")
    
    session = async_get_clientsession(hass)
    client = AvailClient(session, base_url)
    ent_reg = er.async_get(hass)

    # 1. Stop Data (High Frequency)
    stop_coordinator = AvailDataCoordinator(hass, client, stop_id, agency_name)
    entities = [
        AvailStopSensor(stop_coordinator, stop_id, stop_name, agency_name, route_id, route_name)
    ]
    await stop_coordinator.async_config_entry_first_refresh()

    # 2. General Alerts (Low Frequency)
    gen_alert_uid = slugify(f"{agency_name}_general_alerts")
    if not ent_reg.async_get_entity_id("sensor", DOMAIN, gen_alert_uid):
        alerts_coordinator = AvailAlertsCoordinator(hass, client, agency_name)
        await alerts_coordinator.async_config_entry_first_refresh()
        entities.append(AvailAlertsSensor(alerts_coordinator, agency_name, "General"))

    # 3. Route Alerts (Low Frequency)
    if route_id:
        route_alert_uid = slugify(f"{agency_name}_route_{route_id}_alerts")
        if not ent_reg.async_get_entity_id("sensor", DOMAIN, route_alert_uid):
            route_alerts_coordinator = AvailRouteAlertsCoordinator(hass, client, agency_name, route_id)
            await route_alerts_coordinator.async_config_entry_first_refresh()
            entities.append(AvailRouteAlertsSensor(route_alerts_coordinator, agency_name, route_id, route_name))

    async_add_entities(entities, True)

# --- COORDINATORS ---

class AvailDataCoordinator(DataUpdateCoordinator):
    """Coordinator for Stop Departures (Frequent Updates)."""
    def __init__(self, hass, client, stop_id, agency_name):
        self.client = client
        self.stop_id = stop_id
        super().__init__(
            hass, 
            _LOGGER, 
            name=f"{agency_name} Stop {stop_id}", 
            update_interval=DEPARTURE_INTERVAL
        )

    async def _async_update_data(self):
        try:
            return await self.client.get_departures(self.stop_id)
        except Exception as err:
            raise UpdateFailed(f"Error fetching departures: {err}")

class AvailAlertsCoordinator(DataUpdateCoordinator):
    """Coordinator for General Agency Alerts (Slow Updates)."""
    def __init__(self, hass, client, agency_name):
        self.client = client
        super().__init__(
            hass, 
            _LOGGER, 
            name=f"{agency_name} Alerts", 
            update_interval=ALERT_INTERVAL
        )

    async def _async_update_data(self):
        try:
            return await self.client.get_alerts()
        except Exception as err:
            raise UpdateFailed(f"Error fetching alerts: {err}")

class AvailRouteAlertsCoordinator(DataUpdateCoordinator):
    """Coordinator for Specific Route Alerts (Slow Updates)."""
    def __init__(self, hass, client, agency_name, route_id):
        self.client = client
        self.route_id = route_id
        super().__init__(
            hass, 
            _LOGGER, 
            name=f"{agency_name} Route {route_id} Alerts", 
            update_interval=ALERT_INTERVAL
        )

    async def _async_update_data(self):
        try:
            return await self.client.get_route_details(self.route_id)
        except Exception as err:
            raise UpdateFailed(f"Error fetching route alerts: {err}")

# --- SENSORS ---

class AvailStopSensor(CoordinatorEntity, SensorEntity):
    """Sensor for Next Departure."""
    def __init__(self, coordinator, stop_id, stop_name, agency_name, route_id, route_name):
        super().__init__(coordinator)
        self._stop_id = stop_id
        self._stop_name = stop_name
        self._agency_name = agency_name
        self._route_id = str(route_id) if route_id else None
        self._route_name = route_name
        
        self._attr_name = stop_name
        self._attr_unique_id = slugify(f"{agency_name}_{stop_id}_next_departure")
        self._attr_icon = "mdi:bus"

    @property
    def native_value(self):
        """State is the very next departure time and direction."""
        departures = self._get_filtered_departures()
        
        if not departures:
            return "No Service"
            
        next_bus = departures[0]
        
        try:
            raw_time = next_bus.get("eta", "")
            dt = datetime.fromisoformat(raw_time)
            nice_time = dt.strftime("%-I:%M %p")
        except (ValueError, TypeError):
            nice_time = next_bus.get("eta", "Unknown")

        direction = "Outbound" if next_bus.get("direction") == "O" else "Inbound"
        return f"{direction} - {nice_time}"

    @property
    def extra_state_attributes(self):
        return {
            "stop_id": self._stop_id, 
            "stop_name": self._stop_name,
            "agency": self._agency_name, 
            "departures": self._get_filtered_departures()
        }

    def _get_filtered_departures(self):
        raw_data = self.coordinator.data or []
        if self._route_id:
            filtered = [d for d in raw_data if d.get("route_id") == self._route_id]
        else:
            filtered = raw_data

        try:
            return sorted(filtered, key=lambda x: x.get("eta", ""))
        except Exception:
            return filtered

    @property
    def device_info(self) -> DeviceInfo:
        if self._route_id:
            route_display = self._route_name if self._route_name else f"Route {self._route_id}"
            device_name = f"{self._agency_name} {route_display}"
            identifier = f"{self._agency_name}_route_{self._route_id}"
        else:
            device_name = f"{self._agency_name} Stops"
            identifier = f"{self._agency_name}_stops"
            
        return DeviceInfo(
            identifiers={(DOMAIN, slugify(identifier))},
            name=device_name,
            manufacturer="Avail Technologies",
            model="myStop",
        )

class AvailAlertsSensor(CoordinatorEntity, SensorEntity):
    """Sensor for General Alerts."""
    def __init__(self, coordinator, agency_name, alert_type):
        super().__init__(coordinator)
        self._agency_name = agency_name
        self.alert_type = alert_type
        
        self._attr_name = "General Alerts"
        self._attr_unique_id = slugify(f"{agency_name}_general_alerts")
        self._attr_icon = "mdi:alert-circle"

    @property
    def native_value(self):
        return len(self.coordinator.data) if self.coordinator.data else 0

    @property
    def extra_state_attributes(self):
        return {"alerts": self.coordinator.data, "agency": self._agency_name, "type": self.alert_type}

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, slugify(f"{self._agency_name}_info"))},
            name=f"{self._agency_name} Info",
            manufacturer="Avail Technologies",
            model="myStop",
        )

class AvailRouteAlertsSensor(CoordinatorEntity, SensorEntity):
    """Sensor for Route Alerts."""
    def __init__(self, coordinator, agency_name, route_id, route_name):
        super().__init__(coordinator)
        self._agency_name = agency_name
        self._route_id = route_id
        self._route_name = route_name
        
        self._attr_name = "Route Alerts"
        self._attr_unique_id = slugify(f"{agency_name}_route_{route_id}_alerts")
        self._attr_icon = "mdi:alert-octagon"

    @property
    def native_value(self):
        return len(self.coordinator.data) if self.coordinator.data else 0

    @property
    def extra_state_attributes(self):
        return {"alerts": self.coordinator.data, "agency": self._agency_name, "type": "Route"}

    @property
    def device_info(self) -> DeviceInfo:
        route_display = self._route_name if self._route_name else f"Route {self._route_id}"
        device_name = f"{self._agency_name} {route_display}"
        identifier = f"{self._agency_name}_route_{self._route_id}"
        
        return DeviceInfo(
            identifiers={(DOMAIN, slugify(identifier))},
            name=device_name,
            manufacturer="Avail Technologies",
            model="myStop",
        )