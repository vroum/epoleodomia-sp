"""Preview/create the dedicated sync account; keep API credentials unchanged."""

import argparse
from contextlib import closing
from dataclasses import replace
import getpass
import os
from pathlib import Path
import secrets
import sys
import tempfile

import psycopg2
from psycopg2 import sql

from settings import PROJECT_DIR, SettingsError, load_settings, read_env_file
from sync_access import ROLE, inspect_target, read_scope, setup_sql, verify_access
from sync_launcher import check_connection

ENV_PATH = PROJECT_DIR / '.env'
SQL_PATH = PROJECT_DIR / 'sql/admin/epol_sync_writer.sql'


def save_credentials(password, *, env_path=ENV_PATH, expected_source=None):
    """Replace only two sync keys, atomically; never copy a secret into shell text."""
    path = Path(env_path)
    original = path.read_text(encoding='utf-8-sig')
    if expected_source is not None and original != expected_source:
        raise SettingsError('.env changed during setup; use --configure to save sync credentials')
    before = read_env_file(path)
    if not password or any(char in password for char in ('\n', '\r', '\x00')):
        raise SettingsError('Sync password cannot be empty or contain line breaks/NUL')
    # Generated passwords are URL-safe. --configure also supports literal shell characters.
    if '"' not in password:
        encoded = '"' + password + '"'
    elif "'" not in password:
        encoded = "'" + password + "'"
    else:
        raise SettingsError('Password containing both quote styles cannot be saved by the literal .env parser')
    values = {'EPOL_SYNC_DB_USER': ROLE, 'EPOL_SYNC_DB_PASSWORD': encoded}
    lines, seen = [], set()
    for line in original.splitlines():
        key = line.strip().removeprefix('export ').partition('=')[0].strip()
        if key in values:
            lines.append(key + '=' + values[key])
            seen.add(key)
        else:
            lines.append(line)
    lines.extend(key + '=' + value for key, value in values.items() if key not in seen)
    updated = '\n'.join(lines) + '\n'
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n',
                dir=path.parent, prefix='.env.sync-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(updated)
        after = read_env_file(temporary)
        sync_keys = set(values)
        if {k:v for k,v in before.items() if k not in sync_keys} != {k:v for k,v in after.items() if k not in sync_keys}:
            raise SettingsError('Refusing to change non-sync settings')
        if after['EPOL_SYNC_DB_PASSWORD'] != password:
            raise SettingsError('Sync password failed literal round-trip validation')
        if path.read_text(encoding='utf-8-sig') != original:
            raise SettingsError('.env changed during setup; retry configuration')
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def create_writer(connect, password, *, expected_target):
    """Create/grant/login in one transaction; source data and schema stay untouched."""
    source = SQL_PATH.read_text(encoding='utf-8')
    if source != setup_sql():
        raise SettingsError('Reviewed sync SQL differs from the current access contract')
    with closing(connect()) as conn:
        try:
            with conn.cursor() as cur:
                cur.execute("SET LOCAL lock_timeout='5s'")
                cur.execute("SELECT pg_advisory_xact_lock(58321471)")
                if inspect_target(cur) != expected_target:
                    raise SettingsError('Target metadata/history changed since preview')
                cur.execute(source)
                verify_access(cur, require_login=False)
                cur.execute(sql.SQL('ALTER ROLE epol_sync LOGIN PASSWORD {}').format(sql.Literal(password)))
                verify_access(cur)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--apply', action='store_true', help='Create role/grants using an administrator password prompt')
    group.add_argument('--configure', action='store_true', help='Check/store credentials for an already-created epol_sync')
    group.add_argument('--sql', action='store_true', help='Print the reviewed password-free SQL; no connection')
    args = parser.parse_args(argv)
    if args.sql:
        print(setup_sql(), end='')
        return 0
    role_created = False
    try:
        base = load_settings().database
        if base.user == ROLE:
            raise SettingsError('Keep EPOL_DB_USER on the API reader; sync uses separate EPOL_SYNC_DB_* keys')
        if not ENV_PATH.is_file():
            raise SettingsError('Create the project .env with API reader settings first')
        original = ENV_PATH.read_text(encoding='utf-8-sig')
        with closing(psycopg2.connect(**base.connection_kwargs(),
                options='-c default_transaction_read_only=on -c statement_timeout=15000')) as conn, conn.cursor() as cur:
            target = inspect_target(cur)
            cur.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (ROLE,))
            exists = cur.fetchone() is not None
        print(f'Target: {base.host}:{base.port}/{base.database}; API account: {base.user}')
        print(f'Sync role: {ROLE}; state: {"exists" if exists else "not created"}; explicit read scope: {len(read_scope())} tables')
        print(f'Reviewed SQL: {SQL_PATH}')
        if not args.apply and not args.configure:
            print('Read-only preview. Use --apply to create, or --configure for an existing role.')
            return 0
        if not sys.stdin.isatty():
            raise SettingsError('Run in an interactive terminal so the password remains hidden')
        if args.apply:
            if exists:
                raise SettingsError('epol_sync already exists; inspect it and use --configure. No role/password was changed')
            admin = input('PostgreSQL role administrator [docker]: ').strip() or 'docker'
            admin_password = getpass.getpass('Administrator password (hidden): ')
            if not admin_password:
                raise SettingsError('Administrator password is required')
            password = secrets.token_urlsafe(36)
            administrator = replace(base, user=admin, password=admin_password)
            create_writer(lambda: psycopg2.connect(**administrator.connection_kwargs()),
                          password, expected_target=target)
            role_created = True
        else:
            if not exists:
                raise SettingsError('epol_sync does not exist; use --apply first')
            password = getpass.getpass('epol_sync password (hidden): ')
        check_connection(replace(base, user=ROLE, password=password))
        save_credentials(password, expected_source=original)
        print('epol_sync login/grants verified; sync credentials saved in .env. API settings unchanged.')
        print('Next: sync_menu.bat --check (read-only). No sync has been run.')
        return 0
    except (SettingsError, ValueError) as exc:
        print(f'Setup stopped: {exc}')
    except psycopg2.Error as exc:
        print(f'Database setup/check failed ({type(exc).__name__}, SQLSTATE {exc.pgcode or "connection"}).')
    except OSError:
        print('Could not read/write the local settings/SQL file.')
    except (EOFError, KeyboardInterrupt):
        print('Setup interrupted.')
    if role_created:
        print('The database role was committed, but local configuration is incomplete. '
              'An administrator can set a new password, then run --configure.')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
