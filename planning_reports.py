"""Planning-report construction from loaded GIS data.

This module has no HTTP, database or configuration dependencies. Builders accept
provider dictionaries, leave them unchanged, and return the existing AutoCAD
TYPE|col1|col2 text with Windows-1253 character replacement. Spatial queries and
parcel/click selection stay in planning_data.py; the existing planning assumptions
and source-status wording are preserved here.
"""

MISSING_PARCEL = "ERROR|Δεν βρέθηκε λειτουργούν γεωτεμάχιο στο σημείο (ή κλικ σε ΕΚ)"
MISSING_REGULATIONS = "ERROR|No regulations found at this location"

SHORELINE_LABELS = {
    "Γραμμή Αιγιαλού":       "Γραμμή Αιγιαλού",
    "Γραμμή Αιγιαλού_ΠΟΑ":  "Γραμμή Αιγιαλού (ΠΟΑ)",
    "Γραμμή Παραλίας":        "Γραμμή Παραλίας",
    "Γραμμή Παραλίας_ΠΟΑ":  "Γραμμή Παραλίας (ΠΟΑ)",
    "Γραμμή Παλαιού Αιγιαλού": "Γραμμή Παλαιού Αιγιαλού",
}


FOREST_USE_CODES = {"1110", "1111", "1112", "1320", "1330"}


def water_point_label(w: dict) -> str:
    lbl = w.get("eidos") or "Σημείο υδροληψίας"
    if w.get("status"):
        lbl += f" ({w['status']})"
    if w.get("emsy"):
        lbl += f" — ΕΜΣΥ {w['emsy']}"
    return lbl


def _fmt_parcel_dist(d, kind: str = "line") -> str:
    """
    Render a parcel-to-feature distance for the parcel report. A distance of 0
    means the feature crosses or sits inside the parcel; show that as 'διέρχεται'
    for linear features (shoreline, streams) and 'εντός' for point features
    (monuments) instead of a bare '0 μ.'.
    """
    if d is None:
        return "—"
    if d < 0.5:
        return "διέρχεται" if kind == "line" else "εντός"
    return f"{d} μ."


def _shore_crossing_list(shore: dict) -> list:
    """Shoreline/beach/old-shoreline lines that cross the parcel (< 0.5 μ.)."""
    by_type = {r["info"]: r for r in shore.get("lines", [])}
    crossing = []
    for key in ("Γραμμή Αιγιαλού", "Γραμμή Αιγιαλού_ΠΟΑ",
                "Γραμμή Παραλίας", "Γραμμή Παραλίας_ΠΟΑ",
                "Γραμμή Παλαιού Αιγιαλού"):
        r = by_type.get(key)
        if r and r.get("distance_m") is not None and r["distance_m"] < 0.5:
            label = SHORELINE_LABELS.get(key, key)
            fek = f" (ΦΕΚ {r['fek']})" if r.get("fek") else ""
            crossing.append(f"{label}{fek}")
    return crossing


def _build_parcel_shoreline_rows(shore: dict) -> list:
    """
    Summarise shoreline constraints for parcel reports. The legal check is
    whether any shoreline/beach/old-shoreline line crosses the parcel; distance
    is reported only for the nearest current shoreline, established or POA.
    """
    rows = ["HEADER|ΑΙΓΙΑΛΟΣ / ΠΑΡΑΛΙΑ|"]
    by_type = {r["info"]: r for r in shore.get("lines", [])}

    crossing = _shore_crossing_list(shore)
    if crossing:
        rows.append(f"ROW|Διέλευση γραμμής|ΝΑΙ - {', '.join(crossing)}")
    else:
        rows.append("ROW|Διέλευση γραμμής|ΟΧΙ")

    aigialos_types = ["Γραμμή Αιγιαλού", "Γραμμή Αιγιαλού_ΠΟΑ"]
    candidates = [by_type[key] for key in aigialos_types if key in by_type]
    if candidates:
        nearest = min(
            candidates,
            key=lambda r: (
                float("inf") if r.get("distance_m") is None else r["distance_m"],
                1 if str(r.get("info", "")).endswith("_ΠΟΑ") else 0,
            ),
        )
        dist = nearest.get("distance_m")
        value = "-" if dist is None else f"{dist} μ."
        source = "ΠΟΑ" if str(nearest.get("info", "")).endswith("_ΠΟΑ") else "καθορισμένος"
        details = [source]
        if nearest.get("fek"):
            details.append(f"ΦΕΚ {nearest['fek']}")
        rows.append(f"ROW|Απόσταση από Αιγιαλό|{value} ({', '.join(details)})")

    return rows


