"""Preview/enable the single extra data grant for atomic TEE publication."""
import argparse
from contextlib import closing
from dataclasses import replace
import getpass
import sys

import psycopg2

from settings import PROJECT_DIR, SettingsError, load_settings
from sync_access import inspect_target, verify_access
from sync_publication import LOCK_KEY


SQL_PATH = PROJECT_DIR / 'sql/admin/enable_atomic_publication.sql'
STATEMENT = ('-- One additional data privilege for the existing restricted sync role.\n'
             '-- DELETE/INSERT preserves old reader snapshots when replacing duplicate-ID lots.\n'
             '-- No role creation, password reset, ownership, schema or data change.\n'
             'GRANT DELETE ON epoleodomia.building_regs_lot TO epol_sync;\n')


def enabled(cur):
    cur.execute("SELECT has_table_privilege('epol_sync','epoleodomia.building_regs_lot','DELETE')")
    return cur.fetchone()[0]


def enable(connect, expected_target):
    if SQL_PATH.read_text(encoding='utf-8') != STATEMENT:
        raise SettingsError('Reviewed publication grant SQL differs')
    with closing(connect()) as conn:
        try:
            with conn.cursor() as cur:
                cur.execute("SET LOCAL lock_timeout='5s'")
                cur.execute('SELECT pg_try_advisory_xact_lock(%s,%s)', LOCK_KEY)
                if not cur.fetchone()[0]:
                    raise SettingsError('An atomic publication is active; retry setup after it finishes')
                if inspect_target(cur) != expected_target:
                    raise SettingsError('Target metadata/history changed since preview')
                verify_access(cur)
                if not enabled(cur):
                    cur.execute(STATEMENT)
                verify_access(cur)
                if not enabled(cur):
                    raise SettingsError('Publication grant did not take effect')
            conn.commit()
        except BaseException:
            conn.rollback()
            raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--apply', action='store_true', help='Apply using a local hidden schema-owner password prompt')
    group.add_argument('--sql', action='store_true', help='Print the exact reviewed SQL without connecting')
    args = parser.parse_args(argv)
    if args.sql:
        print(STATEMENT, end='')
        return 0
    try:
        base = load_settings().database
        with closing(psycopg2.connect(**base.connection_kwargs(),
                options='-c default_transaction_read_only=on -c statement_timeout=15000')) as conn, conn.cursor() as cur:
            target = inspect_target(cur)
            verify_access(cur)
            current = enabled(cur)
        print(f'Target: {base.host}:{base.port}/{base.database}; lot DELETE: {current}')
        print(f'Reviewed SQL: {SQL_PATH}')
        if not args.apply:
            print('Read-only preview. --apply grants only lot DELETE; no sync or credential change.')
            return 0
        if current:
            print('Publication grant already enabled. No changes required.')
            return 0
        if not sys.stdin.isatty():
            raise SettingsError('Run locally in an interactive terminal so the owner password remains hidden')
        owner = input('PostgreSQL schema owner [docker]: ').strip() or 'docker'
        password = getpass.getpass('Schema-owner password (hidden): ')
        if not password:
            raise SettingsError('Schema-owner password is required')
        administrator = replace(base, user=owner, password=password)
        enable(lambda: psycopg2.connect(**administrator.connection_kwargs()), target)
        print('Atomic publication grant enabled. Credentials and source data unchanged; no sync run.')
        return 0
    except psycopg2.Error as exc:
        print(f'Publication setup stopped ({type(exc).__name__}, SQLSTATE {exc.pgcode or "connection"}).')
    except (SettingsError, ValueError) as exc:
        print(f'Publication setup stopped: {exc}')
    except (EOFError, KeyboardInterrupt):
        print('Publication setup interrupted.')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
