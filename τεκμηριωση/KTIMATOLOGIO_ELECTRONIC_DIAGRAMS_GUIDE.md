# Οδηγός μορφοποίησης ηλεκτρονικών διαγραμμάτων Κτηματολογίου

Ημερομηνία σύνταξης: 2026-07-08  
Βάση: επίσημα παραδείγματα Ελληνικού Κτηματολογίου, έκδοση σελίδας `11_2024`  
Κύρια πηγή: <https://ktimatologio.gov.gr/Professionals/Content/examples/paradeigmata_html_11_2024.html>

Σκοπός του αρχείου είναι να έχουμε ένα αυτοτελές τεχνικό σημείο αναφοράς για το επόμενο στάδιο ανάπτυξης, χωρίς να χρειάζεται να επιστρέφουμε στη σελίδα των παραδειγμάτων. Το κείμενο είναι οργανωμένο ως πρακτικό specification για CAD/DXF validation και παραγωγή οδηγιών.

## 1. Πεδίο εφαρμογής

Τα παραδείγματα καλύπτουν:

- Τοπογραφικά Διαγράμματα (`ΤΔ`) εκτός και εντός σχεδίου.
- Διαγράμματα Γεωμετρικών Μεταβολών (`ΔΓΜ`) για καταχώριση εγγραπτέας πράξης.
- Διαγράμματα Γεωμετρικών Μεταβολών (`ΔΓΜ`) για διόρθωση γεωμετρικών στοιχείων.
- Τοπογραφικά Διαγράμματα Γεωμετρικών Μεταβολών (`ΤΔΓΜ`) που συνοδεύουν δικόγραφα.

Η σελίδα δείχνει παραδείγματα διαγραμμάτων, layers και συχνών σφαλμάτων. Δεν αντικαθιστά το πλήρες τεύχος τεχνικών προδιαγραφών. Για παραγωγικό validator πρέπει να θεωρηθεί οδηγός κανόνων και να συνδυαστεί με το επίσημο τεύχος προδιαγραφών όταν απαιτούνται ακριβείς ανοχές, τύποι γραμμών, text styles, units ή DXF λεπτομέρειες που δεν φαίνονται στα παραδείγματα.

## 2. Κεντρικό μοντέλο σκέψης

Τα παραδείγματα διαχωρίζουν σταθερά τέσσερις έννοιες:

| Έννοια | Layer / layers | Περιγραφή |
|---|---|---|
| Αποτύπωση μηχανικού | `TOPO_PROP`, μαζί με `BOUND_IMPL` / `BOUND_UNIMPL` | Το γεωτεμάχιο όπως αποτυπώνεται στο τοπογραφικό. |
| Εικόνα Κτηματολογίου | `PST_KAEK`, σε ειδικές περιπτώσεις και `PST` | Τα όρια και οι ΚΑΕΚ όπως εμφανίζονται στο Κτηματογραφικό Διάγραμμα. |
| Περιγραφή μεταβολής | `LINE_XM`, `LINE_XM_VST`, `AREA_D`, `AREA_A`, `EAS`, `VST` | Τα γεωμετρικά στοιχεία που εξηγούν τι αλλάζει. |
| Τελικό αποτέλεσμα στη βάση | `DGM_PROP_FINAL`, `EAS_FINAL`, `VST_FINAL` | Τα τελικά όρια/χώροι που θα ενημερώσουν την κτηματολογική βάση. |

Πρακτικός κανόνας:

```text
TOPO_PROP        = τι αποτύπωσε ο μηχανικός
PST_KAEK / PST   = τι δείχνει το Κτηματολόγιο πριν τη μεταβολή
AREA_D / AREA_A  = τι διεκδικείται ή αφαιρείται σε διορθώσεις
LINE_XM          = γραμμή κατάτμησης εγγραπτέας πράξης
LINE_XM_VST      = γραμμή μεταβολής καθέτων / αποκλειστικών χρήσεων
DGM_PROP_FINAL   = τι πρέπει να περάσει τελικά στη βάση
```

## 3. Καθολικοί κανόνες γεωμετρίας και κειμένου

### 3.1 Γεωμετρία

| Περίπτωση | Σωστή οντότητα |
|---|---|
| Όρια γεωτεμαχίου | `Closed LWPolyline` |
| Τελικά πολύγωνα γεωτεμαχίων | `Closed LWPolyline` |
| Πολύγωνα δουλείας | `Closed LWPolyline` |
| Χώροι αποκλειστικής χρήσης / κάθετες | `Closed LWPolyline` |
| Περιοχές `AREA_D` / `AREA_A` | `Closed LWPolyline` |
| Γραμμή κατάτμησης | ανοικτή `LWPolyline` |
| Γραμμή μεταβολής καθέτων | ανοικτή `LWPolyline` |
| Υλοποιημένα ή ανυλοποίητα όρια | ανοικτή ή κλειστή `LWPolyline`, ανάλογα με το πραγματικό τμήμα ορίου |

Κανόνες:

- Τα κλειστά πολύγωνα πρέπει να είναι πραγματικά κλειστά. Η αρχή και το τέλος πρέπει να συμπίπτουν.
- Τα εξωτερικά και εσωτερικά όρια γεωτεμαχίου δεν πρέπει να γίνονται μία ενιαία πολυγωνική γραμμή. Χρειάζονται χωριστές κλειστές πολυγωνικές οντότητες.
- Η γραμμή μεταβολής πρέπει να εφαρμόζει ακριβώς στο όριο αναφοράς που ορίζει η περίπτωση. Δεν πρέπει να υπερβαίνει ούτε να υπολείπεται του σχετικού πολυγώνου.
- Στα τελικά πολύγωνα πρέπει να διατηρούνται οι κρίσιμοι κόμβοι των περιμετρικών ορίων του `PST_KAEK`, όπου αυτό ζητείται από την περίπτωση.

### 3.2 Κείμενο

| Περιεχόμενο | Σωστή οντότητα |
|---|---|
| ΚΑΕΚ στο `PST_KAEK` | `TEXT`, όχι `MTEXT` |
| Κωδικός διοικητικής πράξης στο `DBOUND_PROP` | `TEXT`, όχι `MTEXT` |
| Ονομασία Οικοδομικού Τετραγώνου στο `OT` | `TEXT`, όχι `MTEXT` |
| Ονομασία οδού στο `ROAD` | `TEXT`, όχι `MTEXT` |

Κανόνας validator: σε layers που απαιτούν απλό κείμενο, κάθε `MTEXT` πρέπει να σημαίνεται ως σφάλμα.

### 3.3 Κτηματογραφικό Διάγραμμα

Τα όρια του `PST_KAEK` λαμβάνονται από το Κτηματογραφικό Διάγραμμα. Το Κτηματογραφικό Διάγραμμα χορηγείται από το αρμόδιο Κτηματολογικό Γραφείο και μπορεί να διατεθεί και σε `DXF`.

## 4. Κατάλογος layers