def _build_regs_rows(oroi: dict) -> list:
    """
    Format the ΟΡΟΙ ΔΟΜΗΣΗΣ (building-regulations) section into report rows.
    Shared by the point report (/report/rows) and the parcel report
    (/report/parcel); regulations are always computed at the clicked point.
    """
    rows = []
    ot_label = f"O.T. {oroi['ot_num']}" if oroi.get("ot_num") else "SPETSES"
    rows.append(f"TITLE|ΟΡOI ΔΟΜΗΣΗΣ|{ot_label}")
    rows.append(f"ROW|Χρήσεις γης|{oroi['xriseis']}")

    if oroi["diatagmata_entaxis"]:
        rows.append("HEADER|Διατάγματα Εντάξεως - Ρυμοτομίας|")
        for fek in oroi["diatagmata_entaxis"]:
            rows.append(f"ROW||{fek}")

    if oroi["diatagmata_oron"]:
        rows.append("HEADER|Διατάγματα Όρων Δόμησης|")
        for fek in oroi["diatagmata_oron"]:
            rows.append(f"ROW||{fek}")

    for tomeas in oroi["tomeis"]:
        name = tomeas.get("name", "ΚΑΤΑ ΚΑΝΟΝΑ")
        rows.append(f"HEADER|Κατά Κανόνα  —  Τομέας {name}|")
        if tomeas.get("elax_embado_m2"):
            rows.append(f"ROW|Αρτιότητα|{tomeas['elax_embado_m2']} τ.μ.")
        if tomeas.get("elax_prosop_m"):
            rows.append(f"ROW|Πρόσοψη|{tomeas['elax_prosop_m']} μ.")
        if tomeas.get("coverage_pct"):
            cov = f"{tomeas['coverage_pct']}%"
            if tomeas.get("oik_systima"):
                cov += f"  —  Σύστημα {tomeas['oik_systima']}"
            rows.append(f"ROW|Κάλυψη|{cov}")
        if tomeas.get("sd"):
            sd_val = str(tomeas["sd"])
            if tomeas.get("sd_klimakotos"):
                sd_val += f"  (κλιμακωτός: {tomeas['sd_klimakotos']})"
            rows.append(f"ROW|Συντ. Δόμησης|{sd_val}")
        if tomeas.get("max_height_m"):
            h_val = f"{tomeas['max_height_m']} μ."
            if tomeas.get("num_orofon"):
                h_val += f"  ({tomeas['num_orofon']} όροφοι)"
            rows.append(f"ROW|Μέγ. Ύψος|{h_val}")

    if oroi.get("kata_parekklisi"):
        rows.append("HEADER|Κατά Παρέκκλιση|")
        parek = oroi["kata_parekklisi"]
        if parek.get("date"):
            rows.append(f"ROW|Προ|προ {parek['date']}")
        if parek.get("remarks"):
            rows.append(f"MERGED|{parek['remarks']}|")
        if parek.get("fek"):
            rows.append(f"ROW|ΦΕΚ|{parek['fek']}")

    if oroi["egkriseis"]:
        rows.append("HEADER|Απαιτούμενες Εγκρίσεις|")
        rows.append(f"ROW||{', '.join(oroi['egkriseis'])}")

    loipoi_rows = []
    if oroi.get("loipoi_periorismoi"):
        loipoi_rows.append(f"MERGED|{oroi['loipoi_periorismoi']}|")
    if oroi.get("loipa"):
        for item in oroi["loipa"]:
            if item:
                loipoi_rows.append(f"MERGED|{item}|")
    if oroi.get("plimmyra"):
        loipoi_rows.append(f"MERGED|{oroi['plimmyra']}|")
    if loipoi_rows:
        rows.append("HEADER|Λοιποί Περιορισμοί|")
        rows.extend(loipoi_rows)

    return rows


