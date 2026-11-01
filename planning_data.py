"""Planning GIS providers and report orchestration over an injected query session.

No FastAPI, database driver, environment or connection ownership. SQL references
are trusted constants and coordinates/identities are query parameters. The API
supplies one snapshot and optional-group savepoints for complete reports.
"""

from contextlib import nullcontext

from cadastre_geometry import non_special_use_filter as _kaek_non_special_use_filter
from planning_reports import (
    FOREST_USE_CODES as _KAEK_FOREST_USE_CODES,
    MISSING_PARCEL, MISSING_REGULATIONS,
    build_parcel_report, build_point_report,
)


# Acquire every source lock before the first SELECT: repeatable-read alone
# cannot preserve a table that a replacement sync drops and recreates.
POINT_REPORT_RELATIONS = tuple(sorted((
    ("epoleodomia", "building_blocks"),
    ("epoleodomia", "approved_plan_boundaries"),
    ("epoleodomia", "building_regs_coefficient"),
    ("epoleodomia", "building_regs_height"),
    ("epoleodomia", "building_regs_coverage"),
    ("epoleodomia", "building_regs_lot"),
    ("epoleodomia", "building_regs_system"),
    ("epoleodomia", "natura_2000"),
    ("epoleodomia", "forest_maps"),
    ("epoleodomia", "forest_maps_posted_attica_2021"),
    ("sp_geodata", "kaek_parcels_operating"),
    ("sp_geodata", "Αρχαιολογία_Ζώνες_Προστασίας"),
    ("sp_geodata", "Αρχαιλογία_Κυρηγμένα_Μνημεία"),
    ("sp_geodata", "Εκκλησίες_πολυγωνα"),
    ("sp_geodata", "Αιγιαλός_Παραλία"),
    ("sp_geodata", "orio_sxediou_polews"),
    ("sp_geodata", "Ρεματα_Οικισμού_υπό_Οριοθέτηση"),
    ("sp_geodata", "Ρεματα Νησιου ΤΠΣ (εκτος των 6)"),
    ("sp_geodata", "Ρεματα εντος οικισμου εκτος των 6"),
)))
PARCEL_REPORT_RELATIONS = tuple(sorted(POINT_REPORT_RELATIONS + (
    ("sp_geodata", "kaek_apokleistikes_operating"),
    ("sp_geodata", "kaek_douleies_operating"),
)))
WATER_RELATION = ("sp_geodata", "ydrolipsies_emsy")
OPTIONAL_REPORT_RELATIONS = (WATER_RELATION,)


# Trusted reference fragments: psycopg2 supplies all placeholder arguments.
POINT_REF = "ST_SetSRID(ST_Point(%s, %s), 2100)"          # args: (x, y)


PARCEL_REF = "(SELECT geom FROM sp_geodata.kaek_parcels_operating WHERE kaek = %s)"  # args: (kaek,)


# Keep the flood reference provisional until its publication is reviewed.
STREAM_LABELS = {
    "Υδρογραφική Γραμμή Πλημμυρας":                    "Πιθανή Γρ. Πλημμύρας",
    "Υδρογραφική Γραμμή Οριοθέτησης με τεχν. έργο":   "Γρ. Οριοθέτησης (με έργο)",
    "Υδρογραφική Γραμμή Οριοθέτησης χωρίς έργο":      "Γρ. Οριοθέτησης (χωρίς έργο)",
}


STREAM_ORDER = [
    "Υδρογραφική Γραμμή Πλημμυρας",
    "Υδρογραφική Γραμμή Οριοθέτησης με τεχν. έργο",
    "Υδρογραφική Γραμμή Οριοθέτησης χωρίς έργο",
]


# code -> short label, description, classification category
FOREST_TYPE_LABELS = {
    "ΔΔ": (
        "Δάσος/Δασική έκταση",
        "Δάσος ή δασική έκταση στις αεροφωτογραφίες παλαιότερης ΚΑΙ πρόσφατης λήψης",
        "δασικό",
    ),
    "ΔΑ": (
        "Δάσος (ιστορικό — αυστηρά προστατευμένο)",
        "Δάσος στις αεροφωτογραφίες παλαιότερης λήψης — άλλης μορφής στις πρόσφατες. Διατηρεί δασικό χαρακτήρα, πρακτικά αναλλοίωτος.",
        "δασικό",
    ),
    "ΑΔ": (
        "Δάσος/Δασική έκταση (νέα)",
        "Άλλης μορφής στις αεροφωτογραφίες παλαιότερης λήψης — δάσος ή δασική έκταση στις πρόσφατες. Δασικός χαρακτήρας, ενδέχεται αλλαγή χρήσης.",
        "δασικό",
    ),
    "ΑΑ": (
        "Μη δασική έκταση",
        "Άλλης μορφής/κάλυψης εκτάσεις και στις αεροφωτογραφίες παλαιότερης ΚΑΙ πρόσφατης λήψης",
        "μη δασικό",
    ),
    "ΠΔ": (
        "Δασικό (χαρακτηρισμός)",
        "Τελεσίδικη πράξη/απόφαση χαρακτηρισμού — δασική",
        "δασικό",
    ),
    "ΠΑ": (
        "Μη δασικό (χαρακτηρισμός)",
        "Τελεσίδικη πράξη/απόφαση χαρακτηρισμού — μη δασική",
        "μη δασικό",
    ),
    "ΠΧ": (
        "Χορτολιβαδικό (χαρακτηρισμός)",
        "Τελεσίδικη πράξη/απόφαση χαρακτηρισμού — χορτολιβαδική",
        "χορτολιβαδικό",
    ),
    "ΑΝ": (
        "Αναδασωτέα/Δασωτέα",
        "Αναδασωτέα ή δασωτέα έκταση",
        "αναδασωτέο",
    ),
    "ΧΧ": (
        "Χορτολιβαδική έκταση",
        "Χορτολιβαδική έκταση στις αεροφωτογραφίες παλαιότερης ΚΑΙ πρόσφατης λήψης",
        "χορτολιβαδικό",
    ),
    "ΧΑ": (
        "Χορτολιβαδική (αλλοίωση)",
        "Χορτολιβαδική στις αεροφωτογραφίες παλαιότερης λήψης — άλλης μορφής στις πρόσφατες",
        "χορτολιβαδικό",
    ),
    "ΑΧ": (
        "Χορτολιβαδική (νέα)",
        "Άλλης μορφής στις αεροφωτογραφίες παλαιότερης λήψης — χορτολιβαδική στις πρόσφατες",
        "χορτολιβαδικό",
    ),
}


