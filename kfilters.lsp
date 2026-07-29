;;; =============================================================================
;;; kfilters.lsp  v3  -  TEMPLATE SEEDING (run ONCE, then save as .dwt)
;;; -----------------------------------------------------------------------------
;;;   c:KTSEED        Build a complete template drawing: official layers +
;;;                   EPOL working layers + layer filters. Then SAVEAS .dwt.
;;;   c:KFILTERS      Filters only (rebuild / update patterns in an open dwg).
;;;   c:KFILTERSDEL   Remove only the filters created by this file.
;;;
;;; -----------------------------------------------------------------------------
;;; WHY v3 IS DIFFERENT FROM v2
;;;
;;; v2 treated the filters as a per-drawing command. But layer filters live
;;; INSIDE the dwg, not in the profile - so v2 had to be re-run in every single
;;; drawing. The right home for them is a template (.dwt). This file is now a
;;; one-shot seeder, not a daily tool.
;;;
;;; v2 also had 25 filters for 44 layers (~1 filter per 2 layers). That is not
;;; organisation, that is noise. v3 has 8 groups, each answering a question you
;;; actually ask while drafting.
;;;
;;; FIXED IN v3:
;;;   - "Kathetes KD" never matched anything. The real layer name is written in
;;;     GREEK letters (see the guide, lines 104/119/580). Now matched with the
;;;     ASCII-safe pattern "* *" (see note at group 8).
;;;   - OBJ was in no subgroup, only in the catch-all.
;;;   - The "all official layers" pattern was hand-maintained in parallel with
;;;     *ktima-layers* and had already drifted. It is now DERIVED at runtime.
;;;
;;; Technique: filters are written as XRecords in the ACAD_LAYERFILTERS
;;; dictionary of the layer table's extension dictionary. Field-verified to
;;; show up in the Layer Properties Manager.
;;; =============================================================================

(vl-load-com)

;;; -----------------------------------------------------------------------------
;;; ASCII ONLY IN THIS FILE.
;;; Greek literals in a UTF-8 .lsp loaded by an ANSI AutoCAD produce mojibake -
;;; this project has already been bitten by that once (see STATUS 2026-07-03).
;;; The one Greek layer name we need is matched by shape, not by letters.
;;; -----------------------------------------------------------------------------

;;; Build the "all official layers" pattern from the single source of truth in
;;; epoleodomia.lsp. Falls back to a static list if that file is not loaded.
(defun kf:ktima-pattern ( / s)
  (if *ktima-layers*
    (progn
      (foreach l *ktima-layers*
        (setq s (if s (strcat s "," (car l)) (car l))))
      s)
    (strcat
      "PST_KAEK,PST,ROAD,OT,BOUND_IMPL,BOUND_UNIMPL,BLD,TOPO_PROP,"
      "TOPO_PROP_NEW,LINE_XM,LINE_XM_VST,VST,VST_FINAL,VST_PST,EAS,"
      "EAS_FINAL,EAS_PST,MINE,MINE_FINAL,DGM_PROP_FINAL,AREA_D,AREA_A,"
      "OBJ,DBOUND_PROP,DBOUND_RYM,DBOUND_AIG,DBOUND_PRL,DBOUND_PAIG,"
      "DBOUND_REM,DBOUND_APAL")))