| Layer | Τύπος | Ρόλος | Βασικοί κανόνες |
|---|---|---|---|
| `BOUND_IMPL` | `LWPolyline` ή `Closed LWPolyline` | Υλοποιημένα όρια αποτύπωσης, π.χ. μάντρα, σύρμα, όριο κτιρίου. | Αναφέρεται μόνο στα όρια του `TOPO_PROP`, εκτός αν ειδική περίπτωση απαιτεί περισσότερα εμπλεκόμενα ακίνητα. |
| `BOUND_UNIMPL` | `LWPolyline` ή `Closed LWPolyline` | Ανυλοποίητα όρια αποτύπωσης. | Ίδιος περιορισμός με `BOUND_IMPL`. |
| `TOPO_PROP` | `Closed LWPolyline` | Όρια ιδιοκτησίας/γεωτεμαχίου όπως προκύπτουν από την αποτύπωση. | Συντίθεται από `BOUND_IMPL` και `BOUND_UNIMPL`. Δεν μπαίνουν άσχετα όμορα όρια. |
| `TOPO_PROP_NEW` | `Closed LWPolyline` | Νέα όρια από εγγραπτέα πράξη, π.χ. κατάτμηση ή συνένωση. | Χρησιμοποιείται μόνο σε εγγραπτέες πράξεις, όχι σε διορθώσεις ή ΤΔΓΜ δικογράφων. |
| `PST_KAEK` | `Closed LWPolyline` + `TEXT` ΚΑΕΚ | Όρια Κτηματολογίου και αντίστοιχοι ΚΑΕΚ. | ΚΑΕΚ ως `TEXT`. Περιλαμβάνει όλα τα εμπλεκόμενα/επηρεαζόμενα γεωτεμάχια που απαιτεί η περίπτωση. |
| `PST` | `Closed LWPolyline` | Βοηθητικό layer για αρχική/λανθασμένη θέση γεωτεμαχίου σε ΤΔΓΜ μεταφοράς θέσης. | Δεν αντικαθιστά το `PST_KAEK` για το επηρεαζόμενο γεωτεμάχιο. |
| `DGM_PROP_FINAL` | `Closed LWPolyline` | Τελικά γεωτεμάχια για ενημέρωση κτηματολογικής βάσης. | Περιλαμβάνει όλα τα τελικά επηρεαζόμενα γεωτεμάχια, όχι μόνο το κύριο ακίνητο. |
| `LINE_XM` | ανοικτή `LWPolyline` | Γραμμή κατάτμησης για εγγραπτέες πράξεις. | Εφαρμόζει στα όρια του `PST_KAEK`. Δεν χρησιμοποιείται σε συνένωση ή διορθώσεις. |
| `LINE_XM_VST` | ανοικτή `LWPolyline` | Γραμμή χωρικής μεταβολής καθέτων / αποκλειστικών χρήσεων. | Εφαρμόζει στα όρια του κατάλληλου πολυγώνου αναφοράς: `PST_KAEK` ή `DGM_PROP_FINAL`, ανάλογα με την περίπτωση. |
| `AREA_D` | `Closed LWPolyline` | Επιφάνεια που διεκδικείται ή προστίθεται στο υπό διόρθωση/νέο γεωτεμάχιο. | Χρησιμοποιείται σε διορθώσεις και ΤΔΓΜ δικογράφων. |
| `AREA_A` | `Closed LWPolyline` | Επιφάνεια που αφαιρείται από το υπό διόρθωση γεωτεμάχιο ή εξαιρείται. | Χρησιμοποιείται όπου υπάρχει αποκοπτόμενο τμήμα. |
| `EAS` | `Closed LWPolyline` | Δεσμευμένος χώρος δουλείας όπως περιγράφεται στην πράξη/αποτύπωση. | Εφαρμόζει εντός `TOPO_PROP`. |
| `EAS_FINAL` | `Closed LWPolyline` | Τελικός χώρος δουλείας για ενημέρωση κτηματολογικής βάσης. | Περιορίζεται εντός του σχετικού `PST_KAEK`. |
| `EAS_PST` | `Closed LWPolyline` | Βοηθητική απεικόνιση υφιστάμενης δουλείας από το Κτηματογραφικό Διάγραμμα. | Αναφέρεται ως βοηθητικό/μη υποχρεωτικό στα παραδείγματα διόρθωσης δουλείας. |
| `VST` | `Closed LWPolyline` | Χώροι αποκλειστικής χρήσης όπως περιγράφονται στην πράξη. | Χρησιμοποιείται για σύσταση/τροποποίηση, όχι για κατάργηση καθέτων. |
| `VST_FINAL` | `Closed LWPolyline` | Τελικοί χώροι αποκλειστικής χρήσης για ενημέρωση της βάσης. | Δεν περιλαμβάνει κοινόχρηστο χώρο εκτός καθέτων. Δεν χρησιμοποιείται σε απλή κατάργηση καθέτων. |
| `VST_PST` | `Closed LWPolyline` | Βοηθητική απεικόνιση χώρων αποκλειστικής χρήσης από το Κτηματογραφικό Διάγραμμα. | Βοηθητικό/μη υποχρεωτικό στα παραδείγματα διόρθωσης καθέτων. |
| `DBOUND_PROP` | ανοικτή ή κλειστή `LWPolyline` + `TEXT` | Όρια ιδιοκτησίας βάσει διοικητικής πράξης, π.χ. αναδασμός. | Δεν αφορά καταχώριση διοικητικών πράξεων στα παραδείγματα, επειδή δεν έχει οριστεί ηλεκτρονική υποβολή τους. |
| `DBOUND_RYM` | ανοικτή ή κλειστή `LWPolyline` | Ρυμοτομική γραμμή. | Χρήση σε ΤΔ εντός σχεδίου. |
| `OT` | `TEXT` | Ονομασία Οικοδομικών Τετραγώνων. | Όχι `MTEXT`. |
| `ROAD` | `TEXT` | Ονομασία οδών. | Όχι `MTEXT`. |
| `Κάθετες ΚΔ` | `Closed LWPolyline` | Υφιστάμενα όρια καθέτων από Κτηματογραφικό Διάγραμμα. | Εμφανίζεται στην κατάργηση καθέτων ως στοιχείο του ΚΔ, όχι ως `VST`/`VST_FINAL`. |
| `BLD` | οπτικό layer παραδείγματος | Κτίρια/βοηθητική απεικόνιση στα qgis2web παραδείγματα. | Δεν περιγράφεται ως υποχρεωτικό layer στα βήματα της σελίδας. |
| `text` | οπτικό/βοηθητικό layer παραδείγματος | Ετικέτες σε qgis2web παράδειγμα. | Δεν περιγράφεται ως υποχρεωτικό layer στα βήματα της σελίδας. |

## 5. Πίνακας απόφασης ανά περίπτωση

| Αν θέλουμε... | Τύπος διαγράμματος | Κύρια layers |
|---|---|---|
| Απλή αποτύπωση εκτός σχεδίου | `ΤΔ εκτός σχεδίου` | `BOUND_IMPL`, `BOUND_UNIMPL`, `TOPO_PROP`, `PST_KAEK` |
| Απλή αποτύπωση εντός σχεδίου | `ΤΔ εντός σχεδίου` | παραπάνω + `DBOUND_PROP`, `DBOUND_RYM`, `OT`, `ROAD` |
| Να κοπεί ένα γεωτεμάχιο σε νέα | `ΔΓΜ κατάτμησης` | `TOPO_PROP_NEW`, `LINE_XM`, `DGM_PROP_FINAL` |
| Να ενωθούν γεωτεμάχια | `ΔΓΜ συνένωσης` | `TOPO_PROP_NEW`, `DGM_PROP_FINAL` |
| Να συσταθεί δουλεία | `ΔΓΜ σύστασης δουλείας` | `EAS`, `EAS_FINAL` |
| Να συσταθούν κάθετες | `ΔΓΜ σύστασης καθέτων` | `VST`, `LINE_XM_VST`, `VST_FINAL` |
| Κατάτμηση και μετά σύσταση καθέτων | σύνθετο `ΔΓΜ` | `LINE_XM`, `DGM_PROP_FINAL`, `LINE_XM_VST`, `VST_FINAL` |
| Να καταργηθούν κάθετες | `ΔΓΜ κατάργησης καθέτων` | `PST_KAEK`, `Κάθετες ΚΔ`, `DGM_PROP_FINAL` |
| Να διορθωθούν όρια | `ΔΓΜ διόρθωσης ορίων` | `AREA_D`, `AREA_A`, `DGM_PROP_FINAL` |
| Να διορθωθούν κάθετες χωρίς αλλαγή γεωτεμαχίου | `ΔΓΜ για πράξη` κατά την ηλεκτρονική υποβολή | `VST`, `LINE_XM_VST`, `VST_FINAL`, προαιρετικά `VST_PST` |
| Να διορθωθεί δουλεία χωρίς αλλαγή γεωτεμαχίου | `ΔΓΜ για πράξη` κατά την ηλεκτρονική υποβολή | `EAS`, `EAS_FINAL`, προαιρετικά `EAS_PST` |
| Να διορθωθεί γεωτεμάχιο με εσωτερικό πολύγωνο | `ΔΓΜ διόρθωσης εσωτερικού πολυγώνου` | `AREA_D`, `AREA_A`, `DGM_PROP_FINAL` με χωριστά εξωτερικά/εσωτερικά όρια |
| Να συνοδευτεί δικόγραφο διόρθωσης ορίων | `ΤΔΓΜ` | όπως στη διόρθωση ορίων |
| Να μεταφερθεί γεωτεμάχιο στην ορθή θέση με δικόγραφο | `ΤΔΓΜ μεταφοράς θέσης` | `PST_KAEK`, `PST`, `AREA_D`, `DGM_PROP_FINAL` |
| Να δημιουργηθεί νέο γεωτεμάχιο με δικόγραφο | `ΤΔΓΜ δημιουργίας νέου γεωτεμαχίου` | `AREA_D`, `DGM_PROP_FINAL` |

## 6. Αναλυτικές οδηγίες ανά παράδειγμα

### 6.1 ΤΔ εκτός σχεδίου πόλεως

Πηγή: <https://ktimatologio.gov.gr/Professionals/Content/examples/paradeigmata/topografiko_ektos.html>

Σενάριο: σύνταξη τοπογραφικού για ένα γεωτεμάχιο σε περιοχή με Κτηματολόγιο σε λειτουργία, εκτός σχεδίου ή οικισμού.

Απαιτούμενη λογική:

