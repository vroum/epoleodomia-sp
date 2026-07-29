#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ingest_rasters.py - register locally georeferenced map sheets into PostGIS.

For rasters you georeferenced yourself (GYS 1:5000 sheets, aigialos diagrams,
historic plans) as opposed to the FEK diagrams, which download_rasters.py
fetches from the TEE service.

    validate -> extract -> footprint -> [optimise] -> register

DRY RUN IS THE DEFAULT. Nothing is written to the database or to disk unless
you pass --commit.

Typical use
-----------
    # look first
    python ingest_rasters.py --collection gys5000 --scale 5000

    # then write
    python ingest_rasters.py --collection gys5000 --scale 5000 --commit

    # a historic plan: never traceable, record how it was georeferenced
    python ingest_rasters.py --collection historic --role historical \\
        --georef-method tps --georef-points 12 --georef-rms 8.5 \\
        --doc-ref "Sxedio Spetson 1867" --commit

    # tile + build overviews as well (writes new files, originals untouched)
    python ingest_rasters.py --collection gys5000 --optimize --commit

Re-running is safe: a file whose hash is unchanged is skipped, a changed file
is updated in place, and files that vanished are reported but never deleted.

Requires: rasterio, psycopg2-binary, python-dotenv
"""

import argparse
import hashlib
import os
import sys
from datetime import datetime, timezone

# --------------------------------------------------------------------------
# rasterio is mandatory here.
#
# download_rasters.py does `except ImportError: pass` around its rasterio
# import, so on a machine without rasterio it silently writes NULL metadata
# and reports success. rasterio is also still commented out in
# requirements.txt. We fail loudly instead.
# --------------------------------------------------------------------------
# Imports are checked in main() rather than at module load, so that --help
# still works on a machine that is missing them.
MISSING = []

try:
    import rasterio
    from rasterio.features import shapes as rio_shapes
    from rasterio.enums import Resampling
except ImportError:
    MISSING.append(
        "rasterio     pip install rasterio\n"
        "                 (also uncomment it in requirements.txt - "
        "download_rasters.py\n"
        "                  silently writes empty metadata without it)")

try:
    import psycopg2
except ImportError:
    MISSING.append("psycopg2     pip install psycopg2-binary")

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


TARGET_EPSG = 2100          # EGSA '87 - everything in this project lives here
RASTER_EXTS = {".tif", ".tiff", ".gtif"}
TABLE = "sp_geodata.raster_sheets"


# ==========================================================================
# Database
# ==========================================================================

def db_connect():
    try:
        return psycopg2.connect(
            host=os.environ.get("EPOL_DB_HOST", "localhost"),
            port=os.environ.get("EPOL_DB_PORT", "5432"),
            dbname=os.environ.get("EPOL_DB_NAME", "gis"),
            user=os.environ["EPOL_DB_USER"],
            password=os.environ["EPOL_DB_PASSWORD"],
        )
    except KeyError as e:
        sys.exit(f"FATAL: missing env var {e}. Copy .env.example to .env.")
    except psycopg2.Error as e:
        sys.exit(f"FATAL: cannot connect to the database: {e}")


# ==========================================================================
# File identity
# ==========================================================================

def quick_hash(path, size):
    """Cheap change detector: size + first and last 1 MB.

    Hashing a full 20 MB GeoTIFF for every run is wasteful, and a georeferenced
    TIFF that changes at all changes its header (the geotransform lives near the
    front) or its data. Size plus both ends is enough to notice.
    """
    h = hashlib.sha256()
    h.update(str(size).encode())
    chunk = 1024 * 1024
    with open(path, "rb") as fh:
        h.update(fh.read(chunk))
        if size > 2 * chunk:
            fh.seek(-chunk, os.SEEK_END)
            h.update(fh.read(chunk))
    return h.hexdigest()


# ==========================================================================
# Raster inspection
# ==========================================================================

def envelope_wkt(b):
    return (f"POLYGON(({b.left} {b.bottom}, {b.right} {b.bottom}, "
            f"{b.right} {b.top}, {b.left} {b.top}, {b.left} {b.bottom}))")


def data_footprint_wkt(src, simplify_px=2.0, max_vertices=500):
    """Outline of the valid (non-nodata, non-transparent) pixels.

    A scanned sheet that was warped into EGSA '87 has black or transparent
    triangles in the corners. The file envelope covers them; this does not.
    Returns None when the whole raster is valid - the caller then just uses the
    envelope, which is the correct answer in that case.
    """
    try:
        mask = src.dataset_mask()
    except Exception:
        return None

    if mask is None or mask.size == 0:
        return None
    if not (mask == 0).any():
        return None                     # fully valid, envelope is exact

    try:
        from shapely.geometry import shape as shp_shape
        from shapely.ops import unary_union
    except ImportError:
        return None                     # shapely optional; fall back to envelope

    polys = [
        shp_shape(geom)
        for geom, val in rio_shapes(mask, mask=(mask > 0), transform=src.transform)
        if val > 0
    ]
    if not polys:
        return None

    geom = unary_union(polys)
    if geom.is_empty:
        return None

    # keep only the biggest piece; scanner speckle in the margins is not data
    if geom.geom_type == "MultiPolygon":
        geom = max(geom.geoms, key=lambda g: g.area)

    tol = simplify_px * abs(src.transform[0])
    for _ in range(8):
        simple = geom.simplify(tol, preserve_topology=True)
        if len(simple.exterior.coords) <= max_vertices:
            geom = simple
            break
        tol *= 2
    else:
        geom = geom.simplify(tol, preserve_topology=True)

    # drop interior rings: holes inside a map sheet are scan artefacts
    from shapely.geometry import Polygon as ShpPolygon
    geom = ShpPolygon(geom.exterior)
    return geom.wkt


def inspect(path):
    """Read everything we need from one file. Returns (info, problems)."""
    info, problems = {}, []

    with rasterio.open(path) as src:
        epsg = None
        if src.crs:
            try:
                epsg = src.crs.to_epsg()
            except Exception:
                epsg = None

        if epsg is None:
            problems.append(
                f"no readable EPSG (crs={src.crs!r}). Georeference it first, or "
                f"assign the CRS explicitly - this script will not guess.")
        elif epsg != TARGET_EPSG:
            problems.append(
                f"CRS is EPSG:{epsg}, expected EPSG:{TARGET_EPSG} (EGSA '87). "
                f"Reproject with gdalwarp before ingesting - a wrong datum "
                f"looks plausible and is off by tens of metres.")

        if src.transform.is_identity:
            problems.append("identity geotransform - the file is not georeferenced")

        rot = (src.transform[1], src.transform[3])
        if any(abs(v) > 1e-9 for v in rot):
            problems.append(
                f"rotated geotransform {rot} - AutoCAD ignores rotation on "
                f"attached images, so this would be placed wrongly. "
                f"gdalwarp it to a north-up grid first.")

        info.update(
            width_px=src.width,
            height_px=src.height,
            bands=src.count,
            dtype=str(src.dtypes[0]) if src.dtypes else None,
            res_x=abs(src.transform[0]),
            res_y=abs(src.transform[4]),
            crs_epsg=epsg,
            nodata=src.nodata,
            compression=(src.compression.value if src.compression else None),
            is_tiled=bool(src.profile.get("tiled", False)),
            overview_count=len(src.overviews(1)) if src.count else 0,
            extent_wkt=envelope_wkt(src.bounds),
        )
        info["has_overviews"] = info["overview_count"] > 0
        info["footprint_wkt"] = data_footprint_wkt(src)

    return info, problems


# ==========================================================================
# Optimisation
# ==========================================================================

def optimize(src_path, dst_path, compress="lzw", quality=90):
    """Rewrite tiled with overviews. Originals are never modified.

    Compression note: LZW with PREDICTOR=2 is the default deliberately. JPEG is
    far smaller but it rings around black line work and text, which is exactly
    what a scanned map sheet is made of. Use --compress jpeg only on
    photographic sheets.
    """
    os.makedirs(os.path.dirname(dst_path), exist_ok=True)

    with rasterio.open(src_path) as src:
        profile = src.profile.copy()
        profile.update(driver="GTiff", tiled=True,
                       blockxsize=512, blockysize=512, BIGTIFF="IF_SAFER")

        if compress == "jpeg":
            profile.update(compress="jpeg", jpeg_quality=quality)
            if src.count == 3:
                profile["photometric"] = "YCBCR"
        elif compress == "deflate":
            profile.update(compress="deflate", zlevel=9)
            if src.dtypes and src.dtypes[0] in ("uint8", "int8"):
                profile["predictor"] = 2
        else:
            profile.update(compress="lzw")
            if src.dtypes and src.dtypes[0] in ("uint8", "int8"):
                profile["predictor"] = 2

        with rasterio.open(dst_path, "w", **profile) as dst:
            for band in range(1, src.count + 1):
                dst.write(src.read(band), band)

    # overviews in a second pass so the pyramid is built from the written file
    with rasterio.open(dst_path, "r+") as dst:
        longest = max(dst.width, dst.height)
        factors, f = [], 2
        while longest / f > 256 and f <= 64:
            factors.append(f)
            f *= 2
        if factors:
            dst.build_overviews(factors, Resampling.average)
            dst.update_tags(ns="rio_overview", resampling="average")

    return os.path.getsize(dst_path)


# ==========================================================================
# Upsert
# ==========================================================================

UPSERT = f"""
INSERT INTO {TABLE} (
    collection, filename, rel_path, abs_path,
    file_size_bytes, file_mtime, file_hash,
    extent, footprint,
    width_px, height_px, bands, dtype, res_x, res_y,
    crs_epsg, nodata, compression, is_tiled, has_overviews, overview_count,
    role, nominal_scale, georef_rms, georef_method, georef_points,
    georef_by, georef_date, doc_ref, doc_date, notes
) VALUES (
    %(collection)s, %(filename)s, %(rel_path)s, %(abs_path)s,
    %(file_size_bytes)s, %(file_mtime)s, %(file_hash)s,
    ST_GeomFromText(%(extent_wkt)s, {TARGET_EPSG}),
    CASE WHEN %(footprint_wkt)s IS NULL THEN NULL
         ELSE ST_GeomFromText(%(footprint_wkt)s, {TARGET_EPSG}) END,
    %(width_px)s, %(height_px)s, %(bands)s, %(dtype)s, %(res_x)s, %(res_y)s,
    %(crs_epsg)s, %(nodata)s, %(compression)s, %(is_tiled)s,
    %(has_overviews)s, %(overview_count)s,
    %(role)s, %(nominal_scale)s, %(georef_rms)s, %(georef_method)s,
    %(georef_points)s, %(georef_by)s, %(georef_date)s,
    %(doc_ref)s, %(doc_date)s, %(notes)s
)
ON CONFLICT (collection, rel_path) DO UPDATE SET
    filename        = EXCLUDED.filename,
    abs_path        = EXCLUDED.abs_path,
    file_size_bytes = EXCLUDED.file_size_bytes,
    file_mtime      = EXCLUDED.file_mtime,
    file_hash       = EXCLUDED.file_hash,
    extent          = EXCLUDED.extent,
    footprint       = EXCLUDED.footprint,
    width_px        = EXCLUDED.width_px,
    height_px       = EXCLUDED.height_px,
    bands           = EXCLUDED.bands,
    dtype           = EXCLUDED.dtype,
    res_x           = EXCLUDED.res_x,
    res_y           = EXCLUDED.res_y,
    crs_epsg        = EXCLUDED.crs_epsg,
    nodata          = EXCLUDED.nodata,
    compression     = EXCLUDED.compression,
    is_tiled        = EXCLUDED.is_tiled,
    has_overviews   = EXCLUDED.has_overviews,
    overview_count  = EXCLUDED.overview_count
