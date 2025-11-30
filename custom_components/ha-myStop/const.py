"""Constants for the Avail MyStop integration."""

DOMAIN = "ha_mystop"

# Configuration Keys
CONF_STOP_ID = "stop_id"
CONF_STOP_NAME = "stop_name"
CONF_ROUTE_ID = "route_id"
CONF_ROUTE_NAME = "route_name"
CONF_BASE_URL = "base_url"
CONF_AGENCY_NAME = "agency_name"

# Defaults
DEFAULT_NAME = "myStop"

# The central API to discover all available transit agencies
DISCOVERY_URL = "https://mobilegateway.rideralerts.com/gateway/TransitAuthorities"