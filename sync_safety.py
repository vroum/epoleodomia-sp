"""Shared validation and errors for geodata download/load boundaries."""


class SyncError(RuntimeError):
    """A source or load failure that must stop this table's sync."""


class FetchError(SyncError):
    """The source did not provide a verifiably complete response."""


class LoadError(SyncError):
    """A table load failed and its data transaction was rolled back."""


def feature_objectid(properties):
    """Read supported ArcGIS identity fields without treating zero as missing."""
    for name in ("OBJECTID", "objectid", "OBJECTID_1", "objectid_1"):
        value = properties.get(name)
        if value is not None:
            return value
    return None


def validate_features(geojson, require_unique_ids=False):
    """Reject malformed data before opening a database connection.

    Full replacement permits repeated OBJECTIDs: building_regs_lot has real
    source rows sharing an ID. Tracking/upsert requires unambiguous identities.
    PostGIS parses geometry and enforces column types inside the transaction;
    this does not replace separate topological validation.
    """
    if not isinstance(geojson, dict) or geojson.get("type") != "FeatureCollection":
        raise SyncError("Expected a GeoJSON FeatureCollection")
    features = geojson.get("features")
    if not isinstance(features, list):
        raise SyncError("FeatureCollection must contain a features list")

    seen = set()
    for index, feature in enumerate(features, 1):
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise SyncError(f"Feature {index}: expected a GeoJSON Feature")
        properties = feature.get("properties")
        if not isinstance(properties, dict):
            raise SyncError(f"Feature {index}: missing/invalid properties")
        if "geometry" not in feature:
            raise SyncError(f"Feature {index}: missing geometry member")
        geometry = feature["geometry"]
        if geometry is not None and (
            not isinstance(geometry, dict)
            or geometry.get("type") not in (
                "Point", "MultiPoint", "LineString", "MultiLineString", "Polygon", "MultiPolygon"
            )
            or not isinstance(geometry.get("coordinates"), list)
        ):
            raise SyncError(f"Feature {index}: unsupported/malformed geometry")
        if require_unique_ids:
            objectid = feature_objectid(properties)
            if isinstance(objectid, bool) or not isinstance(objectid, int):
                raise SyncError(f"Feature {index}: missing/invalid integer OBJECTID")
            if objectid in seen:
                raise SyncError(f"Duplicate OBJECTID {objectid}; tracking requires unique IDs")
            seen.add(objectid)
    return features