def _ektos_max_domisi(area_m2: float) -> float:
    """
    Επιτρεπόμενη δόμηση κατοικίας εκτός σχεδίου (Ν.4759/2020, άρθρο 33):
    4.000–8.000: 186 + 0.018×(Ε−4.000) | >8.000: 258 + 0.009×(Ε−8.000), μέγ. 360.
    """
    if area_m2 < 4000:
        return 0.0
    if area_m2 <= 8000:
        return round(186 + 0.018 * (area_m2 - 4000), 1)
    return round(min(258 + 0.009 * (area_m2 - 8000), 360.0), 1)


def _build_ektos_sxediou_rows(parcel_area_m2: float = None,
                              extra_approvals: list = None) -> list:
    """
    ΟΡΟΙ ΔΟΜΗΣΗΣ — ΕΚΤΟΣ ΣΧΕΔΙΟΥ/ΟΡΙΩΝ ΟΙΚΙΣΜΟΥ (static block).
    Πηγές: Π.Δ. 24.05.1985 (ΦΕΚ Δ' 270), Ν.4759/2020 (ΦΕΚ Α' 245),
    ΖΟΕ Αττικής Π.Δ. 22.06.1983 (ΦΕΚ Δ' 284), Ν.5261/2025 (μεταβατικές).
    If parcel_area_m2 is given, computes αρτιότητα and επιτρεπόμενη δόμηση.
    """
    rows = []
    rows.append("TITLE|ΟΡOI ΔΟΜΗΣΗΣ|ΕΚΤΟΣ ΣΧΕΔΙΟΥ")
    rows.append("ROW|Καθεστώς|Π.Δ. 24.05.85 (ΦΕΚ 270Δ') + Ν.4759/2020")

    rows.append("HEADER|Κατά Κανόνα (χρήση: κατοικία)|")
    rows.append("ROW|Αρτιότητα|4.000 τ.μ.")
    rows.append("ROW|Πρόσωπο|σε κοινόχρηστη οδό (25 μ. για γήπεδα μετά 9.12.20)")
    rows.append("ROW|Σε εθν./επαρχ. οδό|πρόσωπο 45 μ. — βάθος 50 μ.")
    rows.append("ROW|Κάλυψη|10%")
    rows.append("ROW|Μέγ. Ύψος|7,50 μ. (2 όροφοι) +1,20 μ. στέγη")
    rows.append("ROW|Αποστάσεις ορίων|15 μ.")
    rows.append("ROW|Από ρέμα / δάσος|10 μ. / 10 μ.")
    rows.append("ROW|Κατάτμηση (ΖΟΕ Αττ.)|20.000 τ.μ. (Π.Δ. 22.06.83, ΦΕΚ 284Δ')")

    rows.append("HEADER|Επιτρεπόμενη Δόμηση (κατοικία)|")
    rows.append("ROW|4.000–8.000 τ.μ.|186 + 0,018×(Ε−4.000) τ.μ.")
    rows.append("ROW|άνω των 8.000 τ.μ.|258 + 0,009×(Ε−8.000) τ.μ. — μέγ. 360")

    if parcel_area_m2:
        if parcel_area_m2 >= 4000:
            dom = _ektos_max_domisi(parcel_area_m2)
            rows.append(f"ROW|Γεωτεμάχιο ({parcel_area_m2:.0f} τ.μ.)|ΑΡΤΙΟ (εμβαδόν) — έως {dom} τ.μ.")
        else:
            rows.append(f"ROW|Γεωτεμάχιο ({parcel_area_m2:.0f} τ.μ.)|ΜΗ ΑΡΤΙΟ κατά κανόνα (< 4.000 τ.μ.)")

    rows.append("HEADER|Κατά Παρέκκλιση|")
    rows.append("MERGED|Παρεκκλίσεις 750/1.200/2.000 τ.μ. καταργήθηκαν (Ν.4759/2020). "
                "Τελευταία μεταβατική προθεσμία 30.06.2026 (Ν.5261/2025) — έχει παρέλθει. "
                "Αναμένεται νέο πλαίσιο (Π.Δ. αναγνώρισης οδών).|")

    rows.append("HEADER|Απαιτούμενες Εγκρίσεις|")
    approvals = ["Συμβούλιο Αρχιτεκτονικής", "Υπηρεσία Νεωτέρων Μνημείων"]
    if extra_approvals:
        approvals.extend(a for a in extra_approvals if a not in approvals)
    rows.append(f"ROW||{', '.join(approvals)}")

    rows.append("HEADER|Λοιποί Περιορισμοί|")
    rows.append("MERGED|Η δόμηση τελεί υπό τον έλεγχο ειδικών καθεστώτων προστασίας "
                "(Natura 2000, δασικός χάρτης, αιγιαλός/παραλία, αρχαιολογία, ρέματα) — "
                "βλ. επόμενες ενότητες.|")

    return rows


