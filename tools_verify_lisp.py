#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify.py - post-split integrity checks for EPOLEODOMIA v2.1.

Checks, against the pre-refactor file recovered from git:
  1  every file is valid UTF-8, LF-only, and has balanced parens
  2  all 29 c: commands present exactly once
  3  all helper defuns present exactly once, none lost, none invented
  4  every namespaced function that is CALLED is also DEFINED
  5  load-order safety: top-level forms only reference things already defined
  6  kexport.lsp / kfilters.lsp dependencies still satisfied
"""

import os
import re
import subprocess
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from tools_lspsplit import parse_forms               # noqa: E402

REPO = HERE + os.sep
LOADER = "epoleodomia.lsp"
MODULES = ["epol-core.lsp", "epol-site.lsp", "epol-bounds.lsp",
           "epol-ktima.lsp", "epol-raster.lsp", "epol-util.lsp"]
EXTRA = ["kexport.lsp", "kfilters.lsp"]

# Things deliberately added after the v2.0 baseline. Everything NOT listed here
# must still match the baseline exactly, so the checks keep catching accidental
# loss, duplication or renaming - they just stop flagging intentional work.
# Add to this list when you add a command; that is the point of the friction.
ADDED_COMMANDS = {
    "ERASTER",          # generic sheet loader over v_all_rasters
}
ADDED_HELPERS = {
    "eraster:collections",   # asks the API what is catalogued
    "eraster:run",           # second half of ERASTER: roles, bbox, attach
}
ADDED_GLOBALS = {
    "*eraster-collection*",   # ERASTER remembers the last collection
}

fails, warns = [], []


def fail(msg):
    fails.append(msg)
    print("  FAIL  " + msg)


def warn(msg):
    warns.append(msg)
    print("  warn  " + msg)


def ok(msg):
    print("  ok    " + msg)


def read(path):
    with open(REPO + path, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def strip_code(src):
    """Remove strings and comments so we only scan real code."""
    out = []
    i, n = 0, len(src)
    in_s = in_c = False
    while i < n:
        c = src[i]
        if in_c:
            if c == "\n":
                in_c = False
                out.append(c)
            i += 1
            continue
        if in_s:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                in_s = False
            i += 1
            continue
        if c == ";":
            in_c = True
            i += 1
            continue
        if c == '"':
            in_s = True
            out.append(" ")
            i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


# --------------------------------------------------------------------------
print("\n[1] encoding / line endings / paren balance")
# --------------------------------------------------------------------------
parsed = {}
for f in [LOADER] + MODULES:
    raw = open(REPO + f, "rb").read()
    try:
        txt = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        fail(f"{f}: not valid UTF-8 ({e})")
        continue
    if raw.startswith(b"\xef\xbb\xbf"):
        fail(f"{f}: has a UTF-8 BOM (AutoLISP chokes on it)")
    if b"\r" in raw:
        fail(f"{f}: contains CR (must stay LF-only)")
    try:
        forms, tail = parse_forms(txt)
        parsed[f] = forms
        if tail.strip():
            warn(f"{f}: {len(tail.strip())} bytes of unparsed tail")
    except ValueError as e:
        fail(f"{f}: paren/string error - {e}")
        continue
    ok(f"{f}: UTF-8 no BOM, LF, balanced ({len(forms)} forms)")

if fails:
    sys.exit("\nABORT: basic file integrity failed")

# --------------------------------------------------------------------------
print("\n[2] recover the pre-refactor original from git")
# the monolith is the last commit in which epoleodomia.lsp was > 1000 lines
BASELINE = os.environ.get("EPOL_BASELINE", "5088735")
# --------------------------------------------------------------------------
orig = subprocess.run(
    ["git", "-C", REPO, "show", BASELINE + ":epoleodomia.lsp"],
    capture_output=True, check=True).stdout.decode("utf-8")
orig_forms, _ = parse_forms(orig)
ok(f"{BASELINE}:epoleodomia.lsp = {len(orig.splitlines())} lines, "
   f"{len(orig_forms)} top-level forms")

# --------------------------------------------------------------------------
print("\n[3] commands: 29 expected, exactly once each")
# --------------------------------------------------------------------------
orig_cmds = Counter(f.name for f in orig_forms if f.kind == "command")
new_cmds = Counter()
where = {}
for m in MODULES:
    for f in parsed[m]:
        if f.kind == "command":
            new_cmds[f.name] += 1
            where.setdefault(f.name, []).append(m)

if len(orig_cmds) != 29:
    warn(f"original had {len(orig_cmds)} commands, expected 29")

for c in sorted(orig_cmds):
    if new_cmds[c] == 0:
        fail(f"command {c} LOST")
    elif new_cmds[c] > 1:
        fail(f"command {c} duplicated in {where[c]}")
for c in sorted(new_cmds):
    if c in orig_cmds:
        continue
    if c in ADDED_COMMANDS:
        ok(f"command {c} added since baseline (declared) -> {where[c][0]}")
    else:
        fail(f"command {c} INVENTED - if intentional, add it to "
             f"ADDED_COMMANDS at the top of this file")
for c in sorted(ADDED_COMMANDS - set(new_cmds)):
    fail(f"command {c} is declared in ADDED_COMMANDS but does not exist")

if not fails:
    ok(f"all {len(orig_cmds)} baseline commands present exactly once "
       f"(+{len(ADDED_COMMANDS)} added)")
    for m in MODULES:
        cs = [f.name for f in parsed[m] if f.kind == "command"]
        if cs:
            ok(f"  {m:18s} {len(cs):2d}: {' '.join(sorted(cs))}")

# --------------------------------------------------------------------------
print("\n[4] helper defuns + globals preserved")
# --------------------------------------------------------------------------
for kind, label, allowed in (("helper", "helper defun", ADDED_HELPERS),
                             ("global", "global setq", ADDED_GLOBALS)):
    o = Counter(f.name for f in orig_forms if f.kind == kind)
    nw = Counter()
    for m in MODULES:
        nw.update(f.name for f in parsed[m] if f.kind == kind)
    lost = [k for k in o if nw[k] == 0]
    dup = [k for k in nw if nw[k] > 1]
    new = [k for k in nw if k not in o and k not in allowed]
    declared = [k for k in nw if k not in o and k in allowed]
    ghost = [k for k in allowed if k not in nw]
    for k in lost:
        fail(f"{label} {k} LOST")
    for k in dup:
        fail(f"{label} {k} duplicated ({nw[k]}x)")
    for k in new:
        fail(f"{label} {k} INVENTED - if intentional, declare it in "
             f"the ADDED_* set at the top of this file")
    for k in ghost:
        fail(f"{label} {k} is declared as added but does not exist")
    if not (lost or dup or new or ghost):
        ok(f"{len(o)} baseline {label}s preserved, exactly once each"
           + (f" (+{len(declared)} added: {' '.join(sorted(declared))})"
              if declared else ""))

# --------------------------------------------------------------------------
print("\n[5] called-but-undefined namespaced functions")
# --------------------------------------------------------------------------
defined = set()
for m in MODULES:
    for f in parsed[m]:
        if f.kind == "helper":
            defined.add(f.name.lower())

CALL = re.compile(r"\((\s*)((?:epol|kgeom|kvert|kgrid|kcheck|eraster):[a-z0-9_\-]+)",
                  re.IGNORECASE)
called = {}
for m in MODULES + EXTRA:
    code = strip_code(read(m))
    for mt in CALL.finditer(code):
        called.setdefault(mt.group(2).lower(), set()).add(m)

undef = {k: v for k, v in called.items() if k not in defined}
if undef:
    for k, v in sorted(undef.items()):
        fail(f"{k} called from {sorted(v)} but never defined")
else:
    ok(f"{len(called)} distinct namespaced calls, all resolve to a definition")

unused = sorted(defined - set(called))
if unused:
    warn(f"defined but never called: {' '.join(unused)}")

# --------------------------------------------------------------------------
print("\n[6] load-order safety (top-level evaluation)")
# --------------------------------------------------------------------------
# Only top-level forms are evaluated at load time. A top-level form may only
# reference functions/globals defined by an EARLIER form in load order.
seen_fn, seen_var = set(), set()
VAR = re.compile(r"\*[a-z0-9_\-]+\*", re.IGNORECASE)
order_problems = []

for m in MODULES:
    for f in parsed[m]:
        body = strip_code(f.body)
        if f.kind in ("helper", "command"):
            # body is not evaluated now; just record the definition
            seen_fn.add(f.name.lower())
            continue
        # global setq / bare (if ...) / (princ ...) -> evaluated at load time
        for mt in CALL.finditer(body):
            if mt.group(2).lower() not in seen_fn:
                order_problems.append(
                    f"{m}: top-level form at L{f.start_line} calls "
                    f"{mt.group(2)} before it is defined")
        head = body.split(None, 1)
        target = None
        if f.kind == "global":
            target = f.name.lower()
        for v in VAR.findall(body):
            v = v.lower()
            if v == target:
                continue
            if v not in seen_var and v not in ("*epol-dir*", "*epol-modules*"):
                # reading an unset global is legal in AutoLISP (yields nil) and
                # the lazy-init guards rely on exactly that, so only note it
                pass
        if f.kind == "global":
            seen_var.add(f.name.lower())

for p in order_problems:
    fail(p)
if not order_problems:
    ok("no top-level form calls a function defined later in load order")

# the one real dependency in the original: (setq *qgis-root* (epol:find-qgis))
core_names = [f.name.lower() for f in parsed["epol-core.lsp"]]
if "epol:find-qgis" in core_names and "*qgis-root*" in core_names:
    if core_names.index("epol:find-qgis") < core_names.index("*qgis-root*"):
        ok("epol:find-qgis defined before (setq *qgis-root* (epol:find-qgis))")
    else:
        fail("*qgis-root* is set before epol:find-qgis is defined")

# --------------------------------------------------------------------------
print("\n[7] kexport.lsp / kfilters.lsp dependencies")
# --------------------------------------------------------------------------
provided = set()
for m in MODULES:
    for f in parsed[m]:
        provided.add(f.name.lower())

for dep in EXTRA:
    code = strip_code(read(dep))
    needed = {v.lower() for v in VAR.findall(code)}
    missing = {v for v in needed
               if v.startswith(("*epol", "*ktima", "*kcheck"))
               and v not in provided}
    if missing:
        fail(f"{dep} needs {sorted(missing)} which no module defines")
    else:
        interesting = sorted(v for v in needed
                             if v.startswith(("*epol", "*ktima", "*kcheck")))
        ok(f"{dep}: {' '.join(interesting) or '(no globals)'} -> all provided")

# --------------------------------------------------------------------------
print("\n[8] loader sanity")
# --------------------------------------------------------------------------
lsrc = read(LOADER)
if any(f.kind == "command" for f in parsed[LOADER]):
    fail("loader defines commands - it should only load modules")
else:
    ok("loader defines no commands")
for m in MODULES:
    if m not in lsrc:
        fail(f"loader does not mention {m}")
if all(m in lsrc for m in MODULES):
    ok("loader references all 6 modules")
if lsrc.index("epol-core.lsp") != min(lsrc.index(m) for m in MODULES):
    fail("epol-core.lsp is not first in the loader's module list")
else:
    ok("epol-core.lsp is first in load order")

# --------------------------------------------------------------------------
print("\n" + "=" * 64)
tot_new = sum(len(open(REPO + f, encoding="utf-8").read().splitlines())
              for f in [LOADER] + MODULES)
print(f"original : {len(orig.splitlines()):5d} lines in 1 file")
print(f"v2.1     : {tot_new:5d} lines in {1 + len(MODULES)} files "
      f"(loader + {len(MODULES)} modules)")
print(f"\n{len(fails)} failures, {len(warns)} warnings")
print("=" * 64)
sys.exit(1 if fails else 0)