def decode_forest_type(code: str) -> tuple:
    """Return (short_label, full_description, category) for a forest type code."""
    if not code:
        return ("—", "Άγνωστος τύπος", "άγνωστο")
    entry = FOREST_TYPE_LABELS.get(code.strip().upper())
    if entry:
        return entry
    return (code, f"Κωδικός: {code}", "άγνωστο")


class PlanningData:
    """Load report sections with one explicit query/optional-group boundary."""

    def __init__(self, query, *, optional_scope=nullcontext, water_available=True):
        self.query = query
        self.optional_scope = optional_scope
        self.water_available = water_available
        self._natura_tracking = None

    def _natura_active_filter(self):
        """Discover the legacy/managed column contract within this query session.

        Cache only on this collector, never across requests/schema changes.
        Required-source/catalog failures propagate; they cannot mean no Natura.
        """
        if self._natura_tracking is None:
            row = self.query("""
                SELECT EXISTS (
                    SELECT 1 FROM pg_catalog.pg_attribute a
                    JOIN pg_catalog.pg_class c ON c.oid = a.attrelid
                    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = %s AND c.relname = %s AND a.attname = %s
                      AND a.attnum > 0 AND NOT a.attisdropped
                )
            """, ("epoleodomia", "natura_2000", "is_deleted"), fetch_one=True)
            if row is None or len(row) != 1 or type(row[0]) is not bool:
                raise RuntimeError("Could not determine Natura tracking-column availability")
            self._natura_tracking = row[0]
        return "NOT COALESCE(n.is_deleted, false)" if self._natura_tracking else "TRUE"

    def get_parcel_rights(self, kaek: str) -> dict:
        """
        Δουλείες (ΕΑΣ) and αποκλειστικές χρήσεις (ΑΧ) registered on a parcel.
        Source: operating cadastre overlay tables (keyed by parent kaek).
        """
        out = {"apokleistikes": [], "douleies": []}
        apok_sql = """
        SELECT vp_num, ROUND(COALESCE(area, ST_Area(geom))::numeric, 1)
        FROM sp_geodata.kaek_apokleistikes_operating
        WHERE kaek = %s ORDER BY vp_num
        """
        for r in (self.query(apok_sql, (kaek,)) or []):
            out["apokleistikes"].append({"num": r[0], "area_m2": float(r[1])})
        doul_sql = """
        SELECT right_sn, ROUND(COALESCE(area, ST_Area(geom))::numeric, 1)
        FROM sp_geodata.kaek_douleies_operating
        WHERE kaek = %s ORDER BY right_sn
        """
        for r in (self.query(doul_sql, (kaek,)) or []):
            out["douleies"].append({"num": r[0], "area_m2": float(r[1])})
        return out

    def get_water_points(self, x: float = None, y: float = None,
                              ref_geom: str = None, ref_args: tuple = None,
                              max_distance: float = 500) -> dict:
        """
        ΕΜΣΥ σημεία υδροληψίας (γεωτρήσεις/πηγάδια/πηγές) relative to a point/parcel.
        Source: sp_geodata.ydrolipsies_emsy, filled by sync_ydrolipsies.py from the
        UNOFFICIAL ΥΠΕΝ viewer service. If the table is missing or the query fails,
        returns available=False and the report silently skips the section.
        """
        if ref_geom is None:
            ref_geom, ref_args = POINT_REF, (x, y)
        result = {"available": False, "inside": [], "nearest": None}
        if not self.water_available:
            return result
        inside_sql = f"""
        SELECT eidos_sy, kathestws_xrhshs, kwdikos_emsy
        FROM sp_geodata.ydrolipsies_emsy
        WHERE ST_DWithin(geom, {ref_geom}, 0.5)
        ORDER BY kwdikos_emsy
        """
        near_sql = f"""
        SELECT eidos_sy, kathestws_xrhshs, kwdikos_emsy,
               ROUND(ST_Distance(geom, {ref_geom})::numeric, 1)
        FROM sp_geodata.ydrolipsies_emsy
        WHERE ST_DWithin(geom, {ref_geom}, %s)
        ORDER BY ST_Distance(geom, {ref_geom})
        LIMIT 1
        """
        try:
            with self.optional_scope():
                inside = self.query(inside_sql, (*ref_args,)) or []
                near = self.query(
                    near_sql, (*ref_args, *ref_args, max_distance, *ref_args),
                    fetch_one=True)
        except Exception:
            return result  # πίνακας δεν υπάρχει ακόμα — τρέξε sync_ydrolipsies.py

        result["available"] = True
        for r in inside:
            result["inside"].append({"eidos": r[0], "status": r[1], "emsy": r[2]})
        if near:
            result["nearest"] = {"eidos": near[0], "status": near[1],
                                 "emsy": near[2], "distance_m": float(near[3])}
        return result

    def get_regulations(self, x: float, y: float) -> dict:
        """Get comprehensive building regulations data for the OROITABLE command."""

        data = {
            "found": False,
            "ot_num": None,                  # Οικοδομικό Τετράγωνο
            "diatagmata_entaxis": [],      # FEKs for Ένταξης-Ρυμοτομίας
            "diatagmata_oron": [],          # FEKs for Όρων Δόμησης
            "xriseis": "Γενική Κατοικία",   # Hardcoded
            "tomeis": [],                    # All sectors with their regulations
            "egkriseis": [],                 # Approvals required (Αρχαιολογία, etc.)
            "loipa": [],                     # Λοιπά remarks from DB
            "loipoi_periorismoi": "ΦΕΚ 740Δ'/1981, ΓΟΚ 85/2000, ΝΟΚ 2012",  # Hardcoded
            "kata_parekklisi": None,         # Exception rules
            "plimmyra": "Η δόμηση επιτρέπεται σε απόσταση 10μ. από τις γραμμές πλημμύρας (Ν.4258/2014 αρθ.9 παρ.4Α — εκκρεμεί ΦΕΚ οριοθέτησης)",  # Hardcoded
        }

        # 0. Get OT number from building_blocks
        ot_sql = """
        SELECT ot_num
        FROM epoleodomia.building_blocks
        WHERE NOT COALESCE(is_deleted, false)
          AND ST_Contains(geom, ST_SetSRID(ST_Point(%s, %s), 2100))
        LIMIT 1
        """
        ot_result = self.query(ot_sql, (x, y), fetch_one=True)
        if ot_result and ot_result[0]:
            data["ot_num"] = ot_result[0]
            data["found"] = True

        # 1. Get ΔΙΑΤΑΓΜΑΤΑ Ένταξης-Ρυμοτομίας from approved_plan_boundaries
        # These are the FEKs for planning/zoning approvals (ρυμοτομικά διατάγματα)
        entaxis_sql = """
        SELECT DISTINCT fek, apof_eidos, title, publ_date
        FROM epoleodomia.approved_plan_boundaries
        WHERE NOT COALESCE(is_deleted, false)
          AND ST_Contains(geom, ST_SetSRID(ST_Point(%s, %s), 2100))
        ORDER BY publ_date
        """
        entaxis_result = self.query(entaxis_sql, (x, y), fetch_one=False)
        if entaxis_result:
            # Format: "ΦΕΚ xxx (Π.Δ./Υ.Α./κλπ)"
            fek_list = []
            for r in entaxis_result:
                if r[0]:  # fek exists
                    fek = r[0]
                    apof_eidos = r[1] if r[1] else ""
                    # Shorten apof_eidos for display
                    if "ΠΡΟΕΔΡΙΚΟ ΔΙΑΤΑΓΜΑ" in apof_eidos:
                        apof_short = "Π.Δ."
                    elif "ΥΠΟΥΡΓΙΚΗ ΑΠΟΦΑΣΗ" in apof_eidos:
                        apof_short = "Υ.Α."
                    elif "ΑΠΟΦΑΣΗ ΝΟΜΑΡΧΗ" in apof_eidos:
                        apof_short = "Απ.Νομ."
                    elif "ΑΠΟΦΑΣΗ ΓΕΝΙΚΟΥ ΓΡΑΜΜΑΤΕΑ" in apof_eidos:
                        apof_short = "Απ.Γ.Γ."
                    else:
                        apof_short = ""

                    if apof_short:
                        fek_list.append(f"{apof_short} ΦΕΚ {fek}")
                    else:
                        fek_list.append(f"ΦΕΚ {fek}")
            data["diatagmata_entaxis"] = fek_list
            data["found"] = True

        # 2. Get ΔΙΑΤΑΓΜΑΤΑ Όρων Δόμησης from all building_regs_* tables
        oron_sql = """
        SELECT DISTINCT fek FROM (
            SELECT fek FROM epoleodomia.building_regs_height
            WHERE NOT COALESCE(is_deleted, false) AND ST_Contains(geom, ST_SetSRID(ST_Point(%s, %s), 2100))
            UNION
            SELECT fek FROM epoleodomia.building_regs_coverage
            WHERE NOT COALESCE(is_deleted, false) AND ST_Contains(geom, ST_SetSRID(ST_Point(%s, %s), 2100))
            UNION
            SELECT fek FROM epoleodomia.building_regs_coefficient
            WHERE NOT COALESCE(is_deleted, false) AND ST_Contains(geom, ST_SetSRID(ST_Point(%s, %s), 2100))
            UNION
            SELECT fek FROM epoleodomia.building_regs_lot
            WHERE NOT COALESCE(is_deleted, false) AND ST_Contains(geom, ST_SetSRID(ST_Point(%s, %s), 2100))
            UNION
            SELECT fek FROM epoleodomia.building_regs_system
            WHERE NOT COALESCE(is_deleted, false) AND ST_Contains(geom, ST_SetSRID(ST_Point(%s, %s), 2100))
        ) AS all_feks
        ORDER BY fek
        """
        oron_result = self.query(oron_sql, (x, y) * 5, fetch_one=False)
        if oron_result:
            data["diatagmata_oron"] = [r[0] for r in oron_result if r[0]]
            data["found"] = True

        # 3. Get ΤΟΜΕΑΣ data - query each table separately at the point
        # Coefficient (has sd_tomeas)
        coef_sql = """
        SELECT DISTINCT sd_tomeas, sd_timh, sd_klimakotos, sd_comment, fek
        FROM epoleodomia.building_regs_coefficient
        WHERE NOT COALESCE(is_deleted, false)
          AND ST_Contains(geom, ST_SetSRID(ST_Point(%s, %s), 2100))
        """
        coef_result = self.query(coef_sql, (x, y), fetch_one=True)

        # Height
        height_sql = """
        SELECT DISTINCT max_height_m, num_orofon, oror_max_height_comment, fek
        FROM epoleodomia.building_regs_height
        WHERE NOT COALESCE(is_deleted, false)
          AND ST_Contains(geom, ST_SetSRID(ST_Point(%s, %s), 2100))
        """
        height_result = self.query(height_sql, (x, y), fetch_one=True)

        # Coverage
        coverage_sql = """
        SELECT DISTINCT synt_kalypsis, remarks, fek
        FROM epoleodomia.building_regs_coverage
        WHERE NOT COALESCE(is_deleted, false)
          AND ST_Contains(geom, ST_SetSRID(ST_Point(%s, %s), 2100))
        """
        coverage_result = self.query(coverage_sql, (x, y), fetch_one=True)

        # Lot (ΚΑΤΑ ΚΑΝΟΝΑ only)
        lot_sql = """
        SELECT DISTINCT elax_embado_m2, elax_prosop_m, fek
        FROM epoleodomia.building_regs_lot
        WHERE NOT COALESCE(is_deleted, false)
          AND oros_type = 'ΚΑΤΑ ΚΑΝΟΝΑ'
          AND ST_Contains(geom, ST_SetSRID(ST_Point(%s, %s), 2100))
        """
        lot_result = self.query(lot_sql, (x, y), fetch_one=True)

        # System
        system_sql = """
        SELECT DISTINCT oik_systima, fek
        FROM epoleodomia.building_regs_system
        WHERE NOT COALESCE(is_deleted, false)
          AND ST_Contains(geom, ST_SetSRID(ST_Point(%s, %s), 2100))
        """
        system_result = self.query(system_sql, (x, y), fetch_one=True)

        # Build single tomeas from results
        if coef_result or height_result or coverage_result:
            tomeas = {
                "name": coef_result[0] if coef_result and coef_result[0] else "ΚΑΤΑ ΚΑΝΟΝΑ",
                "sd": coef_result[1] if coef_result else None,
                "sd_klimakotos": coef_result[2] if coef_result else None,
                "sd_comment": coef_result[3] if coef_result else None,
                "sd_fek": coef_result[4] if coef_result else None,
                "max_height_m": height_result[0] if height_result else None,
                "num_orofon": height_result[1] if height_result else None,
                "height_comment": height_result[2] if height_result else None,
                "height_fek": height_result[3] if height_result else None,
                "coverage_pct": coverage_result[0] if coverage_result else None,
                "coverage_remarks": coverage_result[1] if coverage_result else None,
                "coverage_fek": coverage_result[2] if coverage_result else None,
                "elax_embado_m2": lot_result[0] if lot_result else None,
                "elax_prosop_m": lot_result[1] if lot_result else None,
                "lot_fek": lot_result[2] if lot_result else None,
                "oik_systima": system_result[0] if system_result else None,
                "system_fek": system_result[1] if system_result else None,
            }
            data["tomeis"].append(tomeas)
            data["found"] = True

        # 4. Get ΕΓΚΡΙΣΕΙΣ
        # Always add required approvals for Spetses (hardcoded)
        data["egkriseis"].append("Συμβούλιο Αρχιτεκτονικής")
        data["egkriseis"].append("Υπηρεσία Νεωτέρων Μνημείων")

        # Check sp_geodata archaeology tables for ΕΦΑ approval requirement
        archeo_zone_sql = """
        SELECT 1 FROM sp_geodata."Αρχαιολογία_Ζώνες_Προστασίας"
        WHERE NOT ST_IsEmpty(ST_BuildArea(geom))
          AND ST_Covers(
              ST_CollectionExtract(ST_MakeValid(ST_BuildArea(geom)), 3),
              ST_SetSRID(ST_Point(%s, %s), 2100)
          )
        LIMIT 1
        """
        archeo_mon_sql = """
        SELECT 1 FROM sp_geodata."Αρχαιλογία_Κυρηγμένα_Μνημεία"
        WHERE ST_DWithin(geom, ST_SetSRID(ST_Point(%s, %s), 2100), 100)
        LIMIT 1
        """
        try:
            with self.optional_scope():
                zone_hit = self.query(archeo_zone_sql, (x, y), fetch_one=True)
                mon_hit = self.query(archeo_mon_sql, (x, y), fetch_one=True)
            if (zone_hit or mon_hit) and "Αρχαιολογία (ΕΦΑ)" not in data["egkriseis"]:
                data["egkriseis"].append("Αρχαιολογία (ΕΦΑ)")
        except Exception:
            pass  # archaeology tables unavailable — skip

        # 5. Collect ΛΟΙΠΑ from comments (avoid duplicates)
        loipa_set = set()
        for tomeas in data["tomeis"]:
            if tomeas.get("height_comment"):
                loipa_set.add(tomeas["height_comment"])
            if tomeas.get("sd_comment"):
                loipa_set.add(tomeas["sd_comment"])
            if tomeas.get("coverage_remarks"):
                loipa_set.add(tomeas["coverage_remarks"])
        data["loipa"] = sorted(loipa_set)

        # 6. Get ΚΑΤΑ ΠΑΡΕΚΚΛΙΣΗ
        parek_sql = """
        SELECT remarks, date_pareklisis, fek
        FROM epoleodomia.building_regs_lot
        WHERE NOT COALESCE(is_deleted, false)
          AND oros_type = 'ΚΑΤΑ ΠΑΡΕΚΚΛΙΣΗ'
          AND ST_Contains(geom, ST_SetSRID(ST_Point(%s, %s), 2100))
        LIMIT 1
        """
        parek_result = self.query(parek_sql, (x, y), fetch_one=True)
        if parek_result:
            data["kata_parekklisi"] = {
                "remarks": parek_result[0],
                "date": parek_result[1],
                "fek": parek_result[2],
            }

        return data

    def resolve_parcel(self, x: float, y: float, radius: float = 50) -> dict:
        """
        Resolve the operating-cadastre parcel at a clicked point using the same logic
        as /kaek/operating: point-in-polygon first, else nearest parcel within `radius`
        metres. EK (special-use) parcels are excluded. Returns a dict with
        kaek/area_m2/perim_m/main_use/descr, or None if nothing is found.
        """
        ek_filter = _kaek_non_special_use_filter()
        main_sql = f"""
        SELECT kaek,
               ROUND(ST_Area(geom)::numeric, 2),
               ROUND(ST_Perimeter(geom)::numeric, 2),
               main_use,
               descr
        FROM sp_geodata.kaek_parcels_operating
        WHERE {ek_filter}
          AND ST_Contains(geom, ST_SetSRID(ST_Point(%s, %s), 2100))
        LIMIT 1
        """
        row = self.query(main_sql, (x, y), fetch_one=True)

        if not row:
            near_sql = f"""
            SELECT kaek,
                   ROUND(ST_Area(geom)::numeric, 2),
                   ROUND(ST_Perimeter(geom)::numeric, 2),
                   main_use,
                   descr
            FROM sp_geodata.kaek_parcels_operating
            WHERE {ek_filter}
              AND ST_DWithin(geom, ST_SetSRID(ST_Point(%s, %s), 2100), %s)
            ORDER BY geom <-> ST_SetSRID(ST_Point(%s, %s), 2100)
            LIMIT 1
            """
            row = self.query(near_sql, (x, y, radius, x, y), fetch_one=True)

        if not row:
            return None

        return {
            "kaek": row[0],
            "area_m2": row[1],
            "perim_m": row[2],
            "main_use": row[3] or "",
            "descr": row[4] or "",
        }

    def get_parcel_overlaps(self, kaek: str) -> dict:
        """
        Containment of a parcel for the report: percentage of the parcel area that
        overlaps each Natura 2000 zone, forest-map type, and archaeological protection
        zone. Boundary-only contact is not area overlap. Forest percentages union
        features within each type; total ratified coverage unions across all types.
        ST_MakeValid guards against GEOS topology errors during ST_Intersection.
        """
        parcel = "(SELECT ST_MakeValid(geom) AS geom FROM sp_geodata.kaek_parcels_operating WHERE kaek = %s)"
        out = {"natura": [], "forest": [], "forest_source": None, "archeo_zones": []}

        # ── Natura 2000 ──────────────────────────────────────────────────────────
        natura_sql = f"""
        SELECT n.sitecode, n.sitename, n.sitetype,
               ROUND((ST_Area(ST_Intersection(ST_MakeValid(n.geom), p.geom))
                      / NULLIF(ST_Area(p.geom), 0) * 100)::numeric, 1) AS pct
        FROM epoleodomia.natura_2000 n, {parcel} p
        WHERE {self._natura_active_filter()}
          AND n.geom && p.geom
          AND ST_Intersects(ST_MakeValid(n.geom), p.geom)
          AND ST_Area(ST_Intersection(ST_MakeValid(n.geom), p.geom)) > 0
        ORDER BY pct DESC
        """
        for r in (self.query(natura_sql, (kaek,)) or []):
            out["natura"].append({"code": r[0], "name": r[1], "type": r[2], "pct": r[3]})

        # ── Forest map: κυρωμένος first, fall back to ανάρτηση 2021 ───────────────
        def _forest_rows(table: str):
            # Return code, displayed pct, raw pct, raw total coverage. Thresholds
            # use raw values; all positive pieces contribute to total coverage.
            sql = f"""
            WITH clips AS (
                SELECT f.forest_type, ST_Area(p.geom) AS parcel_area,
                       ST_Intersection(ST_MakeValid(f.geom), p.geom) AS geom
                FROM {table} f, {parcel} p
                WHERE NOT COALESCE(f.is_deleted, false)
                  AND f.geom && p.geom
                  AND ST_Intersects(ST_MakeValid(f.geom), p.geom)
                  AND ST_Area(p.geom) > 0
            ), positive AS (
                SELECT * FROM clips WHERE ST_Area(geom) > 0
            ), coverage AS (
                SELECT ST_Area(ST_UnaryUnion(ST_Collect(geom)))
                       / NULLIF(MAX(parcel_area), 0) * 100 AS pct
                FROM positive
            ), by_type AS (
                SELECT forest_type,
                       ST_Area(ST_UnaryUnion(ST_Collect(geom)))
                       / NULLIF(MAX(parcel_area), 0) * 100 AS pct
                FROM positive GROUP BY forest_type
            )
            SELECT t.forest_type, ROUND(t.pct::numeric, 1), t.pct, c.pct
            FROM by_type t CROSS JOIN coverage c
            ORDER BY t.pct DESC, t.forest_type
            """
            return self.query(sql, (kaek,))

        # Μερική κύρωση: τμήματα με εκκρεμείς αντιρρήσεις ΛΕΙΠΟΥΝ από τον κυρωμένο
        # χάρτη. Αν ο κυρωμένος δεν καλύπτει (σχεδόν) όλο το γεωτεμάχιο, αναφέρουμε
        # ΚΑΙ την ανάρτηση 2021 — αλλιώς 0.3% slivers κρύβουν π.χ. 97% ΔΔ.
        kyr_rows = _forest_rows("epoleodomia.forest_maps") or []
        # Coverage is the union across all types, not the sum of overlapping rows
        # or rounded display percentages. Each source remains reported separately.
        kyr_pct = float(kyr_rows[0][3] or 0) if kyr_rows else 0.0
        out["forest_kyromenos_pct"] = round(kyr_pct, 1)

        def _append_forest(rows_, source):
            for r in rows_:
                if r[2] is None or float(r[2]) < 0.5:
                    continue  # boundary slivers — misaligned linework noise
                code = r[0] or ""
                short_label, full_desc, category = decode_forest_type(code)
                out["forest"].append({
                    "code": code, "label": short_label, "category": category,
                    "pct": r[1], "source": source,
                })

        _append_forest(kyr_rows, "κυρωμένος")
        if kyr_pct < 98.0:
            _append_forest(
                _forest_rows("epoleodomia.forest_maps_posted_attica_2021") or [],
                "ανάρτηση 2021")

        sources = {f["source"] for f in out["forest"]}
        out["forest_source"] = " + ".join(s for s in ("κυρωμένος", "ανάρτηση 2021") if s in sources) or None

        # ── Archaeological protection zones ──────────────────────────────────────
        archeo_sql = f"""
        WITH zones AS (
            SELECT
                site_name,
                ot_number,
                fek_refere,
                ST_CollectionExtract(ST_MakeValid(ST_BuildArea(geom)), 3) AS geom
            FROM sp_geodata."Αρχαιολογία_Ζώνες_Προστασίας"
            WHERE NOT ST_IsEmpty(ST_BuildArea(geom))
        )
        SELECT z.site_name, z.ot_number, z.fek_refere,
               ROUND((ST_Area(ST_Intersection(z.geom, p.geom))
                      / NULLIF(ST_Area(p.geom), 0) * 100)::numeric, 1) AS pct
        FROM zones z, {parcel} p
        WHERE ST_Intersects(z.geom, p.geom)
          AND ST_Area(ST_Intersection(z.geom, p.geom)) > 0
        ORDER BY pct DESC
        """
        for r in (self.query(archeo_sql, (kaek,)) or []):
            out["archeo_zones"].append({"name": r[0], "ot": r[1], "fek": r[2], "pct": r[3]})

        return out

    def get_archaeology(self, x: float = None, y: float = None, max_distance: float = 2000,
                              ref_geom: str = None, ref_args: tuple = None,
                              include_zone: bool = True) -> dict:
        """
        Archaeological information relative to a reference geometry (point or parcel).

        include_zone=False skips the protection-zone proximity check — used by the
        parcel report, which reports zone *overlap %* via _get_parcel_overlaps instead.
        """
        if ref_geom is None:
            ref_geom, ref_args = POINT_REF, (x, y)

        result = {
            "found": False,
            "in_protection_zone": False,
        }

        zone = None
        if include_zone:
            # Check if inside protection zone
            zone_sql = f"""
            SELECT
                site_name,
                ot_number as ot,
                fek_refere as fek,
                ST_Distance(
                    ST_CollectionExtract(ST_MakeValid(ST_BuildArea(geom)), 3),
                    {ref_geom}
                ) as distance
            FROM sp_geodata."Αρχαιολογία_Ζώνες_Προστασίας"
            WHERE NOT ST_IsEmpty(ST_BuildArea(geom))
            ORDER BY distance
            LIMIT 1
            """
            zone = self.query(zone_sql, (*ref_args,), fetch_one=True)

        # Get closest monument
        monument_sql = f"""
        SELECT
            site_name,
            ot_number as ot,
            fek_reference as fek,
            site_location,
            ST_Distance(geom, {ref_geom}) as distance
        FROM sp_geodata."Αρχαιλογία_Κυρηγμένα_Μνημεία"
        WHERE ST_DWithin(geom, {ref_geom}, %s)
        ORDER BY geom <-> {ref_geom}
        LIMIT 1
        """
        monument = self.query(monument_sql, (*ref_args, *ref_args, max_distance, *ref_args), fetch_one=True)

        # Check protection zone (inside if distance < 1m)
        if zone and zone[3] is not None and zone[3] < 1:
            result["in_protection_zone"] = True
            result["zone_name"] = zone[0]
            result["zone_ot"] = zone[1]
            result["zone_fek"] = zone[2]

        if monument:
            result["found"] = True
            result["name"] = monument[0]
            result["ot"] = monument[1]
            result["fek"] = monument[2]
            result["location"] = monument[3]
            result["distance_m"] = round(monument[4], 2) if monument[4] is not None else None

        return result

    def get_church(self, x: float = None, y: float = None, max_distance: float = 500,
                         ref_geom: str = None, ref_args: tuple = None) -> dict:
        """Closest church to a reference geometry (clicked point by default, or a parcel)."""
        if ref_geom is None:
            ref_geom, ref_args = POINT_REF, (x, y)
        sql = f"""
        SELECT
            name,
            type,
            year_built,
            century,
            status,
            address,
            ST_Distance(geom, {ref_geom}) as distance,
            ST_X(ST_Centroid(geom)) as cx,
            ST_Y(ST_Centroid(geom)) as cy
        FROM sp_geodata."Εκκλησίες_πολυγωνα"
        WHERE ST_DWithin(geom, {ref_geom}, %s)
        ORDER BY geom <-> {ref_geom}
        LIMIT 1
        """

        result = self.query(sql, (*ref_args, *ref_args, max_distance, *ref_args), fetch_one=True)

        if not result:
            return {"found": False, "message": "No church found within search distance"}

        return {
            "found": True,
            "name": result[0],
            "type": result[1],
            "year_built": result[2],
            "century": result[3],
            "status": result[4],
            "address": result[5],
            "distance_m": round(result[6], 2) if result[6] is not None else None,
            "centroid_x": result[7],
            "centroid_y": result[8]
        }

    def get_shoreline(self, x: float = None, y: float = None, max_distance: float = 5000,
                            ref_geom: str = None, ref_args: tuple = None) -> dict:
        """Return closest segment per line type within max_distance of a reference geometry."""
        if ref_geom is None:
            ref_geom, ref_args = POINT_REF, (x, y)
        sql = f"""
        SELECT DISTINCT ON (info)
            info,
            fek,
            location,
            ST_Distance(geom, {ref_geom}) AS distance
        FROM sp_geodata."Αιγιαλός_Παραλία"
        WHERE ST_DWithin(geom, {ref_geom}, %s)
        ORDER BY info, distance
        """
        results = self.query(sql, (*ref_args, *ref_args, max_distance), fetch_one=False)

        if not results:
            return {"found": False, "message": "No shoreline found within search distance"}

        lines = []
        for row in results:
            lines.append({
                "info":       row[0],
                "fek":        row[1],
                "location":   row[2],
                "distance_m": round(row[3], 1) if row[3] is not None else None,
            })

        return {"found": True, "lines": lines}

    def is_inside_city_plan(self, x: float, y: float) -> bool:
        """Include the plan boundary so it cannot silently select outside-plan rules."""
        sql = """
        SELECT EXISTS(
            SELECT 1 FROM sp_geodata.orio_sxediou_polews
            WHERE ST_Covers(geom, ST_SetSRID(ST_Point(%s, %s), 2100))
        )
        """
        result = self.query(sql, (x, y), fetch_one=True)
        return result[0] if result else False

    def get_streams(self, x: float = None, y: float = None, max_distance: float = 500,
                          ref_geom: str = None, ref_args: tuple = None) -> dict:
        """
        Stream distances at a reference geometry (clicked point by default, or a parcel).

        Always returns closest segment per layer type from Ρεματα_Οικισμού_υπό_Οριοθέτηση
        (all 3 line types: Πλημμύρας, Οριοθέτησης με έργο, Οριοθέτησης χωρίς έργο).

        ΕΚΤΟΣ σχεδίου also returns distance to Ρεματα Νησιου ΤΠΣ.
        ΕΝΤΟΣ σχεδίου also checks Ρεματα εντος οικισμου εκτος των 6.

        The εντός/εκτός σχεδίου determination always uses the clicked point (x, y),
        matching the building-regulations basis, even when distances use a parcel.
        """
        if ref_geom is None:
            ref_geom, ref_args = POINT_REF, (x, y)
        inside_plan = self.is_inside_city_plan(x, y)
        result = {
            "inside_city_plan": inside_plan,
            "oikismos_lines": [],   # list of {layer, label, distance_m}
            "tps_found": False,
            "other_found": False,
        }

        # ── All 3 layer types from Ρεματα_Οικισμού — always ─────────────────────
        oik_sql = f"""
        SELECT DISTINCT ON (layer)
            layer,
            ST_Distance(geom, {ref_geom}) AS distance
        FROM sp_geodata."Ρεματα_Οικισμού_υπό_Οριοθέτηση"
        WHERE ST_DWithin(geom, {ref_geom}, %s)
        ORDER BY layer, distance
        """
        oik_rows = self.query(oik_sql, (*ref_args, *ref_args, max_distance), fetch_one=False)
        if oik_rows:
            for row in oik_rows:
                result["oikismos_lines"].append({
                    "layer":      row[0],
                    "label":      STREAM_LABELS.get(row[0], row[0]),
                    "distance_m": round(row[1], 1) if row[1] is not None else None,
                })

        # ── ΤΠΣ streams — εκτός σχεδίου only ────────────────────────────────────
        if not inside_plan:
            tps_sql = f"""
            SELECT ST_Distance(geom, {ref_geom}) AS distance
            FROM sp_geodata."Ρεματα Νησιου ΤΠΣ (εκτος των 6)"
            WHERE ST_DWithin(geom, {ref_geom}, %s)
            ORDER BY geom <-> {ref_geom}
            LIMIT 1
            """
            tps = self.query(tps_sql, (*ref_args, *ref_args, max_distance, *ref_args), fetch_one=True)
            if tps:
                result["tps_found"] = True
                result["tps_distance_m"] = round(tps[0], 1) if tps[0] is not None else None

        # ── Other settlement streams — εντός σχεδίου only ────────────────────────
        if inside_plan:
            other_sql = f"""
            SELECT ST_Distance(geom, {ref_geom}) AS distance
            FROM sp_geodata."Ρεματα εντος οικισμου εκτος των 6"
            WHERE ST_DWithin(geom, {ref_geom}, %s)
            ORDER BY geom <-> {ref_geom}
            LIMIT 1
            """
            other = self.query(other_sql, (*ref_args, *ref_args, max_distance, *ref_args), fetch_one=True)
            if other:
                result["other_found"] = True
                result["other_distance_m"] = round(other[0], 1) if other[0] is not None else None

        return result

    def get_natura_forest(self, x: float, y: float) -> dict:
        """
        Check Natura 2000, forest maps, and cadastre land use at a point.
        Forest source priority: forest_maps (κυρωμένος) → forest_maps_posted_attica_2021 (ανάρτηση).
        Also returns cadastre main_use if it indicates woodland.
        """
        result = {
            "in_natura": False,
            "in_forest": False,
            "forest_source": None,       # "κυρωμένος" | "ανάρτηση 2021"
            "kaek_forest_use": None,     # descr from kaek if woodland code
            "kaek_forest_code": None,
        }

        # ── Natura 2000 ──────────────────────────────────────────────────────────
        natura_sql = f"""
        SELECT n.sitecode, n.sitename, n.sitetype, n.area_ha
        FROM epoleodomia.natura_2000 n
        WHERE {self._natura_active_filter()}
          AND ST_Contains(n.geom, ST_SetSRID(ST_Point(%s, %s), 2100))
        LIMIT 1
        """
        natura = self.query(natura_sql, (x, y), fetch_one=True)
        if natura:
            result["in_natura"] = True
            result["natura_code"] = natura[0]
            result["natura_name"] = natura[1]
            result["natura_type"] = natura[2]

        # ── Κυρωμένος Δασικός Χάρτης ─────────────────────────────────────────────
        forest_sql = """
        SELECT region_name, forest_type, status
        FROM epoleodomia.forest_maps
        WHERE NOT COALESCE(is_deleted, false)
          AND ST_Contains(geom, ST_SetSRID(ST_Point(%s, %s), 2100))
        LIMIT 1
        """
        forest = self.query(forest_sql, (x, y), fetch_one=True)

        if forest:
            code = forest[1] or ""
            short_label, full_desc, category = decode_forest_type(code)
            result["in_forest"] = True
            result["forest_source"] = "κυρωμένος"
            result["forest_region"] = forest[0]
            result["forest_type"] = code
            result["forest_type_label"] = short_label
            result["forest_type_desc"] = full_desc
            result["forest_category"] = category
        else:
            # ── Δασική Ανάρτηση 2021 (Αττική) — fallback ─────────────────────────
            posted_sql = """
            SELECT forest_type
            FROM epoleodomia.forest_maps_posted_attica_2021
            WHERE NOT COALESCE(is_deleted, false)
              AND ST_Contains(geom, ST_SetSRID(ST_Point(%s, %s), 2100))
            LIMIT 1
            """
            posted = self.query(posted_sql, (x, y), fetch_one=True)
            if posted:
                code = posted[0] or ""
                short_label, full_desc, category = decode_forest_type(code)
                result["in_forest"] = True
                result["forest_source"] = "ανάρτηση 2021"
                result["forest_type"] = code
                result["forest_type_label"] = short_label
                result["forest_type_desc"] = full_desc
                result["forest_category"] = category

        # ── Κτηματολόγιο — χρήση γης (πάντα, αν δασώδης) ────────────────────────
        kaek_sql = """
        SELECT main_use, descr
        FROM sp_geodata.kaek_parcels_operating
        WHERE ST_Contains(geom, ST_SetSRID(ST_Point(%s, %s), 2100))
        LIMIT 1
        """
        kaek = self.query(kaek_sql, (x, y), fetch_one=True)
        if kaek and kaek[0] in _KAEK_FOREST_USE_CODES:
            result["kaek_forest_code"] = kaek[0]
            result["kaek_forest_use"] = kaek[1]

        return result

    def point_report(self, x: float, y: float) -> str:
        """
        Full planning report: building regs + aigialos + archeo + church + natura + remata.
        Same TYPE|col1|col2 format as /oroitable/rows — for use with EREPORT LISP command.
        """
        oroi = self.get_regulations(x, y)
        outside_plan = not oroi.get("found") and not self.is_inside_city_plan(x, y)
        if not oroi.get("found") and not outside_plan:
            return MISSING_REGULATIONS

        shore = self.get_shoreline(x, y)
        archeo = self.get_archaeology(x, y)
        church = self.get_church(x, y, max_distance=1000)
        natura = self.get_natura_forest(x, y)
        remata = self.get_streams(x, y)
        ydro = self.get_water_points(x=x, y=y)
        return build_point_report(
            oroi=oroi, outside_plan=outside_plan, shore=shore, archeo=archeo,
            church=church, natura=natura, remata=remata, ydro=ydro)

    def parcel_report(self, x: float, y: float) -> str:
        """
        Parcel-based planning report for the EREPORT command.

        Resolves the operating-cadastre parcel at the clicked point, then measures
        every distance from the parcel polygon (not the click point) and reports
        Natura / forest / archaeological zones as % of parcel overlap. Building
        regulations are still computed at the clicked point. Same TYPE|col1|col2
        format as /report/rows.
        """
        parcel = self.resolve_parcel(x, y)
        if not parcel:
            return MISSING_PARCEL

        kaek = parcel["kaek"]
        ref_geom, ref_args = PARCEL_REF, (kaek,)
        shore = self.get_shoreline(ref_geom=ref_geom, ref_args=ref_args)
        oroi = self.get_regulations(x, y)
        outside_plan = not oroi.get("found") and not self.is_inside_city_plan(x, y)
        if not oroi.get("found") and not outside_plan:
            return MISSING_REGULATIONS

        rights = self.get_parcel_rights(kaek)
        overlaps = self.get_parcel_overlaps(kaek)
        archeo = self.get_archaeology(ref_geom=ref_geom, ref_args=ref_args, include_zone=False)
        church = self.get_church(ref_geom=ref_geom, ref_args=ref_args, max_distance=1000)
        remata = self.get_streams(x, y, ref_geom=ref_geom, ref_args=ref_args)
        ydro = self.get_water_points(ref_geom=ref_geom, ref_args=ref_args)
        return build_parcel_report(
            parcel=parcel, oroi=oroi, outside_plan=outside_plan, shore=shore,
            rights=rights, overlaps=overlaps, archeo=archeo, church=church,
            remata=remata, ydro=ydro)