1. Απόδωσε τα υλοποιημένα και ανυλοποίητα όρια στο `BOUND_IMPL` και `BOUND_UNIMPL`.
2. Τα παραπάνω όρια πρέπει να αφορούν μόνο το γεωτεμάχιο του `TOPO_PROP`.
3. Απόδωσε το γεωτεμάχιο του ΤΔ ως κλειστό πολύγωνο στο `TOPO_PROP`.
4. Απόδωσε το γεωτεμάχιο του Κτηματολογίου στο `PST_KAEK`, επίσης ως κλειστό πολύγωνο.
5. Βάλε τον αντίστοιχο ΚΑΕΚ ως απλό `TEXT`, όχι `MTEXT`.

Συχνά σφάλματα:

- `TOPO_PROP` ή `PST_KAEK` δεν είναι πραγματικά κλειστά.
- Ο ΚΑΕΚ είναι `MTEXT`.
- Τα `BOUND_IMPL` / `BOUND_UNIMPL` περιέχουν και όρια όμορων γεωτεμαχίων που δεν ανήκουν στο `TOPO_PROP`.

qgis2web layer set: `BOUND_IMPL`, `BOUND_UNIMPL`, `TOPO_PROP`, `PST_KAEK`.

### 6.2 ΤΔ εντός σχεδίου πόλεως

Πηγή: <https://ktimatologio.gov.gr/Professionals/Content/examples/paradeigmata/topografiko_entos.html>

Σενάριο: σύνταξη τοπογραφικού για ένα γεωτεμάχιο εντός σχεδίου πόλεως.

Απαιτούμενη λογική:

1. Όπως στο ΤΔ εκτός σχεδίου, δημιουργούνται `BOUND_IMPL`, `BOUND_UNIMPL`, `TOPO_PROP` και `PST_KAEK`.
2. Εφόσον υπάρχει ιδιοκτησία βάσει διοικητικής πράξης, αποδίδεται στο `DBOUND_PROP` με ανοιχτή ή κλειστή πολυγωνική γραμμή και κωδικό ως `TEXT`.
3. Η ρυμοτομική γραμμή αποδίδεται στο `DBOUND_RYM`.
4. Τα Οικοδομικά Τετράγωνα αποδίδονται με `TEXT` στο `OT`.
5. Οι ονομασίες οδών αποδίδονται με `TEXT` στο `ROAD`.

Συχνά σφάλματα:

- `TOPO_PROP` ή `PST_KAEK` δεν είναι κλειστά.
- `PST_KAEK`, `DBOUND_PROP`, `OT` ή `ROAD` περιέχουν `MTEXT` αντί για `TEXT`.
- Τα `BOUND_IMPL` / `BOUND_UNIMPL` περιλαμβάνουν άσχετα όμορα όρια.

qgis2web layer set: `BOUND_IMPL`, `BOUND_UNIMPL`, `TOPO_PROP`, `DBOUND_PROP`, `PST_KAEK`, `DBOUND_RYM`, `BLD`, `OT`, `ROAD`.

### 6.3 ΔΓΜ κατάτμησης

Πηγή: <https://ktimatologio.gov.gr/Professionals/Content/examples/paradeigmata/katatmhsh.html>

Σενάριο: ένα ενιαίο γεωτεμάχιο κατατέμνεται σε δύο νέα ενιαία γεωτεμάχια.

Απαιτούμενη λογική:

1. Δημιούργησε `BOUND_IMPL` / `BOUND_UNIMPL` μόνο για τα όρια του αρχικού `TOPO_PROP`.
2. Το αρχικό γεωτεμάχιο του ΤΔ αποδίδεται στο `TOPO_PROP`.
3. Τα νέα γεωτεμάχια όπως περιγράφονται στο ΤΔ αποδίδονται στο `TOPO_PROP_NEW`.
4. Το γεωτεμάχιο Κτηματολογίου αποδίδεται στο `PST_KAEK` με ΚΑΕΚ ως `TEXT`.
5. Η γραμμή κατάτμησης αποδίδεται ως ανοικτή `LWPolyline` στο `LINE_XM`.
6. Τα τελικά νέα γεωτεμάχια που θα ενημερώσουν τη βάση αποδίδονται στο `DGM_PROP_FINAL`.

Κρίσιμοι κανόνες:

- Το `LINE_XM` οριοθετεί την κατάτμηση πάνω στο κλειστό πολύγωνο του `PST_KAEK`.
- Το `DGM_PROP_FINAL` δημιουργείται από τη λογική `PST_KAEK + LINE_XM`.
- Η γραμμή κατάτμησης στο Κτηματολόγιο πρέπει να ακολουθεί τη γραμμή κατάτμησης του ΤΔ, ανεξάρτητα από τις διαφορές εμβαδού που μπορεί να προκύψουν στα τελικά τμήματα.

Συχνά σφάλματα:

- Δεν εμφανίζονται όλα τα νέα πολύγωνα στο `TOPO_PROP_NEW`.
- Το `LINE_XM` δεν τερματίζει ακριβώς στα όρια του `PST_KAEK`.
- Τα περιμετρικά όρια του `DGM_PROP_FINAL` δεν περιλαμβάνουν όλους τους κόμβους του `PST_KAEK`.
- Το `LINE_XM` δεν συμφωνεί με τη γραμμή κατάτμησης του `TOPO_PROP`.

qgis2web layer set: `BOUND_IMPL`, `BOUND_UNIMPL`, `TOPO_PROP`, `TOPO_PROP_NEW`, `PST_KAEK`, `DGM_PROP_FINAL`, `LINE_XM`.

### 6.4 ΔΓΜ συνένωσης

Πηγή: <https://ktimatologio.gov.gr/Professionals/Content/examples/paradeigmata/synenwsh.html>

Σενάριο: δύο γεωτεμάχια συνενώνονται σε ένα νέο ενιαίο γεωτεμάχιο.

Απαιτούμενη λογική:

1. Απόδωσε τα υλοποιημένα/ανυλοποίητα όρια των γεωτεμαχίων στα `BOUND_IMPL` / `BOUND_UNIMPL`.
2. Τα αρχικά γεωτεμάχια του ΤΔ αποδίδονται στο `TOPO_PROP`.
3. Το νέο ενιαίο γεωτεμάχιο από τη συνένωση αποδίδεται στο `TOPO_PROP_NEW`.
4. Τα αρχικά γεωτεμάχια του Κτηματολογίου αποδίδονται στο `PST_KAEK` με τους ΚΑΕΚ ως `TEXT`.
5. Το τελικό γεωτεμάχιο για ενημέρωση της βάσης αποδίδεται στο `DGM_PROP_FINAL`.

Κρίσιμοι κανόνες:

- Δεν υπάρχει γραμμή κατάτμησης, άρα δεν πρέπει να υπάρχει `LINE_XM`.
- Το `DGM_PROP_FINAL` πρέπει να εφαρμόζει στη συνολική έκταση των σχετικών `PST_KAEK`.

Συχνά σφάλματα:

- Το `DGM_PROP_FINAL` δεν εφαρμόζει στα όρια των `PST_KAEK`.
- Χρησιμοποιείται `LINE_XM` για το κοινό όριο των γεωτεμαχίων, ενώ αυτό δεν επιτρέπεται στη συνένωση.
- Το περίγραμμα του `DGM_PROP_FINAL` δεν περιλαμβάνει όλους τους κόμβους των περιμετρικών ορίων των `PST_KAEK`.

qgis2web layer set: `BOUND_IMPL`, `BOUND_UNIMPL`, `TOPO_PROP`, `TOPO_PROP_NEW`, `PST_KAEK`, `DGM_PROP_FINAL`.

### 6.5 ΔΓΜ σύστασης δουλείας διόδου

Πηγή: <https://ktimatologio.gov.gr/Professionals/Content/examples/paradeigmata/douleia_diodou.html>

Σενάριο: συστήνεται δουλεία διόδου μέσα σε δουλεύον ακίνητο.

Απαιτούμενη λογική:

1. Απόδωσε τα όρια του δουλεύοντος ακινήτου στα `BOUND_IMPL` / `BOUND_UNIMPL` και `TOPO_PROP`.
2. Ο δεσμευμένος χώρος της δουλείας όπως συστήνεται στην πράξη αποδίδεται στο `EAS`.
3. Το `EAS` πρέπει να βρίσκεται μέσα στο `TOPO_PROP`.
4. Τα κτηματολογικά όρια των εμπλεκόμενων γεωτεμαχίων αποδίδονται στο `PST_KAEK`.
5. Ο τελικός χώρος δουλείας για τη βάση αποδίδεται στο `EAS_FINAL`.
6. Το `EAS_FINAL` περιορίζεται εντός του `PST_KAEK` που αφορά το δουλεύον ακίνητο.

Συχνά σφάλματα:

- Το `EAS_FINAL` εφαρμόζεται με βάση το `TOPO_PROP` αντί να περιορίζεται στο σχετικό `PST_KAEK`.
- Το `PST_KAEK` περιλαμβάνει μόνο το δουλεύον ακίνητο και όχι τα επηρεαζόμενα όμορα γεωτεμάχια που χρειάζονται.
- Το `TOPO_PROP` περιλαμβάνει και όρια όμορων γεωτεμαχίων, ενώ στο παράδειγμα σύστασης πρέπει να αφορά μόνο το δουλεύον ακίνητο.

