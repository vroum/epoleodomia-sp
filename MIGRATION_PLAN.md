# Εφαρμογή της προετοιμασίας TEE στην υπάρχουσα βάση

Η πρώτη ελεγχόμενη production λήψη raster πέρασε επίσης στις 31/10/2026: ένα
ελλείπον φύλλο 34Δ/2022 (ID 47), μέσω epol_sync, με αμετάβλητα reports,
χειροκίνητα στοιχεία και όλα τα παλιά αρχεία. Η κοινή διαδρομή αποθήκευσης
διορθώθηκε στον υπάρχοντα φάκελο. Ολοκληρώθηκαν και οι 28 υπόλοιπες λήψεις:
διαθέσιμα 103/103 αρχεία, με ίδια φίλτρα/αποκλεισμούς και reports. Τα αρχεία
αρχειοθετήθηκαν επίσης στο NAS με έλεγχο checksum και δοκιμασμένη επαναφορά.
Προστέθηκε μόνο η μη απόρρητη ρύθμιση EPOL_RASTER_NAS_PATH.

Η διαδικασία αφορά τη συγκεκριμένη εγκατάσταση PostgreSQL 18 που ελέγχθηκε στις
27/10/2026. Εφαρμόστηκε στην `gis` στις **31/10/2026, 11:44 ώρα Ελλάδας**, από τον
χρήστη με λογαριασμό PostgreSQL `docker` και τοπική, κρυφή εισαγωγή κωδικού.
Το `codex_reader` παραμένει reader και τα αρχικά `EPOL_DB_*` credentials δεν άλλαξαν.
Σε επόμενο βήμα ο χρήστης δημιούργησε τον περιορισμένο `epol_sync` και πρόσθεσε
ξεχωριστά `EPOL_SYNC_DB_*` credentials για το μενού. Ανεξάρτητος έλεγχος μόνο
ανάγνωσης επιβεβαίωσε τα δικαιώματα, το υγιές API και αμετάβλητα δεδομένα στους
96 τότε πίνακες του project. Μετά την επιβεβαίωση AutoCAD, ολοκληρώθηκε ο πρώτος
production συγχρονισμός TEE ως `epol_sync`: audit #1, 55 layers, 18.794 αμετάβλητες
εγγραφές και κανένα σφάλμα. Τα έξι HTTP reports παραμένουν πανομοιότυπα και τα
curated/κτηματολογικά/EMSY δεδομένα διατηρήθηκαν σε εκείνη την εκτέλεση.
Στη συνέχεια πέρασαν και οι πρώτες production εκτελέσεις κτηματολογίου και EMSY:
3.406 γεωτεμάχια, 21 δουλείες, 725 αποκλειστικές χρήσεις (+2) και 72 σημεία EMSY
(+2). Τα ΚΑΕΚ/γεωμετρίες/κύριες χρήσεις των γεωτεμαχίων διατηρήθηκαν, με αλλαγές
σε prop_hor οκτώ εγγραφών και prop_vert μίας, καθώς και οκτώ νέα source OBJECTID.
Τα έξι reports παρέμειναν ίδια. Στη συνέχεια ολοκληρώθηκαν οι production λήψεις
raster και η ελεγμένη αρχειοθέτηση/ανάκτηση στο NAS, όπως καταγράφεται παραπάνω.

Η τρέχουσα προεπισκόπηση δίνει `prepared`, ενώ το `database_setup.py` δίνει
`managed`, με adopted versions 0001/0002. Τα παρακάτω βήματα τεκμηριώνουν τη
διαδικασία που ακολουθήθηκε και τα όρια ανάκαμψης.

Το πλήρες `gis_Sat.dump` της 31/10 (117.247.779 bytes) αποκαταστάθηκε επιτυχώς
σε προσωρινό αντίγραφο και καταγράφηκε στη receipt με SHA-256
`a6ed955255082d5fe793f708bb533f2b137ae67e2afb59f0069c3c67389bd44d`.
Ο χρήστης επιβεβαίωσε ότι τα updates εκκινούν μόνο χειροκίνητα από το μενού.
Μετά τη διευκρίνιση, οι αρχικές τιμές και των 93 πινάκων ταίριαζαν ακόμη με το
backup· ο τοπικός launcher επανέλεγξε την ίδια αντιστοιχία πριν από την εφαρμογή.

