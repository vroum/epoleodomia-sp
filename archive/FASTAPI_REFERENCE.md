# TEE Epoleodomia - FastAPI & AutoCAD LISP Reference

## Quick Reference for Building the API

**Database:** `postgresql://docker:<EPOL_DB_PASSWORD from .env>@10.90.144.153:65432/gis`
**Schema:** `epoleodomia`
**CRS:** EPSG:2100 (GGRS87)
**Rasters:** `epoleodomia/rasters/georef/`

---

## Core Tables for API

### 1. building_blocks (556 records)
**Primary table** - Urban building blocks (Οικοδομικά Τετράγωνα)

```sql
-- Key columns
objectid     INTEGER PRIMARY KEY
ot_num       TEXT        -- Block number (e.g., "ΟΤ-123")
fek          TEXT        -- Legal reference (ΦΕΚ)
fek_file_url TEXT        -- URL to PDF
geom         GEOMETRY    -- Polygon, SRID 2100
```

**API Endpoints:**
- `GET /blocks` - List all blocks
- `GET /blocks/{ot_num}` - Get block by number
- `GET /blocks/at?x=420000&y=4122000` - Find block at coordinates
- `GET /blocks/{id}/regulations` - Get regulations for block

---

### 2. v_building_blocks_regulations (VIEW - 553 records)
**Pre-joined view** - Blocks with all regulations

```sql
-- Returns complete building data
SELECT * FROM epoleodomia.v_building_blocks_regulations;

-- Columns:
block_id            INTEGER
ot_num              TEXT
fek                 TEXT
fek_file_url        TEXT
max_height_m        NUMERIC     -- Max building height (meters)
num_orofon          INTEGER     -- Number of floors
coverage_pct        NUMERIC     -- Coverage % (κάλυψη)
building_coefficient NUMERIC    -- FAR/ΣΔ value
min_lot_size_m2     NUMERIC     -- Minimum lot size
min_frontage_m      NUMERIC     -- Minimum frontage
building_system     TEXT        -- Building system type
geom                GEOMETRY    -- Block polygon
```

**API Endpoints:**
- `GET /blocks/{id}/full` - Complete block info with regulations

---

### 3. planning_lines (13,185 records)
Street alignment lines (Ρυμοτομικές γραμμές)

```sql
objectid     INTEGER
fek          TEXT
road_width   NUMERIC     -- Road width (meters)
prasia_width NUMERIC     -- Setback width (meters)
rg_type      TEXT        -- Line type
geom         GEOMETRY    -- LineString, SRID 2100
```

**API Endpoints:**
- `GET /lines/planning?bbox=xmin,ymin,xmax,ymax` - Lines in bbox
- `GET /lines/planning/near?x=...&y=...&radius=100` - Lines near point

---

### 4. building_lines (1,301 records)
Building setback lines (Οικοδομικές γραμμές)

```sql
objectid     INTEGER
fek          TEXT
og_type      TEXT        -- Line type
geom         GEOMETRY    -- LineString, SRID 2100
```

**API Endpoints:**
- `GET /lines/building?bbox=...` - Building lines in bbox

---

### 5. raster_catalog (103 records)
Downloaded planning diagram TIFs

```sql
id                  INTEGER
fek                 TEXT
filename            TEXT        -- e.g., "174839FS000433-2024E.tif"
local_path_georef   TEXT        -- "FEK_433D_2024/174839FS000433-2024E.tif"
url_georef          TEXT        -- Original TEE URL
bbox                GEOMETRY    -- Raster bounding box
width_px            INTEGER
height_px           INTEGER
resolution_x        NUMERIC     -- Meters per pixel
download_status     TEXT        -- downloaded/pending/failed
```

**API Endpoints:**
- `GET /rasters` - List all rasters
- `GET /rasters/at?x=...&y=...` - Find rasters covering point
- `GET /rasters/{id}/file` - Serve TIF file
- `GET /rasters/{id}/metadata` - Raster metadata

---

### 6. planning_diagrams (103 records)
Planning diagram boundaries (polygons with TIF URLs)

```sql
objectid              INTEGER
fek                   TEXT
georef_diagram_url    TEXT        -- URL to georef TIF
initial_diagram_url   TEXT        -- URL to raw scan
ggrs87_diagr_georef_rms NUMERIC   -- Georeferencing accuracy (m)
geom                  GEOMETRY    -- Diagram boundary polygon
```

---

### 7. addresses (54 records)
Street addresses

```sql
objectid     INTEGER
addr         TEXT        -- Street name
num          TEXT        -- House number
munic        TEXT        -- Municipality
geom         GEOMETRY    -- Point, SRID 2100
```

**API Endpoints:**
- `GET /addresses?street=Ποσειδώνος` - Search by street
- `GET /addresses/near?x=...&y=...` - Nearest address

---

## Regulation Tables (Spatial Join Required)

These tables define regulation zones. Join to blocks using `ST_Intersects`:

| Table | Key Columns | Use |
|-------|-------------|-----|
| `building_regs_height` | `max_height_m`, `num_orofon` | Height limits |
| `building_regs_coverage` | `synt_kalypsis` (%) | Coverage ratio |
| `building_regs_coefficient` | `sd_timh` | Building coefficient (ΣΔ) |
| `building_regs_lot` | `elax_embado_m2`, `prosopsi_m` | Lot requirements |
| `building_regs_system` | `oik_systima` | Building system |