qgis2web layer set: `BOUND_IMPL`, `TOPO_PROP`, `PST_KAEK`, `EAS`, `EAS_FINAL`.

### 6.6 ΔΓΜ σύστασης καθέτων ιδιοκτησιών

Πηγή: <https://ktimatologio.gov.gr/Professionals/Content/examples/paradeigmata/systash_kathetwn.html>

Σενάριο: σύσταση χώρων αποκλειστικής χρήσης σε ένα ενιαίο γεωτεμάχιο.

Απαιτούμενη λογική:

1. Απόδωσε τα όρια του γεωτεμαχίου στα `BOUND_IMPL` / `BOUND_UNIMPL` και `TOPO_PROP`.
2. Οι χώροι αποκλειστικής χρήσης όπως περιγράφονται στην εγγραπτέα πράξη αποδίδονται στο `VST`.
3. Τα `VST` εφαρμόζουν μέσα στα όρια του ακινήτου που αποτυπώθηκε.
4. Το γεωτεμάχιο Κτηματολογίου αποδίδεται στο `PST_KAEK`.
5. Η γραμμή χωρικής μεταβολής καθέτων αποδίδεται στο `LINE_XM_VST`.
6. Οι τελικοί χώροι αποκλειστικής χρήσης για ενημέρωση της βάσης αποδίδονται στο `VST_FINAL`.

Συχνά σφάλματα:

- Το `LINE_XM_VST` δεν εφαρμόζει ακριβώς στα όρια του `PST_KAEK`.
- Το `LINE_XM_VST` ή/και τα `VST_FINAL` δεν συμφωνούν με τη γραμμή σύστασης του `VST` στο ΤΔ.
- Η χωρική μεταβολή πρέπει να τηρεί τη γραμμή σύστασης του ΤΔ, ανεξάρτητα από επιμέρους εμβαδά που προκύπτουν στο `VST_FINAL`.

qgis2web layer set: `BOUND_IMPL`, `BOUND_UNIMPL`, `TOPO_PROP`, `VST`, `PST_KAEK`, `VST_FINAL`, `LINE_XM_VST`.

### 6.7 ΔΓΜ κατάτμησης και σύστασης καθέτων

Πηγή: <https://ktimatologio.gov.gr/Professionals/Content/examples/paradeigmata/katatmhsh_systash_kathetwn.html>

Σενάριο: πρώτα γίνεται κατάτμηση ενός γεωτεμαχίου και μετά σύσταση χώρων αποκλειστικής χρήσης σε ένα από τα νέα γεωτεμάχια.

Απαιτούμενη λογική:

1. Το αρχικό γεωτεμάχιο του ΤΔ αποδίδεται στο `TOPO_PROP`.
2. Τα νέα γεωτεμάχια από την κατάτμηση αποδίδονται στο `TOPO_PROP_NEW`.
3. Οι χώροι αποκλειστικής χρήσης της πράξης αποδίδονται στο `VST`.
4. Το αρχικό γεωτεμάχιο Κτηματολογίου αποδίδεται στο `PST_KAEK`.
5. Η γραμμή κατάτμησης στο Κτηματολόγιο αποδίδεται στο `LINE_XM`.
6. Τα τελικά νέα γεωτεμάχια από την κατάτμηση αποδίδονται στο `DGM_PROP_FINAL`.
7. Η γραμμή χωρικής μεταβολής καθέτων αποδίδεται στο `LINE_XM_VST`.
8. Οι τελικοί χώροι αποκλειστικής χρήσης αποδίδονται στο `VST_FINAL`.

Κρίσιμοι κανόνες:

- Πρώτα λογικά παράγεται το `DGM_PROP_FINAL` της κατάτμησης.
- Η `LINE_XM_VST` εφαρμόζει στα όρια του σχετικού νέου γεωτεμαχίου, δηλαδή στο αντίστοιχο `DGM_PROP_FINAL`, όχι στο αρχικό `PST_KAEK`.

Συχνά σφάλματα:

- Το `LINE_XM` δεν εφαρμόζει στα όρια του `PST_KAEK`.
- Το `LINE_XM_VST` δεν εφαρμόζει στο `DGM_PROP_FINAL`.
- Το `DGM_PROP_FINAL` δεν διατηρεί όλους τους περιμετρικούς κόμβους του `PST_KAEK`.
- Η `LINE_XM_VST` δεν ακολουθεί τη γραμμή σύστασης του ΤΔ.

qgis2web layer set: `BOUND_IMPL`, `BOUND_UNIMPL`, `TOPO_PROP`, `TOPO_PROP_NEW`, `VST`, `PST_KAEK`, `DGM_PROP_FINAL`, `VST_FINAL`, `LINE_XM`, `LINE_XM_VST`.

### 6.8 ΔΓΜ κατάργησης καθέτων ιδιοκτησιών

Πηγή: <https://ktimatologio.gov.gr/Professionals/Content/examples/paradeigmata/katarghsh_kathetwn.html>

Σενάριο: καταργούνται υφιστάμενοι χώροι αποκλειστικής χρήσης σε γεωτεμάχιο.

Απαιτούμενη λογική:

1. Απόδωσε τα όρια του γεωτεμαχίου στο `TOPO_PROP`.
2. Απόδωσε στο `PST_KAEK` το γεωτεμάχιο Κτηματολογίου με ΚΑΕΚ ως `TEXT`.
3. Απόδωσε τα υφιστάμενα όρια καθέτων όπως εμφανίζονται στο Κτηματογραφικό Διάγραμμα στο layer `Κάθετες ΚΔ`.
4. Απόδωσε το τελικό γεωτεμάχιο μετά την κατάργηση στο `DGM_PROP_FINAL`.

Κρίσιμοι κανόνες:

- Σε κατάργηση καθέτων δεν χρησιμοποιείται το `VST`.
- Σε κατάργηση καθέτων δεν χρησιμοποιείται το `VST_FINAL`.
- Το `DGM_PROP_FINAL` είναι απαραίτητο.

Συχνά σφάλματα:

- Χρήση `VST` για τις κάθετες που καταργούνται.
- Χρήση `VST_FINAL` για υφιστάμενες κάθετες του Κτηματογραφικού Διαγράμματος.
- Παράλειψη του `DGM_PROP_FINAL`.

qgis2web layer set: `BOUND_IMPL`, `BOUND_UNIMPL`, `TOPO_PROP`, `PST_KAEK`, `DGM_PROP_FINAL`, `Κάθετες ΚΔ`.

### 6.9 ΔΓΜ διόρθωσης ορίων

Πηγή: <https://ktimatologio.gov.gr/Professionals/Content/examples/paradeigmata/diorthwsi_oriwn.html>

Σενάριο: διόρθωση εμβαδού και διαστάσεων γεωτεμαχίου με δημιουργία διεκδικούμενων και αποκοπτόμενων τμημάτων σε σχέση με όμορα επηρεαζόμενα γεωτεμάχια.

Απαιτούμενη λογική:

1. Απόδωσε το υπό διόρθωση γεωτεμάχιο στο `TOPO_PROP`.
2. Απόδωσε τα εμπλεκόμενα γεωτεμάχια Κτηματολογίου στο `PST_KAEK`.
3. Η επιφάνεια που αποκόπτεται από όμορα και προστίθεται στο υπό διόρθωση γεωτεμάχιο αποδίδεται στο `AREA_D`.
4. Η επιφάνεια που αφαιρείται από το υπό διόρθωση γεωτεμάχιο αποδίδεται στο `AREA_A`.
5. Τα τελικά όρια όλων των επηρεαζόμενων γεωτεμαχίων αποδίδονται στο `DGM_PROP_FINAL`.

Κρίσιμοι κανόνες:

- Δεν χρησιμοποιείται `TOPO_PROP_NEW`. Αυτό είναι για εγγραπτέες πράξεις.
- Δεν χρησιμοποιείται `LINE_XM`. Αυτό είναι για εγγραπτέες πράξεις.
- Το `DGM_PROP_FINAL` πρέπει να περιλαμβάνει και τα όμορα εμπλεκόμενα γεωτεμάχια.

Συχνά σφάλματα:

- Χρήση `TOPO_PROP_NEW` για το διορθωμένο γεωτεμάχιο.
- Χρήση `LINE_XM` για τη γραμμή διόρθωσης.
- Το `DGM_PROP_FINAL` περιέχει μόνο το κύριο γεωτεμάχιο και όχι τα όμορα που επηρεάζονται.

qgis2web layer set: `BOUND_IMPL`, `TOPO_PROP`, `PST_KAEK`, `DGM_PROP_FINAL`, `AREA_D`, `AREA_A`.