Οι ανεξάρτητοι έλεγχοι μετά το commit επιβεβαίωσαν τα αρχικά δεδομένα, το ιστορικό
και τα περιορισμένα δικαιώματα του reader. Τα έξι reports στα ίδια σημεία
ταίριαξαν με το αμετανάστευτο backup. Το API επανεκκινήθηκε με το venv/reader και
πέρασε health, έξι HTTP reports, ΚΑΕΚ, λειτουργούν κτηματολόγιο και unified rasters
με προεπιλογή `working`. Διορθώθηκε μόνο η ασταθής σειρά των ίδιων παρατηρήσεων
μεταξύ Python processes· τα περιεχόμενα παραμένουν ίδια. Στις 31/10 ο χρήστης
επιβεβαίωσε ότι τα `EREPORT`/`KAEK`/`ERASTER` λειτουργούν στο AutoCAD.
Η αποδοχή του πρώτου ελεγχόμενου συγχρονισμού καταγράφεται ξεχωριστά στο STATUS.md.

## Τι περιέχει το πακέτο

- `prepare_legacy_database.py`: προεπισκόπηση μόνο ανάγνωσης από προεπιλογή και
  ρητή εφαρμογή του συγκεκριμένου πλάνου.
- `sql/preparations/installed_tee_20261027.sql` και το αντίστοιχο JSON: παγωμένο
  SQL, αρχική δομή, επιτρεπόμενες αναπαραστάσεις views και checksums των 0001/0002.
  Το SQL αποτελεί μία ενιαία προστατευμένη εντολή· χωρίς τον controller guard
  δεν εκτελείται κανένα επόμενο DDL, ανεξάρτητα από τον χειρισμό errors του client.
- `tests/run_preparation_tests.py`: δοκιμές με το πραγματικό schema ως fixture,
  συνθετικά δεδομένα και νέο προσωρινό PostgreSQL 18 container.
- `tests/run_preparation_rehearsal.py`: πλήρης αποκατάσταση πραγματικού backup,
  εφαρμογή μόνο στο αντίγραφο και σύγκριση αρχικών δεδομένων και έξι reports.

Η migration προσθέτει τα tracking/audit/lookup αντικείμενα που λείπουν, διευρύνει
τέσσερα απλά πεδία, προσθέτει ελεγμένα constraints/indexes και αναδημιουργεί πέντε
συγκεκριμένα views διατηρώντας ορισμούς, ιδιοκτήτες, δικαιώματα, επιλογές και σχόλια.
Οι αρχικές τιμές/γεωμετρίες, τα generated label points και τα duplicate OBJECTID
του `building_regs_lot` διατηρούνται. Νέα αντικείμενα δημιουργούνται ως ο υπάρχων
ιδιοκτήτης του schema, με τα default privileges του. Ο reader αποκτά SELECT μόνο
στα νέα αντικείμενα και στο ιστορικό εφαρμογής.

Δεν εκτελείται sync, ανακατασκευή της βάσης, αλλαγή CRS, αλλαγή curated δεδομένων
`sp_geodata`, raster exclusion/role ή εγκατάσταση του προαιρετικού `005` registry.
Τα ιστορικά `001_tables.sql` και τα SQL στο αγνοημένο `logs/` δεν είναι εντολές
εφαρμογής. Τα frozen migrations 0001/0002 δεν αλλάζουν ούτε εκτελούνται πάνω στα
υπάρχοντα δεδομένα: καταγράφονται ως adopted στην ίδια συναλλαγή με την προετοιμασία.

## 1. Προεπισκόπηση και έλεγχοι

Από τον φάκελο του project, με το υπάρχον `.env` του reader:

```powershell
& .\.venv\Scripts\python.exe -B prepare_legacy_database.py --json
```

