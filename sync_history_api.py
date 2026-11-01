"""Read-only journal queries and local page; no sync or import endpoints."""
import calendar
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
import psycopg2

from database_sessions import read_only_snapshot
import sync_history as history
from sync_safety import LoadError


ATHENS = ZoneInfo('Europe/Athens')
PAGE = Path(__file__).resolve().parent / 'web' / 'sync_history.html'
ASSETS = {'sync_history.js': 'text/javascript', 'sync_history.css': 'text/css'}
DOMAIN_LABELS = {'tee': 'TEE · Πολεοδομία / Περιβάλλον', 'ktima': 'Κτηματολόγιο', 'ydro': 'Υδροληψίες ΕΜΣΥ'}


def date_range(period, start=None, end=None, *, today=None):
    today = today or datetime.now(ATHENS).date()
    if period not in ('4m', '1m', 'custom', 'latest'):
        raise ValueError('Unknown period')
    if period == 'custom':
        if not start or not end or start > end:
            raise ValueError('Επίλεξε έγκυρη αρχή και τέλος περιόδου.')
    else:
        months = 4 if period == '4m' else 1
        index = today.year * 12 + today.month - 1 - months
        year, month = divmod(index, 12)
        start = date(year, month + 1, min(today.day, calendar.monthrange(year, month + 1)[1]))
        end = today
    if end == date.max:
        raise ValueError('Η ημερομηνία λήξης είναι εκτός ορίων.')
    if (end - start).days > 3660:
        raise ValueError('Η περίοδος δεν μπορεί να ξεπερνά τα 10 έτη.')
    return (datetime.combine(start, time.min, ATHENS).astimezone(timezone.utc),
            datetime.combine(end + timedelta(days=1), time.min, ATHENS).astimezone(timezone.utc))


def _rows(query, statement, params=()):
    result = query(statement, params)
    names = [column.name for column in query.cursor.description]
    return [dict(zip(names, row)) for row in result]


def _label(row):
    row['label'] = history.LABELS.get(row['table_name'], row['table_name'].replace('_', ' '))
    row['domain_label'] = DOMAIN_LABELS[row['domain']]
    return row


def overview(query, *, period, start, end, domain, changed_only, offset, limit):
    if not history.installed(query.cursor):
        return {'installed': False, 'message': 'Η καταγραφή δεν έχει ενεργοποιηθεί ακόμη. Δεν εισάγονται παλιά JSON.'}
    config = query('SELECT started_at FROM epol_meta.sync_history_config WHERE singleton', fetch_one=True)[0]
    lower, upper = date_range(period, start, end)
    params = [lower, upper]
    condition = 'r.started_at >= %s AND r.started_at < %s'
    if period == 'latest':
        latest = query('''SELECT id FROM epol_meta.sync_history_runs r
            WHERE (%s='' OR r.mode IN (%s,'all')) ORDER BY started_at DESC,id DESC LIMIT 1''', (domain, domain))
        condition = 'r.id=%s::uuid'
        params = [str(latest[0][0]) if latest else '00000000-0000-0000-0000-000000000000']
    run_condition = condition + " AND (%s='' OR r.mode IN (%s,'all'))"
    run_params = [*params, domain, domain]
    counts = _rows(query, f'''SELECT status,count(*) count FROM epol_meta.sync_history_runs r
        WHERE {run_condition} GROUP BY status''', run_params)
    runs = _rows(query, f'''SELECT r.id::text,r.started_at,r.completed_at,r.mode,r.status,r.audit_id,r.error_message,
            COALESCE(sum(l.new_count),0)::bigint new,COALESCE(sum(l.updated_count),0)::bigint updated,
            COALESCE(sum(l.removed_count),0)::bigint removed,COALESCE(sum(l.geometry_count),0)::bigint geometry
        FROM epol_meta.sync_history_runs r LEFT JOIN epol_meta.sync_history_layers l
            ON l.run_id=r.id AND (%s='' OR l.domain=%s)
        WHERE {run_condition} GROUP BY r.id ORDER BY r.started_at DESC,r.id DESC LIMIT %s OFFSET %s''',
        [domain, domain, *run_params, limit, offset])
    layers = _rows(query, f'''WITH distinct_keys AS (
            SELECT c.domain,c.table_name,count(DISTINCT c.record_key) unique_records
            FROM epol_meta.sync_history_changes c JOIN epol_meta.sync_history_runs r ON r.id=c.run_id
            WHERE {condition} AND r.status='committed' AND c.change_type<>'source_id'
              AND (%s='' OR c.domain=%s) GROUP BY c.domain,c.table_name)
        SELECT l.domain,l.table_name,sum(l.new_count)::bigint new,sum(l.updated_count)::bigint updated,
            sum(l.removed_count)::bigint removed,sum(l.unchanged_count)::bigint unchanged,
            sum(l.geometry_count)::bigint geometry,sum(l.source_id_count)::bigint source_id,
            count(*)::integer syncs,COALESCE(max(k.unique_records),0)::bigint unique_records
        FROM epol_meta.sync_history_layers l JOIN epol_meta.sync_history_runs r ON r.id=l.run_id
            LEFT JOIN distinct_keys k USING(domain,table_name)
        WHERE {condition} AND r.status='committed' AND (%s='' OR l.domain=%s)
        GROUP BY l.domain,l.table_name
        HAVING NOT %s OR sum(l.new_count+l.updated_count+l.removed_count)>0
        ORDER BY l.domain,l.table_name''', [*params, domain, domain, *params, domain, domain, changed_only])
    # Totals include every layer even when the table displays changed ones only.
    totals = _rows(query, f'''SELECT COALESCE(sum(l.new_count),0)::bigint new,
        COALESCE(sum(l.updated_count),0)::bigint updated,COALESCE(sum(l.removed_count),0)::bigint removed,
        COALESCE(sum(l.geometry_count),0)::bigint geometry,
        COALESCE(sum(l.source_id_count),0)::bigint source_id
        FROM epol_meta.sync_history_layers l JOIN epol_meta.sync_history_runs r ON r.id=l.run_id
        WHERE {condition} AND r.status='committed' AND (%s='' OR l.domain=%s)''', [*params, domain, domain])[0]
    return {'installed': True, 'tracking_started_at': config, 'period_start': lower, 'period_end_exclusive': upper,
            'counts': {item['status']: item['count'] for item in counts}, 'totals': totals,
            'layers': [_label(row) for row in layers], 'runs': runs, 'offset': offset, 'limit': limit,
            'total_runs': sum(item['count'] for item in counts)}


