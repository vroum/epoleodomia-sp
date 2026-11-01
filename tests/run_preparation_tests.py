"""Run installed-schema preparation tests only inside a fresh marked PG18 container."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tests.postgis18_container import disposable_postgis18
from tests.test_legacy_preparation_postgis import MARKER


def main():
    with disposable_postgis18('epol_setup_test',MARKER) as target:
        env = dict(os.environ, EPOL_TEST_PREPARATION_DSN=target.dsn, PYTHONIOENCODING='utf-8')
        return subprocess.run([sys.executable,'-B','-m','unittest',
            'tests.test_legacy_preparation_postgis','-v'],cwd=ROOT,env=env).returncode


if __name__=='__main__':
    raise SystemExit(main())