Αναμενόμενο πριν από εφαρμογή: `state: ready`, κενά `findings`,
`owner: docker`, `can_apply: false`, `applied: false`.
Το `ready` αφορά συμβατότητα του ελεγμένου schema/δεδομένων· δεν δίνει δικαιώματα
εγγραφής στον reader. Η εντολή δεν δημιουργεί πίνακες ή ιστορικό.

Το `plan_hash` συνδέει το πλάνο με τον συγκεκριμένο host/port/database, το SQL,
τη δομή, τα δικαιώματα/default privileges, τα metadata και τους αριθμούς εγγραφών.
Δεν είναι checksum όλων των τιμών. Κατά την εφαρμογή ξαναγίνονται οι έλεγχοι και
συγκρίνονται οι αρχικές τιμές πριν/μετά μέσα στη συναλλαγή.

Αλλαγμένα views, άγνωστες εξαρτήσεις, grant chains άλλων ιδιοκτητών, security
labels στα αναδημιουργούμενα views, μη ελεγμένα constraints, διπλά IDs,
μη πολυγωνικές γεωμετρίες ή μερική προετοιμασία σταματούν τη διαδικασία.
Δεν υπάρχει `--force` ούτε αυτόματη διόρθωση αυτών των ευρημάτων.

## 2. Παράθυρο συντήρησης και φρέσκο backup

1. Παύση όλων των χειροκίνητων/προγραμματισμένων writers του project: TEE,
   κτηματολόγιο, EMSY, raster ingest και άλλες εφαρμογές που γράφουν στο TEE schema.
   Καταγραφή του τρόπου επανεκκίνησής τους και της έκδοσης κώδικα που θα εφαρμοστεί.
2. Παύση του API κατά την τελική εφαρμογή. Αποσύνδεση ενεργών CAD/QGIS εργασιών
   από τη βάση για να αποδεσμευτούν παλιές συναλλαγές και cached query plans.
3. Νέο πλήρες backup μέσω της υπάρχουσας διαδικασίας Synology, μετά την παύση
   writers. Έλεγχος επιτυχίας και χρόνου δημιουργίας. Το πρωινό backup δεν
   αντικαθιστά αυτό το βήμα αν έχουν μεσολαβήσει εγγραφές.
4. Αντιγραφή του archive με μοναδικό όνομα σε τοπικό δίσκο εκτός NAS και καταγραφή
   SHA-256. Τα επίσημα `C:\GIS_BACKUPS` και `O:\backup_synology_gis` είχαν μείνει
   στις 14/08/2026 κατά τον έλεγχο· πρέπει να ενημερωθούν πριν από παραγωγή.

Το ίδιο, αμετάβλητο τοπικό αρχείο χρησιμοποιείται για πρόβα και εφαρμογή.
Παράδειγμα μεταβλητής — αντικατάστησε το όνομα με το πραγματικό νέο archive:

```powershell
$migrationBackup = 'C:\GIS_BACKUPS\gis_pre_migration_YYYYMMDD_HHMM.dump'
$migrationBackupSha = (Get-FileHash -LiteralPath $migrationBackup -Algorithm SHA256).Hash
```

## 3. Αποκατάσταση και πρόβα του ακριβούς archive

Με Docker διαθέσιμο και εγκατεστημένα τα `requirements.txt`:

```powershell
& .\.venv\Scripts\python.exe -B tests/run_preparation_tests.py
& .\.venv\Scripts\python.exe -B tests/run_preparation_rehearsal.py `
    --backup $migrationBackup --output logs/preparation_rehearsal.json
