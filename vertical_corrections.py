"""KGEOMV input validation, spatial calculations and AutoCAD text output.

No API/driver/config imports. The caller supplies one read-only snapshot query
session protecting both the operating parcels and exclusive-use relations.
"""

from collections import Counter
from dataclasses import dataclass
import math
from typing import Optional, Tuple

from cadastre_geometry import (
    EXCLUSIVE_USE_RELATION, PARCEL_RELATION, SurveyInputError,
    non_special_use_filter, parse_survey_ring, ring_strings, wkt_to_coords,
)


VERTICAL_RELATIONS = (PARCEL_RELATION, EXCLUSIVE_USE_RELATION)


@dataclass(frozen=True)
class SurveyedVertical:
    number: str
    specified_number: str
    title_area: Optional[float]
    title_xiliosta: Optional[float]
    wkt: str


@dataclass(frozen=True)
class VerticalSurvey:
    verticals: Tuple[SurveyedVertical, ...]
    tolerance: float


def parse_vertical_survey(body: str, tol: float = 0.5) -> VerticalSurvey:
    """Reject incomplete/ambiguous records before acquiring a database session."""
    if not math.isfinite(tol) or tol < 0:
        raise SurveyInputError("Overlap/sliver tolerance must be finite and non-negative")
    if not body.strip():
        raise SurveyInputError("Empty body")
    verticals = []
    numbers = set()
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("|")
        if len(parts) != 5 or parts[0] != "V":
            raise SurveyInputError("Could not parse VST line (V|num|area|xil|coords)")
        _, specified, area, xiliosta, coords = parts
        specified = specified.strip()
        number = specified or f"{len(verticals) + 1:02d}"
        if number in numbers:
            raise SurveyInputError(f"Duplicate VST number {number}")
        if any(ord(char) < 32 or ord(char) == 127 for char in number):
            raise SurveyInputError("VST number contains unsupported control characters")
        try:
            number.encode("windows-1253")
        except UnicodeEncodeError:
            raise SurveyInputError("VST number is not supported by the AutoCAD text encoding")
        try:
            title_area = float(area) if area.strip() else None
            title_xiliosta = float(xiliosta) if xiliosta.strip() else None
        except ValueError:
            raise SurveyInputError(f"VST {number}: title area/xiliosta must be numeric or empty")
        if title_area is not None and (not math.isfinite(title_area) or title_area < 0):
            raise SurveyInputError(f"VST {number}: title area must be finite and non-negative")
        if title_xiliosta is not None and (not math.isfinite(title_xiliosta) or
                                          not 0 <= title_xiliosta <= 1000):
            raise SurveyInputError(f"VST {number}: title xiliosta must be finite and between 0 and 1000")
        try:
            ring = parse_survey_ring(coords, tol)
        except SurveyInputError as exc:
            message = str(exc).replace("TOPO_PROP", "survey")
            raise SurveyInputError(f"VST {number}: {message}") from exc
        verticals.append(SurveyedVertical(number, specified, title_area, title_xiliosta, ring.wkt))
        numbers.add(number)
    return VerticalSurvey(tuple(verticals), tol)


