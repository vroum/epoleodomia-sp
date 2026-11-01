"""Preview or explicitly apply versioned TEE schema changes. Never sync data."""

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

import psycopg2

from settings import SETTINGS


ROOT = Path(__file__).resolve().parent
MIGRATIONS = ROOT / "sql" / "migrations"
BASELINE_MANIFEST = ROOT / "sql" / "tee_baseline_manifest.json"
LEDGER = "epol_meta.schema_migrations"
LOCK_KEY = (2100, 1784900001)


class SetupError(RuntimeError):
    pass


@dataclass(frozen=True)
class Migration:
    version: int
    filename: str
    checksum: str
    statement: str
    contract: dict = None


@dataclass(frozen=True)
class SetupPlan:
    state: str
    pending: tuple
    findings: tuple = ()
    adopt_version: int = 0


def _valid_schema_contract(value):
    if not isinstance(value, dict) or not isinstance(value.get("relations"), dict) or not value["relations"]:
        return False
    for name, relation in value["relations"].items():
        if (not isinstance(name, str) or not isinstance(relation, dict)
                or relation.get("kind") not in ("r", "p", "v", "m")
                or not isinstance(relation.get("columns"), dict) or not relation["columns"]
                or not all(isinstance(k, str) and isinstance(v, str) for k, v in relation["columns"].items())
                or not isinstance(relation.get("constraints"), list)
                or not all(isinstance(c, str) for c in relation["constraints"])
                or ("view_definition" in relation and not isinstance(relation["view_definition"], str))
                or not isinstance(relation.get("view_definition_variants", []), list)
                or not all(isinstance(v, str) for v in relation.get("view_definition_variants", []))):
            return False
    return (isinstance(value.get("functions", []), list)
            and all(isinstance(f, str) for f in value.get("functions", [])))


