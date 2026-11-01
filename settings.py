"""Shared runtime settings; no dependencies, environment mutation or connections."""

from dataclasses import dataclass, field, replace
import os
from pathlib import Path
import re


PROJECT_DIR = Path(__file__).resolve().parent


class SettingsError(ValueError):
    """Invalid configuration, with values/credentials omitted from messages."""


def read_env_file(path):
    """Read literal values, preserving Windows paths and shell metacharacters.

    Supports #/; comments, export, matching quotes and unquoted inline comments
    preceded by whitespace. No interpolation, escape processing or shell syntax.
    """
    if path is None or not Path(path).exists():
        return {}
    result = {}
    for number, raw in enumerate(Path(path).read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, separator, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise SettingsError(f"Invalid .env entry at line {number}")
        if value.startswith(('"', "'")):
            end = value.find(value[0], 1)
            if end < 0 or (value[end+1:].strip() and not value[end+1:].strip().startswith(("#", ";"))):
                raise SettingsError(f"Invalid quoted .env value at line {number}")
            value = value[1:end]
        else:
            value = re.split(r"\s+[;#]", value, maxsplit=1)[0].rstrip()
        if key in result:
            raise SettingsError(f"Duplicate .env key at line {number}: {key}")
        result[key] = value
    return result


@dataclass(frozen=True)
class DatabaseSettings:
    host: str
    port: int
    database: str
    user: str
    password: str = field(repr=False)
    schema: str = "epoleodomia"
    connect_timeout: int = 10

    def connection_kwargs(self):
        return {key: getattr(self, key) for key in
                ("host", "port", "database", "user", "password", "connect_timeout")}

    def require_password(self):
        if not self.password:
            raise SettingsError("Set EPOL_DB_PASSWORD in the project .env or process environment")


@dataclass(frozen=True)
class RuntimeSettings:
    database: DatabaseSettings
    api_host: str
    api_port: int
    raster_base_path: str
    dji_raster_path: str
    fek_local_path: str
    raster_nas_path: str | None = None


def load_settings(*, environ=None, env_path=PROJECT_DIR / ".env"):
    process = os.environ if environ is None else environ
    file_values = read_env_file(env_path)

    def value(name, default, alias=None):
        # Source precedence applies across aliases as well: an explicit process
        # DB_HOST beats a file EPOL_DB_HOST. EPOL_* wins within the same source.
        for source in (process, file_values):
            for key in (name, alias):
                if key is not None and key in source:
                    return source[key]
        return default

    def text(name, default, alias=None):
        result = value(name, default, alias)
        if not isinstance(result, str) or not result.strip() or "\x00" in result:
            raise SettingsError(f"{name} must be nonempty text")
        return result

    def integer(name, default, upper, alias=None):
        raw = value(name, str(default), alias)
        if not isinstance(raw, str) or not re.fullmatch(r"[0-9]+", raw):
            raise SettingsError(f"{name} must be an integer from 1 to {upper}")
        number = int(raw)
        if not 1 <= number <= upper:
            raise SettingsError(f"{name} must be an integer from 1 to {upper}")
        return number

    password = value("EPOL_DB_PASSWORD", "", "DB_PASSWORD")
    if not isinstance(password, str) or "\x00" in password:
        raise SettingsError("EPOL_DB_PASSWORD must be text without NUL characters")
    schema = text("EPOL_DB_SCHEMA", "epoleodomia", "DB_SCHEMA")
    if schema != "epoleodomia":
        raise SettingsError("EPOL_DB_SCHEMA must be epoleodomia; API source schemas are fixed")
    database = DatabaseSettings(
        host=text("EPOL_DB_HOST", "10.90.144.153", "DB_HOST"),
        port=integer("EPOL_DB_PORT", 65432, 65535, "DB_PORT"),
        database=text("EPOL_DB_NAME", "gis", "DB_NAME"),
        user=text("EPOL_DB_USER", "docker", "DB_USER"), password=password, schema=schema,
        connect_timeout=integer("EPOL_DB_CONNECT_TIMEOUT", 10, 300),
    )
    fek_local_path = text("EPOL_FEK_LOCAL_PATH", r"O:\gis_data\epoleodomia\poleodomikoi oroi\poleodomikoi oroi geotifs")
    nas_path = value("EPOL_RASTER_NAS_PATH", "")
    if not isinstance(nas_path, str) or "\x00" in nas_path:
        raise SettingsError("EPOL_RASTER_NAS_PATH must be text without NUL characters")
    return RuntimeSettings(
        database=database,
        api_host=text("EPOL_API_HOST", "0.0.0.0"),
        api_port=integer("EPOL_API_PORT", 8000, 65535),
        raster_base_path=text("EPOL_RASTER_BASE_PATH", fek_local_path),
        dji_raster_path=text("EPOL_DJI_RASTER_PATH", r"O:\GEODATA\drone data"),
        fek_local_path=fek_local_path,
        raster_nas_path=nas_path.strip() or None,
    )


def load_sync_database(*, environ=None, env_path=PROJECT_DIR / ".env"):
    """Use the same target with explicit sync credentials; never fall back to API auth."""
    process = os.environ if environ is None else environ
    values = read_env_file(env_path)
    credentials = {}
    for key in ('EPOL_SYNC_DB_USER', 'EPOL_SYNC_DB_PASSWORD'):
        value = process.get(key, values.get(key, ''))
        if not isinstance(value, str) or not value or '\x00' in value:
            raise SettingsError(f'Set {key}; run setup_sync_writer.py to configure sync access')
        credentials[key] = value
    if credentials['EPOL_SYNC_DB_USER'] != 'epol_sync':
        raise SettingsError('EPOL_SYNC_DB_USER must be the dedicated epol_sync role')
    base = load_settings(environ=process, env_path=env_path).database
    return replace(base, user=credentials['EPOL_SYNC_DB_USER'],
                   password=credentials['EPOL_SYNC_DB_PASSWORD'])


SETTINGS = load_settings()