def calculate_vertical_correction(survey: VerticalSurvey, query) -> str:
    """Calculate clipped verticals using query(sql, params, fetch_one=False)."""
    vsts, tol = survey.verticals, survey.tolerance
    if not vsts:
        return "ERROR|No V| lines in body"
    values = ",".join("(%s,%s)" for _ in vsts)
    args = tuple(value for v in vsts for value in (v.number, v.wkt))
    invalid = query(f"""
        WITH input(num,wkt) AS (VALUES {values}),
             surveys AS (SELECT num, ST_GeomFromText(wkt,2100) AS g FROM input)
        SELECT num FROM surveys
        WHERE NOT ST_IsValid(g) OR ST_IsEmpty(g) OR ST_Area(g) <= 0
        ORDER BY num LIMIT 1
        """, args, fetch_one=True)
    if invalid:
        return f"ERROR|VST {invalid[0]} must be a valid polygon with positive area"

    G = "ST_GeomFromText(%s, 2100)"

    def union_of(items):
        return f"ST_Union(ARRAY[{','.join([G] * len(items))}])", tuple(v.wkt for v in items)

    union_expr, all_wkts = union_of(vsts)
    parent = query(f"""
        SELECT kaek, ST_Area(ST_MakeValid(geom))
        FROM sp_geodata.kaek_parcels_operating
        WHERE {non_special_use_filter()} AND ST_Intersects(geom, {union_expr})
          AND ST_Area(ST_Intersection(ST_MakeValid(geom), {union_expr})) > 0
        ORDER BY ST_Area(ST_Intersection(ST_MakeValid(geom), {union_expr})) DESC, kaek
        LIMIT 1
        """, all_wkts * 3, fetch_one=True)
    if not parent:
        return "ERROR|No operating parcel overlaps the surveyed kathetes"
    kaek, parcel_raw = parent[0], float(parent[1])
    if not math.isfinite(parcel_raw) or parcel_raw <= 0:
        return "ERROR|Parent parcel must have positive finite area"
    parcel_area = round(parcel_raw, 2)
    PARCEL = "(SELECT ST_MakeValid(geom) FROM sp_geodata.kaek_parcels_operating WHERE kaek = %s)"
    CLIP = f"ST_Intersection({G}, {PARCEL})"

    kt_ax = {}
    for number, area in query("""
            SELECT vp_num, ROUND(COALESCE(area, ST_Area(ST_MakeValid(geom)))::numeric, 1)
            FROM sp_geodata.kaek_apokleistikes_operating WHERE kaek = %s
            """, (kaek,)) or []:
        if number is None or not str(number).strip():
            return "ERROR|Cadastral AX is missing its number"
        number = str(number).strip()
        if number in kt_ax:
            return f"ERROR|Duplicate cadastral AX number {number}; review source records"
        try:
            area = float(area)
        except (TypeError, ValueError):
            return f"ERROR|Cadastral AX {number} has invalid area"
        if not math.isfinite(area) or area < 0:
            return f"ERROR|Cadastral AX {number} has invalid area"
        kt_ax[number] = area

    lines = [f"OK|{kaek}|{parcel_area}"]
    tbl = [f"TITLE|ΠΙΝΑΚΑΣ ΚΑΘΕΤΩΝ|Διόρθωση καθέτων — {kaek}",
           "HEADER|Γεωτεμάχιο|", f"ROW|ΚΑΕΚ|{kaek} — {parcel_area} τ.μ.",
           "HEADER|Κάθετες: τίτλος / κτηματ. / αποτύπωση|"]
    warnings = []
    matches = Counter()
    retained = []
    for v in vsts:
        num = v.number
        meas_raw, clip_raw = map(float, query(
            f"SELECT ST_Area({G}), ST_Area({CLIP})", (v.wkt, v.wkt, kaek), fetch_one=True))
        if not math.isfinite(meas_raw) or not math.isfinite(clip_raw):
            return f"ERROR|VST {num} has non-finite measured/clipped area"
        if clip_raw <= 0 or clip_raw < tol:
            warnings.append(f"ΑΧ {num}: εκτός γεωτεμαχίου ή κάτω από το όριο εμβαδού — αγνοήθηκε")
            continue
        clip_area = round(clip_raw, 2)
        clip_loss = round(meas_raw - clip_raw, 2)
        if clip_loss > 0.05:
            warnings.append(f"ΑΧ {num}: κόπηκαν {clip_loss} τ.μ. εκτός ορίου γεωτεμαχίου")

        candidates = query(f"""
            WITH clip AS (SELECT {CLIP} AS g), candidates AS (
                SELECT a.vp_num, ST_Area(ST_Intersection(ST_MakeValid(a.geom), c.g)) AS area
                FROM sp_geodata.kaek_apokleistikes_operating a CROSS JOIN clip c
                WHERE a.kaek = %s AND ST_Intersects(a.geom, c.g)
            )
            SELECT vp_num, area FROM candidates WHERE area > 0
            ORDER BY area DESC, vp_num LIMIT 2
            """, (v.wkt, kaek, kaek)) or []
        matched = str(candidates[0][0]).strip() if candidates else None
        if matched:
            matches[matched] += 1
            if len(candidates) > 1 and candidates[0][1] == candidates[1][1]:
                warnings.append(f"ΑΧ {num}: ίδια μέγιστη επικάλυψη με κτηματολογικές ΑΧ "
                                f"{candidates[0][0]}, {candidates[1][0]} — έλεγξε αντιστοίχιση")
            if v.specified_number and matched != v.specified_number:
                warnings.append(f"ΑΧ {num}: μέγιστη επικάλυψη με κτηματολογική ΑΧ {matched} — έλεγξε αρίθμηση")
        else:
            warnings.append(f"ΑΧ {num}: δεν βρέθηκε κτηματολογική ΑΧ με θετική επικάλυψη")

        result_rings = ring_strings(query(f"""
            WITH clip AS (SELECT {CLIP} AS g), parts AS (
                SELECT (ST_Dump(ST_CollectionExtract(g,3))).geom AS g FROM clip
            )
            SELECT ST_AsText(ST_ExteriorRing(g)), ST_NumInteriorRings(g)
            FROM parts ORDER BY ST_Area(g) DESC, ST_AsText(g)
            """, (v.wkt, kaek)), reject_holes=True)
        if result_rings is None:
            return f"ERROR|VST {num} has holes; current drawing format cannot represent them"
        if not result_rings:
            return f"ERROR|VST {num} has no drawable polygon after clipping"
        lines.extend(f"VF|{num}|{clip_area}|{coords}" for coords in result_rings)
        retained.append(v)

        implied = round(clip_raw / parcel_raw * 1000, 1)
        title_area = str(v.title_area) if v.title_area is not None else "—"
        title_xil = f"{v.title_xiliosta}‰" if v.title_xiliosta is not None else "—"
        kt_area = str(kt_ax.get(matched, "—")) if matched else "—"
        tbl.append(f"ROW|ΑΧ {num}|τίτλ: {title_area} ({title_xil}) · ΚΤ({matched or '—'}): {kt_area} "
                   f"· μέτρ: {clip_area} ({implied}‰)")
        if v.title_area is not None and abs(clip_raw - v.title_area) > tol:
            delta = round(clip_raw - v.title_area, 2)
            warnings.append(f"ΑΧ {num}: μέτρηση − τίτλος = {delta:+} τ.μ.")

    if not retained:
        return "ERROR|No surveyed VST has positive clipped area at this tolerance"

    for i, first in enumerate(retained):
        for second in retained[i + 1:]:
            overlap = query(f"SELECT ST_Area(ST_Intersection({CLIP}, {CLIP}))",
                            (first.wkt, kaek, second.wkt, kaek), fetch_one=True)
            if overlap and float(overlap[0]) > tol:
                warnings.append(f"ΕΠΙΚΑΛΥΨΗ ΑΧ {first.number} με ΑΧ {second.number}: "
                                f"{round(float(overlap[0]), 2)} τ.μ.")

    union_expr, all_wkts = union_of(retained)
    rest = query(f"SELECT ST_Area(ST_Difference({PARCEL}, {union_expr}))",
                 (kaek,) + all_wkts, fetch_one=True)
    rest_raw = float(rest[0])
    tbl.append("HEADER|Έλεγχοι|")
    tbl.append(f"ROW|Κοινόχρηστο εκτός ΑΧ|{round(rest_raw, 2)} τ.μ. "
               f"({round(rest_raw / parcel_raw * 1000, 1)}‰)")
    for number in sorted(matches):
        if matches[number] > 1:
            warnings.append(f"Κτηματολογική ΑΧ {number}: αντιστοιχήθηκε σε περισσότερες από μία μετρήσεις")
    for number in sorted(set(kt_ax) - set(matches)):
        warnings.append(f"Κτηματολογική ΑΧ {number} ({kt_ax[number]} τ.μ.) δεν αντιστοιχήθηκε σε καμία μέτρηση")
    tbl.extend(f"MERGED|⚠ {warning}|" for warning in warnings)
    if not warnings:
        tbl.append("MERGED|Όλοι οι έλεγχοι εντάξει — καμία προειδοποίηση.|")

    boundary_expr = ",".join([f"ST_Boundary({CLIP})"] * len(retained))
    line_args = tuple(value for v in retained for value in (v.wkt, kaek)) + (kaek,)
    line_rows = query(f"""
        WITH clipped AS (SELECT ST_Union(ARRAY[{boundary_expr}]) AS b)
        SELECT ST_AsText((ST_Dump(ST_LineMerge(ST_CollectionExtract(
            ST_Difference(b, ST_Boundary({PARCEL})), 2)))).geom)
        FROM clipped
        """, line_args) or []
    for row in line_rows:
        coords = wkt_to_coords(row[0])
        if len(coords) > 1:
            lines.append("L|" + ";".join(f"{x},{y}" for x, y in coords))
    lines.extend("TBL|" + row for row in tbl)
    return "\n".join(lines).encode("windows-1253", errors="replace").decode("windows-1253")