### 6.10 ΔΓΜ διόρθωσης καθέτων ιδιοκτησιών

Πηγή: <https://ktimatologio.gov.gr/Professionals/Content/examples/paradeigmata/dgm_diorthwshs_kathetwn.html>

Σενάριο: διορθώνεται εσφαλμένη απεικόνιση καθέτων ιδιοκτησιών. Τα όρια του γεωτεμαχίου δεν μεταβάλλονται.

Σημαντική επιλογή υποβολής:

- Επειδή δεν αλλάζουν τα όρια του γεωτεμαχίου, στην ηλεκτρονική υποβολή επιλέγεται `ΔΓΜ για πράξη`.

Απαιτούμενη λογική:

1. Απόδωσε το γεωτεμάχιο στο `TOPO_PROP`.
2. Απόδωσε τους χώρους αποκλειστικής χρήσης όπως περιγράφονται στην πράξη στο `VST`.
3. Απόδωσε το γεωτεμάχιο Κτηματολογίου στο `PST_KAEK`.
4. Απόδωσε τη γραμμή χωρικής μεταβολής στο `LINE_XM_VST`.
5. Απόδωσε τους τελικούς χώρους αποκλειστικής χρήσης στο `VST_FINAL`.
6. Προαιρετικά, απόδωσε τους χώρους αποκλειστικής χρήσης όπως φαίνονται στο Κτηματογραφικό Διάγραμμα στο `VST_PST`.

Κρίσιμοι κανόνες:

- Το `VST_PST` είναι βοηθητικό και δεν εμφανίζεται ως υποχρεωτικό στο παράδειγμα.
- Αν υπάρχει κοινόχρηστος χώρος εκτός καθέτων, δεν μπαίνει στο `VST_FINAL`.

Συχνά σφάλματα:

- Το `LINE_XM_VST` δεν εφαρμόζει στο `PST_KAEK`.
- Στα `VST` και `VST_FINAL` μπαίνουν και χώροι αποκλειστικής χρήσης που δεν συμμετέχουν στην πράξη διόρθωσης.

qgis2web layer set: `BOUND_IMPL`, `BOUND_UNIMPL`, `TOPO_PROP`, `VST`, `PST_KAEK`, `VST_FINAL`, `VST_PST`, `LINE_XM_VST`.

### 6.11 ΔΓΜ διόρθωσης δουλείας διόδου

Πηγή: <https://ktimatologio.gov.gr/Professionals/Content/examples/paradeigmata/dgm_diorthwshs_douleias.html>

Σενάριο: διορθώνεται εσφαλμένη απεικόνιση των ορίων δεσμευμένου χώρου δουλείας. Τα όρια του γεωτεμαχίου δεν μεταβάλλονται.

Σημαντική επιλογή υποβολής:

- Επειδή δεν αλλάζουν τα όρια του γεωτεμαχίου, στην ηλεκτρονική υποβολή επιλέγεται `ΔΓΜ για πράξη`.

Απαιτούμενη λογική:

1. Απόδωσε τα όρια των εμπλεκόμενων ακινήτων στο `TOPO_PROP`, σύμφωνα με την περίπτωση διόρθωσης.
2. Απόδωσε τη δουλεία της πράξης στο `EAS`.
3. Απόδωσε τα κτηματολογικά όρια στο `PST_KAEK`.
4. Απόδωσε την τελική δουλεία στο `EAS_FINAL`.
5. Προαιρετικά, απόδωσε τη δουλεία όπως εμφανίζεται στο Κτηματογραφικό Διάγραμμα στο `EAS_PST`.

Κρίσιμοι κανόνες:

- Το `EAS_FINAL` πρέπει να περιορίζεται μέσα στα όρια του κατάλληλου `PST_KAEK`.
- Σε διόρθωση δουλείας πρέπει να συμπεριλαμβάνεται και το δεσπόζον ακίνητο όπου το απαιτεί η πράξη/παράδειγμα.
- Το `EAS_PST` είναι βοηθητικό και δεν εμφανίζεται ως υποχρεωτικό στο παράδειγμα.

Συχνά σφάλματα:

- Το `EAS_FINAL` υπερκαλύπτει τα περιμετρικά όρια του `PST_KAEK`.
- Το `PST_KAEK` περιλαμβάνει μόνο το δουλεύον ακίνητο ενώ πρέπει να περιλαμβάνει και το δεσπόζον.
- Το `TOPO_PROP` περιλαμβάνει μόνο το δουλεύον ακίνητο ενώ πρέπει να περιλαμβάνει και το δεσπόζον στην περίπτωση διόρθωσης.

qgis2web layer set: `BOUND_IMPL`, `BOUND_UNIMPL`, `TOPO_PROP`, `PST_KAEK`, `EAS`, `EAS_FINAL`, `EAS_PST`.

### 6.12 ΔΓΜ διόρθωσης ορίων γεωτεμαχίου με εσωτερικό πολύγωνο

Πηγή: <https://ktimatologio.gov.gr/Professionals/Content/examples/paradeigmata/dgm_diorthwsi_eswterikou.html>

Σενάριο: διόρθωση γεωτεμαχίου που έχει εσωτερικό πολύγωνο, π.χ. πυλώνα ΔΕΗ, το οποίο εμφανίζεται σε λάθος θέση.

Απαιτούμενη λογική:

1. Απόδωσε και το εξωτερικό και το εσωτερικό όριο στο `BOUND_IMPL` / `BOUND_UNIMPL` όπου ισχύει.
2. Απόδωσε και το εξωτερικό και το εσωτερικό όριο του ΤΔ στο `TOPO_PROP`.
3. Απόδωσε και το εξωτερικό και το εσωτερικό όριο Κτηματολογίου στο `PST_KAEK`.
4. Η διεκδικούμενη επιφάνεια αποδίδεται στο `AREA_D`.
5. Η αποκοπτόμενη ή εξαιρούμενη επιφάνεια αποδίδεται στο `AREA_A`.
6. Το τελικό γεωτεμάχιο μετά τη διόρθωση αποδίδεται στο `DGM_PROP_FINAL`, με σωστή διαχείριση εξωτερικού και εσωτερικού ορίου.

Κρίσιμοι κανόνες:

- Το εξωτερικό όριο και το εσωτερικό πολύγωνο πρέπει να είναι ξεχωριστές κλειστές πολυγωνικές οντότητες.
- Δεν πρέπει να δημιουργηθεί μία ενιαία polyline που προσπαθεί να περιγράψει και το εξωτερικό και το εσωτερικό όριο.

Συχνά σφάλματα:

- Στο `TOPO_PROP` μπαίνει μόνο το εξωτερικό όριο και παραλείπεται το εσωτερικό.
- Δημιουργείται μία ενιαία polyline για εξωτερικό και εσωτερικό όριο στα `TOPO_PROP` και `DGM_PROP_FINAL`.

qgis2web layer set: `BOUND_IMPL`, `BOUND_UNIMPL`, `TOPO_PROP`, `PST_KAEK`, `DGM_PROP_FINAL`, `AREA_A`, `AREA_D`.

### 6.13 ΤΔΓΜ διόρθωσης ορίων γεωτεμαχίου που συνοδεύει δικόγραφο

Πηγή: <https://ktimatologio.gov.gr/Professionals/Content/examples/paradeigmata/tdgm_diorthwsi_oriwn.html>

Σενάριο: διόρθωση γεωμετρικών στοιχείων με δικόγραφο, με διεκδικούμενα και αποκοπτόμενα τμήματα σε σχέση με όμορα επηρεαζόμενα γεωτεμάχια.

Απαιτούμενη λογική:

1. Χρησιμοποιείται η ίδια βασική λογική με το `ΔΓΜ διόρθωσης ορίων`.
2. Το `TOPO_PROP` δείχνει την αποτύπωση.
3. Το `PST_KAEK` περιλαμβάνει τα εμπλεκόμενα γεωτεμάχια Κτηματολογίου.
4. Το `AREA_D` δείχνει τι διεκδικείται ή προστίθεται.
5. Το `AREA_A` δείχνει τι αποκόπτεται ή εξαιρείται.
6. Το `DGM_PROP_FINAL` περιλαμβάνει τα τελικά όρια όλων των επηρεαζόμενων γεωτεμαχίων.

Συχνά σφάλματα:

- Χρήση `TOPO_PROP_NEW`, ενώ το layer αυτό αφορά εγγραπτέες πράξεις.
- Χρήση `LINE_XM`, ενώ αυτό αφορά εγγραπτέες πράξεις.
- Το `DGM_PROP_FINAL` περιέχει μόνο το υπό διόρθωση γεωτεμάχιο και όχι τα όμορα εμπλεκόμενα.

qgis2web layer set: `BOUND_IMPL`, `BOUND_UNIMPL`, `TOPO_PROP`, `PST_KAEK`, `DGM_PROP_FINAL`, `BLD`, `AREA_D`, `AREA_A`.

