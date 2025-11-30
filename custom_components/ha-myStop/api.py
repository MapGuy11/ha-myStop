"""API Client for Avail MyStop.
"""

from __future__ import annotations

import logging
import json
import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Tuple

import aiohttp
import asyncio
from yarl import URL

_LOGGER = logging.getLogger(__name__)


def _clean_base_url(base_url: str | None) -> str | None:
	if not base_url:
		return None
	try:
		url = URL(base_url.rstrip("/"))
	except Exception:
		raise ValueError("Invalid base_url")

	if url.scheme not in {"http", "https"}:
		raise ValueError("base_url must use http or https")
	if url.user is not None:
		raise ValueError("base_url must not contain user info")
	if url.fragment:
		raise ValueError("base_url must not contain fragment")
	return str(url)


def _validate_numeric_id(value: Any, field: str) -> str:
	if isinstance(value, int):
		return str(value)
	if isinstance(value, str) and value.isdigit():
		return value
	raise ValueError(f"{field} must be a numeric id")


class AvailClient:
	"""Client to interact with Avail MyStop API."""

	def __init__(
		self,
		session: aiohttp.ClientSession,
		base_url: str | None = None,
		timeout: aiohttp.ClientTimeout | None = None,
	) -> None:
		self._session = session
		self.base_url = _clean_base_url(base_url)
		self._timeout = timeout or aiohttp.ClientTimeout(total=30, connect=10, sock_read=20, sock_connect=10)

	async def _get_text(self, url: str) -> str:
		tries = 3
		delay = 0.5
		for attempt in range(1, tries + 1):
			try:
				async with self._session.get(url, timeout=self._timeout) as response:
					response.raise_for_status()
					return await response.text()
			except (aiohttp.ClientError, asyncio.TimeoutError) as err:
				if attempt == tries:
					raise
				_LOGGER.debug("GET %s failed (%s), retrying in %.1fs", url, err, delay)
				await asyncio.sleep(delay)
				delay *= 2

	async def _get_json(self, url: str) -> Any:
		text = await self._get_text(url)
		try:
			return json.loads(text)
		except json.JSONDecodeError:
			raise ValueError("Response was not valid JSON")

	async def get_agencies(self, discovery_url: str) -> Dict[str, str]:
		try:
			data = await self._get_json(discovery_url)

			agencies: Dict[str, str] = {}
			if isinstance(data, list):
				for authority in data:
					name = authority.get("Name")
					url = authority.get("RestUrl")
					if not (name and url):
						continue
					clean_url = str(URL(url.rstrip("/")).with_fragment(None))
					if clean_url.endswith("/rest"):
						clean_url = clean_url[:-5]
					agencies[name] = _clean_base_url(clean_url) or ""
				return agencies
		except Exception as err:
			_LOGGER.error("Error fetching agencies: %s", err)
			return {}

	async def get_routes(self) -> Tuple[Dict[str, str], Dict[str, Dict[str, str]]]:
		if not self.base_url:
			raise ValueError("base_url is required")
		url = f"{self.base_url}/rest/RouteDetails/GetAllRouteDetails"
		try:
			data = await self._get_json(url)
			return self._parse_routes_json(data)
		except Exception as err:
			_LOGGER.error("Error fetching routes from %s: %s", url, err)
			raise

	async def get_departures(self, stop_id: Any) -> List[Dict[str, Any]]:
		if not self.base_url:
			raise ValueError("base_url is required")
		s_id = _validate_numeric_id(stop_id, "stop_id")
		url = f"{self.base_url}/rest/StopDepartures/Get/{s_id}"
		try:
			text = await self._get_text(url)

			try:
				data = json.loads(text)
				return self._parse_departures_json(data)
			except json.JSONDecodeError:
				pass

			xml_text = re.sub(r' xmlns="[^\"]+"', "", text, count=1)
			xml_text = re.sub(r' xmlns:i="[^\"]+"', '', xml_text, count=1)
			try:
				root = ET.fromstring(xml_text)
				return self._parse_departures_xml(root)
			except ET.ParseError:
				_LOGGER.error("Failed to parse departures response")
				return []
		except Exception as err:
			_LOGGER.error("Error fetching departures: %s", err)
			return []

	async def get_stop_info(self, stop_id: Any) -> str:
		if not self.base_url:
			raise ValueError("base_url is required")
		s_id = _validate_numeric_id(stop_id, "stop_id")
		url = f"{self.base_url}/rest/Stops/Get/{s_id}"
		try:
			data = await self._get_json(url)
			name = data.get("Name")
			return name if isinstance(name, str) and name else str(s_id)
		except Exception:
			return str(s_id)

	async def get_alerts(self) -> List[Dict[str, Any]]:
		if not self.base_url:
			raise ValueError("base_url is required")
		url = f"{self.base_url}/rest/PublicMessages/GetCurrentMessages"
		try:
			data = await self._get_json(url)
			return self._parse_alerts_json(data)
		except Exception as err:
			_LOGGER.error("Error fetching alerts: %s", err)
			return []

	async def get_route_details(self, route_id: Any) -> List[Dict[str, Any]]:
		if not self.base_url:
			raise ValueError("base_url is required")
		r_id = _validate_numeric_id(route_id, "route_id")
		url = f"{self.base_url}/rest/RouteDetails/Get/{r_id}"
		try:
			data = await self._get_json(url)
			if isinstance(data, list) and data:
				return self._parse_alerts_json(data[0].get("Messages", []))
			if isinstance(data, dict):
				return self._parse_alerts_json(data.get("Messages", []))
			return []
		except Exception as err:
			_LOGGER.error("Error fetching route details: %s", err)
			return []

	def _parse_routes_json(
		self, data: Any
	) -> Tuple[Dict[str, str], Dict[str, Dict[str, str]]]:
		routes: Dict[str, str] = {}
		stops_map: Dict[str, Dict[str, str]] = {}
		route_list = data if isinstance(data, list) else []

		for route in route_list:
			if not route.get("IsVisible", True):
				continue

			r_id = str(route.get("RouteId"))
			abbr = route.get("RouteAbbreviation", "") or route.get("ShortName", "")
			long_name = route.get("LongName", "")
			label = f"{abbr} - {long_name}".strip(" -")

			if r_id:
				routes[label] = r_id
				stops_map[r_id] = {}
				for stop in route.get("Stops", []):
					s_id = str(stop.get("StopId"))
					s_name = stop.get("Name")
					if s_id and s_name:
						stops_map[r_id][f"{s_name} ({s_id})"] = s_id
		return routes, stops_map

	def _parse_departures_json(self, data: Any) -> List[Dict[str, Any]]:
		flat_departures: List[Dict[str, Any]] = []
		stop_departures = data if isinstance(data, list) else [data]

		for entry in stop_departures:
			for route_dir in entry.get("RouteDirections", []):
				if route_dir.get("IsDone") or not route_dir.get("Departures"):
					continue

				direction_code = route_dir.get("DirectionCode")
				route_id = str(route_dir.get("RouteId"))

				for dep in route_dir.get("Departures", []):
					trip = dep.get("Trip", {})
					eta = dep.get("ETALocalTime") or dep.get("STALocalTime")

					flat_departures.append(
						{
							"route_id": route_id,
							"direction": direction_code,
							"destination": trip.get("InternetServiceDesc")
							or trip.get("InternalSignDesc")
							or "Unknown",
							"eta": eta,
							"status": dep.get("StopStatusReportLabel"),
							"is_realtime": dep.get("Mode") != 0,
						}
					)
		return flat_departures

	def _parse_departures_xml(self, root: ET.Element) -> List[Dict[str, Any]]:
		flat_departures: List[Dict[str, Any]] = []

		entries = root.findall("StopDeparture") if root.tag == "ArrayOfStopDeparture" else [root]

		for entry in entries:
			route_directions = entry.find("RouteDirections")
			if route_directions is None:
				continue

			for route_dir in route_directions.findall("RouteDirection"):
				is_done = route_dir.findtext("IsDone")
				if is_done and is_done.lower() == "true":
					continue

				departures_node = route_dir.find("Departures")
				if departures_node is None or not list(departures_node):
					continue

				direction_code = route_dir.findtext("DirectionCode")
				route_id = route_dir.findtext("RouteId")

				for dep in departures_node.findall("Departure"):
					trip = dep.find("Trip")
					eta = dep.findtext("ETALocalTime") or dep.findtext("STALocalTime")
					status = dep.findtext("StopStatusReportLabel")
					mode = dep.findtext("Mode")

					dest = "Unknown"
					if trip is not None:
						dest = (
							trip.findtext("InternetServiceDesc")
							or trip.findtext("InternalSignDesc")
							or "Unknown"
						)

					flat_departures.append(
						{
							"route_id": str(route_id),
							"direction": direction_code,
							"destination": dest,
							"eta": eta,
							"status": status,
							"is_realtime": mode != "0",
						}
					)
		return flat_departures

	def _parse_alerts_json(self, data: Any) -> List[Dict[str, Any]]:
		alerts: List[Dict[str, Any]] = []
		if isinstance(data, list):
			for msg in data:
				alerts.append(
					{
						"id": msg.get("MessageId"),
						"header": msg.get("Header"),
						"message": msg.get("Message"),
						"priority": msg.get("Priority"),
					}
				)
		return alerts

__all__ = ["AvailClient"]