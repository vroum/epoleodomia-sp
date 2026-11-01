"""Explicit runtime grant contract, separate from schema migrations and API auth."""

from config import SERVICES

ROLE = 'epol_sync'
TEE_TABLES = sorted({layer['table'] for service in SERVICES.values() for layer in service['layers']})
CADASTRE_TABLES = ['kaek_parcels_operating', 'kaek_douleies_operating', 'kaek_apokleistikes_operating']
CATALOG_INSERT = ('planning_diagram_objectid', 'fek', 'filename', 'url_georef', 'url_raw',
                  'georef_rms', 'original_scale', 'download_status')
CATALOG_UPDATE = ('planning_diagram_objectid', 'fek', 'url_raw', 'updated_at',
    'download_status', 'local_path_georef', 'file_size_bytes', 'downloaded_at',
    'last_checked', 'download_error', 'width_px', 'height_px', 'bands',
    'resolution_x', 'resolution_y', 'crs_epsg', 'nodata_value', 'bbox')


def write_scope():
    scope = {('epoleodomia', name): {'INSERT', 'UPDATE'} for name in TEE_TABLES}
    scope['epoleodomia', 'building_regs_lot'] = {'INSERT', 'TRUNCATE'}
    scope.update({('epoleodomia', name): rights for name, rights in (
        ('sync_log', {'INSERT'}), ('sync_runs', {'INSERT', 'UPDATE'}),
        ('changelog', {'INSERT'}), ('raster_catalog', {'INSERT', 'UPDATE'}))})
    scope.update({('sp_geodata', name): {'INSERT', 'DELETE'} for name in CADASTRE_TABLES})
    scope['sp_geodata', 'ydrolipsies_emsy'] = {'INSERT', 'UPDATE'}
    return scope


def read_scope():
    return sorted(set(write_scope()) | {('epoleodomia', 'land_use_codes'),
                                        ('sp_geodata', 'kaek_parcels_anartisi'),
                                        ('epol_meta', 'schema_migrations')})


def qualified(schema, table):
    # All identifiers come from the fixed project contract, never user input.
    return '"' + schema.replace('"', '""') + '"."' + table.replace('"', '""') + '"'


def setup_sql():
    statements = [
        '-- Run transactionally through setup_sync_writer.py. No password in this file.',
        '-- This creates a NEW role; an existing epol_sync deliberately causes failure.',
        'CREATE ROLE epol_sync NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;',
        "DO $$ BEGIN EXECUTE format('GRANT CONNECT,TEMPORARY ON DATABASE %I TO epol_sync', current_database()); END $$;",
        'GRANT USAGE ON SCHEMA epoleodomia,sp_geodata,epol_meta,public TO epol_sync;',
    ]
    for schema, table in read_scope():
        statements.append(f'GRANT SELECT ON {qualified(schema, table)} TO epol_sync;')
    for (schema, table), rights in sorted(write_scope().items()):
        target = qualified(schema, table)
        if table == 'raster_catalog':
            for action, columns in (('INSERT', CATALOG_INSERT), ('UPDATE', CATALOG_UPDATE)):
                statements.append(f'GRANT {action} ({", ".join(columns)}) ON {target} TO epol_sync;')
        else:
            statements.append(f'GRANT {",".join(sorted(rights))} ON {target} TO epol_sync;')
    # Only sequences owned by these runtime target tables, including identity sequences.
    relations = ','.join("'" + qualified(s, t) + "'::regclass" for s, t in sorted(write_scope()))
    statements.append('''DO $$ DECLARE item record; BEGIN
    FOR item IN SELECT DISTINCT n.nspname,c.relname FROM pg_class c
        JOIN pg_namespace n ON n.oid=c.relnamespace
        JOIN pg_depend d ON d.classid='pg_class'::regclass AND d.objid=c.oid
        WHERE c.relkind='S' AND d.refclassid='pg_class'::regclass
          AND d.deptype IN ('a','i') AND d.refobjid IN (''' + relations + ''')
    LOOP EXECUTE format('GRANT USAGE ON SEQUENCE %I.%I TO epol_sync',item.nspname,item.relname);
    END LOOP;
END $$;''')
    return '\n'.join(statements) + '\n'


def inspect_target(cur):
    """Bind setup to an existing project installation; no source-table DDL."""
    cur.execute('SELECT current_database()')
    database = cur.fetchone()[0]
    metadata = []
    for schema, table in read_scope():
        cur.execute('''SELECT c.oid,c.relowner,c.relkind,c.relrowsecurity
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname=%s AND c.relname=%s''', (schema, table))
        row = cur.fetchone()
        kinds = ('r',) if (schema, table) in write_scope() else ('r', 'v', 'm')
        if row is None or row[2] not in kinds or row[3]:
            raise ValueError(f'{schema}.{table}: existing compatible relation without row security required')
        metadata.append((schema, table, *row))
    cur.execute("SELECT version,checksum FROM epol_meta.schema_migrations ORDER BY version")
    history = cur.fetchall()
    from database_setup import load_migrations
    expected = [(migration.version, migration.checksum) for migration in load_migrations()]
    if history != expected or [row[0] for row in history] != [1, 2]:
        raise ValueError('Managed TEE v2 history required before configuring sync access')
    return database, metadata, history


