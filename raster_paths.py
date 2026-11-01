"""Resolve TEE catalog paths and the existing flat-folder layout without copies."""

from pathlib import Path, PureWindowsPath
import re


def validate_filename(name):
    if (not isinstance(name, str) or not name or name in ('.', '..')
            or re.search(r'[<>:"/\\|?*\x00-\x1f]', name)
            or name.rstrip(' .') != name or PureWindowsPath(name).is_reserved()):
        raise ValueError('Unsafe raster filename')
    return name


def resolve_fek_path(root, filename, stored_path=None):
    """Prefer an existing catalog path, then an existing flat file.

    Missing files use their catalog-relative target. Never let Windows path
    separators, drives, parent components or a symlink escape the storage root.
    """
    validate_filename(filename)
    base = Path(root).resolve()
    relative = PureWindowsPath(stored_path or filename)
    if relative.is_absolute() or relative.drive or relative.root or '..' in relative.parts:
        raise ValueError('Raster destination escapes the configured root')
    for component in relative.parts:
        validate_filename(component)
    if relative.name.casefold() != filename.casefold():
        raise ValueError('Catalog path does not match the raster filename')
    target = (base / Path(*relative.parts)).resolve()
    flat = (base / filename).resolve()
    if not target.is_relative_to(base) or not flat.is_relative_to(base):
        raise ValueError('Raster destination escapes the configured root')
    if target.is_file():
        return target
    if flat.is_file():
        return flat
    return target
