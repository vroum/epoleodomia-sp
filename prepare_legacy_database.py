"""Preview the reviewed installed-TEE preparation; writes require an exact plan and backup."""
from dataclasses import asdict, dataclass
import argparse
import hashlib
import json
from pathlib import Path
import re

import psycopg2
from psycopg2 import sql

import database_setup as setup
from settings import SETTINGS


RECIPE = Path(__file__).resolve().parent / 'sql/preparations/installed_tee_20261027.json'
RECEIPTS = 'epol_meta.schema_preparations'


@dataclass(frozen=True)
class Preparation:
    state: str
    target: dict
    plan_hash: str = ''
    findings: tuple = ()
    actions: tuple = ()
    owner: str = ''
    can_apply: bool = False
    applied: bool = False


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':')).encode('utf-8')).hexdigest()


def load_recipe(path=RECIPE):
    path = Path(path)
    raw = path.read_bytes()
    statement_raw = path.with_suffix('.sql').read_bytes()
    if any(v.startswith(b'\xef\xbb\xbf') or b'\r' in v for v in (raw, statement_raw)):
        raise setup.SetupError('Preparation files require UTF-8 without BOM and LF')
    recipe = json.loads(raw.decode('utf-8'))
    if not isinstance(recipe, dict):
        raise setup.SetupError('Invalid installed-schema preparation descriptor')
    if (recipe.get('format_version') != 1
            or recipe.get('preparation_id') != path.stem
            or not re.fullmatch(r'[a-z][a-z0-9_]+', recipe.get('preparation_id', ''))
            or not setup._valid_schema_contract(recipe.get('before'))
            or not re.fullmatch(r'[a-z][a-z0-9_]+', recipe.get('reader_role', ''))
            or recipe.get('target_version') != 2 or recipe.get('server_major') != 18
            or not isinstance(recipe.get('recreated_views'), list)
            or any(v not in recipe['before']['relations'] or
                   recipe['before']['relations'][v]['kind'] != 'v' for v in recipe['recreated_views'])):
        raise setup.SetupError('Invalid installed-schema preparation descriptor')
    if hashlib.sha256(statement_raw).hexdigest() != recipe.get('sql_sha256'):
        raise setup.SetupError('Preparation SQL checksum differs from its reviewed descriptor')
    migrations = setup.load_migrations()
    prefix = tuple(m for m in migrations if m.version <= recipe['target_version'])
    if {str(m.version): m.checksum for m in prefix} != recipe.get('migration_checksums'):
        raise setup.SetupError('Preparation target migration checksums differ from the reviewed versions')
    checksum = hashlib.sha256(statement_raw + b'\0epol-preparation\0' + raw).hexdigest()
    return recipe, statement_raw.decode('utf-8'), checksum, prefix


def check_backup(path, expected_sha256):
    """Confirm the selected local custom archive; logical restore is a separate runbook step."""
    if not path or not re.fullmatch(r'[0-9a-fA-F]{64}', expected_sha256 or ''):
        raise setup.SetupError('Apply requires --backup and its verified --backup-sha256')
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        if stream.read(5) != b'PGDMP':
            raise setup.SetupError('Backup is not a PostgreSQL custom-format archive')
        stream.seek(0)
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    if value.hexdigest() != expected_sha256.lower():
        raise setup.SetupError('Backup checksum mismatch; no database changes were attempted')
    return value.hexdigest()


def original_columns(structure, names):
    return {n: list(structure[n]['columns']) for n in names}


def data_fingerprints(cursor, columns, structure):
    result = {}
    for name, fields in sorted(columns.items()):
        if structure[name]['kind'] != 'r':
            continue
        cursor.execute(sql.SQL("""SELECT count(*),md5(COALESCE(string_agg(h,'' ORDER BY h),''))
            FROM (SELECT md5(row_to_json(t)::text) h FROM (SELECT {} FROM {}) t) z""").format(
                sql.SQL(',').join(map(sql.Identifier, fields)), sql.Identifier('epoleodomia', name)))
        result[name] = cursor.fetchone()
    return result


