"""Collect selected GIS domains, then publish them in one database transaction.

Preview is the default. Raster files/NAS copies are a separate subsequent step.
External services do not expose a common snapshot; this guarantees database
publication, not simultaneous source capture or legal correctness.
"""
import argparse
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import uuid

import psycopg2
from psycopg2 import extensions, sql

from config import SERVICES
import load_postgis as tee_load
import sync_kaek_operating as cadastre
import sync_ydrolipsies as emsy
from fetch_layer import fetch_all_layer_data
from settings import PROJECT_DIR, load_sync_database
from sync_access import ROLE, inspect_target, verify_access
from sync_safety import LoadError, SyncError, validate_features
import sync_history as history


DOMAINS = {'tee': ('tee',), 'ktima': ('ktima',), 'ydro': ('ydro',),
           'all': ('tee', 'ktima', 'ydro')}
LOCK_KEY = (2100, 1784900002)
LOT = ('epoleodomia', 'building_regs_lot')


class CommitOutcomeUnknown(LoadError):
    """A lost/interrupted COMMIT response requires checking the database first."""

    def __init__(self, message, audit_id):
        super().__init__(message)
        self.audit_id = audit_id


@dataclass(frozen=True)
class PreparedLayer:
    domain: str
    table: str
    payload: object
    fields: tuple = ()
    service: str = ''
    layer_id: int | None = None


def targets(mode):
    domains = DOMAINS[mode]
    result = set()
    if 'tee' in domains:
        result.update(('tee', item['table']) for service in SERVICES.values() for item in service['layers'])
    if 'ktima' in domains:
        result.update(('ktima', table) for table in cadastre.LAYERS)
    if 'ydro' in domains:
        result.add(('ydro', 'ydrolipsies_emsy'))
    return result


def collect(mode):
    """Finish all HTTP downloads and source validation before any data SQL."""
    layers = []
    if 'tee' in DOMAINS[mode]:
        for name, service in SERVICES.items():
            for item in service['layers']:
                print(f"Collecting TEE {item['table']}", flush=True)
                payload = fetch_all_layer_data(service['url'], item['id'])
                validate_features(payload, require_unique_ids=item['table'] != LOT[1])
                layers.append(PreparedLayer('tee', item['table'], payload,
                                            service=name, layer_id=item['id']))
    if 'ktima' in DOMAINS[mode]:
        for table, service in cadastre.LAYERS.items():
            fields, rows = cadastre.prepare_layer(table, service)
            if not rows:
                raise LoadError(f'{table}: empty cadastral source; entire publication cancelled')
            layers.append(PreparedLayer('ktima', table, rows, tuple(fields), service))
    if 'ydro' in DOMAINS[mode]:
        payload = emsy._validate_features(emsy.fetch_features(emsy.DEFAULT_BBOX))
        layers.append(PreparedLayer('ydro', 'ydrolipsies_emsy', payload))
    validate_bundle(mode, layers)
    return layers


def validate_bundle(mode, layers):
    keys = [(layer.domain, layer.table) for layer in layers]
    if len(set(keys)) != len(keys) or set(keys) != targets(mode):
        raise LoadError('Publication bundle must contain each selected layer exactly once')
    for layer in layers:
        if layer.domain == 'tee':
            validate_features(layer.payload, require_unique_ids=layer.table != LOT[1])
        elif layer.domain == 'ktima':
            if not layer.fields or not layer.payload:
                raise LoadError(f'{layer.table}: empty cadastral source or metadata')
        else:
            emsy._validate_features(layer.payload)


