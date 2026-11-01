"""Forward-only business changes, written in the GIS publication transaction.

Temporary before-images are discarded on commit/rollback. Only changed records
are retained. Import sequence values, timestamps and ring order are not changes.
No code in this module reads old receipts or changelog files.
"""
from uuid import uuid4

from psycopg2 import sql

from sync_safety import LoadError


TABLES = ('sync_history_config', 'sync_history_runs', 'sync_history_layers', 'sync_history_changes')
RELATIONS = tuple(('epol_meta', name) for name in TABLES)
WRITE_SCOPE = {('epol_meta', 'sync_history_runs'): {'INSERT', 'UPDATE'},
               ('epol_meta', 'sync_history_layers'): {'INSERT'},
               ('epol_meta', 'sync_history_changes'): {'INSERT'}}
CADASTRE_KEYS = {'kaek_parcels_operating': ('kaek',),
                 'kaek_douleies_operating': ('kaek', 'right_sn'),
                 'kaek_apokleistikes_operating': ('kaek', 'vp_num')}
LABELS = {
    'kaek_parcels_operating': 'Κτηματολόγιο · Γεωτεμάχια',
    'kaek_douleies_operating': 'Κτηματολόγιο · Δουλείες',
    'kaek_apokleistikes_operating': 'Κτηματολόγιο · Αποκλειστικές χρήσεις',
    'ydrolipsies_emsy': 'Υδροληψίες ΕΜΣΥ',
    'forest_maps': 'Δασικοί χάρτες · Κυρωμένοι',
    'forest_maps_posted_attica_2021': 'Δασικοί χάρτες · Αναρτημένοι Αττικής',
    'forest_maps_posted_pelop_2022': 'Δασικοί χάρτες · Αναρτημένοι Πελοποννήσου',
    'building_blocks': 'Οικοδομικά τετράγωνα',
    'building_regs_lot': 'Αρτιότητα οικοπέδων',
    'building_regs_coefficient': 'Συντελεστής δόμησης',
    'building_regs_coverage': 'Κάλυψη', 'building_regs_height': 'Ύψος κτιρίων',
    'planning_diagrams': 'Διαγράμματα ΦΕΚ', 'natura_2000': 'Natura 2000',
    'ab_zones_attica': 'Ζώνες Α / Β Αττικής', 'addresses': 'Διευθύνσεις',
    'approved_plan_boundaries': 'Όρια εγκεκριμένων σχεδίων',
    'archaeological_zones_pl': 'Αρχαιολογικές ζώνες σχεδίου',
    'block_vertices': 'Κορυφές οικοδομικών τετραγώνων', 'building_lines': 'Οικοδομικές γραμμές',
    'building_regs_coefficient_zones': 'Ζώνες συντελεστή δόμησης', 'building_regs_system': 'Σύστημα δόμησης',
    'census_blocks_2021': 'Απογραφικά τετράγωνα 2021', 'expropriation_zones': 'Ζώνες απαλλοτρίωσης',
    'fek_no_diagrams': 'ΦΕΚ χωρίς διαγράμματα', 'land_uses_ers': 'Χρήσεις γης · ΕΡΣ',
    'land_uses_gps': 'Χρήσεις γης · ΓΠΣ', 'municipal_communities_2021': 'Δημοτικές κοινότητες 2021',
    'municipal_units_2021': 'Δημοτικές ενότητες 2021', 'municipalities_2021': 'Δήμοι 2021',
    'other_planning_lines': 'Λοιπές πολεοδομικές γραμμές', 'other_planning_zones': 'Λοιπές πολεοδομικές ζώνες',
    'outside_plan_areas': 'Εκτός σχεδίου περιοχές', 'pd_protection_zones': 'Ζώνες προστασίας ΠΔ',
    'pedestrian_zones': 'Πεζόδρομοι', 'planning_lines': 'Ρυμοτομικές γραμμές',
    'protected_buildings': 'Διατηρητέα κτίρια', 'public_spaces': 'Κοινόχρηστοι χώροι',
    'settlement_boundaries': 'Όρια οικισμών', 'settlements_2021': 'Οικισμοί 2021',
    'shorelines': 'Αιγιαλός / παραλία', 'streams': 'Ρέματα · Πολεοδομία',
    'streams_environmental': 'Ρέματα · Περιβαλλοντικά', 'urban_units': 'Πολεοδομικές ενότητες',
    'zoe_zones': 'Ζώνες οικιστικού ελέγχου',
}
for _prefix, _label_text in (
    ('archaeological_sites', 'Αρχαιολογικοί χώροι'), ('historic_sites', 'Ιστορικοί τόποι'),
    ('monuments', 'Μνημεία'), ('protection_zones', 'Ζώνες προστασίας')):
    for _suffix, _shape_label in (('points', 'σημεία'), ('lines', 'γραμμές'), ('polygons', 'επιφάνειες')):
        LABELS[_prefix + '_' + _suffix] = _label_text + ' · ' + _shape_label