```

Ο runner χρησιμοποιεί pinned image PostgreSQL 18/PostGIS, μοναδικό localhost port,
NOLOGIN placeholders για τα ονόματα ρόλων και απενεργοποιημένο cron execution.
Διαβάζει μόνο ονόματα ρόλων από την κανονική βάση. Αποκαθιστά το archive με
`pg_restore --exit-on-error --single-transaction`, ελέγχει ότι το archive δεν
άλλαξε κατά την ανάγνωση, συγκρίνει τις αρχικές τιμές των project tables και
απαιτεί ίδια έξι reports πριν/μετά. Το αντίγραφο διαγράφεται αυτόματα στο τέλος.

Απαιτείται επιτυχία (`ok: true`) και SHA που συμφωνεί με το archive της εφαρμογής.
Το report καταγράφει checksums του recipe/controller, εκδόσεις και αποτελέσματα.
Η πρόβα δεν μεταφέρει passwords, role memberships ή πλήρη ρύθμιση δικαιωμάτων
σύνδεσης των ρόλων. Δεν πιστοποιεί συμπεριφορά AutoCAD ή αντοχή σε απώλεια ρεύματος.

Η εντολή εφαρμογής ελέγχει το format marker και το SHA του επιλεγμένου αρχείου.
Δεν πραγματοποιεί από μόνη της αποκατάσταση ούτε πιστοποιεί την ηλικία ή την
προέλευση του backup. Τα παραπάνω βήματα είναι ευθύνη του χειριστή της εφαρμογής.

## 4. Τελικό πλάνο με λογαριασμό εφαρμογής

Απαιτείται λογαριασμός που μπορεί να κάνει `SET ROLE` στον ιδιοκτήτη του schema.
Ο ιδιοκτήτης χρειάζεται CREATE στη βάση για το `epol_meta`. Δεν αλλάζουμε τον
`codex_reader`, το `.env` του API ή role memberships μέσα από αυτή τη διαδικασία.

Για προσωρινή επιλογή λογαριασμού σε αποκλειστική PowerShell συνεδρία:

```powershell
$migrationPreviousUser = $env:EPOL_DB_USER
$migrationPreviousPassword = $env:EPOL_DB_PASSWORD
$migrationCredential = Get-Credential -Message 'PostgreSQL migration account'
$env:EPOL_DB_USER = $migrationCredential.UserName
$env:EPOL_DB_PASSWORD = $migrationCredential.GetNetworkCredential().Password
```

Το όνομα χρήστη είναι ρόλος PostgreSQL, όχι Windows λογαριασμός. Μην εμφανίζεις
ή αποθηκεύεις το password. Μην ξεκινήσεις API/sync μέσα σε αυτή τη συνεδρία.

Δημιουργία του τελικού, μόνο ανάγνωσης πλάνου:

```powershell
& .\.venv\Scripts\python.exe -B prepare_legacy_database.py --json `
    | Tee-Object -FilePath logs/preparation_final_preview.json
```

Έλεγχος host/port/database, `findings`, ενεργειών, owner και `can_apply: true`.
Ο χειριστής εγκρίνει αυτό το συγκεκριμένο πλάνο πριν από την επόμενη εντολή.
Αν το πλάνο αλλάξει, απαιτείται νέα προεπισκόπηση και έλεγχος.

## 5. Ρητή εφαρμογή και επαλήθευση

Μόνο μετά την ολοκλήρωση/έγκριση των παραπάνω:

```powershell
try {
    $migrationPlan = Get-Content -LiteralPath logs/preparation_final_preview.json -Raw | ConvertFrom-Json
    if ($migrationPlan.state -ne 'ready' -or $migrationPlan.findings.Count -ne 0 -or -not $migrationPlan.can_apply) {
        throw 'The reviewed migration plan is not ready.'
    }
    & .\.venv\Scripts\python.exe -B prepare_legacy_database.py --apply `
        --expect-plan $migrationPlan.plan_hash `
        --backup $migrationBackup --backup-sha256 $migrationBackupSha
    if ($LASTEXITCODE -ne 0) { throw 'Migration failed; keep writers paused.' }
    & .\.venv\Scripts\python.exe -B database_setup.py
    if ($LASTEXITCODE -ne 0) { throw 'Post-migration schema validation failed.' }
}
finally {
    $env:EPOL_DB_USER = $migrationPreviousUser
    $env:EPOL_DB_PASSWORD = $migrationPreviousPassword
    $migrationCredential = $null
}
```

Αν διακοπεί η διαδικασία πριν από το τελευταίο block, επανάφερε αμέσως τις δύο
μεταβλητές περιβάλλοντος ή κλείσε την αποκλειστική PowerShell συνεδρία.
Ούτε τα credentials ούτε το `.env` αποθηκεύονται από τη migration.