def _encode_report(rows: list) -> str:
    return "\n".join(rows).encode("windows-1253", errors="replace").decode("windows-1253")


def build_point_report(*, oroi: dict, outside_plan: bool, shore: dict,
                       archeo: dict, church: dict, natura: dict, remata: dict,
                       ydro: dict) -> str:
    """Render point results; the caller explicitly determines outside_plan."""
    rows = []

    # ── BUILDING REGULATIONS ─────────────────────────────────────────────────
    if oroi.get("found"):
        rows.extend(_build_regs_rows(oroi))
    elif outside_plan:
        # Εκτός σχεδίου — γενικές διατάξεις (Π.Δ. 24.05.85 + Ν.4759/2020)
        rows.extend(_build_ektos_sxediou_rows())
    else:
        return MISSING_REGULATIONS

    # ── ΑΙΓΙΑΛΟΣ / ΠΑΡΑΛΙΑ ──────────────────────────────────────────────────
    if shore.get("found"):
        rows.append("HEADER|ΑΙΓΙΑΛΟΣ / ΠΑΡΑΛΙΑ|")
        priority = ["Γραμμή Αιγιαλού", "Γραμμή Αιγιαλού_ΠΟΑ",
                    "Γραμμή Παραλίας", "Γραμμή Παραλίας_ΠΟΑ", "Γραμμή Παλαιού Αιγιαλού"]
        by_type = {r["info"]: r for r in shore["lines"]}
        for key in priority:
            if key in by_type:
                r = by_type[key]
                label = SHORELINE_LABELS.get(key, key)
                fek = f" (ΦΕΚ {r['fek']})" if r.get("fek") else ""
                rows.append(f"ROW|{label}|{r['distance_m']} μ.{fek}")

    # ── ΑΡΧΑΙΟΛΟΓΙΑ ──────────────────────────────────────────────────────────
    rows.append("HEADER|ΑΡΧΑΙΟΛΟΓΙΑ|")
    if archeo.get("in_protection_zone"):
        rows.append(f"ROW|Ζώνη Προστασίας|ΝΑΙ — {archeo.get('zone_name', '')}")
    else:
        rows.append("ROW|Ζώνη Προστασίας|ΟΧΙ")
    if archeo.get("found"):
        mn = archeo['name']
        if archeo.get("ot"):
            mn += f" — {archeo['ot']}"
        mn += f"  ({archeo['distance_m']} μ.)"
        rows.append(f"ROW|Πλησιέστερο Μνημείο|{mn}")
    else:
        rows.append("ROW|Πλησιέστερο Μνημείο|ΟΧΙ (εντός 2000 μ.)")

    # ── ΕΚΚΛΗΣΙΕΣ ────────────────────────────────────────────────────────────
    if church.get("found"):
        rows.append("HEADER|ΕΚΚΛΗΣΙΕΣ|")
        ch_label = church.get("name", "-")
        if church.get("type"):
            ch_label += f" ({church['type']})"
        rows.append(f"ROW|Πλησιέστερη|{ch_label}")
        rows.append(f"ROW|Απόσταση|{church['distance_m']} μ.")

    # ── NATURA / ΔΑΣΗ ────────────────────────────────────────────────────────
    rows.append("HEADER|NATURA / ΔΑΣΗ|")
    if natura.get("in_natura"):
        rows.append(f"ROW|Natura 2000|ΝΑΙ — {natura.get('natura_name', '')} ({natura.get('natura_code', '')})")
    else:
        rows.append("ROW|Natura 2000|ΟΧΙ")
    if natura.get("in_forest"):
        fcode = natura.get("forest_type", "")
        flabel = natura.get("forest_type_label", "")
        fcat = natura.get("forest_category", "")
        fsrc = natura.get("forest_source", "")
        src_label = f" ({fsrc})" if fsrc else ""
        rows.append(f"ROW|Δασικός Χάρτης{src_label}|ΝΑΙ ({fcode} — {flabel})")
        rows.append(f"ROW|Κατηγορία δάσους|{fcat}")
    else:
        rows.append("ROW|Δασικός Χάρτης|ΟΧΙ")
    if natura.get("kaek_forest_use"):
        rows.append(f"ROW|Χρήση γης ΚΑΕΚ|{natura['kaek_forest_use']}")

    # ── ΡΕΜΑΤΑ ───────────────────────────────────────────────────────────────
    by_layer = {r["layer"]: r for r in remata["oikismos_lines"]}
    has_remata = bool(remata["oikismos_lines"]) or remata.get("tps_found") or remata.get("other_found")
    if has_remata:
        rows.append("HEADER|ΡΕΜΑΤΑ|")
        # Only Γρ. Πλημμύρας: the οριοθέτηση lines come from the (non-ratified)
        # delimitation study, so they are not reported. "Άλλο ρέμα" still shown below.
        key = "Υδρογραφική Γραμμή Πλημμυρας"
        if key in by_layer:
            r = by_layer[key]
            rows.append(f"ROW|{r['label']}|{r['distance_m']} μ.")
        if remata.get("tps_found"):
            rows.append(f"ROW|Ρέμα ΤΠΣ|{remata['tps_distance_m']} μ.")
        if remata.get("other_found"):
            rows.append(f"ROW|Άλλο ρέμα (εντός οικ.)|{remata['other_distance_m']} μ.")

    # ── ΥΔΡΟΛΗΨΙΕΣ ΕΜΣΥ ─────────────────────────────────────────────────────
    if ydro["available"]:
        rows.append("HEADER|ΥΔΡΟΛΗΨΙΕΣ (ΕΜΣΥ)|")
        if ydro["nearest"]:
            n = ydro["nearest"]
            rows.append(f"ROW|Πλησιέστερη|{water_point_label(n)} — {n['distance_m']} μ.")
        else:
            rows.append("ROW|Πλησιέστερη|ΟΧΙ (εντός 500 μ.)")

    return _encode_report(rows)


