"""Config flow for Avail MyStop integration."""
import logging
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN, CONF_BASE_URL, CONF_STOP_ID, CONF_STOP_NAME, CONF_AGENCY_NAME, CONF_ROUTE_ID, CONF_ROUTE_NAME, DISCOVERY_URL
from .api import AvailClient

_LOGGER = logging.getLogger(__name__)

class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Avail MyStop."""

    VERSION = 1

    def __init__(self):
        """Initialize the flow."""
        self.found_agencies = {}
        self.selected_agency = None
        self.selected_base_url = None
        self.selected_route_id = None
        self.selected_route_name = None
        self.routes_map = {}
        self.stops_map = {}

    async def async_step_user(self, user_input=None):
        """Step 1: Select Agency."""
        errors = {}
        session = async_get_clientsession(self.hass)
        client = AvailClient(session)

        if user_input is not None:
            selection = user_input.get(CONF_AGENCY_NAME)
            
            if selection == "Manual Entry":
                return await self.async_step_manual()

            if selection in self.found_agencies:
                self.selected_agency = selection
                self.selected_base_url = self.found_agencies[selection]
                return await self.async_step_route()

        if not self.found_agencies:
            self.found_agencies = await client.get_agencies(DISCOVERY_URL)

        if not self.found_agencies:
             return await self.async_step_manual()

        agency_names = sorted(list(self.found_agencies.keys()))
        agency_names.insert(0, "Manual Entry")
        
        return self.async_show_form(
            step_id="user", 
            data_schema=vol.Schema({
                vol.Required(CONF_AGENCY_NAME): vol.In(agency_names)
            }), 
            errors=errors
        )

    async def async_step_route(self, user_input=None):
        """Step 2: Select Route."""
        errors = {}
        session = async_get_clientsession(self.hass)
        client = AvailClient(session, self.selected_base_url)

        if user_input is not None:
            route_label = user_input.get("route")
            if route_label in self.routes_map:
                self.selected_route_id = self.routes_map[route_label]
                self.selected_route_name = route_label
                return await self.async_step_stop()
            errors["base"] = "unknown"

        if not self.routes_map:
            try:
                self.routes_map, self.stops_map = await client.get_routes()
            except Exception:
                return await self.async_step_manual()

        if not self.routes_map:
            return await self.async_step_manual()

        def route_sort_key(label):
            try:
                parts = label.split(" - ")
                val = parts[0]
                return (int(val) if val.isdigit() else float('inf'), label)
            except (ValueError, IndexError):
                return (float('inf'), label)

        route_list = sorted(list(self.routes_map.keys()), key=route_sort_key)
        
        return self.async_show_form(
            step_id="route",
            data_schema=vol.Schema({vol.Required("route"): vol.In(route_list)}),
            errors=errors,
            description_placeholders={"agency": self.selected_agency}
        )

    async def async_step_stop(self, user_input=None):
        """Step 3: Select Stop."""
        if user_input is not None:
            stop_label = user_input.get("stop")
            
            clean_name = stop_label.rpartition(" (")[0]
            
            route_stops = self.stops_map.get(self.selected_route_id, {})
            stop_id = route_stops.get(stop_label)

            if stop_id:
                unique_id = f"{self.selected_base_url}_{stop_id}"
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                # Title uses Name now!
                return self.async_create_entry(
                    title=f"{self.selected_agency} - {clean_name}",
                    data={
                        CONF_AGENCY_NAME: self.selected_agency,
                        CONF_BASE_URL: self.selected_base_url,
                        CONF_STOP_ID: str(stop_id),
                        CONF_STOP_NAME: clean_name,
                        CONF_ROUTE_ID: str(self.selected_route_id),
                        CONF_ROUTE_NAME: self.selected_route_name
                    }
                )

        route_stops = self.stops_map.get(self.selected_route_id, {})
        stop_list = sorted(list(route_stops.keys()))

        return self.async_show_form(
            step_id="stop",
            data_schema=vol.Schema({vol.Required("stop"): vol.In(stop_list)}),
            description_placeholders={"route_id": str(self.selected_route_id)}
        )

    async def async_step_manual(self, user_input=None):
        """Handle manual entry."""
        errors = {}
        
        schema_dict = {}
        if self.selected_agency:
            schema_dict[vol.Required(CONF_AGENCY_NAME, default=self.selected_agency)] = str
        else:
            schema_dict[vol.Required(CONF_AGENCY_NAME)] = str

        if self.selected_base_url:
            schema_dict[vol.Required(CONF_BASE_URL, default=self.selected_base_url)] = str
        else:
            schema_dict[vol.Required(CONF_BASE_URL)] = str

        schema_dict[vol.Required(CONF_STOP_ID)] = str

        if user_input is not None:
            session = async_get_clientsession(self.hass)
            client = AvailClient(session, user_input[CONF_BASE_URL])
            try:
                # 1. Connection Test
                await client.get_departures(user_input[CONF_STOP_ID])
                
                # 2. Fetch Name
                stop_name = await client.get_stop_info(user_input[CONF_STOP_ID])
                
                unique_id = f"{user_input[CONF_BASE_URL]}_{user_input[CONF_STOP_ID]}"
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                data = user_input.copy()
                data[CONF_STOP_NAME] = stop_name
                
                # Title uses Name now!
                return self.async_create_entry(
                    title=f"{user_input.get(CONF_AGENCY_NAME)} - {stop_name}", 
                    data=data
                )
            except Exception:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="manual", 
            data_schema=vol.Schema(schema_dict), 
            errors=errors
        )