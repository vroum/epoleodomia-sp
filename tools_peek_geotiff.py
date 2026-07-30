#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
peek_geotiff.py - read GeoTIFF headers with no GDAL/rasterio.

Enough of the TIFF + GeoTIFF spec to answer the only question that matters
before ingest: will ingest_rasters.py accept this file, or reject it?

Checks the same three things ingest_rasters.py checks:
  - is there a readable EPSG, and is it 2100
  - is the geotransform present
  - is it north-up (no rotation)
"""

import glob
import os
import struct
import sys

# TIFF tags we care about
T = {
    256: "ImageWidth", 257: "ImageLength", 258: "BitsPerSample",
    259: "Compression", 262: "Photometric", 277: "SamplesPerPixel",
    322: "TileWidth", 323: "TileLength",
    339: "SampleFormat",
    33550: "ModelPixelScale", 33922: "ModelTiepoint", 34264: "ModelTransform",
    34735: "GeoKeyDirectory", 34736: "GeoDoubleParams", 34737: "GeoAsciiParams",
    42112: "GDAL_METADATA", 42113: "GDAL_NODATA",
}

COMPRESSION = {1: "none", 5: "LZW", 6: "JPEG(old)", 7: "JPEG", 8: "deflate",
               32773: "packbits", 32946: "deflate", 34712: "JP2000",
               34887: "LERC", 50000: "zstd", 50001: "webp"}

FMT = {1: ("B", 1), 2: ("s", 1), 3: ("H", 2), 4: ("I", 4), 5: ("II", 8),
       6: ("b", 1), 7: ("B", 1), 8: ("h", 2), 9: ("i", 4), 10: ("ii", 8),
       11: ("f", 4), 12: ("d", 8),
       16: ("Q", 8), 17: ("q", 8), 18: ("Q", 8)}


def read_ifd(fh):
    head = fh.read(8)
    if len(head) < 8:
        raise ValueError("too short to be a TIFF")
    bo = head[:2]
    if bo == b"II":
        e = "<"
    elif bo == b"MM":
        e = ">"
    else:
        raise ValueError(f"not a TIFF (byte order {bo!r})")

    magic = struct.unpack(e + "H", head[2:4])[0]
    if magic == 42:
        big = False
        offset = struct.unpack(e + "I", head[4:8])[0]
    elif magic == 43:
        big = True
        fh.seek(8)
        offsz, _pad = struct.unpack(e + "HH", fh.read(4))
        if offsz != 8:
            raise ValueError("BigTIFF with unusual offset size")
        offset = struct.unpack(e + "Q", fh.read(8))[0]
    else:
        raise ValueError(f"bad TIFF magic {magic}")

    fh.seek(offset)
    if big:
        n = struct.unpack(e + "Q", fh.read(8))[0]
        entry_size, cnt_fmt, off_fmt = 20, "Q", "Q"
    else:
        n = struct.unpack(e + "H", fh.read(2))[0]
        entry_size, cnt_fmt, off_fmt = 12, "I", "I"

    raw = fh.read(n * entry_size)
    tags = {}
    for i in range(n):
        b = raw[i * entry_size:(i + 1) * entry_size]
        tag, typ = struct.unpack(e + "HH", b[:4])
        count = struct.unpack(e + cnt_fmt, b[4:4 + struct.calcsize(cnt_fmt)])[0]
        vbytes = b[4 + struct.calcsize(cnt_fmt):]

        if typ not in FMT:
            continue
        code, size = FMT[typ]
        total = size * count

        if total <= len(vbytes):
            data = vbytes[:total]
        else:
            ptr = struct.unpack(e + off_fmt, vbytes[:struct.calcsize(off_fmt)])[0]
            keep = fh.tell()
            fh.seek(ptr)
            data = fh.read(total)
            fh.seek(keep)

        if typ == 2:
            val = data.split(b"\0")[0].decode("latin-1", "replace")
        elif typ in (5, 10):
            nums = struct.unpack(e + code[0] * (2 * count), data)
            val = [nums[k] / nums[k + 1] if nums[k + 1] else 0
                   for k in range(0, len(nums), 2)]
        else:
            val = list(struct.unpack(e + code * count, data))
            if count == 1:
                val = val[0]
        tags[tag] = val

    return tags, e, big


def geokeys(tags):
    gk = tags.get(34735)
    if not gk or len(gk) < 4:
        return {}
    _, _, _, n = gk[:4]
    out = {}
    for i in range(n):
        base = 4 + i * 4
        if base + 3 >= len(gk):
            break
        key, loc, cnt, off = gk[base:base + 4]
        if loc == 0:
            out[key] = off
        elif loc == 34736:
            dbl = tags.get(34736) or []
            out[key] = dbl[off] if off < len(dbl) else None
        elif loc == 34737:
            asc = tags.get(34737) or ""
            out[key] = asc[off:off + cnt].rstrip("|\0")
    return out


def describe(path):
    problems, notes = [], []
    with open(path, "rb") as fh:
        tags, e, big = read_ifd(fh)

    gk = geokeys(tags)
    w = tags.get(256)
    h = tags.get(257)
    bands = tags.get(277, 1)
    bits = tags.get(258)
    if isinstance(bits, list):
        bits = bits[0]
    comp = COMPRESSION.get(tags.get(259), str(tags.get(259)))
    tiled = 322 in tags

    scale = tags.get(33550)
    tie = tags.get(33922)
    xform = tags.get(34264)

    epsg = gk.get(3072) or gk.get(2048)     # Projected, else Geographic
    citation = gk.get(3073) or gk.get(1026) or ""

    # --- the three ingest checks ---
    if not epsg or epsg in (0, 32767):
        problems.append(f"no usable EPSG in GeoKeys (3072={gk.get(3072)}, "
                        f"citation={citation!r})")
    elif epsg != 2100:
        problems.append(f"EPSG:{epsg}, expected 2100")

    resx = resy = None
    ext = None
    rot = None
    fixable = False

    if scale and len(scale) >= 2 and tie and len(tie) >= 6:
        # --- the easy, north-up case ---
        resx, resy = abs(scale[0]), abs(scale[1])
        i, j, _k, x, y, _z = tie[:6]
        left = x - i * resx
        top = y + j * resy
        ext = (left, top - h * resy, left + w * resx, top)

    elif xform and len(xform) >= 8:
        # --- full 4x4 ModelTransformation, row-major ---
        #   x = a*col + b*row + c ;  y = d*col + e*row + f
        a, b, _c0, c = xform[0], xform[1], xform[2], xform[3]
        d, e, _g0, f = xform[4], xform[5], xform[6], xform[7]
        det = a * e - b * d
        resx = resy = abs(det) ** 0.5

        corners = []
        for (col, row) in ((0, 0), (w, 0), (w, h), (0, h)):
            corners.append((a * col + b * row + c, d * col + e * row + f))
        xs = [p[0] for p in corners]
        ys = [p[1] for p in corners]
        ext = (min(xs), min(ys), max(xs), max(ys))

        if abs(b) > 1e-9 or abs(d) > 1e-9:
            import math
            rot = math.degrees(math.atan2(b / resx, a / resx))
            fixable = True
            problems.append(
                f"not north-up: rotated {rot:.2f} deg"
                + (", and mirrored" if det > 0 else "")
                + ". AutoCAD does not read rotation from the GeoTIFF, so it "
                  "would be placed wrongly. Fix with "
                  "ingest_rasters.py --warp-northup")
        # note: a normal north-up raster also has det < 0, because the row
        # axis grows downward while y grows upward. det sign is not the tell.

    else:
        problems.append("no ModelPixelScale+Tiepoint and no ModelTransform")

    if resx and resy and abs(resx - resy) > 1e-9:
        notes.append(f"non-square pixels {resx} x {resy}")

    return dict(w=w, h=h, bands=bands, bits=bits, comp=comp, tiled=tiled,
                epsg=epsg, citation=citation, resx=resx, resy=resy, ext=ext,
                rot=rot, fixable=fixable,
                nodata=tags.get(42113), problems=problems, notes=notes,
                bigtiff=big)


def main():
    args = sys.argv[1:] or [os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "rasters", "*", "*.tif")]
    paths = []
    for a in args:
        paths.extend(sorted(glob.glob(a)) if any(c in a for c in "*?[") else [a])

    if not paths:
        sys.exit("no files matched")

    print(f"\n{'file':28s} {'pixels':>13s} {'m/px':>8s} {'EPSG':>6s} "
          f"{'bands':>5s} {'comp':>8s}  {'MB':>6s}  status")
    print("-" * 104)

    allext = []
    okc = badc = 0
    details = []

    for p in paths:
        name = os.path.basename(p)
        mb = os.path.getsize(p) / 1048576
        try:
            d = describe(p)
        except Exception as ex:
            badc += 1
            print(f"{name:28s} {'-':>13s} {'-':>8s} {'-':>6s} {'-':>5s} "
                  f"{'-':>8s}  {mb:6.1f}  UNREADABLE: {ex}")
            continue

        if not d["problems"]:
            status = "OK"
        elif d["fixable"] and len(d["problems"]) == 1:
            status = "WARP"
        else:
            status = "REJECT"
        if d["problems"] and status != "WARP":
            badc += 1
        else:
            okc += 1
            if d["ext"]:
                allext.append(d["ext"])

        print(f"{name:28s} {str(d['w'])+'x'+str(d['h']):>13s} "
              f"{(('%.3f' % d['resx']) if d['resx'] else '-'):>8s} "
              f"{str(d['epsg'] or '-'):>6s} {str(d['bands']):>5s} "
              f"{d['comp']:>8s}  {mb:6.1f}  {status}")
        details.append((name, d))

    print("-" * 104)
    warpc = sum(1 for _, x in details if x["fixable"])
    print(f"{okc} usable ({warpc} need --warp-northup), {badc} rejected\n")

    for name, d in details:
        if d["problems"] or d["notes"]:
            print(f"  {name}")
            for x in d["problems"]:
                print(f"    {'WARP  ' if d['fixable'] else 'REJECT'}: {x}")
            for x in d["notes"]:
                print(f"    note:   {x}")

    if allext:
        minx = min(e[0] for e in allext)
        miny = min(e[1] for e in allext)
        maxx = max(e[2] for e in allext)
        maxy = max(e[3] for e in allext)
        print(f"\n  combined extent (EGSA87):")
        print(f"    X {minx:12.2f} .. {maxx:12.2f}   ({maxx-minx:9.1f} m)")
        print(f"    Y {miny:12.2f} .. {maxy:12.2f}   ({maxy-miny:9.1f} m)")
        print(f"    area {(maxx-minx)*(maxy-miny)/1e6:.2f} km2")
        print(f"\n  test ERASTER over:  {minx:.0f},{miny:.0f} "
              f"to {maxx:.0f},{maxy:.0f}")
        d0 = details[0][1]
        if d0["citation"]:
            print(f"\n  CRS citation: {d0['citation']!r}")


if __name__ == "__main__":
    main()