def preserved_metadata(cursor, columns, functions=None):
    """Normalize effective ACLs by role name; retain original-column metadata only."""
    names = list(columns)
    cursor.execute('SET LOCAL search_path TO pg_catalog,public')
    cursor.execute("""SELECT c.relname,c.relkind,pg_get_userbyid(c.relowner),c.reloptions,
            obj_description(c.oid,'pg_class'),c.relrowsecurity,c.relforcerowsecurity,
            c.relpersistence,c.relreplident,CASE WHEN c.relkind='r' THEN c.oid::bigint END
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='epoleodomia' AND c.relname=ANY(%s) ORDER BY 1""", (names,))
    result = {'relations': {}, 'functions': {}, 'indexes': {}, 'labels': []}
    for name, kind, owner, options, comment, rls, force_rls, persistence, replica, oid in cursor.fetchall():
        result['relations'][name] = dict(kind=kind, owner=owner, options=sorted(options or []),
            comment=comment, rls=rls, force_rls=force_rls, persistence=persistence,
            replica=replica, table_oid=oid, acl=[], columns={})
    cursor.execute("""SELECT c.relname,pg_get_userbyid(a.grantor),
            CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END,
            a.privilege_type,a.is_grantable
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        CROSS JOIN LATERAL aclexplode(COALESCE(c.relacl,acldefault('r',c.relowner))) a
        WHERE n.nspname='epoleodomia' AND c.relname=ANY(%s) ORDER BY 1,2,3,4,5""", (names,))
    for name, *acl in cursor.fetchall():
        result['relations'][name]['acl'].append(acl)
    cursor.execute("""SELECT c.relname,a.attname,col_description(c.oid,a.attnum),a.attnotnull,
            a.attgenerated,a.attidentity,pg_get_expr(d.adbin,d.adrelid)
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped
        LEFT JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum
        WHERE n.nspname='epoleodomia' AND c.relname=ANY(%s) ORDER BY 1,a.attnum""", (names,))
    for name, field, *attrs in cursor.fetchall():
        if field in columns[name]:
            result['relations'][name]['columns'][field] = dict(attributes=attrs, acl=[])
    cursor.execute("""SELECT c.relname,t.attname,pg_get_userbyid(a.grantor),
            CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END,
            a.privilege_type,a.is_grantable
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        JOIN pg_attribute t ON t.attrelid=c.oid
        CROSS JOIN LATERAL aclexplode(t.attacl) a
        WHERE n.nspname='epoleodomia' AND c.relname=ANY(%s) ORDER BY 1,2,3,4,5,6""", (names,))
    for name, field, *acl in cursor.fetchall():
        if field in columns[name]:
            result['relations'][name]['columns'][field]['acl'].append(acl)
    cursor.execute("""SELECT c.relname,s.objsubid,s.provider,s.label FROM pg_seclabel s
        JOIN pg_class c ON s.classoid='pg_class'::regclass AND s.objoid=c.oid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='epoleodomia' AND c.relname=ANY(%s) ORDER BY 1,2,3""", (names,))
    result['labels'] = cursor.fetchall()
    cursor.execute("""SELECT i.relname,t.relname,pg_get_indexdef(i.oid),obj_description(i.oid,'pg_class'),
            i.reloptions,pg_get_userbyid(i.relowner),x.indisvalid,x.indisready
        FROM pg_index x JOIN pg_class i ON i.oid=x.indexrelid JOIN pg_class t ON t.oid=x.indrelid
        JOIN pg_namespace n ON n.oid=t.relnamespace
        WHERE n.nspname='epoleodomia' AND t.relname=ANY(%s) ORDER BY 1""", (names,))
    result['indexes'] = {name: attrs for name, *attrs in cursor.fetchall()}
    cursor.execute("""SELECT p.oid::regprocedure::text,pg_get_functiondef(p.oid),
            pg_get_userbyid(p.proowner),obj_description(p.oid,'pg_proc'),
            ARRAY(SELECT ROW(pg_get_userbyid(a.grantor),
                CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END,
                a.privilege_type,a.is_grantable)::text
                FROM aclexplode(COALESCE(p.proacl,acldefault('f',p.proowner))) a
                ORDER BY 1)
        FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname='epoleodomia' ORDER BY 1""")
    result['functions'] = {name: attrs for name, *attrs in cursor.fetchall()
                           if functions is None or name in functions}
    cursor.execute("""SELECT pg_get_userbyid(n.nspowner),obj_description(n.oid,'pg_namespace'),
            pg_get_userbyid(a.grantor),
            CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END,
            a.privilege_type,a.is_grantable
        FROM pg_namespace n CROSS JOIN LATERAL
            aclexplode(COALESCE(n.nspacl,acldefault('n',n.nspowner))) a
        WHERE n.nspname='epoleodomia' ORDER BY 1,2,3,4,5,6""")
    result['schema'] = cursor.fetchall()
    cursor.execute("""SELECT d.defaclobjtype,COALESCE(s.nspname,'*'),
            pg_get_userbyid(a.grantor),
            CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END,
            a.privilege_type,a.is_grantable
        FROM pg_default_acl d JOIN pg_namespace n ON n.nspname='epoleodomia' AND n.nspowner=d.defaclrole
        LEFT JOIN pg_namespace s ON s.oid=d.defaclnamespace
        CROSS JOIN LATERAL aclexplode(d.defaclacl) a
        WHERE d.defaclnamespace IN (0,n.oid) ORDER BY 1,2,3,4,5,6""")
    result['default_privileges'] = cursor.fetchall()
    return result


