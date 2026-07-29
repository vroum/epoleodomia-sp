# Epoleodomia API — Specification
## Version 0.1 — February 2026

---

## Philosophy

One coordinate → one complete answer.

A surveyor standing on a plot in Spetses with EGSA87 coordinates should get back
everything they need in **one API call**: building regulations, land use, forest
classification, archaeological constraints, shoreline proximity, and any known
data gaps. Thin per-resource endpoints exist for specific lookups but the
**primary endpoint** is the point query.

---

## Stack

- **FastAPI** (Python 3.11) on Synology DS224+ via Docker
- **PostGIS** backend (existing `epoleodomia` schema)
- **Authentication**: API key header (simple, for you + trusted collaborators)
- **Response format**: JSON (GeoJSON geometry where applicable)
- **Credentials**: Loaded from `.env` (same as sync scripts)

---

## Endpoints

### 1. `GET /api/v1/query` — The Primary Endpoint

Point-in-polygon against everything.

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `x` | float | yes | — | X coordinate |
| `y` | float | yes | — | Y coordinate |
| `srid` | int | no | 2100 | Input SRID (2100=EGSA87, 4326=WGS84) |
| `radius` | int | no | 50 | Proximity search radius in meters |
| `include` | string | no | `all` | Comma-separated: `regulations,forest,archaeological,shoreline,admin` |

### 2. `GET /api/v1/block/{ot_num}` — Block Lookup
### 3. `GET /api/v1/forest?x=...&y=...` — Forest Classification
### 4. `GET /api/v1/fek/{fek_id}` — FEK Lookup
### 5. `GET /api/v1/diagrams?x=...&y=...` — Planning Diagrams
### 6. `GET /api/v1/address/{query}` — Address Search
### 7. `GET /api/v1/health` — System Status

---

## Data Sources per Section

| Response Section | Primary Table/View | Fallback |
|------------------|--------------------|----------|
| `location` | municipalities_2021, settlements_2021, approved_plan_boundaries | — |
| `block` | building_blocks | — |
| `regulations` | **v_building_blocks_regulations** | building_regs_coefficient_zones |
| `forest` | forest_maps + posted_attica + posted_pelop | — |
| `archaeological` | **sp_geodata.Αρχαιλογία_Κυρηγμένα_Μνημεία** (62 curated monuments), **sp_geodata.Αρχαιολογία_Ζώνες_Προστασίας** (5 zones incl. whole-island 1967), natural_landscapes_polygons | epoleodomia.monuments_points |
| `shoreline` | sp_geodata.Αιγιαλός_Παραλία (79 features, full FEK) | epoleodomia.shorelines (7 only) |
| `overlays` | public_spaces, pedestrian_zones, protected_buildings | — |
| `data_gaps` | fek_no_diagrams | — |
| `fek_history` | approved_plan_boundaries, planning_diagrams | — |

---

## SQL Strategy

One SQL function → JSONB. All spatial ops server-side, single round-trip.

```sql
CREATE OR REPLACE FUNCTION epoleodomia.query_point(
    p_x DOUBLE PRECISION, p_y DOUBLE PRECISION,
    p_srid INTEGER DEFAULT 2100, p_radius INTEGER DEFAULT 50
) RETURNS JSONB ...
```

FastAPI just does: `SELECT epoleodomia.query_point(%s, %s, %s, %s)`

---

## Implementation Order

1. SQL function `query_point()` — test in pgAdmin
2. FastAPI skeleton with `/query` and `/health`
3. `/block/{ot_num}` endpoint
4. `/fek/{id}` endpoint
5. AutoLISP integration helper
6. Docker compose for NAS deployment

---

*See the full v1.0 API_SPEC.md for complete response examples and AutoLISP integration code.*