def preflight(conn, mode, *, applying):
    """Read metadata/privileges; preview takes no publication/advisory locks."""
    with conn.cursor() as cur:
        cur.execute('SELECT current_user')
        if cur.fetchone() != (ROLE,):
            raise LoadError('Publication must authenticate as epol_sync')
        inspect_target(cur)
        verify_access(cur)
        cur.execute("SELECT has_table_privilege(%s,'epoleodomia.building_regs_lot','DELETE')", (ROLE,))
        lot_delete = cur.fetchone()[0]
        if applying and 'tee' in DOMAINS[mode] and not lot_delete:
            raise LoadError('Atomic TEE publication requires the reviewed lot DELETE grant; '
                            'run enable_sync_publication.py with the schema owner first')
    return {'lot_delete_granted': lot_delete,
            'ready': 'tee' not in DOMAINS[mode] or lot_delete}


def _lock_targets(conn, mode):
    relations = sorted({('epoleodomia' if domain == 'tee' else 'sp_geodata', table)
                        for domain, table in targets(mode)})
    if 'tee' in DOMAINS[mode]:
        relations.append(('epoleodomia', 'raster_catalog'))
        relations.sort()
    with conn.cursor() as cur:
        cur.execute("SET LOCAL lock_timeout='5s'")
        cur.execute("SET LOCAL statement_timeout='120s'")
        cur.execute("SET LOCAL idle_in_transaction_session_timeout='60s'")
        for schema, table in relations:
            target = sql.Identifier(schema, table)
            # Catalog UPDATE rights are column-scoped. Keep that restriction:
            # parent/source tables serialize writers, while ordinary catalog
            # DML takes row locks and preserves concurrent manual columns.
            mode = 'ACCESS SHARE' if (schema, table) == ('epoleodomia', 'raster_catalog') else 'SHARE ROW EXCLUSIVE'
            cur.execute(sql.SQL('LOCK TABLE {} IN ' + mode + ' MODE').format(target))
            name = schema + '.' + table
            cur.execute('''SELECT relkind,relrowsecurity,relhasrules FROM pg_class
                           WHERE oid=to_regclass(%s)''', (name,))
            if cur.fetchone() != ('r', False, False):
                raise LoadError(f'{name}: ordinary table without row security/rules required')
            cur.execute('''SELECT 1 FROM pg_trigger WHERE tgrelid=to_regclass(%s) AND NOT tgisinternal
                UNION ALL SELECT 1 FROM pg_inherits
                    WHERE inhrelid=to_regclass(%s) OR inhparent=to_regclass(%s)''', (name, name, name))
            if cur.fetchone():
                raise LoadError(f'{name}: custom triggers or inheritance require publication review')
            if (schema, table) == LOT:
                cur.execute("SELECT 1 FROM pg_constraint WHERE contype='f' AND confrelid=to_regclass(%s)", (name,))
                if cur.fetchone():
                    raise LoadError('Lot foreign-key consumers require review before DELETE replacement')
    return relations