### 6.14 ΤΔΓΜ μεταφοράς γεωτεμαχίου στην ορθή θέση

Πηγή: <https://ktimatologio.gov.gr/Professionals/Content/examples/paradeigmata/tdgm_metafora_theshs.html>

Σενάριο: ένα γεωτεμάχιο εμφανίζεται σε λανθασμένη θέση και μεταφέρεται στην ορθή θέση, η οποία βρίσκεται μέσα σε άλλο επηρεαζόμενο γεωτεμάχιο.

Απαιτούμενη λογική:

1. Απόδωσε τα όρια της ορθής θέσης στο `TOPO_PROP`.
2. Απόδωσε το επηρεαζόμενο γεωτεμάχιο Κτηματολογίου στο `PST_KAEK`.
3. Απόδωσε το αρχικό γεωτεμάχιο που είχε αποδοθεί σε λανθασμένη θέση στο `PST`.
4. Η επιφάνεια του επηρεαζόμενου γεωτεμαχίου που διεκδικείται για την αποκατάσταση της ορθής θέσης αποδίδεται στο `AREA_D`.
5. Τα τελικά γεωτεμάχια για ενημέρωση της βάσης αποδίδονται στο `DGM_PROP_FINAL`.

Κρίσιμοι κανόνες:

- Το `PST_KAEK` χρησιμοποιείται για το επηρεαζόμενο γεωτεμάχιο.
- Το αρχικό/λανθασμένα τοποθετημένο γεωτεμάχιο αποδίδεται στο `PST`.
- Το `TOPO_PROP_NEW` δεν χρησιμοποιείται για την ορθή θέση.

Συχνά σφάλματα:

- Χρήση `PST_KAEK` για το αρχικό γεωτεμάχιο που ήταν στη λάθος θέση. Για αυτό χρησιμοποιείται `PST`.
- Χρήση `TOPO_PROP_NEW` για τη σωστή θέση, ενώ πρέπει να χρησιμοποιείται `TOPO_PROP`.

qgis2web layer set: `BOUND_IMPL`, `BOUND_UNIMPL`, `TOPO_PROP`, `PST`, `PST_KAEK`, `DGM_PROP_FINAL`, `AREA_D`, `text`.

### 6.15 ΤΔΓΜ δημιουργίας νέου γεωτεμαχίου

Πηγή: <https://ktimatologio.gov.gr/Professionals/Content/examples/paradeigmata/tdgm_dhmiourgias_neou_gewtemaxiou.html>

Σενάριο: δημιουργείται νέα ιδιοκτησία/νέο γεωτεμάχιο από διεκδικούμενα τμήματα επηρεαζόμενων γεωτεμαχίων.

Απαιτούμενη λογική:

1. Απόδωσε την αποτύπωση στο `TOPO_PROP`.
2. Απόδωσε τα εμπλεκόμενα γεωτεμάχια Κτηματολογίου στο `PST_KAEK`.
3. Η επιφάνεια που αποκόπτεται από τα επηρεαζόμενα γεωτεμάχια και δημιουργεί το νέο γεωτεμάχιο αποδίδεται στο `AREA_D`.
4. Το `DGM_PROP_FINAL` περιλαμβάνει τα τελικά όρια του νέου γεωτεμαχίου και των επηρεαζόμενων γεωτεμαχίων που μεταβλήθηκαν.

Κρίσιμοι κανόνες:

- Το `DGM_PROP_FINAL` δεν είναι μόνο το νέο γεωτεμάχιο. Περιλαμβάνει και τα τελικά όρια των επηρεαζόμενων.
- Το `TOPO_PROP_NEW` δεν χρησιμοποιείται. Η σωστή αποτύπωση δίνεται στο `TOPO_PROP`.

Συχνά σφάλματα:

- Στο `DGM_PROP_FINAL` μπαίνει μόνο το υπό δημιουργία γεωτεμάχιο.
- Χρήση `TOPO_PROP_NEW` για το υπό δημιουργία γεωτεμάχιο.

qgis2web layer set: `BOUND_IMPL`, `BOUND_UNIMPL`, `TOPO_PROP`, `PST`, `PST_KAEK`, `DGM_PROP_FINAL`, `AREA_D`.

## 7. Αρνητικοί κανόνες ανά layer

Αυτοί είναι χρήσιμοι για validator, επειδή πιάνουν πολλά από τα συχνά λάθη:

| Layer | Μην το χρησιμοποιείς όταν... |
|---|---|
| `TOPO_PROP_NEW` | Η υπόθεση είναι διόρθωση ορίων ή ΤΔΓΜ δικογράφου. |
| `LINE_XM` | Η υπόθεση είναι συνένωση, διόρθωση ορίων, διόρθωση καθέτων, διόρθωση δουλείας ή ΤΔΓΜ. |
| `VST` | Η υπόθεση είναι κατάργηση καθέτων. |
| `VST_FINAL` | Η υπόθεση είναι κατάργηση καθέτων. |
| `PST_KAEK` | Στο ΤΔΓΜ μεταφοράς θέσης δεν χρησιμοποιείται για το αρχικό λάθος γεωτεμάχιο. Εκεί χρησιμοποιείται `PST`. |
| `MTEXT` | Δεν πρέπει να υπάρχει σε ΚΑΕΚ, `DBOUND_PROP`, `OT`, `ROAD`. |

## 8. Ελάχιστα automated checks για επόμενο στάδιο

### 8.1 Checks αρχείου / entities

- Υπάρχουν όλα τα required layers για τον δηλωμένο τύπο διαγράμματος.
- Δεν υπάρχουν forbidden layers για τον δηλωμένο τύπο.
- Τα polygon layers περιέχουν μόνο κλειστά `LWPolyline`.
- Τα line-only layers (`LINE_XM`, `LINE_XM_VST`) περιέχουν ανοικτές `LWPolyline`.
- Τα text layers περιέχουν `TEXT` και όχι `MTEXT`.
- Τα labels ΚΑΕΚ στο `PST_KAEK` είναι απλό `TEXT` και μπορούν να διαβαστούν από τον αυτοματοποιημένο έλεγχο.

### 8.2 Checks τοπολογίας

- `TOPO_PROP` είναι συνεπές με `BOUND_IMPL` + `BOUND_UNIMPL`.
- `BOUND_IMPL` / `BOUND_UNIMPL` δεν περιέχουν άσχετα όμορα όρια.
- `LINE_XM` έχει άκρα επάνω στο `PST_KAEK`.
- `LINE_XM_VST` έχει άκρα επάνω στο σωστό όριο αναφοράς:
  - `PST_KAEK` σε απλή σύσταση/διόρθωση καθέτων.
  - `DGM_PROP_FINAL` όταν οι κάθετες συστήνονται μετά από κατάτμηση.
- `DGM_PROP_FINAL` περιλαμβάνει όλα τα τελικά επηρεαζόμενα γεωτεμάχια.
- Στις κατατμήσεις και συνενώσεις, το περίγραμμα του `DGM_PROP_FINAL` διατηρεί τους περιμετρικούς κόμβους του `PST_KAEK`.
- Στις διορθώσεις, `AREA_D` και `AREA_A` συμφωνούν χωρικά με τη διαφορά ανάμεσα σε `PST_KAEK` και `DGM_PROP_FINAL`.
- `EAS` είναι μέσα στο `TOPO_PROP`.
- `EAS_FINAL` είναι μέσα στο σχετικό `PST_KAEK`.
- `VST` είναι μέσα στο αντίστοιχο `TOPO_PROP`.
- `VST_FINAL` είναι μέσα στο αντίστοιχο `PST_KAEK` ή τελικό γεωτεμάχιο αναφοράς.
- Σε εσωτερικά πολύγωνα, το εξωτερικό και το εσωτερικό όριο είναι χωριστές κλειστές οντότητες.

### 8.3 Checks πληρότητας ανά περίπτωση