LABELS.update(natural_landscapes_points='Τοπία φυσικού κάλλους · σημεία',
              natural_landscapes_polygons='Τοπία φυσικού κάλλους · επιφάνειες')


def installed(cur):
    """Absent is supported; a partial/unknown installation must fail closed."""
    cur.execute('SELECT to_regclass(name) IS NOT NULL FROM unnest(%s::text[]) name',
                (['epol_meta.' + name for name in TABLES],))
    present = [row[0] for row in cur.fetchall()]
    if not any(present):
        return False
    if len(present) != len(TABLES) or not all(present):
        raise LoadError('Incomplete sync history installation; run setup_sync_history.py')
    cur.execute('SELECT version FROM epol_meta.sync_history_config WHERE singleton')
    if cur.fetchall() != [(1,)]:
        raise LoadError('Unsupported sync history version')
    return True


def begin(conn, mode):
    """Called in autocommit after acquiring the publication session lock."""
    run_id = str(uuid4())
    with conn.cursor() as cur:
        cur.execute("INSERT INTO epol_meta.sync_history_runs(id,mode,status) VALUES (%s,%s,'collecting')",
                    (run_id, mode))
    return run_id


def fail(conn, run_id, message, *, unknown=False):
    """Never replace a committed result after losing its COMMIT acknowledgement."""
    with conn.cursor() as cur:
        cur.execute('''UPDATE epol_meta.sync_history_runs SET status=%s,
            completed_at=clock_timestamp(),error_message=%s WHERE id=%s AND status='collecting' ''',
            ('commit_unknown' if unknown else 'failed', message[:2000], run_id))


def _source(cur, domain, table):
    schema = 'epoleodomia' if domain == 'tee' else 'sp_geodata'
    # Inputs are fixed publication targets, not web parameters.
    cur.execute('''SELECT attname,attgenerated FROM pg_attribute
        WHERE attrelid=to_regclass(%s) AND attnum>0 AND NOT attisdropped''', (schema + '.' + table,))
    columns = dict(cur.fetchall())
    keys = CADASTRE_KEYS[table] if domain == 'ktima' else ('objectid', 'oros_type') if table == 'building_regs_lot' else ('objectid',)
    if not set((*keys, 'objectid', 'geom')).issubset(columns):
        raise LoadError(f'{schema}.{table}: stable history key/geometry columns missing')
    ignored = {'geom', 'fetched_at', 'created_at', 'updated_at', 'synced_at', 'deleted_at', 'is_deleted'}
    ignored.update(name for name, generated in columns.items() if generated)
    if domain == 'tee':
        ignored.add('id')  # Import PK; cadastre's source field named id IS meaningful.
        if table.startswith('forest_maps'):
            ignored.add('area_m2')  # Derived by post-sync recalculation.
    else:
        ignored.add('gid')
    if domain == 'ktima':
        ignored.add('objectid')  # Source service can renumber the same KAEK.
    key_expr = sql.SQL('jsonb_build_object({})').format(sql.SQL(',').join(
        sql.SQL('{},t.{}').format(sql.Literal(k), sql.Identifier(k)) for k in keys))
    active = sql.SQL('WHERE NOT COALESCE(t.is_deleted,false)') if 'is_deleted' in columns else sql.SQL('')
    query = sql.SQL('''SELECT {key} AS record_key, to_jsonb(t)-{ignore}::text[] AS attrs,
        t.geom, t.objectid::text AS source_id FROM {target} t {active}''').format(
        key=key_expr, ignore=sql.Literal(sorted(ignored)), target=sql.Identifier(schema, table), active=active)
    # The NULL classification of a lot is a valid distinct variant.
    required = tuple(k for k in keys if k != 'oros_type')
    return query, required


