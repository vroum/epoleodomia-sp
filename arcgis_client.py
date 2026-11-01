"""HTTP response validation and identity checks for ArcGIS source adapters."""

import re
import requests

from sync_safety import FetchError


def request_json(url, params, timeout, source="ArcGIS", method="GET"):
    """Raise on transport, JSON or service errors; never invent an empty result."""
    if method not in {"GET", "POST"}:
        raise ValueError(f"Unsupported ArcGIS request method: {method}")
    try:
        if method == "GET":
            response = requests.get(url, params=params, timeout=timeout)
        elif method == "POST":
            # Object-ID batches can exceed proxy/server URL length limits.
            response = requests.post(url, data=params, timeout=timeout)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as exc:
        raise FetchError(f"{source} request failed for {url}: {exc}") from exc
    except ValueError as exc:
        raise FetchError(f"{source} returned invalid JSON for {url}") from exc
    if not isinstance(data, dict):
        raise FetchError(f"{source} returned a non-object response for {url}")
    if "error" in data:
        raise FetchError(f"{source} error for {url}: {data['error']}")
    return data


def fetch_count(url, params, timeout, source="ArcGIS"):
    data = request_json(url, dict(params, f="json", returnCountOnly="true"), timeout, source)
    count = data.get("count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise FetchError(f"{source}: missing/invalid source count")
    return count


def fetch_object_ids(url, params, timeout, source="ArcGIS"):
    data = request_json(url, dict(params, f="json", returnIdsOnly="true"), timeout, source)
    name, ids = data.get("objectIdFieldName"), data.get("objectIds")
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise FetchError(f"{source}: missing/invalid object-ID field name")
    if not isinstance(ids, list) or any(isinstance(i, bool) or not isinstance(i, int) for i in ids):
        raise FetchError(f"{source}: missing/invalid object-ID list")
    if len(set(ids)) != len(ids):
        raise FetchError(f"{source}: duplicate source object IDs")
    return name, set(ids)
