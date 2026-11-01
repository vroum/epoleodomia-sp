"""Provision disposable localhost PostGIS, run schema-write tests, remove it."""

from contextlib import closing
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

import psycopg2


def main():
    root = Path(__file__).resolve().parents[1]
    name = "epol-setup-tests-" + uuid.uuid4().hex[:12]
    container_id = None
    try:
        result = subprocess.run([
            "docker", "run", "--detach", "--rm", "--name", name,
            "--tmpfs", "/var/lib/postgresql/data",
            "--env", "POSTGRES_DB=epol_setup_test", "--env", "POSTGRES_PASSWORD=epol-test-only",
            "--publish", "127.0.0.1::5432", "postgis/postgis:16-3.5"],
            check=True, capture_output=True, text=True, timeout=60)
        container_id = result.stdout.strip()
        port = subprocess.run(["docker", "port", container_id, "5432/tcp"],
                              check=True, capture_output=True, text=True, timeout=10).stdout.strip().rsplit(":", 1)[1]
        dsn = psycopg2.extensions.make_dsn(host="127.0.0.1", port=port, dbname="epol_setup_test",
                                          user="postgres", password="epol-test-only")
        deadline = time.monotonic() + 30
        while True:
            try:
                conn = psycopg2.connect(dsn, connect_timeout=2)
                break
            except psycopg2.OperationalError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("Disposable PostGIS did not become ready")
                time.sleep(0.25)
        with closing(conn):
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute("COMMENT ON DATABASE epol_setup_test IS 'EPOL disposable setup tests'")
        env = dict(os.environ, EPOL_TEST_SETUP_DSN=dsn)
        return subprocess.run([sys.executable, "-B", "-m", "unittest",
                               "tests.test_database_setup_postgis", "tests.test_schema_compatibility_postgis",
                               "tests.test_tee_contract_postgis",
                               "tests.test_sync_writers_postgis",
                               "tests.test_sync_access_postgis",
                               "-v"], cwd=root, env=env).returncode
    finally:
        if container_id:
            # Only the exact container returned by this run. --rm removes its
            # anonymous volumes; there are no host mounts or production data.
            subprocess.run(["docker", "stop", "--timeout", "5", container_id],
                           check=True, stdout=subprocess.DEVNULL, timeout=20)


if __name__ == "__main__":
    raise SystemExit(main())