| Περίπτωση | Required layers | Forbidden / suspicious |
|---|---|---|
| ΤΔ εκτός | `BOUND_IMPL` ή/και `BOUND_UNIMPL`, `TOPO_PROP`, `PST_KAEK` | `TOPO_PROP_NEW`, `LINE_XM`, `DGM_PROP_FINAL` |
| ΤΔ εντός | `BOUND_IMPL` ή/και `BOUND_UNIMPL`, `TOPO_PROP`, `PST_KAEK`, `DBOUND_RYM`, `OT`, `ROAD` όπου υπάρχουν | `MTEXT` σε `PST_KAEK`, `DBOUND_PROP`, `OT`, `ROAD` |
| ΔΓΜ κατάτμησης | `TOPO_PROP`, `TOPO_PROP_NEW`, `PST_KAEK`, `LINE_XM`, `DGM_PROP_FINAL` | ελλιπές `TOPO_PROP_NEW`, κακό snap `LINE_XM` |
| ΔΓΜ συνένωσης | `TOPO_PROP`, `TOPO_PROP_NEW`, `PST_KAEK`, `DGM_PROP_FINAL` | `LINE_XM` |
| ΔΓΜ σύστασης δουλείας | `TOPO_PROP`, `PST_KAEK`, `EAS`, `EAS_FINAL` | `EAS_FINAL` εκτός `PST_KAEK` |
| ΔΓΜ σύστασης καθέτων | `TOPO_PROP`, `VST`, `PST_KAEK`, `LINE_XM_VST`, `VST_FINAL` | `LINE_XM_VST` που δεν πατά στο όριο |
| ΔΓΜ κατάτμησης + καθέτων | `TOPO_PROP`, `TOPO_PROP_NEW`, `VST`, `PST_KAEK`, `LINE_XM`, `DGM_PROP_FINAL`, `LINE_XM_VST`, `VST_FINAL` | `LINE_XM_VST` που πατά στο λάθος layer |
| ΔΓΜ κατάργησης καθέτων | `TOPO_PROP`, `PST_KAEK`, `Κάθετες ΚΔ`, `DGM_PROP_FINAL` | `VST`, `VST_FINAL` |
| ΔΓΜ διόρθωσης ορίων | `TOPO_PROP`, `PST_KAEK`, `AREA_D`, `AREA_A`, `DGM_PROP_FINAL` | `TOPO_PROP_NEW`, `LINE_XM` |
| ΔΓΜ διόρθωσης καθέτων | `TOPO_PROP`, `VST`, `PST_KAEK`, `LINE_XM_VST`, `VST_FINAL`, προαιρετικό `VST_PST` | άσχετες κάθετες στα `VST`/`VST_FINAL` |
| ΔΓΜ διόρθωσης δουλείας | `TOPO_PROP`, `PST_KAEK`, `EAS`, `EAS_FINAL`, προαιρετικό `EAS_PST` | παράλειψη δεσπόζοντος όπου απαιτείται |
| ΔΓΜ εσωτερικού πολυγώνου | `TOPO_PROP`, `PST_KAEK`, `AREA_D`, `AREA_A`, `DGM_PROP_FINAL` | ενιαία polyline για εξωτερικό+εσωτερικό όριο |
| ΤΔΓΜ διόρθωσης ορίων | `TOPO_PROP`, `PST_KAEK`, `AREA_D`, `AREA_A`, `DGM_PROP_FINAL` | `TOPO_PROP_NEW`, `LINE_XM` |
| ΤΔΓΜ μεταφοράς θέσης | `TOPO_PROP`, `PST_KAEK`, `PST`, `AREA_D`, `DGM_PROP_FINAL` | χρήση `PST_KAEK` για το αρχικό λάθος γεωτεμάχιο |
| ΤΔΓΜ δημιουργίας νέου | `TOPO_PROP`, `PST_KAEK`, `AREA_D`, `DGM_PROP_FINAL` | `DGM_PROP_FINAL` μόνο για το νέο γεωτεμάχιο, `TOPO_PROP_NEW` |

## 9. Suggested internal profile names

Για κώδικα, μπορούμε να ορίσουμε εσωτερικά profile IDs:

```yaml
td_outside:
  title: "Τοπογραφικό Διάγραμμα εκτός σχεδίου"
  core_layers: [BOUND_IMPL, BOUND_UNIMPL, TOPO_PROP, PST_KAEK]

td_inside:
  title: "Τοπογραφικό Διάγραμμα εντός σχεδίου"
  core_layers: [BOUND_IMPL, BOUND_UNIMPL, TOPO_PROP, DBOUND_PROP, PST_KAEK, DBOUND_RYM, OT, ROAD]

dgm_split:
  title: "ΔΓΜ κατάτμησης"
  core_layers: [BOUND_IMPL, BOUND_UNIMPL, TOPO_PROP, TOPO_PROP_NEW, PST_KAEK, LINE_XM, DGM_PROP_FINAL]
  forbidden_layers: []

dgm_merge:
  title: "ΔΓΜ συνένωσης"
  core_layers: [BOUND_IMPL, BOUND_UNIMPL, TOPO_PROP, TOPO_PROP_NEW, PST_KAEK, DGM_PROP_FINAL]
  forbidden_layers: [LINE_XM]

dgm_easement_create:
  title: "ΔΓΜ σύστασης δουλείας διόδου"
  core_layers: [BOUND_IMPL, BOUND_UNIMPL, TOPO_PROP, PST_KAEK, EAS, EAS_FINAL]

dgm_vertical_create:
  title: "ΔΓΜ σύστασης καθέτων ιδιοκτησιών"
  core_layers: [BOUND_IMPL, BOUND_UNIMPL, TOPO_PROP, VST, PST_KAEK, LINE_XM_VST, VST_FINAL]

dgm_split_vertical_create:
  title: "ΔΓΜ κατάτμησης και σύστασης καθέτων"
  core_layers: [BOUND_IMPL, BOUND_UNIMPL, TOPO_PROP, TOPO_PROP_NEW, VST, PST_KAEK, LINE_XM, DGM_PROP_FINAL, LINE_XM_VST, VST_FINAL]

dgm_vertical_cancel:
  title: "ΔΓΜ κατάργησης καθέτων ιδιοκτησιών"
  core_layers: [BOUND_IMPL, BOUND_UNIMPL, TOPO_PROP, PST_KAEK, "Κάθετες ΚΔ", DGM_PROP_FINAL]
  forbidden_layers: [VST, VST_FINAL]

dgm_boundary_correction:
  title: "ΔΓΜ διόρθωσης ορίων"
  core_layers: [BOUND_IMPL, BOUND_UNIMPL, TOPO_PROP, PST_KAEK, AREA_D, AREA_A, DGM_PROP_FINAL]
  forbidden_layers: [TOPO_PROP_NEW, LINE_XM]

dgm_vertical_correction:
  title: "ΔΓΜ διόρθωσης καθέτων ιδιοκτησιών"
  submission_choice: "ΔΓΜ για πράξη"
  core_layers: [BOUND_IMPL, BOUND_UNIMPL, TOPO_PROP, VST, PST_KAEK, LINE_XM_VST, VST_FINAL]
  optional_layers: [VST_PST]

dgm_easement_correction:
  title: "ΔΓΜ διόρθωσης δουλείας διόδου"
  submission_choice: "ΔΓΜ για πράξη"
  core_layers: [BOUND_IMPL, BOUND_UNIMPL, TOPO_PROP, PST_KAEK, EAS, EAS_FINAL]
  optional_layers: [EAS_PST]

dgm_inner_polygon_correction:
  title: "ΔΓΜ διόρθωσης ορίων με εσωτερικό πολύγωνο"
  core_layers: [BOUND_IMPL, BOUND_UNIMPL, TOPO_PROP, PST_KAEK, AREA_D, AREA_A, DGM_PROP_FINAL]

tdgm_boundary_correction:
  title: "ΤΔΓΜ διόρθωσης ορίων που συνοδεύει δικόγραφο"
  core_layers: [BOUND_IMPL, BOUND_UNIMPL, TOPO_PROP, PST_KAEK, AREA_D, AREA_A, DGM_PROP_FINAL]
  forbidden_layers: [TOPO_PROP_NEW, LINE_XM]

tdgm_position_transfer:
  title: "ΤΔΓΜ μεταφοράς γεωτεμαχίου στην ορθή θέση"
  core_layers: [BOUND_IMPL, BOUND_UNIMPL, TOPO_PROP, PST_KAEK, PST, AREA_D, DGM_PROP_FINAL]
  forbidden_patterns:
    - "Do not use PST_KAEK for the original misplaced parcel; use PST."
    - "Do not use TOPO_PROP_NEW for the corrected position."

tdgm_new_parcel:
  title: "ΤΔΓΜ δημιουργίας νέου γεωτεμαχίου"
  core_layers: [BOUND_IMPL, BOUND_UNIMPL, TOPO_PROP, PST_KAEK, AREA_D, DGM_PROP_FINAL]
  forbidden_layers: [TOPO_PROP_NEW]
```

## 10. Appendix: επίσημες σελίδες και οπτικά resources

### 10.1 Σελίδες παραδειγμάτων