def _snapshot(cur, name, query, required):
    cur.execute(sql.SQL('CREATE TEMP TABLE {} ON COMMIT DROP AS {}').format(sql.Identifier(name), query))
    cur.execute(sql.SQL('SELECT 1 FROM {} WHERE {} LIMIT 1').format(sql.Identifier(name), sql.SQL(' OR ').join(
        sql.SQL("NULLIF(btrim(record_key->>{}), '') IS NULL").format(sql.Literal(k)) for k in required)))
    if cur.fetchone():
        raise LoadError('Missing stable record identity; publication cancelled before history can be ambiguous')
    cur.execute(sql.SQL('SELECT 1 FROM {} GROUP BY record_key HAVING count(*)>1 LIMIT 1').format(sql.Identifier(name)))
    if cur.fetchone():
        raise LoadError('Duplicate stable record identity; publication cancelled rather than guessing changes')
    cur.execute(sql.SQL('CREATE UNIQUE INDEX ON {} (record_key)').format(sql.Identifier(name)))


def capture_before(conn, domain, table):
    with conn.cursor() as cur:
        query, required = _source(cur, domain, table)
        _snapshot(cur, 'epol_history_before', query, required)


def capture_after(conn, run_id, domain, table, source_records):
    """Diff the actual publication result, including retained empty-source tables."""
    with conn.cursor() as cur:
        query, required = _source(cur, domain, table)
        _snapshot(cur, 'epol_history_after', query, required)
        cur.execute('''CREATE TEMP TABLE epol_history_diff ON COMMIT DROP AS
            SELECT COALESCE(o.record_key,n.record_key) record_key,
                CASE WHEN o.record_key IS NULL THEN 'new'
                     WHEN n.record_key IS NULL THEN 'removed'
                     WHEN o.attrs IS DISTINCT FROM n.attrs OR
                          CASE WHEN o.geom IS NULL OR n.geom IS NULL THEN (o.geom IS NULL) <> (n.geom IS NULL)
                               ELSE NOT ST_Equals(o.geom,n.geom) END THEN 'updated'
                     WHEN o.source_id IS DISTINCT FROM n.source_id THEN 'source_id'
                     ELSE 'unchanged' END change_type,
                o.attrs old_values,n.attrs new_values,o.geom old_geom,n.geom new_geom,
                o.source_id old_source_id,n.source_id new_source_id,
                (o.record_key IS NOT NULL AND n.record_key IS NOT NULL AND
                    CASE WHEN o.geom IS NULL OR n.geom IS NULL THEN (o.geom IS NULL) <> (n.geom IS NULL)
                         ELSE NOT ST_Equals(o.geom,n.geom) END) geometry_changed
            FROM epol_history_before o FULL JOIN epol_history_after n USING(record_key)''')
        cur.execute('''SELECT count(*) FILTER (WHERE change_type='new'),
            count(*) FILTER (WHERE change_type='updated'),count(*) FILTER (WHERE change_type='removed'),
            count(*) FILTER (WHERE change_type IN ('unchanged','source_id')),
            count(*) FILTER (WHERE geometry_changed),count(*) FILTER (WHERE change_type='source_id')
            FROM epol_history_diff''')
        counts = dict(zip(('new', 'updated', 'removed', 'unchanged', 'geometry', 'source_id'), cur.fetchone()))
        cur.execute('''INSERT INTO epol_meta.sync_history_layers VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                    (run_id, domain, table, source_records, *counts.values()))
        cur.execute('''INSERT INTO epol_meta.sync_history_changes
            (run_id,domain,table_name,record_key,change_type,changed_fields,old_values,new_values,
             geometry_changed,old_geom,new_geom,old_source_id,new_source_id)
            SELECT %s,%s,%s,record_key,change_type,
                ARRAY(SELECT key FROM (SELECT jsonb_object_keys(COALESCE(old_values,'{}')) key
                    UNION SELECT jsonb_object_keys(COALESCE(new_values,'{}'))) fields
                    WHERE old_values->key IS DISTINCT FROM new_values->key ORDER BY key),
                old_values,new_values,geometry_changed,old_geom,new_geom,old_source_id,new_source_id
            FROM epol_history_diff WHERE change_type<>'unchanged' ''', (run_id, domain, table))
        cur.execute('DROP TABLE epol_history_before,epol_history_after,epol_history_diff')
    return counts


def complete(conn, run_id, audit_id):
    with conn.cursor() as cur:
        cur.execute("""UPDATE epol_meta.sync_history_runs SET status='committed',audit_id=%s,
            completed_at=clock_timestamp() WHERE id=%s AND status='collecting' """, (audit_id, run_id))
        if cur.rowcount != 1:
            raise LoadError('History attempt disappeared or changed during publication')