def verify_access(cur, *, require_login=True):
    """Check positive rights and reject inherited administration/unscoped writes."""
    cur.execute('''SELECT rolcanlogin,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls
        FROM pg_roles WHERE rolname=%s''', (ROLE,))
    flags = cur.fetchone()
    if flags is None or any(flags[1:]) or (require_login and not flags[0]):
        raise ValueError('epol_sync must be a login without administrative role attributes')
    cur.execute('''SELECT count(*) FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname=%s)''', (ROLE,))
    if cur.fetchone()[0]:
        raise ValueError('epol_sync must have no role memberships')
    cur.execute("SELECT nspname FROM pg_namespace WHERE nspname !~ '^pg_' AND nspname<>'information_schema' AND has_schema_privilege(%s,oid,'CREATE')", (ROLE,))
    if cur.fetchall():
        raise ValueError('epol_sync unexpectedly has schema CREATE privileges')
    cur.execute("SELECT has_database_privilege(%s,current_database(),'TEMPORARY'),has_database_privilege(%s,current_database(),'CREATE')", (ROLE, ROLE))
    if cur.fetchone() != (True, False):
        raise ValueError('epol_sync requires TEMPORARY and must not have database CREATE')
    for schema, table in read_scope():
        cur.execute('SELECT has_table_privilege(%s,%s,\'SELECT\')', (ROLE, qualified(schema, table)))
        if cur.fetchone() != (True,):
            raise ValueError(f'Missing SELECT: {schema}.{table}')
    scope = write_scope()
    cur.execute('''SELECT n.nspname,c.relname,
        has_any_column_privilege(%s,c.oid,'INSERT'),has_any_column_privilege(%s,c.oid,'UPDATE'),
        has_table_privilege(%s,c.oid,'DELETE'),has_table_privilege(%s,c.oid,'TRUNCATE'),
        has_table_privilege(%s,c.oid,'TRIGGER'),has_any_column_privilege(%s,c.oid,'REFERENCES')
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname !~ '^pg_' AND n.nspname<>'information_schema' AND c.relkind IN ('r','p','v','m','f')
          AND NOT EXISTS (SELECT 1 FROM pg_depend extension_object
              WHERE extension_object.classid='pg_class'::regclass AND extension_object.objid=c.oid
                AND extension_object.refclassid='pg_extension'::regclass AND extension_object.deptype='e')''', (ROLE,)*6)
    found = set()
    for schema, table, *rights in cur.fetchall():
        actual = {name for name, allowed in zip(('INSERT','UPDATE','DELETE','TRUNCATE','TRIGGER','REFERENCES'), rights) if allowed}
        expected = scope.get((schema, table), set())
        if actual != expected:
            raise ValueError(f'Unexpected or missing write privileges: {schema}.{table}')
        found.add((schema, table))
    if not set(scope).issubset(found):
        raise ValueError('Missing sync write targets')
    for action, allowed in (('INSERT', CATALOG_INSERT), ('UPDATE', CATALOG_UPDATE)):
        cur.execute('''SELECT a.attname,has_column_privilege(%s,a.attrelid,a.attnum,%s)
            FROM pg_attribute a WHERE a.attrelid='epoleodomia.raster_catalog'::regclass
                AND a.attnum>0 AND NOT a.attisdropped''', (ROLE, action))
        if {name for name, granted in cur.fetchall() if granted} != set(allowed):
            raise ValueError(f'Unexpected raster catalog {action} columns')
    cur.execute('''SELECT n.nspname,c.relname,
        CASE WHEN c.relkind='S' THEN has_sequence_privilege(%s,c.oid,'USAGE') END,
        CASE WHEN c.relkind='S' THEN has_sequence_privilege(%s,c.oid,'SELECT') END,
        CASE WHEN c.relkind='S' THEN has_sequence_privilege(%s,c.oid,'UPDATE') END,
        EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid='pg_class'::regclass
            AND d.objid=c.oid AND d.refclassid='pg_class'::regclass AND d.deptype IN ('a','i')
            AND d.refobjid=ANY(%s::regclass[]))
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE c.relkind='S' AND n.nspname !~ '^pg_'
          AND NOT EXISTS (SELECT 1 FROM pg_depend extension_object
              WHERE extension_object.classid='pg_class'::regclass AND extension_object.objid=c.oid
                AND extension_object.refclassid='pg_extension'::regclass AND extension_object.deptype='e')''',
        (ROLE, ROLE, ROLE, [qualified(s,t) for s,t in sorted(scope)]))
    for schema, name, usage, select, update, expected_usage in cur.fetchall():
        if usage != expected_usage or select or update:
            raise ValueError(f'Unexpected sequence privileges: {schema}.{name}')