;;; -----------------------------------------------------------------------------
;;; THE 8 GROUPS
;;;
;;; Ordering follows the workflow, not the alphabet:
;;;   1 = what ships       2..5 = how it is built     6..8 = scaffolding
;;; -----------------------------------------------------------------------------
(defun kf:filters ()
 (list
  ;; --- 1. What goes into the submitted DXF. The only filter that is a rule,
  ;;        not a convenience: everything OUTSIDE it must be purged on export.
  (cons "1 YPOVOLI (PINAKAS I)"   (kf:ktima-pattern))

  ;; --- 2. What came out of the Ktimatologio (the KD background you did not
  ;;        measure and must not edit).
  (cons "2 Ypovathro KD"
        "PST_KAEK,PST,VST_PST,EAS_PST,BOUND_IMPL,BOUND_UNIMPL,BLD,OT,ROAD")

  ;; --- 3. What you measured / what the deed says (the "before" state).
  (cons "3 Metrisi-Protasi"       "TOPO_PROP,TOPO_PROP_NEW,VST,EAS,MINE")

  ;; --- 4. What the change produces (the "after" state + the change geometry).
  (cons "4 Metavoli (FINAL)"
        "DGM_PROP_FINAL,VST_FINAL,EAS_FINAL,MINE_FINAL,AREA_D,AREA_A,LINE_XM,LINE_XM_VST")

  ;; --- 5. Zone boundaries drawn on the diagram (aigialos, remata, rymotomiki...).
  (cons "5 Oria zonon (DBOUND)"   "DBOUND_*")

  ;; --- 6. Everything the GIS query tools draw. Never submitted.
  (cons "6 EPOL (GIS queries)"    "EPOL_*")

  ;; --- 7. Every raster layer, whatever the source. Never submitted.
  (cons "7 Rasters"               "R_*")

  ;; --- 8. Drafting scaffolding.
  ;;     NOTE ON "* *": the layer "Kathetes KD" is officially named in GREEK
  ;;     letters with a space in the middle. Rather than embed a Greek literal
  ;;     in this file (encoding trap), we match "any layer name containing a
  ;;     space" - which in this layer set is that layer and nothing else.
  ;;     Side effect: xref/imported layers with spaces will also land here.
  (cons "8 Voithitika"            "XY_PTS,GRID,OBJ,* *")
 )
)

;;; -----------------------------------------------------------------------------
;;; Get (or create) the ACAD_LAYERFILTERS dictionary in the layer table's
;;; extension dictionary. Returns the dictionary ename.
(defun kf:filter-dict ( / xdict dict)
  (setq xdict
    (vlax-vla-object->ename
      (vla-getextensiondictionary
        (vla-get-layers
          (vla-get-activedocument (vlax-get-acad-object))))))
  (if (setq dict (dictsearch xdict "ACAD_LAYERFILTERS"))
    (cdr (assoc -1 dict))
    (dictadd xdict "ACAD_LAYERFILTERS"
      (entmakex
       '((0 . "dictionary")
         (100 . "AcDbDictionary")
         (280 . 0)
         (281 . 1))))
  )
)

;;; Create ONE layer filter XRecord: fname matching wildcard pattern pat.
;;; Field order follows the documented ACAD_LAYERFILTERS xrecord layout:
;;;   (1 name)(1 name-pattern)(1 color)(1 ltype)(70 flags)(1 lweight)(1 pstyle)
;;;   + ACAD xdata with the modern boolean expression.
(defun kf:make (dict fname pat)
  (if (dictsearch dict fname)
    (dictremove dict fname))          ; rebuild = update pattern
  (dictadd dict fname
    (entmakex
      (append
       '((0 . "xrecord")
         (100 . "AcDbXrecord")
         (280 . 1))
        (list (cons 1 fname))
        (list (cons 1 pat))
       '((1 . "*")
         (1 . "*")
         (70 . 0)
         (1 . "*")
         (1 . "*"))
        (list
          (list -3
            (list "ACAD"
              (cons 1000 (strcat "( NAME==\"" pat "\" )"))))))))
)