def build_parcel_report(*, parcel: dict, oroi: dict, outside_plan: bool,
                        shore: dict, rights: dict, overlaps: dict, archeo: dict,
                        church: dict, remata: dict, ydro: dict) -> str:
    """Render parcel-based results, with regulations evaluated at the click."""
    if not parcel:
        return MISSING_PARCEL

    kaek = parcel["kaek"]

    # ── ΑΙΓΙΑΛΟΣ (a crossing adds Κτηματική Υπηρεσία approval) ────────────────
    shore_crossing = _shore_crossing_list(shore) if shore.get("found") else []
    _KTIMATIKI = "Κτηματική Υπηρεσία Δημοσίου"

    # ── BUILDING REGULATIONS (at click point — a parcel may span zones) ──────
    if oroi.get("found"):
        if shore_crossing and _KTIMATIKI not in oroi["egkriseis"]:
            oroi = {**oroi, "egkriseis": [*oroi["egkriseis"], _KTIMATIKI]}
        regs_rows = _build_regs_rows(oroi)
        ot_label = f"O.T. {oroi['ot_num']}" if oroi.get("ot_num") else "SPETSES"
    elif outside_plan:
        # Εκτός σχεδίου — γενικές διατάξεις με υπολογισμό από εμβαδόν γεωτεμαχίου
        try:
            area = float(parcel["area_m2"])
        except (TypeError, ValueError):
            area = None
        regs_rows = _build_ektos_sxediou_rows(
            parcel_area_m2=area,
            extra_approvals=[_KTIMATIKI] if shore_crossing else None)
        ot_label = "ΕΚΤΟΣ ΣΧΕΔΙΟΥ"
    else:
        return MISSING_REGULATIONS
    # Demote the regs-block title to a section header — the report has its own title
    regs_rows[0] = f"HEADER|ΟΡΟΙ ΔΟΜΗΣΗΣ — {ot_label}|"

    # ── Report skeleton: ΚΤΗΜΑΤΟΛΟΓΙΟ first, then ΟΡΟΙ ΔΟΜΗΣΗΣ, then the rest ─
    rows = [
        f"TITLE|ΠΟΛΕΟΔΟΜΙΚΕΣ ΠΛΗΡΟΦΟΡΙΕΣ|{ot_label}",
        "HEADER|ΚΤΗΜΑΤΟΛΟΓΙΟ (σε λειτουργία)|",
        f"ROW|ΚΑΕΚ|{kaek}",
        f"ROW|Εμβαδόν / Περίμετρος|{parcel['area_m2']} τ.μ. / {parcel['perim_m']} μ.",
    ]
    if rights["apokleistikes"]:
        ax = rights["apokleistikes"]
        total = round(sum(a["area_m2"] for a in ax), 1)
        rows.append(f"ROW|Αποκλ. χρήσεις (ΑΧ)|{len(ax)} πολύγωνα — σύνολο {total} τ.μ.")
    if rights["douleies"]:
        dl = rights["douleies"]
        total = round(sum(d["area_m2"] for d in dl), 1)
        rows.append(f"ROW|Δουλείες|{len(dl)} — σύνολο {total} τ.μ.")

    rows.extend(regs_rows)


    # ── ΑΙΓΙΑΛΟΣ / ΠΑΡΑΛΙΑ (distance from parcel) ────────────────────────────
    if shore.get("found"):
        rows.extend(_build_parcel_shoreline_rows(shore))

    # ── ΑΡΧΑΙΟΛΟΓΙΑ (zone = parcel overlap %, monument = distance from parcel) ─
    rows.append("HEADER|ΑΡΧΑΙΟΛΟΓΙΑ|")
    if overlaps["archeo_zones"]:
        for z in overlaps["archeo_zones"]:
            zname = z.get("name") or ""
            rows.append(f"ROW|Ζώνη Προστασίας|ΝΑΙ — {zname} ({z['pct']}% γεωτεμαχίου)")
    else:
        rows.append("ROW|Ζώνη Προστασίας|ΟΧΙ")
    if archeo.get("found"):
        mn = archeo['name']
        if archeo.get("ot"):
            mn += f" — {archeo['ot']}"
        mn += f"  ({_fmt_parcel_dist(archeo['distance_m'], 'point')})"
        rows.append(f"ROW|Πλησιέστερο Μνημείο|{mn}")
    else:
        rows.append("ROW|Πλησιέστερο Μνημείο|ΟΧΙ (εντός 2000 μ.)")

    # ── ΕΚΚΛΗΣΙΕΣ (distance from parcel) ─────────────────────────────────────
    if church.get("found"):
        rows.append("HEADER|ΕΚΚΛΗΣΙΕΣ|")
        ch_label = church.get("name", "-")
        if church.get("type"):
            ch_label += f" ({church['type']})"
        rows.append(f"ROW|Πλησιέστερη|{ch_label}")
        rows.append(f"ROW|Απόσταση|{_fmt_parcel_dist(church['distance_m'], 'point')}")

    # ── NATURA / ΔΑΣΗ (parcel overlap %) ─────────────────────────────────────
    rows.append("HEADER|NATURA / ΔΑΣΗ|")
    if overlaps["natura"]:
        for n in overlaps["natura"]:
            rows.append(f"ROW|Natura 2000|ΝΑΙ — {n.get('name', '')} ({n.get('code', '')}) {n['pct']}%")
    else:
        rows.append("ROW|Natura 2000|ΟΧΙ")
    if overlaps["forest"]:
        for f in overlaps["forest"]:
            if f.get("source") == "ανάρτηση 2021":
                flabel = "Δασική Ανάρτηση 2021"
            else:
                flabel = "Δασικός Χάρτης (κυρωμένος)"
            rows.append(f"ROW|{flabel}|{f['label']} ({f['category']}) {f['pct']}%")
        kyr_pct = overlaps.get("forest_kyromenos_pct") or 0
        if kyr_pct < 98.0 and any(f.get("source") == "ανάρτηση 2021" for f in overlaps["forest"]):
            rows.append(f"MERGED|Το {round(100 - kyr_pct, 1)}% του γεωτεμαχίου είναι εκτός "
                        "του μερικώς κυρωμένου δασικού χάρτη (πιθανώς εκκρεμείς αντιρρήσεις) "
                        "— για το τμήμα αυτό ισχύει η ανάρτηση 2021.|")
    else:
        rows.append("ROW|Δασικός Χάρτης|ΟΧΙ")
    if parcel["main_use"] in FOREST_USE_CODES and parcel.get("descr"):
        rows.append(f"ROW|Χρήση γης ΚΑΕΚ|{parcel['descr']}")

    # ── ΡΕΜΑΤΑ (distance from parcel; εντός/εκτός σχεδίου at click point) ─────
    by_layer = {r["layer"]: r for r in remata["oikismos_lines"]}
    has_remata = bool(remata["oikismos_lines"]) or remata.get("tps_found") or remata.get("other_found")
    if has_remata:
        rows.append("HEADER|ΡΕΜΑΤΑ|")
        # Only Γρ. Πλημμύρας: the οριοθέτηση lines come from the (non-ratified)
        # delimitation study, so they are not reported. "Άλλο ρέμα" still shown below.
        key = "Υδρογραφική Γραμμή Πλημμυρας"
        if key in by_layer:
            r = by_layer[key]
            rows.append(f"ROW|{r['label']}|{_fmt_parcel_dist(r['distance_m'], 'line')}")
        if remata.get("tps_found"):
            rows.append(f"ROW|Ρέμα ΤΠΣ|{_fmt_parcel_dist(remata['tps_distance_m'], 'line')}")
        if remata.get("other_found"):
            rows.append(f"ROW|Άλλο ρέμα (εντός οικ.)|{_fmt_parcel_dist(remata['other_distance_m'], 'line')}")

    # ── ΥΔΡΟΛΗΨΙΕΣ ΕΜΣΥ (δηλωτέες στα τοπογραφικά) ───────────────────────────
    if ydro["available"]:
        rows.append("HEADER|ΥΔΡΟΛΗΨΙΕΣ (ΕΜΣΥ)|")
        if ydro["inside"]:
            for w in ydro["inside"]:
                rows.append(f"ROW|Εντός γεωτεμαχίου|{water_point_label(w)}")
        else:
            rows.append("ROW|Εντός γεωτεμαχίου|ΟΧΙ")
            if ydro["nearest"]:
                n = ydro["nearest"]
                rows.append(f"ROW|Πλησιέστερη|{water_point_label(n)} — {n['distance_m']} μ.")

    return _encode_report(rows)