def publish_bundle(conn, mode, layers, *, history_id=None):
    """Own exactly one transaction; borrowed loaders never commit/close it."""
    validate_bundle(mode, layers)
    if conn.autocommit or conn.get_transaction_status() != extensions.TRANSACTION_STATUS_IDLE:
        raise LoadError('Publication requires a fresh non-autocommit connection')
    started = time.monotonic()
    result = {'status': 'publishing', 'mode': mode, 'tables': [], 'timings_seconds': {}}
    try:
        _lock_targets(conn, mode)
        result['timings_seconds']['locks_and_guards'] = time.monotonic() - started
        audit_id = tee_load.start_sync_run('publication_' + mode, connection=conn)
        if audit_id is None:
            raise LoadError('Publication audit table is required')
        totals = dict(new=0, updated=0, deleted=0, tables_synced=0)
        for layer in layers:
            item_started = time.monotonic()
            item = {'domain': layer.domain, 'table': layer.table}
            if history_id:
                history.capture_before(conn, layer.domain, layer.table)
            if layer.domain == 'tee':
                count = len(layer.payload['features'])
                if not count:
                    stats = dict(new=0, updated=0, deleted=0, unchanged=0, errors=0)
                    status = 'empty'
                elif layer.table == LOT[1]:
                    inserted = tee_load.load_geojson_to_table(layer.payload, layer.table,
                        connection=conn, replace_via_delete=True)
                    if inserted != count:
                        raise LoadError(f'{layer.table}: incomplete replacement')
                    stats = dict(new=0, updated=0, deleted=0, unchanged=0, errors=0, replaced=inserted)
                    status = 'replaced'
                else:
                    stats = tee_load.load_geojson_with_tracking(layer.payload, layer.table,
                        sync_run_id=audit_id, connection=conn)
                    if stats.get('errors') or sum(stats.get(k, 0) for k in ('new', 'updated', 'unchanged')) != count:
                        raise LoadError(f'{layer.table}: incomplete tracked load')
                    status = 'success'
                if count:
                    tee_load.post_sync_recalculate(layer.table, connection=conn)
                tee_load.log_sync(layer.table, layer.service, layer.layer_id, count, status,
                    sync_started=datetime.now(), sync_completed=datetime.now(), connection=conn)
                for key in ('new', 'updated', 'deleted'):
                    totals[key] += stats[key]
                totals['tables_synced'] += 1
                item.update(stats=stats, source_records=count, status=status)
            elif layer.domain == 'ktima':
                success, diff = cadastre._replace_layer(conn, layer.table, layer.fields, layer.payload, commit=False)
                if not success:
                    raise LoadError(f'{layer.table}: cadastral publication failed')
                item.update(source_records=len(layer.payload), diff=diff)
            else:
                item.update(source_records=len(layer.payload), stats=emsy.load(layer.payload, connection=conn))
            item['seconds'] = time.monotonic() - item_started
            if history_id:
                item['history'] = history.capture_after(conn, history_id, layer.domain, layer.table, item['source_records'])
            result['tables'].append(item)
        totals['tables_synced'] = len(layers)
        tee_load.complete_sync_run(audit_id, totals, connection=conn)
        result['audit_id'] = audit_id
        result['audit_counter_scope'] = 'TEE tracked rows; lot replacements and other domains are detailed per table'
        if history_id:
            history.complete(conn, history_id, audit_id)
            result['history_id'] = history_id
        commit_started = time.monotonic()
        try:
            conn.commit()
        except BaseException as exc:
            raise CommitOutcomeUnknown('COMMIT acknowledgement was lost or rejected; '
                f'inspect sync_runs id={audit_id} and data before retrying this publication', audit_id) from exc
        result['status'] = 'committed'
        result['timings_seconds']['transaction'] = time.monotonic() - started
        result['timings_seconds']['commit'] = time.monotonic() - commit_started
        return result
    except BaseException:
        try:
            conn.rollback()
        except psycopg2.Error:
            pass  # Preserve the original error/outcome; caller closes connection.
        raise


def run(mode, database, *, apply=False, check_only=False, collector=None, connect=None):
    connect = psycopg2.connect if connect is None else connect
    options = '-c statement_timeout=120000 -c lock_timeout=5000'
    if not apply:
        options += ' -c default_transaction_read_only=on'
    with closing(connect(**database.connection_kwargs(), options=options)) as conn:
        conn.autocommit = True
        access = preflight(conn, mode, applying=apply)
        if check_only:
            return {'status': 'checked', 'mode': mode, 'access': access}
        if apply:
            # Session lock spans collection and publication, so an earlier
            # capture cannot overtake a newer atomic publisher. Close releases
            # this lock on success, interruption and every failure path.
            with conn.cursor() as cur:
                cur.execute('SELECT pg_try_advisory_lock(%s,%s)', LOCK_KEY)
                if not cur.fetchone()[0]:
                    raise LoadError('Another atomic publication is already running')
        history_id = None
        try:
            if apply:
                with conn.cursor() as cur:
                    enabled = history.installed(cur)
                if enabled:
                    history_id = history.begin(conn, mode)
            captured = time.monotonic()
            layers = (collect if collector is None else collector)(mode)
            validate_bundle(mode, layers)
            collection_seconds = time.monotonic() - captured
            if not apply:
                return {'status': 'preview', 'mode': mode, 'access': access,
                        'layers': len(layers), 'collection_seconds': collection_seconds}
            conn.autocommit = False
            options = {'history_id': history_id} if history_id else {}
            result = publish_bundle(conn, mode, layers, **options)
            result['timings_seconds']['collection'] = collection_seconds
            return result
        except BaseException as exc:
            if history_id:
                message = str(exc).replace(database.password, '<redacted>') if database.password else str(exc)
                try:
                    # A fresh connection also resolves a lost COMMIT response:
                    # committed rows cannot be overwritten by fail().
                    with closing(connect(**database.connection_kwargs(), options=options_for_failure())) as journal:
                        journal.autocommit = True
                        history.fail(journal, history_id, message, unknown=isinstance(exc, CommitOutcomeUnknown))
                except Exception:
                    print(f'History attempt {history_id}: could not confirm final status; inspect before retrying.', flush=True)
                setattr(exc, 'history_id', history_id)
            raise