;;; -----------------------------------------------------------------------------
;;; FILTERS ONLY
(defun c:KFILTERS ( / dict n res lst)
  (if (not (tblsearch "APPID" "ACAD"))
    (regapp "ACAD"))                  ; xdata appid must be registered
  (setq dict (kf:filter-dict) lst (kf:filters))
  (if (not dict)
    (princ "\nKFILTERS ERROR: could not access ACAD_LAYERFILTERS dictionary.")
    (progn
      (setq n 0)
      (foreach f lst
        (setq res (vl-catch-all-apply 'kf:make (list dict (car f) (cdr f))))
        (if (vl-catch-all-error-p res)
          (princ (strcat "\n  FAILED: " (car f) " -> "
                         (vl-catch-all-error-message res)))
          (setq n (1+ n))))
      (princ (strcat "\nKFILTERS: created/updated " (itoa n) " of "
                     (itoa (length lst)) " layer filters."))
      (if (not *ktima-layers*)
        (princ "\n  WARNING: epoleodomia.lsp not loaded - filter 1 used the static fallback."))
      (princ "\nClose & reopen the Layer Properties Manager (LA) to see them.")
    )
  )
  (princ)
)

;;; Remove only this file's filters (v3 names + leftover v2 names)
(defun c:KFILTERSDEL ( / dict n)
  (setq dict (kf:filter-dict))
  (setq n 0)
  (if dict
    (progn
      (foreach f (kf:filters)
        (if (dictsearch dict (car f))
          (progn (dictremove dict (car f)) (setq n (1+ n)))))
      (foreach old '("1 EPOL (all)" "1.1 EPOL KAEK-OT" "1.2 EPOL Operating (OP)"
                     "1.3 EPOL Douleies (DX)" "1.4 EPOL Text-Labels"
                     "1.5 EPOL Tables" "1.6 EPOL Raster-Clip" "1.7 EPOL Archeo"
                     "2 KTIMA (all)" "2.1 KTIMA Ypovathro" "2.2 KTIMA Topografiko"
                     "2.3 KTIMA Grammes GM" "2.4 KTIMA Douleies VST" "2.5 KTIMA EAS"
                     "2.6 KTIMA Metalleia" "2.7 KTIMA DGM Final" "2.8 KTIMA Emvada"
                     "2.9 KTIMA Oria (DBOUND)" "3 RASTER (all)" "3.1 RASTER FEK"
                     "3.2 RASTER DE" "3.3 RASTER DJI drone" "3.4 RASTER Clipped"
                     "4 Voithitika")
        (if (dictsearch dict old)
          (progn (dictremove dict old) (setq n (1+ n)))))))
  (princ (strcat "\nKFILTERSDEL: removed " (itoa n) " filters (layers untouched)."))
  (princ)
)

;;; -----------------------------------------------------------------------------
;;; KTSEED - build the whole template in one go. RUN ONCE.
;;;
;;; Needs epoleodomia.lsp loaded (uses *ktima-layers*, *epol-layers*,
;;; epol:make-klayer, epol:make-layer).
;;; -----------------------------------------------------------------------------
(defun c:KTSEED ( / n)
  (if (not (and *ktima-layers* *epol-layers*))
    (princ "\nKTSEED: load epoleodomia.lsp first (needs *ktima-layers* / *epol-layers*).")
    (progn
      ;; 1. official PINAKAS I layers (colors + linetypes per spec)
      (setq n 0)
      (foreach l *ktima-layers*
        (if (not (tblsearch "LAYER" (car l)))
          (progn (epol:make-klayer (car l) (cadr l) (caddr l))
                 (setq n (1+ n)))))
      (princ (strcat "\nKTSEED: " (itoa n) " official layers created ("
                     (itoa (length *ktima-layers*)) " total)."))

      ;; 2. EPOL working layers - normally created lazily by each command;
      ;;    seeding them up front means the template carries the full tree.
      (setq n 0)
      (foreach l *epol-layers*
        (if (not (tblsearch "LAYER" (car l)))
          (progn (epol:make-layer (car l) (cdr l)) (setq n (1+ n)))))
      (princ (strcat "\nKTSEED: " (itoa n) " EPOL layers created ("
                     (itoa (length *epol-layers*)) " total)."))

      ;; 3. drafting scaffolding layers used by KVERT / KGRID
      (foreach l '(("XY_PTS" 7) ("GRID" 8))
        (if (not (tblsearch "LAYER" (car l)))
          (epol:make-klayer (car l) (cadr l) "Continuous")))

      ;; 4. the filters
      (c:KFILTERS)

      (princ "\n")
      (princ "\n=== NEXT STEPS (by hand, once) ===")
      (princ "\n 1. Create the Greek-named layer  Kathetes KD  (in GREEK letters,")
      (princ "\n    per the guide) - only needed for DGM katargisis kathetwn.")
      (princ "\n 2. Set text style / dimstyle / units / limits as you want them.")
      (princ "\n 3. PURGE, ZOOM E, set layer 0 current.")
      (princ "\n 4. SAVEAS -> AutoCAD Drawing Template (*.dwt) -> e.g. SPETSES.dwt")
      (princ "\n 5. OPTIONS > Files > Template Settings > Default Template = SPETSES.dwt")
      (princ "\n")
      (princ "\nAfter that you never run KTSEED or KFILTERS again -")
      (princ "\nevery new drawing starts with the full layer tree.")
    )
  )
  (princ)
)

(princ "\nkfilters.lsp v3 loaded.  KTSEED (once) | KFILTERS | KFILTERSDEL")
(princ)
