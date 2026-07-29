"""
Sync Logger - Local log file generation for TEE data sync

Generates both human-readable .log files and machine-parseable .json files
for comprehensive change tracking and audit trail.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional

from config import DATABASE


# Friendly Greek labels for the change digest — tables that matter most.
# Anything not listed falls back to the raw table name.
DIGEST_LABELS = {
    "planning_lines": "Πολεοδομικές γραμμές",
    "building_lines": "Οικοδομικές γραμμές",
    "building_blocks": "Οικοδομικά τετράγωνα",
    "block_vertices": "Κορυφές Ο.Τ.",
    "building_regs_lot": "Όροι δόμησης (τομείς)",
    "building_regs_coefficient_zones": "Ζώνες συντ. δόμησης",
    "shorelines": "Αιγιαλός/Παραλία",
    "aigialos_lines": "Γραμμές αιγιαλού",
    "forest_maps": "Δασικός χάρτης",
    "forest_maps_posted_attica_2021": "Δασική ανάρτηση Αττικής 2021",
    "forest_maps_posted_pelop_2022": "Δασική ανάρτηση Πελοπ. 2022",
    "archaeological_sites": "Αρχαιολογικοί χώροι",
    "archaeological_protection_zones": "Ζώνες αρχαιολ. προστασίας",
    "natura_2000": "Natura 2000",
    "remata": "Ρέματα",
    "flood_zones": "Ζώνες πλημμύρας",
    "churches": "Εκκλησίες",
    "protected_buildings": "Διατηρητέα κτίρια",
    "pedestrian_zones": "Πεζόδρομοι",
    "fek_rasters": "ΦΕΚ (ράστερ)",
    "dji_rasters": "Ορθοφωτογραφίες DJI",
    "de_rasters": "Ράστερ Δ.Ε.",
    "planning_diagrams": "Πολεοδομικά διαγράμματα",
    "approved_plan_boundaries": "Όρια εγκεκριμένου σχεδίου",
    "census_blocks_2021": "Απογραφικά τετράγωνα 2021",
}

# Tables whose changes deserve a warning banner — they affect issued reports.
DIGEST_CRITICAL = {
    "building_regs_lot", "building_regs_coefficient_zones", "planning_lines",
    "building_lines", "forest_maps", "shorelines", "aigialos_lines",
    "archaeological_sites", "archaeological_protection_zones",
}


class SyncLogger:
    def __init__(self, mode='full', sync_run_id=None, log_dir=None, enabled=True):
        self.mode = mode
        self.sync_run_id = sync_run_id
        self.enabled = enabled
        self.started_at = datetime.now()
        self.completed_at = None

        self.log_dir = Path(log_dir) if log_dir else Path(__file__).parent / "logs"
        if self.enabled:
            self.log_dir.mkdir(exist_ok=True)

        self.timestamp = self.started_at.strftime("%Y-%m-%d_%H%M%S")
        self.log_file = self.log_dir / f"sync_{self.timestamp}.log"
        self.json_file = self.log_dir / f"sync_{self.timestamp}.json"

        self.json_data = {
            "sync_run": {"id": sync_run_id, "started_at": self.started_at.isoformat(),
                         "completed_at": None, "mode": mode, "status": "running"},
            "config": {"database": f"{DATABASE['host']}:{DATABASE['port']}/{DATABASE['database']}",
                       "schema": DATABASE["schema"], "area": "Spetses Island"},
            "services": [], "tables": [],
            "summary": {"tables_synced": 0, "tables_with_data": 0, "tables_empty": 0,
                        "total_new": 0, "total_updated": 0, "total_deleted": 0,
                        "total_unchanged": 0, "total_errors": 0, "duration_sec": 0}
        }
        self.current_service = None
        self._log_handle = open(self.log_file, 'w', encoding='utf-8') if self.enabled else None

    def _write_log(self, message, newline=True):
        if self._log_handle:
            self._log_handle.write(message)
            if newline:
                self._log_handle.write('\n')
            self._log_handle.flush()

    def _time_str(self):
        return datetime.now().strftime("%H:%M:%S")

    def log_start(self):
        if not self.enabled: return
        self._write_log("=" * 80)
        self._write_log(f"TEE SYNC LOG - {self.started_at.strftime('%Y-%m-%d %H:%M:%S')}")
        run_info = f"Mode: {self.mode}"
        if self.sync_run_id: run_info += f" | Run ID: {self.sync_run_id}"
        self._write_log(run_info)
        self._write_log("=" * 80)
        self._write_log("")
        self._write_log(f"[{self._time_str()}] STARTING SYNC")
        self._write_log(f"[{self._time_str()}] Database: {DATABASE['host']}:{DATABASE['port']}/{DATABASE['database']}")
        self._write_log(f"[{self._time_str()}] Schema: {DATABASE['schema']}")
        self._write_log(f"[{self._time_str()}] Area: Spetses Island")
        self._write_log("")

    def log_service_start(self, service_name):
        if not self.enabled: return
        self.current_service = service_name
        self.json_data["services"].append(service_name)
        self._write_log("-" * 80)
        self._write_log(f"SERVICE: {service_name}")
        self._write_log("-" * 80)
        self._write_log("")

    def log_table_result(self, table_name, layer_id, stats, changes=None, duration_sec=0, fetched=0, status='success'):
        if not self.enabled: return
        self.json_data["summary"]["tables_synced"] += 1
        if status == 'empty' or fetched == 0:
            self.json_data["summary"]["tables_empty"] += 1
        else:
            self.json_data["summary"]["tables_with_data"] += 1
        for key in ('new', 'updated', 'deleted', 'unchanged', 'errors'):
            self.json_data["summary"][f"total_{key}"] += stats.get(key, 0)

        self.json_data["tables"].append({
            "name": table_name, "layer_id": layer_id, "service": self.current_service,
            "fetched": fetched, "new": stats.get('new',0), "updated": stats.get('updated',0),
            "deleted": stats.get('deleted',0), "unchanged": stats.get('unchanged',0),
            "errors": stats.get('errors',0), "duration_sec": round(duration_sec, 2),
            "status": status, "changes": changes or []
        })

        self._write_log(f"[{self._time_str()}] TABLE: {table_name} (Layer {layer_id})")
        if status == 'empty':
            self._write_log(f"           Status: EMPTY (no data in area)")
        elif status == 'error':
            self._write_log(f"           Status: ERROR")
        else:
            self._write_log(f"           Fetched: {fetched} features")
            self._write_log(f"           New: {stats.get('new',0)} | Updated: {stats.get('updated',0)} | Deleted: {stats.get('deleted',0)} | Unchanged: {stats.get('unchanged',0)}")
            if duration_sec > 0:
                self._write_log(f"           Duration: {duration_sec:.1f}s")
            if changes:
                self._write_log(f"           Changes:")
                for change in changes[:20]:
                    self._format_change_log(change)
                if len(changes) > 20:
                    self._write_log(f"             ... and {len(changes) - 20} more changes (see JSON file)")
        self._write_log("")

    def _format_change_log(self, change):
        ct = change.get('type', 'UNKNOWN')
        oid = change.get('objectid', '?')
        if ct == 'INSERT':
            nv = change.get('new_values', {})
            ident = nv.get('ot_num') or nv.get('fek') or nv.get('addr') or ''
            self._write_log(f"             - INSERT objectid={oid}{': ' + ident if ident else ''}")
        elif ct == 'UPDATE':
            cf = change.get('changed_fields', [])
            ov, nv = change.get('old_values', {}), change.get('new_values', {})
            gc = change.get('geometry_changed', False)
            if gc and not cf:
                self._write_log(f"             - UPDATE objectid={oid}: geometry changed")
            elif cf:
                f = cf[0]
                old_v = str(ov.get(f, '?'))[:30]
                new_v = str(nv.get(f, '?'))[:30]
                if len(cf) == 1:
                    self._write_log(f'             - UPDATE objectid={oid}: {f} "{old_v}" → "{new_v}"')
                else:
                    self._write_log(f"             - UPDATE objectid={oid}: {f} + {len(cf)-1} more fields")
            else:
                self._write_log(f"             - UPDATE objectid={oid}")
        elif ct == 'DELETE':
            ov = change.get('old_values', {})
            ident = ov.get('ot_num') or ov.get('fek') or ''
            self._write_log(f"             - DELETE objectid={oid}{': ' + ident if ident else ''}")
        else:
            self._write_log(f"             - {ct} objectid={oid}")

    def log_error(self, message, table_name=None):
        if not self.enabled: return
        prefix = f"[{self._time_str()}] ERROR"
        if table_name: prefix += f" ({table_name})"
        self._write_log(f"{prefix}: {message}")

    def log_warning(self, message):
        if self.enabled: self._write_log(f"[{self._time_str()}] WARNING: {message}")

    def log_info(self, message):
        if self.enabled: self._write_log(f"[{self._time_str()}] {message}")

    def log_complete(self, status='success', error_message=None):
        if not self.enabled: return
        self.completed_at = datetime.now()
        duration = (self.completed_at - self.started_at).total_seconds()
        self.json_data["sync_run"]["completed_at"] = self.completed_at.isoformat()
        self.json_data["sync_run"]["status"] = status
        self.json_data["summary"]["duration_sec"] = round(duration, 1)
        if error_message: self.json_data["sync_run"]["error_message"] = error_message

        dur_str = f"{int(duration//60)}m {int(duration%60)}s" if duration >= 60 else f"{duration:.1f}s"
        self._write_log("")
        self._write_log("=" * 80)
        self._write_log("SUMMARY")
        self._write_log("=" * 80)
        s = self.json_data["summary"]
        self._write_log(f"Total tables synced: {s['tables_synced']}")
        self._write_log(f"  - With data: {s['tables_with_data']}")
        self._write_log(f"  - Empty: {s['tables_empty']}")
        self._write_log("")
        if s['total_new'] + s['total_updated'] + s['total_deleted'] > 0 or self.mode == 'track':
            self._write_log("Total changes:")
            self._write_log(f"  - New records: {s['total_new']}")
            self._write_log(f"  - Updated records: {s['total_updated']}")
            self._write_log(f"  - Deleted records: {s['total_deleted']}")
            if s['total_unchanged'] > 0: self._write_log(f"  - Unchanged: {s['total_unchanged']}")
            self._write_log("")
        if s['total_errors'] > 0: self._write_log(f"Errors: {s['total_errors']}\n")
        self._write_log(f"Duration: {dur_str}")
        self._write_log(f"Status: {status.upper()}")
        if error_message: self._write_log(f"Error: {error_message}")
        self._write_log("")
        self._write_log("=" * 80)
        self._write_log(f"Log file: {self.log_file}")
        self._write_log(f"JSON file: {self.json_file}")
        self._write_log("=" * 80)

        if self._log_handle:
            self._log_handle.close()
            self._log_handle = None
        with open(self.json_file, 'w', encoding='utf-8') as f:
            json.dump(self.json_data, f, indent=2, ensure_ascii=False, default=str)

        # Auto-generate the human digest (overwritten with raster info later
        # by sync_all.py when --rasters is used).
        self.write_changes_digest()

        return {"log_file": str(self.log_file), "json_file": str(self.json_file)}

    def _digest_change_line(self, change):
        """One-line Greek description of a tracked change."""
        ct = change.get('type', '?')
        oid = change.get('objectid', '?')
        nv = change.get('new_values', {}) or {}
        ov = change.get('old_values', {}) or {}
        ident = (nv.get('ot_num') or nv.get('fek') or nv.get('name')
                 or ov.get('ot_num') or ov.get('fek') or ov.get('name') or '')
        ident = f" — {ident}" if ident else ""
        if ct == 'INSERT':
            return f"    - νέο (objectid {oid}){ident}"
        if ct == 'DELETE':
            return f"    - διαγραφή (objectid {oid}){ident}"
        cf = change.get('changed_fields', [])
        if change.get('geometry_changed') and not cf:
            return f"    - αλλαγή γεωμετρίας (objectid {oid}){ident}"
        if cf:
            f0 = cf[0]
            old_v = str(ov.get(f0, '?'))[:40]
            new_v = str(nv.get(f0, '?'))[:40]
            more = f" (+{len(cf)-1} πεδία)" if len(cf) > 1 else ""
            return f"    - {f0}: «{old_v}» → «{new_v}»{more} (objectid {oid})"
        return f"    - ενημέρωση (objectid {oid}){ident}"

    def write_changes_digest(self, raster_results=None):
        """
        Write a compact 'τι άλλαξε' digest in Greek to logs/CHANGES_latest.md.
        Overwrites the previous digest — the full history stays in the
        timestamped .log/.json files. Also prints the digest to the console.
        """
        if not self.enabled:
            return None

        tables = self.json_data.get("tables", [])
        changed = [t for t in tables if t["new"] + t["updated"] + t["deleted"] > 0]
        errors = [t for t in tables if t["status"] == "error"]
        critical = [t for t in changed if t["name"] in DIGEST_CRITICAL]

        ts = self.started_at.strftime('%Y-%m-%d %H:%M')
        lines = [f"# Αλλαγές δεδομένων — sync {ts}", ""]

        if critical:
            names = ", ".join(DIGEST_LABELS.get(t["name"], t["name"]) for t in critical)
            lines.append(f"> ⚠ ΠΡΟΣΟΧΗ: αλλαγές σε κρίσιμα δεδομένα ({names}). "
                         f"Reports που εκδόθηκαν πριν το sync ίσως χρειάζονται επανέλεγχο.")
            lines.append("")

        if not changed and not errors:
            lines.append("Καμία αλλαγή στα δεδομένα.")
        else:
            for t in sorted(changed, key=lambda t: -(t["new"] + t["updated"] + t["deleted"])):
                label = DIGEST_LABELS.get(t["name"], t["name"])
                parts = []
                if t["new"]:
                    parts.append(f"{t['new']} νέα")
                if t["updated"]:
                    parts.append(f"{t['updated']} ενημερώσεις")
                if t["deleted"]:
                    parts.append(f"{t['deleted']} διαγραφές")
                lines.append(f"- **{label}** (`{t['name']}`): {', '.join(parts)}")
                for change in (t.get("changes") or [])[:5]:
                    lines.append(self._digest_change_line(change))
                extra = len(t.get("changes") or []) - 5
                if extra > 0:
                    lines.append(f"    - … και {extra} ακόμα (βλ. {self.json_file.name})")

        if errors:
            lines.append("")
            lines.append("## Σφάλματα")
            for t in errors:
                label = DIGEST_LABELS.get(t["name"], t["name"])
                lines.append(f"- {label} (`{t['name']}`) — απέτυχε το sync")

        if raster_results:
            lines.append("")
            dl = raster_results.get("downloaded", 0)
            fl = raster_results.get("failed", 0)
            if dl or fl:
                lines.append(f"**Ράστερ:** {dl} νέα διαγράμματα" + (f", {fl} απέτυχαν" if fl else ""))
            else:
                lines.append("**Ράστερ:** κανένα νέο.")

        lines.append("")
        lines.append(f"_Πλήρες log: {self.log_file.name} / {self.json_file.name}_")

        digest = "\n".join(lines)
        digest_path = self.log_dir / "CHANGES_latest.md"
        with open(digest_path, 'w', encoding='utf-8') as f:
            f.write(digest + "\n")

        # Console echo — the part the user actually reads after sync.bat
        print("\n" + "=" * 60)
        print("ΤΙ ΑΛΛΑΞΕ (CHANGES_latest.md)")
        print("=" * 60)
        try:
            print(digest)
        except UnicodeEncodeError:
            enc = sys.stdout.encoding or 'ascii'
            print(digest.encode(enc, errors='replace').decode(enc, errors='replace'))
        return str(digest_path)

    def get_log_paths(self):
        return {"log_file": str(self.log_file), "json_file": str(self.json_file)}

    def __enter__(self): return self
    def __exit__(self, *args):
        if self._log_handle:
            self._log_handle.close()
            self._log_handle = None
        return False


def create_logger(mode='full', sync_run_id=None, log_dir=None, enabled=True):
    return SyncLogger(mode, sync_run_id, log_dir, enabled)
