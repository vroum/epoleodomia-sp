"""Menu sync entry point: scoped credentials passed only to sync child processes."""

import argparse
from contextlib import closing
import os
import subprocess
import sys

import psycopg2

from settings import PROJECT_DIR, SettingsError, load_settings, load_sync_database
from sync_access import ROLE, inspect_target, verify_access

COMMANDS = {
    'tee': ('sync_all.py', '--track'),
    'ktima': ('sync_kaek_operating.py',),
    'ydro': ('sync_ydrolipsies.py',),
    'rasters': ('download_rasters.py', '--repair-missing'),
}
MODES = {name: (name,) for name in COMMANDS}
MODES.update({'all': ('tee', 'ktima', 'ydro'), 'all-rasters': ('tee', 'ktima', 'ydro', 'rasters')})


def check_connection(database):
    with closing(psycopg2.connect(**database.connection_kwargs(),
                 options='-c default_transaction_read_only=on -c statement_timeout=15000')) as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT current_user')
            if cur.fetchone() != (ROLE,):
                raise ValueError('Sync connection must authenticate as epol_sync')
            inspect_target(cur)
            verify_access(cur)


def child_environment(database, environ=None):
    environment = dict(os.environ if environ is None else environ)
    for name, value in (('HOST', database.host), ('PORT', database.port),
                        ('NAME', database.database), ('USER', database.user),
                        ('PASSWORD', database.password), ('SCHEMA', database.schema),
                        ('CONNECT_TIMEOUT', database.connect_timeout)):
        environment['EPOL_DB_' + name] = str(value)
    return environment


def choose_mode():
    choices = {'1': 'tee', '2': 'ktima', '3': 'ydro', '4': 'rasters',
               '5': 'all', '6': 'all-rasters', '0': None}
    while True:
        print('\nSpetses GIS - Sync Menu\n'
              '  1. TEE epoleodomia tables\n'
              '  2. Ktimatologio operating\n'
              '  3. Ydrolipsies EMSY\n'
              '  4. TEE FEK raster downloads\n'
              '  5. ALL (1+2+3)\n'
              '  6. ALL + rasters (1+2+3+4)\n'
              '  0. Exit')
        choice = input('Select [0-6]: ').strip()
        if choice in choices:
            return choices[choice]
        print('Invalid choice.')


def replica_command(mode):
    if load_settings().raster_nas_path:
        return ('raster_replica.py', mode, '--apply')
    return None


def run_replica(mode):
    command = replica_command(mode)
    if command is None:
        return True
    print(f'\n--- NAS raster {mode} ---', flush=True)
    try:
        # Keep normal reader settings; writer credentials are only for downloads.
        result = subprocess.run([sys.executable, '-B', *command],
                                cwd=PROJECT_DIR, env=dict(os.environ))
        return result.returncode == 0
    except OSError:
        print(f'Could not start NAS raster {mode}.')
        return False


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=tuple(MODES), nargs='?')
    parser.add_argument('--check', action='store_true', help='Check sync access read-only; run no updates')
    parser.add_argument('--raster-id', type=int, help='rasters only: select one catalog row')
    parser.add_argument('--limit', type=int, help='rasters only: maximum number of files')
    parser.add_argument('--parallel', type=int, help='rasters only: number of download workers')
    parser.add_argument('--force', action='store_true', help='rasters only: refresh downloaded files')
    parser.add_argument('--dry-run', action='store_true', help='rasters only: read-only file preview')
    args = parser.parse_args(argv)
    if args.check and args.mode:
        parser.error('--check is standalone')
    raster_options = []
    for option in ('raster_id', 'limit', 'parallel'):
        number = getattr(args, option)
        if number is not None:
            if number < 1:
                parser.error('--' + option.replace('_', '-') + ' must be positive')
            raster_options.extend(('--' + option.replace('_', '-'), str(number)))
    for option in ('force', 'dry_run'):
        if getattr(args, option):
            raster_options.append('--' + option.replace('_', '-'))
    if raster_options and args.mode != 'rasters':
        parser.error('Raster download options require the rasters mode')
    try:
        mode = args.mode if args.mode or args.check else choose_mode()
        if not mode and not args.check:
            return 0
        database = load_sync_database()
        check_connection(database)
    except (SettingsError, ValueError) as exc:
        print(f'Sync access error: {exc}')
        return 1
    except psycopg2.Error:
        print('Sync connection/privilege check failed. Run setup_sync_writer.py to inspect access.')
        return 1
    except (EOFError, KeyboardInterrupt):
        return 130
    print(f'Sync account: {database.user}; target: {database.host}:{database.port}/{database.database}', flush=True)
    if args.check:
        print('Read-only access check passed. No updates run.')
        return 0
    environment = child_environment(database)
    failed = []
    for step in MODES[mode]:
        print(f'\n--- {step} ---', flush=True)
        try:
            if step == 'rasters' and not args.dry_run and not run_replica('pull'):
                failed.append('rasters NAS pull')
            options = raster_options if step == 'rasters' else []
            result = subprocess.run([sys.executable, '-B', *COMMANDS[step], *options],
                                    cwd=PROJECT_DIR, env=environment)
        except KeyboardInterrupt:
            return 130
        except OSError:
            print(f'Could not start {step}.')
            failed.append(step)
            continue
        if result.returncode:
            failed.append(step)
        elif step == 'rasters' and not args.dry_run:
            try:
                if not run_replica('push'):
                    failed.append('rasters NAS push')
            except KeyboardInterrupt:
                return 130
    print('\nSync completed OK.' if not failed else '\nSync failed: ' + ', '.join(failed))
    return int(bool(failed))


if __name__ == '__main__':
    raise SystemExit(main())