def load_migrations(directory=MIGRATIONS):
    migrations = []
    for path in sorted(Path(directory).glob("*.sql")):
        match = re.fullmatch(r"([0-9]{4})_[a-z0-9_]+\.sql", path.name)
        if not match:
            raise SetupError("Invalid migration filename: " + path.name)
        raw = path.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw:
            raise SetupError("Migration must use UTF-8 without BOM and LF: " + path.name)
        statement = raw.decode("utf-8")
        if not statement.strip():
            raise SetupError("Empty migration: " + path.name)
        contract = None
        contract_path = path.with_suffix(".json")
        checksum_input = raw
        if contract_path.exists():
            contract_raw = contract_path.read_bytes()
            if contract_raw.startswith(b"\xef\xbb\xbf") or b"\r" in contract_raw:
                raise SetupError("Contract must use UTF-8 without BOM and LF: " + contract_path.name)
            try:
                contract = json.loads(contract_raw.decode("utf-8"))
            except (ValueError, UnicodeError) as exc:
                raise SetupError("Invalid migration contract: " + contract_path.name) from exc
            if (not isinstance(contract, dict) or contract.get("format_version") != 1
                    or set(contract) - {"format_version", "before", "after", "recreated_views"}
                    or not all(_valid_schema_contract(contract.get(k)) for k in ("before", "after"))):
                raise SetupError("Invalid migration contract: " + contract_path.name)
            views = contract.get("recreated_views", [])
            if (not isinstance(views, list)
                    or any(not isinstance(v, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", v) for v in views)
                    or len(set(views)) != len(views)
                    or any(v not in contract["before"]["relations"] or
                           contract["before"]["relations"][v]["kind"] != "v" for v in views)):
                raise SetupError("Invalid recreated-view contract: " + contract_path.name)
            checksum_input += b"\0epol-contract\0" + contract_raw
        migrations.append(Migration(int(match[1]), path.name, hashlib.sha256(checksum_input).hexdigest(),
                                    statement, contract))
    if not migrations or [m.version for m in migrations] != list(range(1, len(migrations)+1)):
        raise SetupError("Migration versions must start at 0001 and be consecutive without duplicates")
    return tuple(migrations)


def read_structure(cursor):
    """Catalog metadata only, including views; no source rows are read."""
    # DDL may have changed the local search path. Canonicalize constraint/type
    # rendering so fresh and adopted schemas are compared identically.
    cursor.execute("SET LOCAL search_path TO pg_catalog, public")
    cursor.execute("""
        SELECT c.relname, c.relkind, a.attname, format_type(a.atttypid, a.atttypmod),
               a.attnotnull, pg_get_expr(d.adbin, d.adrelid), a.attgenerated, a.attidentity
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_attribute a ON a.attrelid = c.oid
        LEFT JOIN pg_attrdef d ON d.adrelid = c.oid AND d.adnum = a.attnum
        WHERE n.nspname = 'epoleodomia' AND c.relkind IN ('r','p','v','m')
          AND a.attnum > 0 AND NOT a.attisdropped
        ORDER BY c.relname, a.attnum
    """)
    structure = {}
    for name, kind, column, column_type, not_null, default, generated, identity in cursor.fetchall():
        entry = structure.setdefault(name, {"kind": kind, "columns": {}, "constraints": [],
                                            "column_attributes": {}, "indexes": []})
        entry["columns"][column] = column_type
        entry["column_attributes"][column] = dict(not_null=not_null, default=default,
                                                generated=generated, identity=identity)
    cursor.execute("""
        SELECT c.relname, pg_get_constraintdef(k.oid)
        FROM pg_constraint k JOIN pg_class c ON c.oid = k.conrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'epoleodomia' AND k.contype IN ('p','u','f','c')
        ORDER BY c.relname, pg_get_constraintdef(k.oid)
    """)
    for name, definition in cursor.fetchall():
        if name in structure:
            structure[name]["constraints"].append(definition)
    cursor.execute("""
        SELECT c.relname, pg_get_viewdef(c.oid, false)
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'epoleodomia' AND c.relkind = 'v'
    """)
    for name, definition in cursor.fetchall():
        if name in structure:
            structure[name]["view_definition"] = definition.strip()
    cursor.execute("""
        SELECT c.relname, am.amname, i.indisunique,
               ARRAY(SELECT pg_get_indexdef(i.indexrelid, j, true)
                     FROM generate_series(1, i.indnkeyatts) j),
               pg_get_expr(i.indpred, i.indrelid)
        FROM pg_index i JOIN pg_class c ON c.oid = i.indrelid
        JOIN pg_class ix ON ix.oid = i.indexrelid
        JOIN pg_am am ON am.oid = ix.relam JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'epoleodomia' AND i.indisvalid AND i.indisready
    """)
    for name, method, unique, columns, predicate in cursor.fetchall():
        if name in structure:
            structure[name]["indexes"].append(dict(method=method, unique=unique,
                                                  columns=columns, predicate=predicate))
    return structure


def baseline_findings(cursor, manifest_path=BASELINE_MANIFEST):
    expected = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    return contract_findings(cursor, expected)


def contract_findings(cursor, expected):
    """Required properties only; preserve unrelated objects and extra columns."""
    actual = read_structure(cursor)
    findings = []
    for name, definition in expected["relations"].items():
        current = actual.get(name)
        if current is None or current["kind"] != definition["kind"]:
            findings.append(f"Missing or incompatible relation: epoleodomia.{name}")
            continue
        for column, kind in definition["columns"].items():
            if current["columns"].get(column) != kind:
                findings.append(f"Missing or incompatible column: epoleodomia.{name}.{column} (expected {kind})")
        for constraint in definition["constraints"]:
            if constraint not in current["constraints"]:
                findings.append(f"Missing constraint on epoleodomia.{name}: {constraint}")
        for column, attributes in definition.get("column_attributes", {}).items():
            if any(current.get("column_attributes", {}).get(column, {}).get(k) != v
                   for k, v in attributes.items()):
                findings.append(f"Incompatible column attributes: epoleodomia.{name}.{column}")
        accepted_views = ([definition["view_definition"]] + definition.get("view_definition_variants", [])
                          if "view_definition" in definition else [])
        if (accepted_views and current.get("view_definition") not in {v.strip() for v in accepted_views}):
            findings.append(f"View definition differs; review before replacement: epoleodomia.{name}")
        for index in definition.get("indexes", []):
            if index not in current.get("indexes", []):
                findings.append(f"Missing valid index on epoleodomia.{name}: {index}")
    for signature in expected.get("functions", []):
        cursor.execute("SELECT to_regprocedure(%s) IS NOT NULL", (signature,))
        if not cursor.fetchone()[0]:
            findings.append("Missing function: " + signature)
    lot = actual.get("building_regs_lot", {})
    if ("UNIQUE (objectid)" in lot.get("constraints", []) or any(
            index["unique"] and index["columns"] == ["objectid"] and index["predicate"] is None
            for index in lot.get("indexes", []))):
        findings.append("building_regs_lot must allow duplicate objectid values; review its UNIQUE constraint")
    return tuple(findings)


def upgrade_findings(cursor, pending):
    if pending and pending[0].contract is not None:
        contract = pending[0].contract
        findings = contract_findings(cursor, contract["before"])
        views = contract.get("recreated_views", [])
        if views:
            cursor.execute("""
                SELECT DISTINCT v.relname, dn.nspname, dependent.relname
                FROM pg_class v JOIN pg_namespace vn ON vn.oid = v.relnamespace
                JOIN pg_depend d ON d.refclassid = 'pg_class'::regclass AND d.refobjid = v.oid
                JOIN pg_rewrite r ON d.classid = 'pg_rewrite'::regclass AND r.oid = d.objid
                JOIN pg_class dependent ON dependent.oid = r.ev_class
                JOIN pg_namespace dn ON dn.oid = dependent.relnamespace
                WHERE vn.nspname = 'epoleodomia' AND v.relname = ANY(%s)
                  AND dependent.oid <> v.oid
                  AND NOT (dn.nspname = 'epoleodomia' AND dependent.relname = ANY(%s))
                ORDER BY 1,2,3
            """, (views, views))
            findings += tuple(f"External view depends on epoleodomia.{name}: {schema}.{dependent}"
                              for name, schema, dependent in cursor.fetchall())
            cursor.execute("""
                SELECT DISTINCT c.relname FROM pg_seclabel s
                JOIN pg_class c ON s.classoid = 'pg_class'::regclass AND c.oid = s.objoid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'epoleodomia' AND c.relname = ANY(%s)
                ORDER BY 1
            """, (views,))
            findings += tuple("Security labels need a separate preservation plan: epoleodomia." + r[0]
                              for r in cursor.fetchall())
            cursor.execute("""
                SELECT DISTINCT c.relname
                FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                CROSS JOIN LATERAL aclexplode(c.relacl) a
                WHERE n.nspname = 'epoleodomia' AND c.relname = ANY(%s) AND a.grantor <> c.relowner
                UNION
                SELECT DISTINCT c.relname
                FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                JOIN pg_attribute column_acl ON column_acl.attrelid = c.oid
                CROSS JOIN LATERAL aclexplode(column_acl.attacl) a
                WHERE n.nspname = 'epoleodomia' AND c.relname = ANY(%s) AND a.grantor <> c.relowner
                ORDER BY 1
            """, (views, views))
            findings += tuple("Non-owner grant chains need a separate preservation plan: epoleodomia." + r[0]
                              for r in cursor.fetchall())
        return findings
    return ()


def inspect_plan(cursor, migrations, *, adopt=False, manifest_path=BASELINE_MANIFEST):
    cursor.execute("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'postgis')")
    if not cursor.fetchone()[0]:
        return SetupPlan("blocked", (), ("PostGIS must be installed by the database administrator first",))
    cursor.execute("SELECT to_regclass(%s)", (LEDGER,))
    has_ledger = cursor.fetchone()[0] is not None
    if has_ledger:
        cursor.execute("SELECT version, filename, checksum, mode FROM " + LEDGER + " ORDER BY version")
        applied = cursor.fetchall()
        if not applied:
            return SetupPlan("blocked", (), ("Migration ledger is empty; investigate before proceeding",))
        if [r[0] for r in applied] != list(range(1, len(applied)+1)):
            return SetupPlan("blocked", (), ("Migration ledger contains gaps or invalid versions",))
        available = {m.version: m for m in migrations}
        seen_applied = False
        adopted_through = 0
        for version, filename, checksum, mode in applied:
            migration = available.get(version)
            if (migration is None or migration.filename != filename or migration.checksum != checksum
                    or mode not in ("applied", "adopted")
                    or (mode == "adopted" and seen_applied)):
                return SetupPlan("blocked", (), ("Migration history mismatch at version " + str(version),))
            if mode == "adopted":
                adopted_through = version
            seen_applied = seen_applied or mode == "applied"
        if adopted_through > 1 and available[adopted_through].contract is None:
            return SetupPlan("blocked", (), ("Adopted prefix has no declared final contract",))
        if adopt:
            return SetupPlan("blocked", (), ("This database is already managed; omit --adopt",))
        current = available[applied[-1][0]]
        pending = tuple(m for m in migrations if m.version > len(applied))
        findings = (contract_findings(cursor, current.contract["after"])
                    if current.contract is not None else ())
        findings += upgrade_findings(cursor, pending)
        return SetupPlan("managed", pending, findings)

    cursor.execute("""
        SELECT EXISTS (
            SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'epoleodomia'
            UNION ALL
            SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = 'epoleodomia'
            UNION ALL
            SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace WHERE n.nspname = 'epoleodomia'
        )
    """)
    occupied = cursor.fetchone()[0]
    if occupied:
        # Adopt the highest explicitly described compatible state. A later
        # adoption records its entire prefix; it never replays earlier DDL.
        latest_findings = None
        for migration in reversed(migrations[1:]):
            if migration.contract is None:
                continue
            candidate_findings = contract_findings(cursor, migration.contract["after"])
            if latest_findings is None:
                latest_findings = candidate_findings
            if not candidate_findings:
                findings = upgrade_findings(cursor, migrations[migration.version:])
                if not adopt:
                    findings += ("Existing unmanaged schema: explicitly use --adopt",)
                return SetupPlan("legacy", migrations, findings, migration.version)
        findings = baseline_findings(cursor, manifest_path)
        if not findings:
            findings = upgrade_findings(cursor, migrations[1:])
        elif latest_findings is not None:
            findings = latest_findings
        if not adopt:
            findings += ("Existing unmanaged schema: review findings, then explicitly use --adopt",)
        return SetupPlan("legacy", migrations, findings, 1)
    if adopt:
        return SetupPlan("blocked", (), ("Cannot adopt an empty schema; omit --adopt for a fresh installation",))
    return SetupPlan("new", migrations)


def run_setup(*, apply=False, adopt=False, migrations_dir=MIGRATIONS,
              manifest_path=BASELINE_MANIFEST, connect=None):
    """All changes and history commit together; inspection is read-only by default.

    connect is a keyword-only psycopg2-compatible connection factory for tests.
    Migration files are trusted, reviewed repository SQL, not user input. They
    must not contain transaction control or operations outside a transaction.
    """
    migrations = load_migrations(migrations_dir)
    factory = psycopg2.connect if connect is None else connect
    kwargs = SETTINGS.database.connection_kwargs()
    if not apply:
        kwargs["options"] = "-c default_transaction_read_only=on"
    conn = factory(**kwargs)
    failed = False
    try:
        conn.autocommit = False
        with conn.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE, READ WRITE" if apply else
                           "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cursor.execute("SET LOCAL search_path TO pg_catalog, public")
            if apply:
                cursor.execute("SET LOCAL lock_timeout = '5s'")
                cursor.execute("SET LOCAL statement_timeout = '120s'")
                cursor.execute("SELECT pg_try_advisory_xact_lock(%s, %s)", LOCK_KEY)
                if not cursor.fetchone()[0]:
                    raise SetupError("Another setup/upgrade is in progress; retry after it completes")
            plan = inspect_plan(cursor, migrations, adopt=adopt, manifest_path=manifest_path)
            if plan.findings or not apply or not plan.pending:
                return plan
            cursor.execute("CREATE SCHEMA IF NOT EXISTS epol_meta")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS epol_meta.schema_migrations (
                    version INTEGER PRIMARY KEY,
                    filename TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    mode TEXT NOT NULL CHECK (mode IN ('applied', 'adopted')),
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """)
            for migration in plan.pending:
                adopting = plan.state == "legacy" and migration.version <= (plan.adopt_version or 1)
                if not adopting:
                    if migration.contract is not None:
                        findings = upgrade_findings(cursor, (migration,))
                        if findings:
                            raise SetupError("Migration preconditions failed: " + "; ".join(findings))
                    cursor.execute(migration.statement)
                    if migration.version == 1:
                        findings = baseline_findings(cursor, manifest_path)
                        if findings:
                            raise SetupError("Fresh baseline does not match its manifest: " + "; ".join(findings))
                    if migration.contract is not None:
                        findings = contract_findings(cursor, migration.contract["after"])
                        if findings:
                            raise SetupError("Migration postconditions failed: " + "; ".join(findings))
                cursor.execute("INSERT INTO " + LEDGER +
                               " (version, filename, checksum, mode) VALUES (%s, %s, %s, %s)",
                               (migration.version, migration.filename, migration.checksum,
                                "adopted" if adopting else "applied"))
        conn.commit()
        return plan
    except BaseException:
        failed = True
        raise
    finally:
        cleanup_error = None
        try:
            conn.rollback()
        except Exception as exc:
            cleanup_error = exc
        try:
            conn.close()
        except Exception as exc:
            cleanup_error = cleanup_error or exc
        if cleanup_error is not None and not failed:
            raise cleanup_error


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Apply a reviewed plan in one transaction")
    parser.add_argument("--adopt", action="store_true", help="Record the compatible schema prefix without replaying it; apply reviewed later migrations")
    args = parser.parse_args(argv)
    db = SETTINGS.database
    print(f"Target: {db.host}:{db.port}/{db.database}; schema=epoleodomia")
    print("Mode: " + ("APPLY" if args.apply else "READ-ONLY PREVIEW"))
    try:
        plan = run_setup(apply=args.apply, adopt=args.adopt)
    except (SetupError, psycopg2.Error, OSError, ValueError) as exc:
        print("Setup failed: " + str(exc))
        return 1
    print("State: " + plan.state)
    for finding in plan.findings:
        print("  BLOCKED: " + finding)
    if plan.findings:
        return 1
    for migration in plan.pending:
        action = "adopt" if plan.state == "legacy" and migration.version <= (plan.adopt_version or 1) else "apply"
        print(f"  {action}: {migration.filename}")
    print("Completed." if args.apply else "Preview only. Re-run the reviewed command with --apply to write.")
    print("TEE schema only: sp_geodata sources, raster unification, data imports and post-sync seeds are separate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
