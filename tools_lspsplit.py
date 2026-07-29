#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
lspsplit.py - split a monolithic AutoLISP file into modules.

Parses top-level forms with a real tokenizer (balanced parens, string-aware,
comment-aware), keeps each form's preceding comment block attached to it, then
emits modules according to an explicit name -> module map.

Nothing is paraphrased or retyped: every byte of every form is carried over
verbatim. Verification is done by comparing the multiset of form texts.
"""

import os
import re
import sys
from collections import Counter, OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__)) + os.sep
SRC = HERE + "epoleodomia.lsp"


# --------------------------------------------------------------------------
# Tokenizer / parser
# --------------------------------------------------------------------------

class Form:
    """One top-level form plus the raw text that preceded it (comments/blanks)."""

    __slots__ = ("lead", "body", "start_line", "kind", "name")

    def __init__(self, lead, body, start_line):
        self.lead = lead
        self.body = body
        self.start_line = start_line
        self.kind, self.name = classify(body)

    @property
    def text(self):
        return self.lead + self.body

    def __repr__(self):
        return f"<Form {self.kind}:{self.name} @L{self.start_line}>"


def parse_forms(src):
    """Return (preamble, [Form, ...]).

    preamble is any leading text before the first top-level form.
    """
    forms = []
    i = 0
    n = len(src)
    depth = 0
    in_string = False
    in_comment = False
    form_start = None
    chunk_start = 0          # start of the not-yet-consumed lead text

    while i < n:
        c = src[i]

        if in_comment:
            if c == "\n":
                in_comment = False
            i += 1
            continue

        if in_string:
            if c == "\\":
                i += 2       # skip escaped char
                continue
            if c == '"':
                in_string = False
            i += 1
            continue

        # not in string or comment
        if c == ";":
            in_comment = True
            i += 1
            continue

        if c == '"':
            in_string = True
            i += 1
            continue

        if c == "(":
            if depth == 0:
                form_start = i
            depth += 1
            i += 1
            continue

        if c == ")":
            depth -= 1
            if depth < 0:
                raise ValueError(f"unbalanced ')' at offset {i}")
            if depth == 0:
                # top-level form just closed; consume trailing same-line text
                end = i + 1
                while end < n and src[end] in " \t":
                    end += 1
                if end < n and src[end] == "\n":
                    end += 1
                lead = src[chunk_start:form_start]
                body = src[form_start:end]
                start_line = src.count("\n", 0, form_start) + 1
                forms.append(Form(lead, body, start_line))
                chunk_start = end
                form_start = None
            i += 1
            continue

        i += 1

    if depth != 0:
        raise ValueError(f"unbalanced '(' - depth {depth} at EOF")
    if in_string:
        raise ValueError("unterminated string at EOF")

    tail = src[chunk_start:]
    return forms, tail


DEFUN_RE = re.compile(r"^\(\s*defun\s+([^\s()/]+)", re.IGNORECASE)
SETQ_RE = re.compile(r"^\(\s*setq\s+([^\s()]+)", re.IGNORECASE)
HEAD_RE = re.compile(r"^\(\s*([^\s()]+)")


def classify(body):
    m = DEFUN_RE.match(body)
    if m:
        raw = m.group(1)
        if raw.lower().startswith("c:"):
            return "command", raw[2:].upper()
        return "helper", raw
    m = SETQ_RE.match(body)
    if m:
        return "global", m.group(1)
    m = HEAD_RE.match(body)
    if m:
        return "other", m.group(1).lower()
    return "other", "?"


# --------------------------------------------------------------------------
# Module map  (explicit and auditable - no heuristics)
# --------------------------------------------------------------------------

"""
Anonymous top-level forms (guards, banners) have no unique name, so they are
addressed by their line number in the source via ("at", N).
"""

# Idempotent lazy-init guards that appear TWICE in the source. Keeping the
# first occurrence only is provably behaviour-preserving:
#   (if (not X) (setq X v))  run twice == run once
DROP_DUPLICATE_LINES = {
    2616: "duplicate of L2564  (if (not *epol-tbl-scale*) ...)",
    2617: "duplicate of L2565  (if (not *epol-tbl-width*) ...)",
}

# The trailing load banner belongs to the loader, not to any module.
TO_LOADER_LINES = set(range(3435, 3444))

MODULES = OrderedDict()

MODULES["epol-core.lsp"] = dict(
    title="CORE - config, HTTP, parsing, layers, drawing & table primitives",
    blurb="Shared foundation for every other module. Load first: it defines\n"
          "*epol-api-url*, *qgis-root*, *epol-layers* and all epol: helpers.",
    names=[
        # config + globals
        ("other", "vl-load-com"),
        ("global", "*epol-api-url*"),
        ("helper", "epol:find-qgis"),
        ("global", "*qgis-root*"),
        ("at", 85),                      # (if *qgis-root* ...) startup message
        ("global", "*epol-layers*"),
        # http
        ("helper", "epol:http-get"),
        ("helper", "epol:http-post"),
        ("helper", "epol:num-to-str"),
        ("helper", "epol:build-url"),
        # parsing
        ("helper", "epol:remove-cr"),
        ("helper", "epol:split"),
        ("helper", "epol:parse-coords"),
        ("helper", "epol:extract-json-value"),
        ("helper", "epol:extract-json-number"),
        # layers
        ("helper", "epol:sanitize-layer-name"),
        ("helper", "epol:make-layer"),
        ("helper", "epol:get-layer"),
        ("helper", "epol:ensure-ltype"),
        ("helper", "epol:make-klayer"),
        # drawing
        ("helper", "epol:draw-text"),
        ("helper", "epol:draw-polygon"),
        ("helper", "epol:draw-open-pline"),
        ("helper", "epol:polygon-centroid"),
        # input
        ("helper", "epol:get-point"),
        ("helper", "epol:get-bbox"),
        # table primitives
        ("helper", "epol:tbl-rect"),
        ("helper", "epol:tbl-text"),
        ("helper", "epol:tbl-text-fit"),
        ("helper", "epol:tbl-text-ctr"),
        ("helper", "epol:tbl-mtext"),
        ("helper", "epol:draw-table-rows"),
        ("helper", "epol:draw-table-grid"),
        ("helper", "epol:add-table-text"),
        ("helper", "epol:create-fek-table"),
    ],
)

MODULES["epol-site.lsp"] = dict(
    title="SITE ANALYSIS - building regulations & environmental constraints",
    blurb="OROITABLE ETABLE EREPORT ENOTES ARCHEO CHURCH NATURA AIGIALOS REMATA",
    names=[
        ("command", "OROITABLE"),
        ("command", "ARCHEO"),
        ("command", "CHURCH"),
        ("command", "NATURA"),
        ("command", "ENOTES"),
        ("command", "AIGIALOS"),
        ("command", "REMATA"),
        ("at", 2564),                    # (if (not *epol-tbl-scale*) ...)
        ("at", 2565),                    # (if (not *epol-tbl-width*) ...)
        ("helper", "epol:run-table-cmd"),
        ("command", "ETABLE"),
        ("command", "EREPORT"),
    ],
)

MODULES["epol-bounds.lsp"] = dict(
    title="BOUNDARIES - cadastral parcels & building blocks",
    blurb="KAEK EKAEK OT EOBT KAEK_OP",
    names=[
        ("command", "KAEK"),
        ("command", "EKAEK"),
        ("command", "OT"),
        ("command", "EOBT"),
        ("command", "KAEK_OP"),
    ],
)

MODULES["epol-ktima.lsp"] = dict(
    title="KTIMATOLOGIO - official electronic diagram tools (TD / DGM / TDGM)",
    blurb="KLAYERS KPST KGEOM KGEOMV KVERT KGRID AIGDRAW KCHECK",
    names=[
        ("global", "*ktima-layers*"),
        ("command", "KLAYERS"),
        ("command", "KPST"),
        ("at", 1361),                    # (if (not *kgeom-tol*) ...)
        ("helper", "kgeom:poly-coords"),
        ("command", "KGEOM"),
        ("command", "KGEOMV"),
        ("at", 1691),                    # (if (not *kvert-num*) ...)
        ("helper", "kvert:n3"),
        ("helper", "kvert:existing-marks"),
        ("helper", "kvert:find-mark"),
        ("helper", "kvert:clean"),
        ("command", "KVERT"),
        ("at", 1947),                    # (if (not *kgrid-style*) ...)
        ("helper", "kgrid:line"),
        ("helper", "kgrid:label"),
        ("helper", "kgrid:vlabel"),
        ("command", "KGRID"),
        ("command", "AIGDRAW"),
        ("global", "*kcheck-profiles*"),
        ("global", "*kcheck-poly-layers*"),
        ("global", "*kcheck-text-ok-layers*"),
        ("global", "*kcheck-line-layers*"),
        ("global", "*kcheck-textonly-layers*"),
        ("global", "*kcheck-mixed-layers*"),
        ("helper", "kcheck:count"),
        ("helper", "kcheck:scan"),
        ("command", "KCHECK"),
    ],
)

MODULES["epol-raster.lsp"] = dict(
    title="RASTERS - planning diagrams, drone orthophotos, GDAL clipping",
    blurb="FEK DJI DE CLIPR",
    names=[
        ("command", "FEK"),
        ("helper", "epol:parse-rasters-info"),
        ("command", "DJI"),
        ("helper", "epol:parse-paths"),
        ("helper", "epol:load-raster"),
        ("command", "DE"),
        ("command", "CLIPR"),
        ("helper", "epol:get-image-path"),
        ("helper", "epol:run-gdal"),
    ],
)

MODULES["epol-util.lsp"] = dict(
    title="UTILITIES - transparency, layer listing, help",
    blurb="ETRANS ELAYERS EHELP",
    names=[
        ("command", "ETRANS"),
        ("command", "ELAYERS"),
        ("command", "EHELP"),
    ],
)


BANNER = ";;; " + "=" * 74


def header(fname, spec, count):
    lines = [
        BANNER,
        f";;; {fname} - {spec['title']}",
        BANNER,
        ";;;",
    ]
    for ln in spec["blurb"].split("\n"):
        lines.append(f";;;   {ln}")
    lines += [
        ";;;",
        ";;; Part of EPOLEODOMIA GIS Tools v2.1. Do not load directly - load",
        ";;; epoleodomia.lsp, which loads every module in the correct order.",
        f";;; Contains {count} top-level forms.",
        BANNER,
        "",
        "",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    with open(SRC, "r", encoding="utf-8", newline="") as fh:
        src = fh.read()

    if "\r" in src:
        sys.exit("FAIL: source contains CR - expected LF-only")

    forms, tail = parse_forms(src)

    print(f"parsed {len(forms)} top-level forms, tail={len(tail)} bytes")

    by_line = {f.start_line: f for f in forms}

    # index named forms; anonymous ones ("other") are addressed by line
    index = {}
    dupes = []
    for f in forms:
        if f.kind == "other" and f.name in ("if", "princ"):
            continue
        key = (f.kind, f.name)
        if key in index:
            dupes.append(key)
        index.setdefault(key, []).append(f)

    if dupes:
        print("!! duplicate NAMED definitions in SOURCE:")
        for k in sorted(set(dupes)):
            print("   ", k, [x.start_line for x in index[k]])

    # ---- pre-account for deliberate exclusions ----
    excluded = {}
    for ln, why in DROP_DUPLICATE_LINES.items():
        if ln not in by_line:
            sys.exit(f"ABORT: DROP line {ln} is not a top-level form start")
        excluded[id(by_line[ln])] = ("dropped", why)
    for ln in TO_LOADER_LINES:
        if ln in by_line:
            excluded[id(by_line[ln])] = ("loader", "load banner -> epoleodomia.lsp")

    print(f"\ndeliberate exclusions: {len(excluded)} forms")
    for ln, why in sorted(DROP_DUPLICATE_LINES.items()):
        print(f"   DROP  L{ln}: {why}")
    nloader = sum(1 for k, v in excluded.items() if v[0] == "loader")
    print(f"   LOADER: {nloader} trailing (princ ...) banner forms")

    # ---- resolve the map ----
    assigned = {}
    missing = []
    for fname, spec in MODULES.items():
        for key in spec["names"]:
            if key[0] == "at":
                f = by_line.get(key[1])
                if f is None:
                    missing.append((fname, key))
                    continue
                targets = [f]
            elif key not in index:
                missing.append((fname, key))
                continue
            else:
                targets = index[key]
            for f in targets:
                if id(f) in assigned:
                    print(f"!! {key} claimed twice ({assigned[id(f)]} + {fname})")
                if id(f) in excluded:
                    print(f"!! {key} is both mapped to {fname} and excluded")
                assigned[id(f)] = fname

    if missing:
        print("!! mapped but not found in source:")
        for fname, key in missing:
            print(f"   {fname}: {key}")

    unassigned = [f for f in forms
                  if id(f) not in assigned and id(f) not in excluded]
    if unassigned:
        print("!! present in source but neither mapped nor excluded:")
        for f in unassigned:
            print(f"   L{f.start_line}: {f.kind} {f.name}")

    if missing or unassigned or dupes:
        sys.exit("ABORT: map does not exactly cover the source")

    # ---- emit ----
    outdir = HERE
    written = {}
    for fname, spec in MODULES.items():
        chosen = []
        for key in spec["names"]:
            if key[0] == "at":
                chosen.append(by_line[key[1]])
            else:
                chosen.extend(index[key])
        # preserve original file order inside each module
        chosen.sort(key=lambda f: f.start_line)

        parts = [header(fname, spec, len(chosen))]
        for f in chosen:
            lead = f.lead.strip("\n")
            if lead:
                parts.append(lead + "\n")
            parts.append(f.body.rstrip("\n") + "\n\n")
        out = "".join(parts).rstrip("\n") + "\n"

        with open(outdir + fname, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(out)
        written[fname] = (len(chosen), out.count("\n"))
        print(f"  wrote {fname:22s} {len(chosen):3d} forms  {out.count(chr(10)):5d} lines")

    # ---- verify: multiset of form bodies preserved ----
    # excluded forms are expected to be absent from the modules
    orig_bodies = Counter(f.body.strip() for f in forms
                          if id(f) not in excluded)
    new_bodies = Counter()
    for fname in MODULES:
        with open(outdir + fname, "r", encoding="utf-8", newline="") as fh:
            nf, ntail = parse_forms(fh.read())
        new_bodies.update(f.body.strip() for f in nf)

    if orig_bodies == new_bodies:
        print("\nVERIFY OK: every top-level form body preserved byte-for-byte")
    else:
        only_orig = orig_bodies - new_bodies
        only_new = new_bodies - orig_bodies
        print(f"\nVERIFY FAILED: -{sum(only_orig.values())} +{sum(only_new.values())}")
        for b in list(only_orig)[:3]:
            print("  LOST:", b[:120])
        for b in list(only_new)[:3]:
            print("  NEW :", b[:120])
        sys.exit(1)

    # ---- show what the loader must reproduce ----
    print("\nBanner forms the loader must reproduce (from source L3435-3443):")
    for f in forms:
        if id(f) in excluded and excluded[id(f)][0] == "loader":
            print("   |", f.body.rstrip())
    if tail.strip():
        print("\nUnconsumed source tail:")
        for ln in tail.strip().split("\n"):
            print("   |", ln)


if __name__ == "__main__":
    main()