def data_findings(cursor, target):
    findings = []
    for name, relation in target['relations'].items():
        if relation['kind'] != 'r':
            continue
        table = sql.Identifier('epoleodomia', name)
        if 'UNIQUE (objectid)' in relation['constraints']:
            cursor.execute(sql.SQL('SELECT 1 FROM {} WHERE objectid IS NOT NULL GROUP BY objectid HAVING count(*)>1 LIMIT 1').format(table))
            if cursor.fetchone():
                findings.append('Duplicate non-NULL objectid values: epoleodomia.' + name)
        if any(c.startswith('CHECK ((geometrytype(geom)') for c in relation['constraints']):
            cursor.execute(sql.SQL("SELECT 1 FROM {} WHERE geom IS NOT NULL AND GeometryType(geom) NOT IN ('POLYGON','MULTIPOLYGON') LIMIT 1").format(table))
            if cursor.fetchone():
                findings.append('Non-polygon geometry needs review: epoleodomia.' + name)
    return findings


def inspect(cursor, conn, recipe, statement, checksum, migrations):
    cursor.execute("SELECT current_database(),current_user,current_setting('server_version_num')::integer")
    database, executor, version = cursor.fetchone()
    dsn = conn.get_dsn_parameters()
    target = dict(host=dsn.get('host', ''), port=dsn.get('port', '5432'), database=database)
    cursor.execute('SELECT to_regclass(%s)', (setup.LEDGER,))
    if cursor.fetchone()[0] is not None:
        cursor.execute('SELECT to_regclass(%s)', (RECEIPTS,))
        if cursor.fetchone()[0] is None:
            return Preparation('blocked', target, findings=('Managed history exists; use database_setup.py instead of legacy preparation',)), None
        cursor.execute('SELECT checksum,target_version FROM ' + RECEIPTS + ' WHERE preparation_id=%s', (recipe['preparation_id'],))
        receipt = cursor.fetchone()
        if receipt != (checksum, recipe['target_version']):
            return Preparation('blocked', target, findings=('Preparation receipt is missing or its checksum differs',)), None
        plan = setup.inspect_plan(cursor, setup.load_migrations())
        findings = plan.findings + (('New migrations are pending; use database_setup.py',) if plan.pending else ())
        return Preparation('blocked' if findings else 'prepared', target, findings=findings), None
    cursor.execute("SELECT to_regnamespace('epol_meta')")
    if cursor.fetchone()[0] is not None:
        return Preparation('blocked', target, findings=('Unmanaged epol_meta schema needs review before preparation',)), None
    findings = []
    cursor.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (recipe['reader_role'],))
    if cursor.fetchone() is None:
        findings.append('Configured reader role is missing: ' + recipe['reader_role'])
    if version // 10000 != recipe['server_major']:
        findings.append('This legacy preparation was reviewed for PostgreSQL 18 only')
    contract = dict(before=recipe['before'], recreated_views=recipe['recreated_views'])
    findings += list(setup.upgrade_findings(cursor, (setup.Migration(0, '', '', '', contract),)))
    actual = setup.read_structure(cursor)
    for name, expected in recipe['before']['relations'].items():
        for constraint in actual.get(name, {}).get('constraints', []):
            if constraint not in expected['constraints']:
                findings.append('Unreviewed source constraint: epoleodomia.' + name)
    for name in recipe['must_be_absent']:
        if name in actual:
            findings.append('Unexpected existing preparation target: epoleodomia.' + name)
    target_contract = migrations[-1].contract['after']
    for name, relation in target_contract['relations'].items():
        before_indexes = recipe['before']['relations'].get(name, {}).get('indexes', [])
        for index in relation.get('indexes', []):
            if index not in before_indexes and index in actual.get(name, {}).get('indexes', []):
                findings.append('Partially installed target index needs review: epoleodomia.' + name)
    for name, columns in recipe.get('absent_columns', {}).items():
        for field in columns:
            if field in actual.get(name, {}).get('columns', {}):
                findings.append(f'Partial preparation needs review: epoleodomia.{name}.{field}')
    for signature in recipe.get('absent_functions', []):
        cursor.execute('SELECT to_regprocedure(%s)', (signature,))
        if cursor.fetchone()[0] is not None:
            findings.append('Unexpected existing preparation function: ' + signature)
    reserved = re.findall(r'CREATE (?:UNIQUE )?INDEX "(epol_reconcile_idx_[0-9]+)"', statement)
    reserved += re.findall(r'ADD CONSTRAINT "([^"]+)" UNIQUE', statement)
    cursor.execute("SELECT relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='epoleodomia' AND relname=ANY(%s)", (reserved,))
    findings += ['Reserved preparation index already exists: ' + r[0] for r in cursor.fetchall()]
    cursor.execute("SELECT evtname FROM pg_event_trigger WHERE evtenabled<>'D'")
    findings += ['Enabled DDL event trigger needs review: ' + r[0] for r in cursor.fetchall()]
    if findings:
        return Preparation('blocked', target, findings=tuple(findings)), None
    columns = original_columns(actual, recipe['before']['relations'])
    metadata = preserved_metadata(cursor, columns)
    cursor.execute("SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname='epoleodomia'")
    owner = cursor.fetchone()[0]
    if any(r['owner'] != owner for r in metadata['relations'].values()):
        findings.append('Mixed table/view ownership needs a separate reviewed preparation')
    cursor.execute("SELECT pg_has_role(current_user,%s,'SET'),has_database_privilege(%s,current_database(),'CREATE')", (owner, owner))
    can_set, can_create = cursor.fetchone()
    # Source-shape checks must finish before any source-row query can assume a
    # column/type exists. These are read-only even in an apply transaction.
    findings += data_findings(cursor, target_contract)
    row_counts = {}
    for name in columns:
        if actual[name]['kind'] == 'r':
            cursor.execute(sql.SQL('SELECT count(*) FROM {}').format(sql.Identifier('epoleodomia', name)))
            row_counts[name] = cursor.fetchone()[0]
    normalized = json.loads(json.dumps(actual))
    for relation in normalized.values():
        relation['indexes'] = sorted(relation['indexes'], key=lambda v: json.dumps(v, sort_keys=True))
    signature = digest(dict(target=target, checksum=checksum, owner=owner,
        structure={n: normalized[n] for n in columns}, metadata=metadata, row_counts=row_counts))
    plan = Preparation('blocked' if findings else 'ready', target, signature, tuple(findings),
                       tuple(recipe['summary']), owner, bool(can_set and can_create))
    return plan, dict(columns=columns, structure=actual, metadata=metadata, executor=executor)