def details(query, run_id, *, domain, table, kind, key, offset, limit):
    if not history.installed(query.cursor):
        raise HTTPException(409, 'Η καταγραφή δεν έχει ενεργοποιηθεί.')
    runs = _rows(query, 'SELECT id::text,started_at,completed_at,mode,status,error_message FROM epol_meta.sync_history_runs WHERE id=%s', (str(run_id),))
    if not runs:
        raise HTTPException(404, 'Ο συγχρονισμός δεν βρέθηκε.')
    layers = _rows(query, '''SELECT domain,table_name,source_records,new_count AS new,updated_count AS updated,
        removed_count AS removed,unchanged_count AS unchanged,geometry_count AS geometry,source_id_count AS source_id
        FROM epol_meta.sync_history_layers WHERE run_id=%s ORDER BY domain,table_name''', (str(run_id),))
    clause = """run_id=%s AND (%s='' OR domain=%s) AND (%s='' OR table_name=%s)
        AND (%s='' AND change_type<>'source_id' OR change_type=%s)
        AND (%s='' OR EXISTS (SELECT 1 FROM jsonb_each_text(record_key) k
            WHERE k.value ILIKE %s ESCAPE '\\'))"""
    # A literal substring search; %, _ and backslash in identifiers are not wildcards.
    escaped = key.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    params = (str(run_id), domain, domain, table, table, kind, kind, key, '%' + escaped + '%')
    total = query('SELECT count(*) FROM epol_meta.sync_history_changes WHERE ' + clause, params, fetch_one=True)[0]
    changes = _rows(query, '''SELECT id,domain,table_name,record_key,change_type,changed_fields,
        old_values,new_values,geometry_changed,old_source_id,new_source_id
        FROM epol_meta.sync_history_changes WHERE ''' + clause + ' ORDER BY id LIMIT %s OFFSET %s', (*params, limit, offset))
    return {'run': runs[0], 'layers': [_label(row) for row in layers], 'changes': [_label(row) for row in changes],
            'total_changes': total, 'offset': offset, 'limit': limit}


def create_router(pool_provider):
    router = APIRouter()

    def read(operation, **kwargs):
        try:
            with read_only_snapshot(pool_provider()) as query:
                query.cursor.execute("SET LOCAL statement_timeout='15s'")
                query.cursor.execute("SET LOCAL lock_timeout='3s'")
                return operation(query, **kwargs)
        except (psycopg2.Error, LoadError):
            raise HTTPException(503, 'Το ιστορικό δεν είναι διαθέσιμο. Έλεγξε τη σύνδεση και το setup_sync_history.py.') from None
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    @router.get('/sync-history', include_in_schema=False)
    def page():
        return FileResponse(PAGE, media_type='text/html', headers={
            'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
            'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"})

    @router.get('/sync-history/assets/{name}', include_in_schema=False)
    def asset(name: str):
        if name not in ASSETS:
            raise HTTPException(404)
        return FileResponse(PAGE.parent / name, media_type=ASSETS[name],
                            headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})

    @router.get('/sync-history/api/overview')
    def get_overview(period: str = Query('4m', pattern='^(4m|1m|custom|latest)$'),
                     start: date | None = None, end: date | None = None,
                     domain: str = Query('', pattern='^(|tee|ktima|ydro)$'), changed_only: bool = True,
                     offset: int = Query(0, ge=0, le=1000000), limit: int = Query(25, ge=1, le=100)):
        return read(overview, period=period, start=start, end=end, domain=domain,
                    changed_only=changed_only, offset=offset, limit=limit)

    @router.get('/sync-history/api/runs/{run_id}')
    def get_details(run_id: UUID, domain: str = Query('', pattern='^(|tee|ktima|ydro)$'),
                    table: str = Query('', max_length=100), kind: str = Query('', pattern='^(|new|updated|removed|source_id)$'),
                    key: str = Query('', max_length=200), offset: int = Query(0, ge=0, le=1000000),
                    limit: int = Query(25, ge=1, le=100)):
        return read(details, run_id=run_id, domain=domain, table=table, kind=kind, key=key, offset=offset, limit=limit)

    return router
