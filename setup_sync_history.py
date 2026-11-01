"""Install the forward-only sync journal; preview by default, owner prompt locally."""
import argparse
from contextlib import closing
from dataclasses import replace
import getpass
import sys

import psycopg2

from settings import PROJECT_DIR, SettingsError, load_settings
from sync_access import ROLE, inspect_target, qualified, verify_access
from sync_publication import LOCK_KEY
import sync_history as history
from sync_safety import LoadError


SQL_PATH = PROJECT_DIR / 'sql/admin/sync_history.sql'


def grant_sql(reader):
    statements = [f'GRANT USAGE ON SCHEMA epol_meta TO {qualified_role(reader)};']
    for relation in history.RELATIONS:
        statements.append(f'GRANT SELECT ON {qualified(*relation)} TO {qualified_role(reader)},epol_sync;')
    for relation, rights in sorted(history.WRITE_SCOPE.items()):
        statements.append(f'GRANT {",".join(sorted(rights))} ON {qualified(*relation)} TO epol_sync;')
    statements.append('GRANT USAGE ON SEQUENCE epol_meta.sync_history_changes_id_seq TO epol_sync;')
    return '\n'.join(statements)


def qualified_role(name):
    return '"' + name.replace('"', '""') + '"'


def verify_reader(cur, reader):
    for schema, table in history.RELATIONS:
        cur.execute('''SELECT has_table_privilege(%s,%s,'SELECT'),
            has_any_column_privilege(%s,%s,'INSERT'),has_any_column_privilege(%s,%s,'UPDATE'),
            has_table_privilege(%s,%s,'DELETE'),has_table_privilege(%s,%s,'TRUNCATE')''',
            (reader, qualified(schema, table)) * 5)
        if cur.fetchone() != (True, False, False, False, False):
            raise SettingsError('API account must have SELECT only on the sync journal')


def install(connect, expected_target, reader):
    """No GIS table alteration/DML and no credential changes, in one transaction."""
    with closing(connect()) as conn:
        try:
            with conn.cursor() as cur:
                cur.execute("SET LOCAL lock_timeout='5s'")
                cur.execute("SET LOCAL statement_timeout='30s'")
                cur.execute('SELECT pg_try_advisory_xact_lock(%s,%s)', LOCK_KEY)
                if not cur.fetchone()[0]:
                    raise SettingsError('A publication is active; install after it finishes')
                if inspect_target(cur) != expected_target:
                    raise SettingsError('Target metadata changed since preview')
                verify_access(cur)
                if not history.installed(cur):
                    cur.execute(SQL_PATH.read_text(encoding='utf-8'))
                    cur.execute(grant_sql(reader))
                verify_access(cur)
                verify_reader(cur, reader)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--apply', action='store_true')
    group.add_argument('--sql', action='store_true')
    args = parser.parse_args(argv)
    try:
        base = load_settings().database
        if base.user == ROLE:
            raise SettingsError('Use the normal API reader environment for history setup')
        if args.sql:
            print(SQL_PATH.read_text(encoding='utf-8') + '\n' + grant_sql(base.user))
            return 0
        with closing(psycopg2.connect(**base.connection_kwargs(),
            options='-c default_transaction_read_only=on -c statement_timeout=15000')) as conn, conn.cursor() as cur:
            target = inspect_target(cur)
            verify_access(cur)
            current = history.installed(cur)
            if current:
                verify_reader(cur, base.user)
        print(f'Target: {base.host}:{base.port}/{base.database}; history installed: {current}')
        print(f'Reviewed SQL: {SQL_PATH}')
        if not args.apply or current:
            print('Read-only preview. History starts at installation; old JSON files are never imported.'
                  if not current else 'History is enabled. Existing start date and entries preserved.')
            return 0
        if not sys.stdin.isatty():
            raise SettingsError('Run locally in an interactive terminal for the hidden owner password prompt')
        owner = input('PostgreSQL schema owner [docker]: ').strip() or 'docker'
        password = getpass.getpass('Schema-owner password (hidden): ')
        if not password:
            raise SettingsError('Schema-owner password is required')
        administrator = replace(base, user=owner, password=password)
        install(lambda: psycopg2.connect(**administrator.connection_kwargs()), target, base.user)
        print('Forward-only history enabled. Next menu data sync will be recorded. No sync run; .env unchanged.')
        return 0
    except psycopg2.Error as exc:
        print(f'History setup stopped ({type(exc).__name__}, SQLSTATE {exc.pgcode or "connection"}).')
    except (SettingsError, ValueError, LoadError) as exc:
        print(f'History setup stopped: {exc}')
    except (KeyboardInterrupt, EOFError):
        print('History setup interrupted.')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