- Main index: <https://ktimatologio.gov.gr/Professionals/Content/examples/paradeigmata_html_11_2024.html>
- ΤΔ εκτός σχεδίου: <https://ktimatologio.gov.gr/Professionals/Content/examples/paradeigmata/topografiko_ektos.html>
- ΤΔ εντός σχεδίου: <https://ktimatologio.gov.gr/Professionals/Content/examples/paradeigmata/topografiko_entos.html>
- ΔΓΜ κατάτμησης: <https://ktimatologio.gov.gr/Professionals/Content/examples/paradeigmata/katatmhsh.html>
- ΔΓΜ συνένωσης: <https://ktimatologio.gov.gr/Professionals/Content/examples/paradeigmata/synenwsh.html>
- ΔΓΜ σύστασης δουλείας διόδου: <https://ktimatologio.gov.gr/Professionals/Content/examples/paradeigmata/douleia_diodou.html>
- ΔΓΜ σύστασης καθέτων: <https://ktimatologio.gov.gr/Professionals/Content/examples/paradeigmata/systash_kathetwn.html>
- ΔΓΜ κατάτμησης και σύστασης καθέτων: <https://ktimatologio.gov.gr/Professionals/Content/examples/paradeigmata/katatmhsh_systash_kathetwn.html>
- ΔΓΜ κατάργησης καθέτων: <https://ktimatologio.gov.gr/Professionals/Content/examples/paradeigmata/katarghsh_kathetwn.html>
- ΔΓΜ διόρθωσης ορίων: <https://ktimatologio.gov.gr/Professionals/Content/examples/paradeigmata/diorthwsi_oriwn.html>
- ΔΓΜ διόρθωσης καθέτων: <https://ktimatologio.gov.gr/Professionals/Content/examples/paradeigmata/dgm_diorthwshs_kathetwn.html>
- ΔΓΜ διόρθωσης δουλείας: <https://ktimatologio.gov.gr/Professionals/Content/examples/paradeigmata/dgm_diorthwshs_douleias.html>
- ΔΓΜ διόρθωσης με εσωτερικό πολύγωνο: <https://ktimatologio.gov.gr/Professionals/Content/examples/paradeigmata/dgm_diorthwsi_eswterikou.html>
- ΤΔΓΜ διόρθωσης ορίων με δικόγραφο: <https://ktimatologio.gov.gr/Professionals/Content/examples/paradeigmata/tdgm_diorthwsi_oriwn.html>
- ΤΔΓΜ μεταφοράς θέσης: <https://ktimatologio.gov.gr/Professionals/Content/examples/paradeigmata/tdgm_metafora_theshs.html>
- ΤΔΓΜ δημιουργίας νέου γεωτεμαχίου: <https://ktimatologio.gov.gr/Professionals/Content/examples/paradeigmata/tdgm_dhmiourgias_neou_gewtemaxiou.html>

### 10.2 qgis2web iframe resources

Base URL: `https://ktimatologio.gov.gr/Professionals/Content/examples/paradeigmata/`

| Παράδειγμα | qgis2web resource |
|---|---|
| ΤΔ εκτός | `qgis2web/qgis2web_topo_ektos/index.html` |
| ΤΔ εντός | `qgis2web/qgis2web_topo_entos/index.html` |
| ΔΓΜ κατάτμησης | `qgis2web/qgis2web_dgm_katatmhshs/index.html` |
| ΔΓΜ συνένωσης | `qgis2web/qgis2web_dgm_synenwshs/index.html` |
| ΔΓΜ δουλείας | `qgis2web/qgis2web_dgm_douleia_diodou/index.html` |
| ΔΓΜ σύστασης καθέτων | `qgis2web/qgis2web_dgm_systashs_kathetwn/index.html` |
| ΔΓΜ κατάτμησης και καθέτων | `qgis2web/qgis2web_katatmhshs_systashs_kathetwn/index.html` |
| ΔΓΜ κατάργησης καθέτων | `qgis2web/qgis2web_dgm_katarghshs_kathetwn/index.html` |
| ΔΓΜ διόρθωσης ορίων | `qgis2web/qgis2web_dgm_diorthwsis_oriwn/index.html` |
| ΔΓΜ διόρθωσης καθέτων | `qgis2web/qgis2web_dgm_diorthwsis_kathetwn/index.html` |
| ΔΓΜ διόρθωσης δουλείας | `qgis2web/qgis2web_dgm_diorthwsis_douleias/index.html` |
| ΔΓΜ εσωτερικού πολυγώνου | `qgis2web/qgis2web_dgm_diorthwsi_eswterikou/index.html` |
| ΤΔΓΜ διόρθωσης ορίων | `qgis2web/qgis2web_tdgm_diorthwsis_oriwn/index.html` |
| ΤΔΓΜ μεταφοράς θέσης | `qgis2web/qgis2web_tdgm_metafora_allh_thesh/index.html` |
| ΤΔΓΜ δημιουργίας νέου | `qgis2web/qgis2web_tdgm_dhmiourgia_neou_gewtemaxiou/index.html` |

### 10.3 Resources σφαλμάτων

Τα κουμπιά "Σφάλμα" στις σελίδες φορτώνουν τα παρακάτω resources. Τα κρατάμε για πιθανό visual QA ή για να δημιουργηθούν test fixtures/περιγραφές σφαλμάτων.

| Παράδειγμα | Resources σφαλμάτων |
|---|---|
| ΤΔ εκτός | `images/topo ektos sxediou/sfalma_1_topo_prop_no_closed.png`, `images/topo ektos sxediou/sfalma_2_mtext.png`, `qgis2web/qgis2web_topo_ektos_sfalmata/index.html` |
| ΤΔ εντός | `images/topo entos sxediou/sfalma_1_pst_kaek_no_closed.png`, `images/topo entos sxediou/sfalma_2_pst_kaek_mtext.png`, `qgis2web/qgis2web_topo_entos_sfalmata/index.html` |
| ΔΓΜ κατάτμησης | `qgis2web/qgis2web_dgm_katatmhshs_sfalmata/sfalma_1/index.html`, `sfalma_2`, `sfalma_3`, `sfalma_4` |
| ΔΓΜ συνένωσης | `qgis2web/qgis2web_dgm_synenwshs_sfalmata/sfalma_1/index.html`, `sfalma_2`, `sfalma_3` |
| ΔΓΜ δουλείας | `qgis2web/qgis2web_dgm_douleia_diodou_sfalmata/sfalma_1/index.html`, `sfalma_2`, `sfalma_3` |
| ΔΓΜ σύστασης καθέτων | `qgis2web/qgis2web_dgm_systashs_kathetwn_sfalmata/sfalma_1/index.html`, `sfalma_2` |
| ΔΓΜ κατάτμησης και καθέτων | `qgis2web/qgis2web_katatmhshs_systashs_kathetwn_sfalmata/sfalma_1/index.html`, `sfalma_2`, `sfalma_3`, `sfalma_4` |
| ΔΓΜ κατάργησης καθέτων | `qgis2web/qgis2web_dgm_katarghshs_kathetwn_sfalmata/sfalma_1/index.html`, `sfalma_2`, `sfalma_3` |
| ΔΓΜ διόρθωσης ορίων | `qgis2web/qgis2web_dgm_diorthwsis_oriwn_sfalmata/sfalma_1/index.html`, `sfalma_2`, `sfalma_3` |
| ΔΓΜ διόρθωσης καθέτων | `qgis2web/qgis2web_dgm_diorthwsis_kathetwn_sfalmata/sfalma_1/index.html`, `sfalma_2` |
| ΔΓΜ διόρθωσης δουλείας | `qgis2web/qgis2web_dgm_diorthwsis_douleias_sfalmata/sfalma_1/index.html`, `sfalma_2`, `sfalma_3` |
| ΔΓΜ εσωτερικού πολυγώνου | `qgis2web/qgis2web_dgm_diorthwsi_eswterikou_sfalmata/sfalma_1/index.html`, `sfalma_2` |
| ΤΔΓΜ διόρθωσης ορίων | `qgis2web/qgis2web_tdgm_diorthwsis_oriwn_sfalmata/sfalma_1/index.html`, `sfalma_2`, `sfalma_3` |
| ΤΔΓΜ μεταφοράς θέσης | `qgis2web/qgis2web_tdgm_metafora_allh_thesh_sfalmata/sfalma_1/index.html`, `sfalma_2` |
| ΤΔΓΜ δημιουργίας νέου | `qgis2web/qgis2web_tdgm_dhmiourgia_neou_sfalmata/sfalma_1/index.html`, `sfalma_2` |

## 11. Σημεία που λείπουν από τα παραδείγματα και θέλουν επίσημη προδιαγραφή

Τα παραδείγματα είναι αρκετά για layer logic και συχνά λάθη, αλλά δεν δίνουν πλήρη πληροφορία για όλα τα παρακάτω:

- Ακριβείς γεωμετρικές ανοχές snap/overlap/containment.
- Υποχρεωτικά χρώματα, lineweights, linetypes και text styles.
- Αναλυτικό schema attributes ανά layer.
- Units και coordinate reference system, πέρα από το ότι τα στοιχεία προέρχονται/συμφωνούν με το Κτηματογραφικό Διάγραμμα.
- Πλήρες machine-readable DXF validation schema.

Για το επόμενο στάδιο, αυτά πρέπει είτε να παραμετροποιηθούν είτε να ληφθούν από το επίσημο τεύχος τεχνικών προδιαγραφών.