def run_preparation(*, apply=False, expected_plan=None, backup_path=None,
                    backup_sha256=None, recipe_path=RECIPE, connect=None):
    recipe, statement, checksum, migrations = load_recipe(recipe_path)
    backup_hash = None
    if apply:
        if not re.fullmatch(r'[0-9a-fA-F]{64}', expected_plan or ''):
            raise setup.SetupError('Apply requires --expect-plan from a fresh reviewed preview')
        expected_plan = expected_plan.lower()
        backup_hash = check_backup(backup_path, backup_sha256)
    factory = psycopg2.connect if connect is None else connect
    kwargs = SETTINGS.database.connection_kwargs()
    if not apply:
        kwargs['options'] = '-c default_transaction_read_only=on'
    conn = factory(**kwargs)
    failed = False
    try:
        conn.autocommit = False
        with conn.cursor() as cur:
            # Fresh statement snapshots are intentional on apply: a writer may
            # finish while we wait for locks. Once all source relations are
            # locked, their data and DDL stay fixed through commit/rollback.
            cur.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED, READ WRITE' if apply else
                        'SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            cur.execute("SET LOCAL search_path TO pg_catalog,public; SET LOCAL lock_timeout='5s'; SET LOCAL statement_timeout='120s'")
            if apply:
                cur.execute('SELECT pg_try_advisory_xact_lock(%s,%s)', setup.LOCK_KEY)
                if not cur.fetchone()[0]:
                    raise setup.SetupError('Another schema operation is in progress')
                # Prevent source writes/DDL through preservation checks and
                # history publication. Sorted locking reduces lock inversions.
                cur.execute("SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='epoleodomia' AND c.relkind IN ('r','v') AND c.relname=ANY(%s) ORDER BY 1", (list(recipe['before']['relations']),))
                tables = [r[0] for r in cur.fetchall()]
                if tables:
                    cur.execute(sql.SQL('LOCK TABLE {} IN ACCESS EXCLUSIVE MODE').format(
                        sql.SQL(',').join(sql.Identifier('epoleodomia', n) for n in tables)))
            plan, context = inspect(cur, conn, recipe, statement, checksum, migrations)
            if plan.findings or not apply or plan.state == 'prepared':
                return plan
            if plan.plan_hash != expected_plan:
                raise setup.SetupError('Plan changed since preview; review a fresh preview before applying')
            if not plan.can_apply:
                raise setup.SetupError('The migration account cannot SET ROLE to the existing schema owner with database CREATE; keep the reader read-only')
            before_data = data_fingerprints(cur, context['columns'], context['structure'])
            cur.execute("SELECT set_config('epol.preparation_guard',%s,true)", (recipe['preparation_id'],))
            cur.execute(statement)
            findings = setup.contract_findings(cur, migrations[-1].contract['after'])
            if findings:
                raise setup.SetupError('Preparation postconditions failed: ' + '; '.join(findings))
            after_metadata = preserved_metadata(cur, context['columns'], context['metadata']['functions'])
            # New indexes are expected; every pre-existing index must survive.
            after_metadata['indexes'] = {n: after_metadata['indexes'].get(n) for n in context['metadata']['indexes']}
            if after_metadata != context['metadata']:
                raise setup.SetupError('Original ownership/grants/comments/defaults/functions or relation metadata changed')
            after_data = data_fingerprints(cur, context['columns'], context['structure'])
            if before_data != after_data:
                raise setup.SetupError('Original source values changed; preparation rolled back')
            cur.execute('CREATE SCHEMA epol_meta')
            cur.execute("""CREATE TABLE epol_meta.schema_migrations (
                version integer PRIMARY KEY,filename text NOT NULL,checksum text NOT NULL,
                mode text NOT NULL CHECK(mode IN ('applied','adopted')),
                applied_at timestamptz NOT NULL DEFAULT now())""")
            cur.execute("""CREATE TABLE epol_meta.schema_preparations (
                preparation_id text PRIMARY KEY,checksum text NOT NULL,target_version integer NOT NULL,
                reviewed_plan text NOT NULL,backup_sha256 text NOT NULL,data_fingerprint text NOT NULL,
                executed_by name NOT NULL,applied_at timestamptz NOT NULL DEFAULT now())""")
            reader = sql.Identifier(recipe['reader_role'])
            cur.execute(sql.SQL('GRANT USAGE ON SCHEMA epol_meta TO {}').format(reader))
            cur.execute(sql.SQL('GRANT SELECT ON TABLE epol_meta.schema_migrations,epol_meta.schema_preparations TO {}').format(reader))
            for migration in migrations:
                cur.execute('INSERT INTO '+setup.LEDGER+'(version,filename,checksum,mode) VALUES(%s,%s,%s,\'adopted\')',
                            (migration.version, migration.filename, migration.checksum))
            cur.execute('INSERT INTO '+RECEIPTS+'(preparation_id,checksum,target_version,reviewed_plan,backup_sha256,data_fingerprint,executed_by) VALUES(%s,%s,%s,%s,%s,%s,%s)',
                (recipe['preparation_id'], checksum, recipe['target_version'], plan.plan_hash,
                 backup_hash, digest(before_data), context['executor']))
        conn.commit()
        return Preparation(**dict(asdict(plan), state='prepared', applied=True))
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
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--expect-plan', help='SHA-256 shown by the reviewed preview')
    parser.add_argument('--backup', help='Fresh custom-format archive verified by a restore rehearsal')
    parser.add_argument('--backup-sha256', help='SHA-256 of that exact archive')
    parser.add_argument('--json', action='store_true', help='Emit a plan without connection secrets or row contents')
    args = parser.parse_args(argv)
    if args.apply and not all((args.expect_plan, args.backup, args.backup_sha256)):
        parser.error('--apply requires --expect-plan, --backup and --backup-sha256')
    try:
        plan = run_preparation(apply=args.apply, expected_plan=args.expect_plan,
                               backup_path=args.backup, backup_sha256=args.backup_sha256)
    except (setup.SetupError, psycopg2.Error, OSError, ValueError) as exc:
        print('Preparation failed: ' + str(exc))
        return 1
    if args.json:
        print(json.dumps(asdict(plan), ensure_ascii=False, indent=2))
    else:
        print('Target: {host}:{port}/{database}'.format(**plan.target))
        print('Mode: ' + ('APPLY' if args.apply else 'READ-ONLY PREVIEW'))
        print('State: ' + plan.state)
        for finding in plan.findings:
            print('  BLOCKED: ' + finding)
        for action in plan.actions:
            print('  ' + action)
        if plan.plan_hash:
            print('Reviewed plan: ' + plan.plan_hash)
            print('Required owner role: ' + plan.owner)
            print('This account can apply: ' + str(plan.can_apply))
        print('Committed.' if plan.applied else 'No changes written.')
    return 1 if plan.findings else 0


if __name__ == '__main__':
    raise SystemExit(main())
