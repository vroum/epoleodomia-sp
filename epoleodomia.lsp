;;; =============================================================================
;;; EPOLEODOMIA.LSP - GIS Tools for AutoCAD Civil 3D  (v2.1 loader)
;;; =============================================================================
;;;
;;; A complete toolset for integrating Greek urban planning data (epoleodomia)
;;; with AutoCAD Civil 3D. Data comes from PostGIS via a FastAPI server.
;;;
;;; REQUIREMENTS:
;;;   - API server running: python api_server.py (port 8000)
;;;   - Drawing in EGSA '87 (EPSG:2100) coordinates
;;;   - QGIS installed for GDAL tools (raster clipping)
;;;
;;; =============================================================================
;;; COMMANDS REFERENCE
;;; =============================================================================
;;;
;;; SITE ANALYSIS:
;;;   OROITABLE - Full building regulations as MTEXT annotation
;;;   ETABLE    - Full building regulations as a ruled table in the drawing
;;;   EREPORT   - Full planning report table (regs + aigialos + archeo + church + natura + remata)
;;;   ENOTES    - Auto-filled ΠΑΡΑΤΗΡΗΣΕΙΣ (notary notes) from notes_template.txt
;;;   ARCHEO    - Archaeological sites + protection zone status
;;;   CHURCH    - Distance to closest church
;;;   NATURA    - Natura 2000 / forest map restrictions
;;;   AIGIALOS  - Distance to shoreline with FEK reference
;;;   REMATA    - Stream/flood line distances
;;;
;;; BOUNDARIES:
;;;   KAEK      - Show cadastral parcel number at point
;;;   EKAEK     - Draw KAEK parcel polygon + neighbors
;;;   OT        - Show building block number at point
;;;   EOBT      - Draw OT polygon + neighbors
;;;   KAEK_OP   - Draw operating cadastre parcel + neighbors (Hellenic Cadastre λειτουργία)
;;;
;;; KTIMATOLOGIO DIAGRAMS:
;;;   KLAYERS   - Create the official electronic-diagram layers (ΠΙΝΑΚΑΣ Ι)
;;;   KPST      - Draw PST_KAEK background (parcels + KAEK TEXT labels, ΑΧ→VST_PST)
;;;   KCHECK    - Validate drawing against a diagram profile (15 τύποι ΤΔ/ΔΓΜ/ΤΔΓΜ)
;;;   KGEOM     - Διόρθωση ορίων: select TOPO_PROP → AREA_D/AREA_A/DGM_PROP_FINAL + πίνακας
;;;   KGEOMV    - Διόρθωση καθέτων: select ΑΧ polylines → VST_FINAL/LINE_XM_VST + πίνακας
;;;   KVERT     - Κυκλάκια+αρίθμηση κορυφών + πίνακας συντεταγμένων (open/closed)
;;;   KGRID     - Κάνναβος 10x10εκ (σταυρουδάκια/πλήρης) + περιμετρικές συντεταγμένες
;;;   AIGDRAW   - Υφιστάμενες οριογραμμές αιγιαλού/παραλίας σε bbox (με ΦΕΚ labels)
;;;
;;; RASTERS:
;;;   FEK       - Load planning diagram rasters in selected area
;;;   DJI       - Load DJI drone orthophotos in selected area
;;;   DE        - Load DE (Diagramma Efarmogis) rasters in selected area
;;;   CLIPR     - Clip raster to selected area using GDAL
;;;
;;; UTILITIES:
;;;   EHELP     - Show this help
;;;   ETRANS    - Enable transparency on drone rasters
;;;   ELAYERS   - List all epoleodomia layers
;;;
;;; =============================================================================
;;; =============================================================================
;;; MODULE MAP  (v2.1 - the 3443-line monolith is now six modules)
;;; =============================================================================
;;;
;;;   epol-core.lsp     config, HTTP, JSON/coord parsing, layers, drawing,
;;;                     table primitives           <- must load first
;;;   epol-site.lsp     OROITABLE ETABLE EREPORT ENOTES ARCHEO CHURCH
;;;                     NATURA AIGIALOS REMATA
;;;   epol-bounds.lsp   KAEK EKAEK OT EOBT KAEK_OP
;;;   epol-ktima.lsp    KLAYERS KPST KGEOM KGEOMV KVERT KGRID AIGDRAW KCHECK
;;;   epol-raster.lsp   FEK DJI DE CLIPR
;;;   epol-util.lsp     ETRANS ELAYERS EHELP
;;;
;;; This file only locates and loads them. It defines no commands itself, so
;;; APPLOAD epoleodomia.lsp keeps working exactly as it did in v2.0.
;;;
;;; KEXPORT / KFILTERS are still loaded separately (kexport.lsp, kfilters.lsp)
;;; and still require this file to be loaded first.
;;;
;;; IF LOADING FAILS: add this folder to AutoCAD's Support File Search Path
;;;   (OPTIONS > Files > Support File Search Path > Add...)
;;; or set the folder explicitly before loading, e.g.
;;;   (setq *epol-dir* "O:\\claude_code area\\...\\clean\\")
;;;   (load "epoleodomia.lsp")
;;; =============================================================================

