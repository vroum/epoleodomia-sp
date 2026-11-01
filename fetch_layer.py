"""
Fetch layers from ArcGIS REST API
"""

import hashlib
import json
import requests
from typing import Dict, List, Optional, Any
from config import SPETSES_BBOX, MAX_RECORDS_PER_REQUEST, REQUEST_TIMEOUT
from arcgis_client import request_json
from sync_safety import FetchError, SyncError, validate_features


def build_query_url(service_url: str, layer_id: int) -> str:
    """Build the query URL for a specific layer."""
    return f"{service_url}/{layer_id}/query"


def _request_json(url, params):
    """A failed request is never interchangeable with an empty source layer."""
    return request_json(url, params, REQUEST_TIMEOUT)


def fetch_layer_count(service_url: str, layer_id: int, bbox: Dict = None) -> int:
    """
    Get the total count of features in a layer within the bounding box.

    Args:
        service_url: Base URL of the MapServer
        layer_id: ID of the layer to query
        bbox: Bounding box dict (defaults to SPETSES_BBOX)

    Returns:
        Total feature count
    """
    if bbox is None:
        bbox = SPETSES_BBOX

    url = build_query_url(service_url, layer_id)

    params = {
        "where": "1=1",
        "geometry": json.dumps(bbox),
        "geometryType": "esriGeometryEnvelope",
        "inSR": bbox["spatialReference"]["wkid"],
        "spatialRel": "esriSpatialRelIntersects",
        "returnCountOnly": "true",
        "f": "json"
    }

    data = _request_json(url, params)
    count = data.get("count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise FetchError(f"ArcGIS returned a missing/invalid count for {url}")
    return count


def fetch_layer_data(
    service_url: str,
    layer_id: int,
    bbox: Dict = None,
    offset: int = 0,
    max_records: int = None
) -> Dict[str, Any]:
    """
    Fetch GeoJSON data from an ArcGIS REST layer.

    Args:
        service_url: Base URL of the MapServer
        layer_id: ID of the layer to query
        bbox: Bounding box dict (defaults to SPETSES_BBOX)
        offset: Result offset for pagination
        max_records: Maximum records to fetch (defaults to MAX_RECORDS_PER_REQUEST)

    Returns:
        GeoJSON FeatureCollection dict
    """
    if bbox is None:
        bbox = SPETSES_BBOX
    if max_records is None:
        max_records = MAX_RECORDS_PER_REQUEST

    url = build_query_url(service_url, layer_id)

    params = {
        "where": "1=1",
        "geometry": json.dumps(bbox),
        "geometryType": "esriGeometryEnvelope",
        "inSR": bbox["spatialReference"]["wkid"],
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*",
        "returnGeometry": "true",
        "returnDomainValues": "true",
        "outSR": bbox["spatialReference"]["wkid"],
        "resultOffset": offset,
        "resultRecordCount": max_records,
        "f": "geojson"
    }

    try:
        data = _request_json(url, params)
        validate_features(data)
    except SyncError as exc:
        raise FetchError(f"Layer {layer_id}, offset {offset}: {exc}") from exc
    return data


def fetch_all_layer_data(
    service_url: str,
    layer_id: int,
    bbox: Dict = None
) -> Dict[str, Any]:
    """
    Fetch a complete layer into memory before permitting a database load.

    Raises FetchError on failed pages, malformed responses, repeated pages or
    a count mismatch. Short pages are allowed (server-side page caps vary).
    Counts are checked again at the end to detect source changes during paging;
    this cannot provide a transactional snapshot of the remote service.

    Args:
        service_url: Base URL of the MapServer
        layer_id: ID of the layer to query
        bbox: Bounding box dict (defaults to SPETSES_BBOX)

    Returns:
        GeoJSON FeatureCollection with all features
    """
    if bbox is None:
        bbox = SPETSES_BBOX

    total_count = fetch_layer_count(service_url, layer_id, bbox)
    print(f"  Total features in bbox: {total_count}")

    if total_count == 0:
        return {"type": "FeatureCollection", "features": []}

    all_features = []
    seen_pages = set()
    offset = 0

    while offset < total_count:
        print(f"  Fetching records {offset} to {offset + MAX_RECORDS_PER_REQUEST}...")

        data = fetch_layer_data(service_url, layer_id, bbox, offset)
        features = data.get("features", [])

        if not features:
            raise FetchError(
                f"Layer {layer_id}: incomplete download ({offset}/{total_count} records)")

        page_hash = hashlib.sha256(json.dumps(features, sort_keys=True).encode("utf-8")).digest()
        if page_hash in seen_pages:
            raise FetchError(f"Layer {layer_id}: repeated page at offset {offset}")
        seen_pages.add(page_hash)

        all_features.extend(features)
        offset += len(features)

        if offset > total_count:
            raise FetchError(
                f"Layer {layer_id}: downloaded {offset} records, expected {total_count}")

    final_count = fetch_layer_count(service_url, layer_id, bbox)
    if final_count != total_count:
        raise FetchError(
            f"Layer {layer_id}: source count changed during download "
            f"({total_count} -> {final_count}); rerun the sync")

    print(f"  Total features fetched: {len(all_features)}")

    return {
        "type": "FeatureCollection",
        "features": all_features
    }


def get_layer_info(service_url: str, layer_id: int) -> Dict[str, Any]:
    """
    Get metadata about a layer.

    Args:
        service_url: Base URL of the MapServer
        layer_id: ID of the layer

    Returns:
        Layer metadata dict
    """
    url = f"{service_url}/{layer_id}"
    params = {"f": "json"}

    try:
        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()

    except requests.exceptions.RequestException as e:
        print(f"Request error: {e}")
        return {}
    except json.JSONDecodeError as e:
        print(f"JSON decode error: {e}")
        return {}


if __name__ == "__main__":
    from config import SERVICES

    service = SERVICES["UDM_SERVICE_POLEODOMIKI_PLIROFORIA"]
    service_url = service["url"]
    layer_id = 6

    print(f"Testing fetch from {service_url}, layer {layer_id}")
    count = fetch_layer_count(service_url, layer_id)
    print(f"Feature count: {count}")

    if count > 0:
        data = fetch_layer_data(service_url, layer_id)
        print(f"Fetched {len(data.get('features', []))} features")
        if data.get("features"):
            print("\nSample feature:")
            print(json.dumps(data["features"][0], indent=2, ensure_ascii=False))
