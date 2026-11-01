"""KGEOM boundary correction: validated survey + a caller-owned query session.

No FastAPI, database-driver or configuration imports. All SQL runs through the
supplied query callable; callers must keep it in one read-only repeatable-read
transaction and protect the parcel relation against replacement. The geometry
rules and AutoCAD text protocol are kept here, independently of API routing.
"""

from cadastre_geometry import (
    PARCEL_RELATION,
    SurveyInputError,
    SurveyRing,
    is_special_kaek,
    non_special_use_filter,
    parse_survey_ring,
    ring_strings,
    wkt_to_coords,
)


def calculate_boundary_correction(survey: SurveyRing, query) -> str:
    """Run the spatial calculation using query(sql, params, fetch_one=False)."""
    topo_wkt, tol = survey.wkt, survey.tolerance

    def rings(statement, args, reject_holes=False):
        return ring_strings(query(statement, args), reject_holes=reject_holes)

    # A surveyed boundary must be valid as supplied; repairing it changes the survey.
    valid = query("""
        WITH survey AS (SELECT ST_GeomFromText(%s, 2100) AS g)
        SELECT ST_IsValid(g) AND NOT ST_IsEmpty(g) AND ST_Area(g) > 0 FROM survey
        """, (topo_wkt,), fetch_one=True)
    if not valid or not valid[0]:
        return "ERROR|TOPO_PROP must be a valid polygon with positive area"
    TOPO = "ST_GeomFromText(%s, 2100)"

    # ── Subject: non-special parcel with max overlap ─────────────────────────
    EK_FILTER = non_special_use_filter()
    subj_sql = f"""
    SELECT kaek, ROUND(ST_Area(geom)::numeric, 2)
    FROM sp_geodata.kaek_parcels_operating
    WHERE {EK_FILTER} AND ST_Intersects(geom, {TOPO})
      AND ST_Area(ST_Intersection(ST_MakeValid(geom), {TOPO})) > 0
    ORDER BY ST_Area(ST_Intersection(ST_MakeValid(geom), {TOPO})) DESC, kaek
    LIMIT 1
    """
    subj = query(subj_sql, (topo_wkt, topo_wkt, topo_wkt), fetch_one=True)
    if not subj:
        return "ERROR|No operating parcel overlaps the TOPO_PROP polygon"
    subject_kaek, subject_area0 = subj[0], float(subj[1])

    topo_area_sql = f"SELECT ROUND(ST_Area({TOPO})::numeric, 2)"
    topo_area = float(query(topo_area_sql, (topo_wkt,), fetch_one=True)[0])

    SUBJ = "(SELECT ST_MakeValid(geom) FROM sp_geodata.kaek_parcels_operating WHERE kaek = %s)"

    # ── Δi: split the claimed area by donor, including any unmapped remainder ─
    d_pieces = f"""
    WITH claim AS (
        SELECT ST_CollectionExtract(ST_Difference({TOPO}, {SUBJ}), 3) AS g
    ), donors AS (
        SELECT p.kaek,
               ST_CollectionExtract(ST_Intersection(ST_MakeValid(p.geom), c.g), 3) AS g
        FROM sp_geodata.kaek_parcels_operating p CROSS JOIN claim c
        WHERE p.kaek != %s AND ST_Intersects(p.geom, c.g)
    ), pieces AS (
        SELECT kaek, (ST_Dump(g)).geom AS g FROM donors
        UNION ALL
        SELECT NULL::text, (ST_Dump(ST_CollectionExtract(ST_Difference(c.g,
            COALESCE((SELECT ST_Union(g) FROM donors),
                     ST_GeomFromText('POLYGON EMPTY', 2100))), 3))).geom
        FROM claim c
    )
    """
    d_args = (topo_wkt, subject_kaek, subject_kaek, tol)
    d_sql = d_pieces + """
    SELECT ST_AsText(ST_ExteriorRing(g)),
           ROUND(ST_Area(g)::numeric, 2), kaek, ST_NumInteriorRings(g)
    FROM pieces
    WHERE ST_Area(g) >= %s
    ORDER BY ST_Area(g) DESC, kaek, ST_AsText(g)
    """
    d_rows = query(d_sql, d_args) or []

    # sliver accounting
    d_sliv_sql = d_pieces + """
    SELECT COUNT(*), COALESCE(ROUND(SUM(ST_Area(g))::numeric, 2), 0),
           EXISTS (SELECT 1 FROM donors a JOIN donors b ON a.kaek < b.kaek
                   WHERE ST_Area(ST_Intersection(a.g, b.g)) > 0)
    FROM pieces WHERE ST_Area(g) < %s
    """
    d_sliv = query(d_sliv_sql, d_args, fetch_one=True)
    if d_sliv and d_sliv[2]:
        return "ERROR|Claimed area overlaps multiple donor parcels; review cadastral topology"
    if any(r[2] is None for r in d_rows):
        return "ERROR|Claimed area is not fully covered by donor parcels at this tolerance"
    if any(r[3] for r in d_rows):
        return "ERROR|Claimed piece has holes; current drawing format cannot represent them"

    # ── Αi: cut pieces (subject − TOPO), assigned by longest shared boundary ─
    a_sql = f"""
    WITH pieces AS (
        SELECT (ST_Dump(ST_CollectionExtract(
                   ST_Difference({SUBJ}, {TOPO}), 3))).geom AS g
    )
    SELECT ST_AsText(ST_ExteriorRing(g)),
           ROUND(ST_Area(g)::numeric, 2),
           (SELECT p.kaek FROM sp_geodata.kaek_parcels_operating p
            WHERE p.kaek != %s AND ST_DWithin(p.geom, g, 0.05)
              AND ST_Length(ST_Intersection(
                  ST_Boundary(ST_MakeValid(p.geom)), ST_Boundary(g))) > 0
            ORDER BY ST_Length(ST_Intersection(
                ST_Boundary(ST_MakeValid(p.geom)), ST_Boundary(g))) DESC, p.kaek
            LIMIT 1), ST_NumInteriorRings(g)
    FROM pieces
    WHERE ST_Area(g) >= %s
    ORDER BY ST_Area(g) DESC, ST_AsText(g)
    """
    a_rows = query(a_sql, (subject_kaek, topo_wkt, subject_kaek, tol)) or []
    if any(r[3] for r in a_rows):
        return "ERROR|Cut piece has holes; current drawing format cannot represent them"
    if any(r[2] is None for r in a_rows):
        return "ERROR|Cut piece has no neighbor with a positive shared boundary"

    a_sliv_sql = f"""
    WITH pieces AS (
        SELECT (ST_Dump(ST_CollectionExtract(
                   ST_Difference({SUBJ}, {TOPO}), 3))).geom AS g
    )
    SELECT COUNT(*), COALESCE(ROUND(SUM(ST_Area(g))::numeric, 2), 0)
    FROM pieces WHERE ST_Area(g) < %s
    """
    a_sliv = query(a_sliv_sql, (subject_kaek, topo_wkt, tol), fetch_one=True)

    # ── Affected parcels & finals ────────────────────────────────────────────
    # X_final = (X − TOPO) ∪ assigned Αi pieces; subject_final = TOPO
    gains = {}  # kaek -> True (receives Αi)
    for r in a_rows:
        if r[2]:
            gains[r[2]] = True
    losers = {}  # kaek -> True (loses Δi)
    for r in d_rows:
        if r[2]:
            losers[r[2]] = True
    affected = sorted(set(list(gains) + list(losers)))

    lines = [f"OK|{subject_kaek}|{tol}"]

    for i, r in enumerate(d_rows, 1):
        coords = wkt_to_coords(r[0])
        if coords:
            cs = ";".join(f"{c[0]},{c[1]}" for c in coords)
            lines.append(f"D|Δ{i}|{r[2] or '—'}|{r[1]}|{cs}")

    for i, r in enumerate(a_rows, 1):
        coords = wkt_to_coords(r[0])
        if coords:
            cs = ";".join(f"{c[0]},{c[1]}" for c in coords)
            lines.append(f"A|Α{i}|{r[2] or '—'}|{r[1]}|{cs}")

    # Subject final = the surveyed polygon itself
    subj_final_rings = rings(
        f"SELECT ST_AsText(ST_ExteriorRing((ST_Dump({TOPO})).geom))", (topo_wkt,))
    for cs in subj_final_rings:
        lines.append(f"F|{subject_kaek}|{topo_area}|{cs}")

    # Neighbor finals (skip EK/roads — too large to draw; reported in table)
    finals_table = [(subject_kaek, subject_area0, topo_area, False)]
    for nk in affected:
        special = is_special_kaek(nk)
        fin_sql = f"""
        WITH base AS (
            SELECT ST_Difference(
                (SELECT ST_MakeValid(geom)
                 FROM sp_geodata.kaek_parcels_operating WHERE kaek = %s),
                {TOPO}) AS g
        )
        SELECT ROUND(ST_Area(g)::numeric, 2), ST_AsText(g) FROM base
        """
        fin = query(fin_sql, (nk, topo_wkt), fetch_one=True)
        if not fin:
            continue
        # add assigned Αi areas
        gained = sum(float(r[1]) for r in a_rows if r[2] == nk)
        init_sql = """
        SELECT ROUND(ST_Area(geom)::numeric, 2)
        FROM sp_geodata.kaek_parcels_operating WHERE kaek = %s
        """
        init = query(init_sql, (nk,), fetch_one=True)
        init_area = float(init[0]) if init else 0.0
        final_area = round(float(fin[0]) + gained, 2)
        finals_table.append((nk, init_area, final_area, special))

        if not special:
            fin_rings_sql = f"""
            WITH base AS (
                SELECT ST_Union(
                    ST_Difference(
                        (SELECT ST_MakeValid(geom)
                         FROM sp_geodata.kaek_parcels_operating WHERE kaek = %s),
                        {TOPO}),
                    COALESCE((
                        SELECT ST_Union(g) FROM (
                            SELECT (ST_Dump(ST_CollectionExtract(
                                ST_Difference({SUBJ}, {TOPO}), 3))).geom AS g
                        ) pieces
                        WHERE ST_Area(g) >= %s
                          AND (SELECT p2.kaek FROM sp_geodata.kaek_parcels_operating p2
                               WHERE p2.kaek != %s AND ST_DWithin(p2.geom, g, 0.05)
                                 AND ST_Length(ST_Intersection(
                                     ST_Boundary(ST_MakeValid(p2.geom)), ST_Boundary(g))) > 0
                               ORDER BY ST_Length(ST_Intersection(
                                   ST_Boundary(ST_MakeValid(p2.geom)), ST_Boundary(g))) DESC, p2.kaek
                               LIMIT 1) = %s
                    ), ST_GeomFromText('POLYGON EMPTY', 2100))
                ) AS g
            ), rings AS (
                SELECT (ST_Dump(ST_CollectionExtract(g, 3))).geom AS g FROM base
            )
            SELECT ST_AsText(ST_ExteriorRing(g)), ST_NumInteriorRings(g) FROM rings
            """
            final_rings = rings(fin_rings_sql,
                                     (nk, topo_wkt, subject_kaek, topo_wkt,
                                      tol, subject_kaek, nk), reject_holes=True)
            if final_rings is None:
                return f"ERROR|Final parcel {nk} has holes; current drawing format cannot represent them"
            for cs in final_rings:
                lines.append(f"F|{nk}|{final_area}|{cs}")

    # ── Ισοζύγιο & πίνακας μεταβολών ─────────────────────────────────────────
    sum_d = round(sum(float(r[1]) for r in d_rows), 2)
    sum_a = round(sum(float(r[1]) for r in a_rows), 2)
    balance = round(subject_area0 + sum_d - sum_a - topo_area, 2)

    tbl = ["TITLE|ΠΙΝΑΚΑΣ ΜΕΤΑΒΟΛΩΝ|Διόρθωση ορίων",
           "HEADER|Αρχικά / Τελικά γεωτεμάχια|"]
    for kaek, a0, a1, special in finals_table:
        diff = round(a1 - a0, 2)
        sign = f"+{diff}" if diff > 0 else str(diff)
        note = " (κοινόχρ./ΕΚ — δεν σχεδιάζεται)" if special else ""
        tbl.append(f"ROW|{kaek}{note}|{a0} → {a1} τ.μ. ({sign})")
    if d_rows or a_rows:
        tbl.append("HEADER|Τμήματα|")
        for i, r in enumerate(d_rows, 1):
            tbl.append(f"ROW|Δ{i} (από {r[2] or '—'})|{r[1]} τ.μ.")
        for i, r in enumerate(a_rows, 1):
            tbl.append(f"ROW|Α{i} (προς {r[2] or '—'})|{r[1]} τ.μ.")
    tbl.append(f"MERGED|Ισοζύγιο: {subject_area0} + Δ({sum_d}) − Α({sum_a}) − "
               f"τελικό({topo_area}) = {balance} τ.μ."
               + (" ✓" if abs(balance) < 0.05 else " — ΕΛΕΓΞΕ!") + "|")
    if d_sliv and (d_sliv[0] or 0) > 0:
        tbl.append(f"MERGED|Αγνοήθηκαν {d_sliv[0]} slivers Δ συνολικού εμβαδού "
                   f"{d_sliv[1]} τ.μ. (όριο {tol} τ.μ.)|")
    if a_sliv and (a_sliv[0] or 0) > 0:
        tbl.append(f"MERGED|Αγνοήθηκαν {a_sliv[0]} slivers Α συνολικού εμβαδού "
                   f"{a_sliv[1]} τ.μ. (όριο {tol} τ.μ.)|")

    lines.extend("TBL|" + t for t in tbl)

    text = "\n".join(lines)
    return text.encode('windows-1253', errors='replace').decode('windows-1253')
