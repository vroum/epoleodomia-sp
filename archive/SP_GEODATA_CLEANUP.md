# sp_geodata Schema Cleanup Plan

**Date:** 2026-02-26
**Status:** PENDING user confirmation before executing deletes

---

## Context

The `sp_geodata` schema contains manually imported tables accumulated over time.
Many now duplicate data that is auto-synced into the `epoleodomia` schema from TEE.
This audit identifies which tables to delete (exact duplicates) and which to keep
(unique professional data not available from TEE).

---

## Tables to DELETE (8) — Exact duplicates of epoleodomia

| sp_geodata Table | Rows | Replaced By (epoleodomia) |
|---|---|---|
| `Οικοδομικά Τετράγωνα_epoleodomia` | 484 | building_blocks |
| `Πολεοδομικές Γραμμές_epoleodomia` | 11020 | planning_lines |
| `Πολύγωνα Ορων Δόμησης_epoleodomia` | 15 | building_regs_lot |
| `Δασική Ανάρτηση_14_06_21` | 949 | forest_maps_posted_attica_2021 |
| `Δασικοι Χάρτες_13_11_25_ΤΕΕ` | 848 | forest_maps |
| `Πολεοδομικοί Οροι` | 24 | approved_plan_boundaries |
| `Footprints epoleodomia rasters egsa` | 74 | planning_diagrams |
| `oroi_domisis` | 6 | Superseded by v_building_blocks_regulations + building_regs_coefficient_zones |

```sql
DROP TABLE IF EXISTS sp_geodata."Οικοδομικά Τετράγωνα_epoleodomia";
DROP TABLE IF EXISTS sp_geodata."Πολεοδομικές Γραμμές_epoleodomia";
DROP TABLE IF EXISTS sp_geodata."Πολύγωνα Ορων Δόμησης_epoleodomia";
DROP TABLE IF EXISTS sp_geodata."Δασική Ανάρτηση_14_06_21";
DROP TABLE IF EXISTS sp_geodata."Δασικοι Χάρτες_13_11_25_ΤΕΕ";
DROP TABLE IF EXISTS sp_geodata."Πολεοδομικοί Οροι";
DROP TABLE IF EXISTS sp_geodata."Footprints epoleodomia rasters egsa";
DROP TABLE IF EXISTS sp_geodata."oroi_domisis";
```

---

## Tables to KEEP (24+) — Unique data

### Archaeological (RICHER than epoleodomia — PRIMARY source for API)

| Table | Rows | Why Keep |
|---|---|---|
| `Αρχαιλογία_Κυρηγμένα_Μνημεία` | 62 | Curated: site_name, site_name_en, OT numbers, site_category, full FEK refs |
| `Αρχαιολογία_Ζώνες_Προστασίας` | 5 | Curated: includes whole-island 1967 designation with FEK refs |

### Shoreline (RICHER than epoleodomia)

| Table | Rows | Why Keep |
|---|---|---|
| `Αιγιαλός_Παραλία` | 79 | Full FEK chronology 1969-2018. epoleodomia has only 7 features |

### Cadastral

| Table | Rows | Why Keep |
|---|---|---|
| `Ανάρτηση_Κτηματολογιου` | 3147 | Posted cadastral parcels |
| `Προανάρτηση_Κτηματολογίου` | 3149 | Pre-posting cadastral parcels |

### Geological / Streams / ENFIA / Churches / Infrastructure / FEK / Reference

*(See full list in v1.0 SP_GEODATA_CLEANUP.md for complete inventory)*

---

## API Integration Notes

Archaeological queries should use sp_geodata curated tables as primary source.
Shoreline queries should use sp_geodata.Αιγιαλός_Παραλία (79 features) over epoleodomia.shorelines (7).
