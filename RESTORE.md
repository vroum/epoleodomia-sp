# RESTORE Runbook — gis database

> Διάβασέ το ΠΡΙΝ το χρειαστείς. Δοκίμασε το Σενάριο Β μία φορά με ηρεμία —
> backup που δεν έχει γίνει ποτέ restore είναι ελπίδα, όχι backup.

## Τι υπάρχει και πού

| Αρχείο | Τι είναι | Πού |
|---|---|---|
| `gis_<Ημέρα>.dump` | Πλήρες dump, κυκλικά 7 ημερών | Synology `/volume1/gis_backups/gis` + τοπικά `C:\GIS_BACKUPS`, `O:\backup_synology_gis` |
| `gis_monthly_YYYYMM.dump` | Μηνιαίο keeper (6 τελευταία) | ίδια |
| `sp_geodata_latest.dump` | ΜΟΝΟ τα curated (αναντικατάστατα) | ίδια |

Το `epoleodomia` schema και τα `kaek_*_operating` ξαναχτίζονται και με sync
(`sync_menu.bat all`) — το κρίσιμο είναι το `sp_geodata`.

---

## Σενάριο Α — Η βάση χάλασε, το Synology ζει

```bash
# SSH στο Synology (ή Container Manager terminal)
# 1. Αντιγραφή του dump μέσα στο container
docker cp /volume1/gis_backups/gis/gis_Mon.dump postgis:/tmp/gis.dump

# 2. Restore σε ΝΕΑ βάση πρώτα (ποτέ κατευθείαν πάνω στην παλιά)
#    ΠΡΟΣΟΧΗ: πάντα «docker exec -u postgres ... -U postgres» — το local socket
#    έχει peer auth (ως root/docker βγάζει "Peer authentication failed")
docker exec -u postgres postgis createdb -U postgres gis_restored
docker exec -u postgres postgis pg_restore -U postgres -d gis_restored /tmp/gis.dump

# 3. Έλεγχος (βλ. Verification παρακάτω), μετά rename:
docker exec -u postgres postgis psql -U postgres -c "ALTER DATABASE gis RENAME TO gis_broken;"
docker exec -u postgres postgis psql -U postgres -c "ALTER DATABASE gis_restored RENAME TO gis;"
```

## Σενάριο Β — Το Synology πέθανε (disaster)

Χρειάζεσαι: Docker Desktop στο PC + το τελευταίο dump από `C:\GIS_BACKUPS`.

```bash
# 1. Τοπικό postgis container — ΙΔΙΟ image με το NAS
docker run -d --name postgis-local -p 65432:5432 ^
  -e POSTGRES_USER=docker -e POSTGRES_PASS=<ο κωδικός από το .env> ^
  -e POSTGRES_DB=gis -e POSTGRES_MULTIPLE_EXTENSIONS=postgis,hstore,pg_cron ^
  -v postgis_local_data:/var/lib/postgresql ^
  kartoza/postgis:latest

# 2. Restore (πάντα -u postgres / -U postgres — peer auth στο local socket)
docker cp C:\GIS_BACKUPS\gis_Mon.dump postgis-local:/tmp/gis.dump
docker exec -u postgres postgis-local pg_restore -U postgres -d gis --clean --if-exists /tmp/gis.dump

# 3. Στο .env του project: EPOL_DB_HOST=127.0.0.1  (port μένει 65432)
# 4. start_server.bat — δουλεύεις ξανά. Σύνολο: ~30 λεπτά.
```

Σημείωση kartoza: η μεταβλητή είναι `POSTGRES_PASS` (όχι POSTGRES_PASSWORD).

## Σενάριο Γ — Χάλασε μόνο το sp_geodata (κατά λάθος DROP κλπ.)

```bash
docker cp /volume1/gis_backups/gis/sp_geodata_latest.dump postgis:/tmp/spg.dump
docker exec -u postgres postgis psql -U postgres -d gis -c "DROP SCHEMA IF EXISTS sp_geodata CASCADE;"
docker exec -u postgres postgis pg_restore -U postgres -d gis /tmp/spg.dump
```

Ένας πίνακας μόνο: `pg_restore -U postgres -d gis -n sp_geodata -t <table> /tmp/spg.dump`

---

## Verification μετά από κάθε restore

```sql
SELECT count(*) FROM sp_geodata.kaek_parcels_operating;   -- ~3405
SELECT count(*) FROM sp_geodata."Αιγιαλός_Παραλία";       -- 79
SELECT count(*) FROM epoleodomia.planning_lines;           -- ~11000
SELECT PostGIS_Version();
```

Μετά: `start_server.bat` → στο AutoCAD `EREPORT` σε γνωστό σημείο →
σύγκρινε με παλιό report.

---

## Προληπτικά (κάν' τα τώρα, όχι μετά)

1. **Κλείδωσε το image version.** Το container τρέχει `kartoza/postgis:latest` —
   ένα "update" στο Container Manager μπορεί να πηδήξει major PostgreSQL version
   και ο data volume να μην ανοίγει. Δες την τρέχουσα έκδοση με
   `docker exec postgis psql -U docker -c "SELECT version();"` και ξαναστήσιμο
   με tag π.χ. `kartoza/postgis:16-3.4` όταν ευκαιρήσεις.
2. **Backup του O: προς το NAS.** Το O: είναι τοπικός δίσκος με το project +
   τα εισηγμένα rasters (δικά σου δεδομένα — τα DJI δεν ξανακατεβαίνουν από
   πουθενά). Η βάση έχει πλέον backup, το O: όχι: ένα robocopy PC→NAS ή
   Synology Drive sync του project folder κλείνει την τρύπα — NAS και PC
   αλληλοκαλύπτονται.
3. **Δοκιμαστικό restore** του Σεναρίου Β μία φορά — σημείωσε εδώ πότε:
   - [x] Τελευταίο restore test: **2026-07-04** (Docker Desktop, gis_Sat.dump,
     πλήρης αλυσίδα: restore → API → EREPORT στο AutoCAD — OK)
4. **Το .env ΔΕΝ είναι στο backup της βάσης** — κράτα τον κωδικό και σε
   password manager.