-- deliberately NOT overwritten on re-ingest: role, nominal_scale, georef_*,
-- doc_*, notes, useful_area. Those are human judgements; a rescan of the file
-- must not silently discard them.
"""


# ==========================================================================
# Main
# ==========================================================================

def human(n):
    if n is None:
        return "-"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def main():
    ap = argparse.ArgumentParser(
        description="Register locally georeferenced map sheets into PostGIS.",
        formatter_class=argparse.RawDescriptionHelpFormatter)

    ap.add_argument("--collection", required=True,
                    help="collection tag, e.g. gys5000 | aigialos | historic")
    ap.add_argument("--root",
                    help="folder to scan (default: $EPOL_SHEET_ROOT/<collection>)")
    ap.add_argument("--commit", action="store_true",
                    help="actually write. Without this it is a dry run.")

    ap.add_argument("--role", default="working",
                    choices=["working", "context", "historical", "excluded"],
                    help="working = traceable (default); historical = evidence "
                         "document, never measured on")
    ap.add_argument("--scale", type=int, dest="nominal_scale",
                    help="nominal scale denominator, e.g. 5000")
    ap.add_argument("--doc-ref", help="FEK, sheet name or archive reference")
    ap.add_argument("--doc-date", help="date of the document, YYYY-MM-DD")
    ap.add_argument("--notes")

    ap.add_argument("--georef-method",
                    help="affine | poly2 | tps | native - how it was warped")
    ap.add_argument("--georef-points", type=int, help="control points used")
    ap.add_argument("--georef-rms", type=float, help="reported RMS in metres")
    ap.add_argument("--georef-by")
    ap.add_argument("--georef-date", help="YYYY-MM-DD")

    ap.add_argument("--optimize", action="store_true",
                    help="write a tiled copy with overviews into <root>/_optimized")
    ap.add_argument("--compress", default="lzw", choices=["lzw", "deflate", "jpeg"],
                    help="lzw (default, lossless, safe for line work) | deflate | "
                         "jpeg (smaller but rings around text)")
    ap.add_argument("--quality", type=int, default=90, help="JPEG quality")
    ap.add_argument("--force", action="store_true",
                    help="re-read and re-register even if the hash is unchanged")

    args = ap.parse_args()

    if MISSING:
        sys.exit("FATAL: missing required package(s):\n    "
                 + "\n    ".join(MISSING))

    root = args.root or os.path.join(
        os.environ.get("EPOL_SHEET_ROOT", "rasters"), args.collection)
    root = os.path.abspath(root)

    if not os.path.isdir(root):
        sys.exit(f"FATAL: not a folder: {root}\n"
                 f"       create it, or pass --root / set EPOL_SHEET_ROOT")

    # ---- gather -----------------------------------------------------------
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith("_")]
        for fn in sorted(filenames):
            if os.path.splitext(fn)[1].lower() in RASTER_EXTS:
                files.append(os.path.join(dirpath, fn))

    mode = "COMMIT" if args.commit else "DRY RUN"
    print(f"\n{'='*78}")
    print(f" ingest_rasters.py   collection={args.collection}   [{mode}]")
    print(f" root: {root}")
    print(f" found {len(files)} raster file(s)")
    print(f"{'='*78}\n")

    if not files:
        print("Nothing to do.")
        return 0

    conn = db_connect()
    cur = conn.cursor()

    cur.execute(f"SELECT rel_path, file_hash FROM {TABLE} WHERE collection = %s",
                (args.collection,))
    known = dict(cur.fetchall())

    stats = dict(new=0, updated=0, skipped=0, failed=0, optimized=0)
    problems_seen = []

    for path in files:
        rel = os.path.relpath(path, root).replace("\\", "/")
        name = os.path.basename(path)
        st = os.stat(path)
        fhash = quick_hash(path, st.st_size)

        if rel in known and known[rel] == fhash and not args.force:
            stats["skipped"] += 1
            print(f"  skip     {rel}")
            continue

        try:
            info, problems = inspect(path)
        except Exception as e:
            stats["failed"] += 1
            print(f"  FAIL     {rel}\n           cannot read: {e}")
            continue

        if problems:
            stats["failed"] += 1
            problems_seen.append((rel, problems))
            print(f"  REJECT   {rel}")
            for p in problems:
                print(f"           - {p}")
            continue

        verb = "update" if rel in known else "new"

        flags = ["footprint" if info["footprint_wkt"] else "envelope"]
        if info["is_tiled"]:
            flags.append("tiled")
        if info["has_overviews"]:
            flags.append(f"ovr={info['overview_count']}")
        if info["compression"]:
            flags.append(str(info["compression"]).lower())

        print(f"  {verb:8s} {rel}")
        print(f"           {info['width_px']}x{info['height_px']}px  "
              f"{info['res_x']:.4f} m/px  {info['bands']}band {info['dtype']}  "
              f"{human(st.st_size)}  EPSG:{info['crs_epsg']}  "
              f"[{' '.join(flags)}]")

        abs_path = path
        if args.optimize:
            dst = os.path.join(root, "_optimized", rel)
            if args.commit:
                try:
                    newsize = optimize(path, dst, args.compress, args.quality)
                    stats["optimized"] += 1
                    print(f"           optimised -> {human(newsize)} "
                          f"({human(st.st_size)} original, "
                          f"{args.compress}, tiled, overviews)")
                    abs_path = dst
                except Exception as e:
                    print(f"           optimise FAILED, keeping original: {e}")
            else:
                print(f"           would optimise -> {dst}")
                abs_path = dst

        row = dict(
            collection=args.collection,
            filename=name,
            rel_path=rel,
            abs_path=abs_path,
            file_size_bytes=st.st_size,
            file_mtime=datetime.fromtimestamp(st.st_mtime, tz=timezone.utc),
            file_hash=fhash,
            role=args.role,
            nominal_scale=args.nominal_scale,
            georef_rms=args.georef_rms,
            georef_method=args.georef_method,
            georef_points=args.georef_points,
            georef_by=args.georef_by,
            georef_date=args.georef_date or None,
            doc_ref=args.doc_ref,
            doc_date=args.doc_date or None,
            notes=args.notes,
        )
        row.update({k: info[k] for k in (
            "extent_wkt", "footprint_wkt", "width_px", "height_px", "bands",
            "dtype", "res_x", "res_y", "crs_epsg", "nodata", "compression",
            "is_tiled", "has_overviews", "overview_count")})

        if args.commit:
            try:
                cur.execute(UPSERT, row)
                stats["updated" if rel in known else "new"] += 1
            except psycopg2.Error as e:
                conn.rollback()
                stats["failed"] += 1
                print(f"           DB ERROR: {e}")
                continue
        else:
            stats["updated" if rel in known else "new"] += 1

    # ---- files in the catalog that are gone from disk ---------------------
    on_disk = {os.path.relpath(p, root).replace("\\", "/") for p in files}
    missing = sorted(set(known) - on_disk)

    if args.commit:
        conn.commit()
    conn.close()

    # ---- report ----------------------------------------------------------
    print(f"\n{'-'*78}")
    print(f" new {stats['new']}   updated {stats['updated']}   "
          f"skipped {stats['skipped']}   rejected/failed {stats['failed']}"
          + (f"   optimised {stats['optimized']}" if args.optimize else ""))

    if missing:
        print(f"\n {len(missing)} row(s) in the catalog with no file on disk "
              f"(nothing was deleted):")
        for m in missing[:20]:
            print(f"   - {m}")
        if len(missing) > 20:
            print(f"   ... and {len(missing)-20} more")

    if problems_seen:
        print(f"\n {len(problems_seen)} file(s) rejected. Fix and re-run:")
        for rel, ps in problems_seen:
            print(f"   {rel}")
            for p in ps:
                print(f"     - {p}")

    if not args.commit:
        print("\n DRY RUN - nothing was written. Re-run with --commit.")
    print(f"{'-'*78}\n")

    return 1 if stats["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