Η εφαρμογή αποκτά κοινό advisory lock με το `database_setup.py` και locks στα
αρχικά TEE relations. Μετά την απόκτηση των locks ξαναδιαβάζει το πλάνο. Έχει
lock timeout 5 s και statement timeout 120 s· αποτυχία/timeout προκαλεί rollback,
όχι απεριόριστη αναμονή ή απενεργοποίηση των ελέγχων.

Όλα τα DDL, οι έλεγχοι διατήρησης και τα δύο είδη ιστορικού (`schema_migrations`,
`schema_preparations`) γίνονται στην ίδια συναλλαγή. Στο δεύτερο αποθηκεύονται
recipe checksum, plan hash, backup SHA, fingerprint αρχικών δεδομένων και χρήστης
εφαρμογής. Επανάληψη μετά από επιτυχία ελέγχει το ιστορικό χωρίς replay του SQL.

Με τα reader credentials ξανατρέξε την προεπισκόπηση: αναμένεται `prepared`.
Έπειτα ξεκίνησε το API με τον reader, έλεγξε point/parcel reports εντός και εκτός
σχεδίου και τις βασικές εντολές AutoCAD (`EREPORT`, `KAEK`, raster εμφάνιση).
Μόνο μετά από αυτά επανεκκινούν οι writers με τα δικά τους κατάλληλα credentials.
Δεν εκτελούμε όλα τα sync για πρώτη δοκιμή πάνω στην παραγωγή.

## 6. Επαναφορά

**Αποτυχία πριν από commit:** η ίδια συναλλαγή αναιρεί SQL και ιστορικό. Επιβεβαίωσε
το αποτέλεσμα με νέα προεπισκόπηση, κράτησε writers/API σε συντήρηση και διάγνωσε
το συγκεκριμένο error. Δεν επαναλαμβάνουμε με `--force` ή παλιό plan hash.

**Χαμένη σύνδεση κατά το commit:** το αποτέλεσμα μπορεί να έχει ολοκληρωθεί στον
server. Πρώτα σύνδεση μόνο ανάγνωσης και έλεγχος `prepared`/ιστορικού. Αν είναι
έτοιμο και έγκυρο, δεν ξανατρέχουμε DDL. Αν το αποτέλεσμα είναι ασαφές, σταματά η
διαδικασία για έλεγχο διαχειριστή.

**Πρόβλημα μετά από επιτυχημένο commit:** παύση writers και διατήρηση της τρέχουσας
βάσης για διάγνωση. Δεν υπάρχει αυτόματο αντίστροφο SQL που να στενεύει πεδία ή να
σβήνει tracking/history. Ο διαχειριστής αποκαθιστά το ελεγμένο backup σε ξεχωριστή
βάση/container με μόνιμο storage, επαληθεύει API/δεδομένα και εγκρίνει τη μεταφορά
της σύνδεσης στην αποκατεστημένη εγκατάσταση. Αν έχουν μεσολαβήσει νέες εγγραφές,
απαιτείται απόφαση για τη διατήρησή τους πριν από τη μεταφορά.

Η `gis` περιέχει και άλλες υπηρεσίες, όπως το `sp_ais`. Για ολική επαναφορά
συντονίζονται και οι δικοί τους writers/μεταγενέστερες εγγραφές. Η στοχευμένη
επαναφορά schema απαιτεί ξεχωριστό έλεγχο διασχηματικών εξαρτήσεων από τον
διαχειριστή. Δεν αντικαθιστούμε αυτόματα ολόκληρη τη βάση για πρόβλημα μόνο του TEE.

Ο προσωρινός runner δοκιμών χρησιμοποιεί tmpfs και αυτόματο cleanup· δεν είναι
περιβάλλον παραγωγικής ανάκαμψης. Η ίδια η μεταφορά υπηρεσίας σε ανακτημένη βάση
δεν εκτελέστηκε ούτε αυτοματοποιείται από αυτό το πακέτο.