def options_for_failure():
    return '-c statement_timeout=10000 -c lock_timeout=5000'


def print_summary(result):
    if result['status'] != 'committed':
        return
    rows = [(item['table'], item['history']) for item in result.get('tables', []) if 'history' in item]
    if not rows:
        print('Detailed history is not enabled. Preview: python setup_sync_history.py')
        return
    print('\nCommitted changes (geometry is a subset of updated):')
    for table, counts in rows:
        if counts['new'] or counts['updated'] or counts['removed']:
            print(f"  {table}: +{counts['new']} / ~{counts['updated']} / -{counts['removed']} (geometry {counts['geometry']})")
    totals = {key: sum(c[key] for _, c in rows) for key in ('new','updated','removed','source_id')}
    print(f"Total: +{totals['new']} / ~{totals['updated']} / -{totals['removed']}; source-ID-only: {totals['source_id']}")
    print('History: http://127.0.0.1:8000/sync-history')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=tuple(DOMAINS))
    parser.add_argument('--apply', action='store_true', help='Publish the complete selected bundle atomically')
    parser.add_argument('--check', action='store_true', help='Read-only access check; no HTTP downloads')
    parser.add_argument('--report', type=Path, help='JSON receipt path (preview/failure/commit is explicit)')
    args = parser.parse_args(argv)
    if args.check and args.apply:
        parser.error('--check cannot write; do not combine with --apply')
    report = args.report or PROJECT_DIR / 'logs' / ('publication_' + datetime.now().strftime('%Y%m%d_%H%M%S_') + uuid.uuid4().hex[:8] + '.json')
    database = None
    try:
        database = load_sync_database()
        result = run(args.mode, database, apply=args.apply, check_only=args.check)
    except (Exception, KeyboardInterrupt) as exc:
        message = str(exc)
        if database is not None and database.password:
            message = message.replace(database.password, '<redacted>')
        result = {'status': 'commit_unknown' if isinstance(exc, CommitOutcomeUnknown) else 'failed',
                  'mode': args.mode, 'error': message,
                  'interrupted': isinstance(exc, KeyboardInterrupt)}
        if isinstance(exc, CommitOutcomeUnknown):
            result['audit_id'] = exc.audit_id
        if getattr(exc, 'history_id', None):
            result['history_id'] = exc.history_id
    result['recorded_at'] = datetime.now(timezone.utc).isoformat()
    try:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf-8')
    except OSError as exc:
        print(f"Publication status: {result['status']}; could not save receipt: {exc}")
        return 1
    print(f"Publication status: {result['status']}; receipt: {report}")
    print_summary(result)
    if result.get('error'):
        print(result['error'])
    return 0 if result['status'] in ('committed', 'preview', 'checked') else 130 if result.get('interrupted') else 1


if __name__ == '__main__':
    raise SystemExit(main())