**Spatial Join Example:**
```sql
SELECT b.ot_num, h.max_height_m, c.synt_kalypsis, f.sd_timh
FROM building_blocks b
LEFT JOIN building_regs_height h ON ST_Intersects(ST_Centroid(b.geom), h.geom)
LEFT JOIN building_regs_coverage c ON ST_Intersects(ST_Centroid(b.geom), c.geom)
LEFT JOIN building_regs_coefficient f ON ST_Intersects(ST_Centroid(b.geom), f.geom)
WHERE b.ot_num = '123';
```

---

## Useful Functions

### Find block at point
```sql
SELECT * FROM epoleodomia.building_blocks
WHERE ST_Contains(geom, ST_SetSRID(ST_MakePoint(420000, 4122000), 2100));
```

### Find rasters at point
```sql
SELECT * FROM epoleodomia.find_rasters_at_point(420000, 4122000);
```

### Get GeoJSON for block
```sql
SELECT ST_AsGeoJSON(geom) FROM epoleodomia.building_blocks WHERE ot_num = '123';
```

### Get block bounds
```sql
SELECT ST_XMin(geom), ST_YMin(geom), ST_XMax(geom), ST_YMax(geom)
FROM epoleodomia.building_blocks WHERE ot_num = '123';
```

---

## FastAPI Endpoint Suggestions

### Core Endpoints

```python
# Blocks
GET  /api/v1/blocks                         # List blocks (paginated)
GET  /api/v1/blocks/{ot_num}                # Block by number
GET  /api/v1/blocks/at                      # Block at coordinates
GET  /api/v1/blocks/bbox                    # Blocks in bounding box
GET  /api/v1/blocks/{id}/regulations        # Full regulations
GET  /api/v1/blocks/{id}/geojson           # Block as GeoJSON

# Lines
GET  /api/v1/lines/planning                 # Planning lines
GET  /api/v1/lines/building                 # Building lines
GET  /api/v1/lines/bbox                     # All lines in bbox

# Rasters
GET  /api/v1/rasters                        # List rasters
GET  /api/v1/rasters/at                     # Rasters at point
GET  /api/v1/rasters/{id}                   # Raster metadata
GET  /api/v1/rasters/{id}/file              # Serve TIF file
GET  /api/v1/rasters/{id}/thumbnail         # Generate thumbnail

# FEK (Legal References)
GET  /api/v1/fek                            # List all FEKs
GET  /api/v1/fek/{fek}                      # FEK details + related data

# Search
GET  /api/v1/search?q=...                   # Full-text search
GET  /api/v1/search/address?q=...          # Address search
```

### AutoCAD LISP Integration

For LISP, provide simple endpoints that return:
- WKT geometry strings
- Coordinate lists
- Entity data as JSON

```python
# LISP-friendly endpoints
GET  /api/v1/lisp/block/{ot_num}/wkt       # Block as WKT
GET  /api/v1/lisp/block/{ot_num}/coords    # Vertex coordinates
GET  /api/v1/lisp/lines/bbox?...           # Lines as coordinate pairs
GET  /api/v1/lisp/raster/{id}/path         # Local TIF file path
```

---

## Raster File Serving

### Local Path Structure
```
epoleodomia/rasters/georef/
├── FEK_433D_2024/174839FS000433-2024E.tif
├── FEK_1D_1981/021962FS000001-1981E.tif
└── ...
```

### Serving via FastAPI
```python
from fastapi import FastAPI
from fastapi.responses import FileResponse

@app.get("/rasters/{raster_id}/file")
async def get_raster_file(raster_id: int):
    # Query raster_catalog for local_path_georef
    # Return FileResponse with TIF
    return FileResponse(
        path=f"rasters/georef/{local_path}",
        media_type="image/tiff",
        filename=filename
    )
```

---

## Connection String

```python
# SQLAlchemy
DATABASE_URL = "postgresql://docker:<EPOL_DB_PASSWORD from .env>@10.90.144.153:65432/gis"

# psycopg2
conn = psycopg2.connect(
    host="10.90.144.153",
    port=65432,
    database="gis",
    user="docker",
    password="<EPOL_DB_PASSWORD from .env>"
)

# Always use schema prefix
cursor.execute("SELECT * FROM epoleodomia.building_blocks")
```

---

## GeoJSON Output

```python
# Full feature collection
@app.get("/blocks/geojson")
async def blocks_geojson():
    query = """
    SELECT jsonb_build_object(
        'type', 'FeatureCollection',
        'features', COALESCE(jsonb_agg(
            jsonb_build_object(
                'type', 'Feature',
                'id', objectid,
                'properties', jsonb_build_object(
                    'ot_num', ot_num,
                    'fek', fek
                ),
                'geometry', ST_AsGeoJSON(geom)::jsonb
            )
        ), '[]'::jsonb)
    )
    FROM epoleodomia.building_blocks
    """
    return execute_query(query)
```

---

## Key Notes

1. **All geometries are EPSG:2100** (GGRS87 Greek coordinate system)
2. **Use the view `v_building_blocks_regulations`** for complete block data
3. **Rasters are already downloaded** to `rasters/georef/` - just serve them
4. **FEK** = Government Gazette reference - links regulations to legal documents
5. **Soft deletes**: Check `is_deleted = false` for current records
6. **Spatial queries**: Use `ST_Intersects`, `ST_Contains`, `ST_DWithin`

---

*Reference for FastAPI + AutoCAD LISP project*
*Data source: TEE Epoleodomia mirror*
*Last updated: 2026-02-03*
