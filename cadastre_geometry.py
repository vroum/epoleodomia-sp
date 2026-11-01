"""Shared cadastral geometry and AutoCAD ring-protocol helpers; no I/O."""

from dataclasses import dataclass
import math
import re
from typing import Optional


def non_special_use_filter(alias: str = None) -> str:
    """SQL filter that excludes special-use parcels marked with Latin EK or Greek ΕΚ."""
    col = f"{alias}.kaek" if alias else "kaek"
    return f"{col} NOT ILIKE '%%EK%%' AND {col} NOT ILIKE '%%ΕΚ%%'"


def is_special_kaek(kaek: str) -> bool:
    """EK/ΕΚ special-use parcels (roads, beaches...) — affected but not drawable."""
    k = (kaek or "").upper()
    return "ΕΚ" in k or "EK" in k


def wkt_to_coords(wkt: str) -> list:
    """
    Convert WKT geometry to list of coordinate pairs.
    Handles POLYGON, MULTIPOLYGON, LINESTRING, MULTILINESTRING.
    """
    if not wkt:
        return []

    coords = []
    pattern = r'(-?\d+\.?\d*)\s+(-?\d+\.?\d*)'
    matches = re.findall(pattern, wkt)

    for match in matches:
        coords.append([float(match[0]), float(match[1])])

    return coords


def ring_strings(rows, reject_holes: bool = False) -> Optional[list]:
    """Exterior rings; optional second-column hole counts return None if unsupported."""
    out = []
    for r in (rows or []):
        if reject_holes and r[1]:
            return None
        coords = wkt_to_coords(r[0])
        if coords:
            out.append(";".join(f"{c[0]},{c[1]}" for c in coords))
    return out


PARCEL_RELATION = ("sp_geodata", "kaek_parcels_operating")
EXCLUSIVE_USE_RELATION = ("sp_geodata", "kaek_apokleistikes_operating")


class SurveyInputError(ValueError):
    """Survey input cannot be sent to the geometry calculation."""


@dataclass(frozen=True)
class SurveyRing:
    wkt: str
    tolerance: float


def parse_survey_ring(body: str, tol: float = 0.5) -> SurveyRing:
    """Validate finite coordinates/tolerance and close the ring without any I/O."""
    if not math.isfinite(tol) or tol < 0:
        raise SurveyInputError("Sliver tolerance must be finite and non-negative")
    body = body.strip()
    if not body or ";" not in body:
        raise SurveyInputError("Empty/invalid TOPO_PROP coordinates in request body")

    # Build closed POLYGON WKT from "x,y;x,y;..."
    try:
        pts = []
        for pair in body.split(";"):
            pair = pair.strip()
            if not pair:
                continue
            xs, ys = pair.split(",")
            point = (float(xs), float(ys))
            if not all(math.isfinite(value) for value in point):
                raise SurveyInputError("TOPO_PROP coordinates must be finite")
            pts.append(point)
        if len(set(pts)) < 3:
            raise SurveyInputError("Need at least 3 distinct vertices")
        if pts[0] != pts[-1]:
            pts.append(pts[0])
        topo_wkt = "POLYGON((" + ",".join(f"{p[0]} {p[1]}" for p in pts) + "))"
    except SurveyInputError:
        raise
    except (ValueError, IndexError):
        raise SurveyInputError("Could not parse coordinates (expected x,y;x,y;...)")
    return SurveyRing(topo_wkt, tol)