(vl-load-com)

;;; --- EDIT THIS IF YOU MOVE THE PROJECT FOLDER ----------------------------
;;; Used as the last-resort fallback when AutoCAD cannot find the modules on
;;; its own. Forward slashes are fine and avoid backslash-escaping headaches.
;;; Must end with a slash.
(setq *epol-dir-default*
  "O:/claude_code area/mega project postgis-autocad/lisp for acad v2 - Copy/clean/")

;;; --- module list, in load order ------------------------------------------
(setq *epol-modules*
  (list "epol-core.lsp"        ; must be first: globals + epol: helpers
        "epol-site.lsp"
        "epol-bounds.lsp"
        "epol-ktima.lsp"
        "epol-raster.lsp"
        "epol-util.lsp"
  )
)

;;; --- resolve the folder holding the modules ------------------------------
;;; Tried in order; the first one that actually contains epol-core.lsp wins.
(setq *epol-dir*
  (cond
    ;; 1. caller pre-set *epol-dir* and it really contains the modules
    ((and *epol-dir*
          (= (type *epol-dir*) 'STR)
          (findfile (strcat *epol-dir* "epol-core.lsp")))
     *epol-dir*)

    ;; 2. this folder is on the Support File Search Path -> use our own dir
    ((and (findfile "epoleodomia.lsp")
          (findfile (strcat (vl-filename-directory (findfile "epoleodomia.lsp"))
                            "\\epol-core.lsp")))
     (strcat (vl-filename-directory (findfile "epoleodomia.lsp")) "\\"))

    ;; 3. the modules themselves are on the Support File Search Path
    ((findfile "epol-core.lsp") "")

    ;; 4. last resort: the hardcoded project folder above. This is what makes
    ;;    (load "<abs path>/epoleodomia.lsp") work with no AutoCAD setup.
    ((findfile (strcat *epol-dir-default* "epol-core.lsp")) *epol-dir-default*)

    (T nil)
  )
)

;;; --- load ----------------------------------------------------------------
(if (null *epol-dir*)
  (progn
    (princ "\n")
    (princ "\n*** EPOLEODOMIA: cannot locate the epol-*.lsp modules. ***")
    (princ "\n    Tried: *epol-dir*, this file's folder, the support path, and")
    (princ (strcat "\n    " *epol-dir-default*))
    (princ "\n    Fix: edit *epol-dir-default* at the top of epoleodomia.lsp,")
    (princ "\n    or add the folder to OPTIONS > Files > Support File Search Path.")
    (princ "\n")
  )
  (progn
    (setq *epol-loaded* 0  *epol-failed* nil)
    (foreach m *epol-modules*
      (if (findfile (strcat *epol-dir* m))
        (if (vl-catch-all-error-p
              (vl-catch-all-apply 'load (list (strcat *epol-dir* m))))
          (setq *epol-failed* (cons m *epol-failed*))
          (setq *epol-loaded* (1+ *epol-loaded*))
        )
        (setq *epol-failed* (cons m *epol-failed*))
      )
    )

    (princ "\n")
    (princ "\n========================================")
    (princ "\n EPOLEODOMIA GIS TOOLS v2.1 LOADED")
    (princ "\n========================================")
    (princ (strcat "\n Modules: " (itoa *epol-loaded*)
                   "/" (itoa (length *epol-modules*))))
    (if *epol-failed*
      (foreach m (reverse *epol-failed*)
        (princ (strcat "\n *** FAILED: " m " ***")))
    )
    (princ "\n Type EHELP for command list")
    (princ "\n API: http://127.0.0.1:8000")
    (princ "\n========================================")
    (princ "\n")
  )
)
(princ)
