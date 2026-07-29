;;; =============================================================================
;;; kexport.lsp  v1  -  Pre-flight for the submitted DXF (Ilektroniko Diagramma)
;;; -----------------------------------------------------------------------------
;;;   c:KEXPORT   Check + clean the drawing, then tell you exactly what to press.
;;;
;;; Requires epoleodomia.lsp loaded (*ktima-layers*, kcheck:count).
;;;
;;; -----------------------------------------------------------------------------
;;; WHAT THE SPEC ACTUALLY SAYS  (Tefxos Tehnikon Prodiagrafon v1.3, 12/2024)
;;;
;;;  4.2    DXF version 2004-2014 (FAQ B.1: 2000-2014 fully supported).
;;;  4.3    Filename: <=15 chars + ".dxf", latin letters / digits / underscore
;;;         only, no spaces, no dots, no special chars. Should carry the
;;;         "topo_" or "dgm_" prefix and a "_vNN" version. The PDF must use the
;;;         same base name.
;;;  4.4    Drawing units must be METERS.
;;;  4.4.1  ii - EXTRA layers ARE ALLOWED beyond PINAKAS I (legend, tables,
;;;         grid, engineer declarations, kerbs, poles...), named freely at the
;;;         engineer's discretion. So XY_PTS / GRID / tables stay in the file.
;;;  4.5.1  Entities of PINAKAS I must NOT be blocks, xrefs or images.
;;;         Layer names must use latin characters.
;;;         No overlapping / duplicate entities on the same layer.
;;;
;;; So this is NOT a "strip everything but PINAKAS I" tool. It only removes
;;; what genuinely does not belong in a submission (GIS query layers + rasters)
;;; and refuses to proceed on real spec violations.
;;;
;;; -----------------------------------------------------------------------------
;;; SAFETY
;;; All modifications happen inside ONE undo group. After you have written the
;;; DXF, a single UNDO restores the drawing exactly as it was. KEXPORT never
;;; saves the drawing itself.
;;; =============================================================================

(vl-load-com)

;;; Layers that must NOT reach the submission: GIS query output + rasters.
(setq *kx-drop* "EPOL_*,R_*")

;;; -----------------------------------------------------------------------------
;;; 1. FILENAME VALIDATION  (spec 4.3)
;;; -----------------------------------------------------------------------------
(defun kx:check-name (nm / errs warns i c ok)
  (setq errs nil warns nil)
  (cond
    ((or (not nm) (= nm ""))
     (setq errs (list "empty filename")))
    (t
     (if (> (strlen nm) 15)
       (setq errs (cons (strcat "too long: " (itoa (strlen nm))
                                " chars (max 15, extension not counted)") errs)))
     ;; character whitelist: A-Z a-z 0-9 _
     (setq i 1)
     (while (<= i (strlen nm))
       (setq c (ascii (substr nm i 1)))
       (setq ok (or (and (>= c 65) (<= c 90))
                    (and (>= c 97) (<= c 122))
                    (and (>= c 48) (<= c 57))
                    (= c 95)))
       (if (not ok)
         (setq errs (cons (strcat "illegal character at position " (itoa i)
                                  ": \"" (substr nm i 1) "\"") errs)))
       (setq i (1+ i)))
     ;; recommendations (not fatal)
     (if (not (or (wcmatch nm "topo_*") (wcmatch nm "TOPO_*")
                  (wcmatch nm "dgm_*")  (wcmatch nm "DGM_*")))
       (setq warns (cons "no \"topo_\" / \"dgm_\" prefix (spec 4.3 asks for it)" warns)))
     (if (not (wcmatch nm "*_v#*"))
       (setq warns (cons "no version suffix (e.g. _v01)" warns)))
    )
  )
  (list (reverse errs) (reverse warns))
)

;;; -----------------------------------------------------------------------------
;;; 2. FORBIDDEN ENTITIES ON PINAKAS I LAYERS  (spec 4.5.1)
;;; -----------------------------------------------------------------------------
(defun kx:pinakas-filter ( / s)
  (foreach l *ktima-layers*
    (setq s (if s (strcat s "," (car l)) (car l))))
  s
)

(defun kx:forbidden ( / ss i e ed out)
  (setq out nil)
  (setq ss (ssget "_X" (list '(0 . "INSERT,IMAGE,WIPEOUT")
                             (cons 8 (kx:pinakas-filter)))))
  (if ss
    (progn
      (setq i 0)
      (repeat (sslength ss)
        (setq e (ssname ss i) ed (entget e) i (1+ i))
        (setq out (cons (strcat "  " (cdr (assoc 0 ed))
                                " on layer " (cdr (assoc 8 ed))
                                "  (handle " (cdr (assoc 5 ed)) ")") out)))))
  (reverse out)
)

;;; List attached xref block names
(defun kx:xrefs ( / tb out)
  (setq tb (tblnext "BLOCK" T))
  (while tb
    (if (= 4 (logand 4 (cdr (assoc 70 tb))))
      (setq out (cons (cdr (assoc 2 tb)) out)))
    (setq tb (tblnext "BLOCK")))
  (reverse out)
)

;;; Layers with non-latin characters in the name (spec 4.5.1).
;;; Tolerated on helper layers - the official examples themselves use greek
;;; names - but flagged if it ever hits a PINAKAS I layer.
(defun kx:nonlatin ( / tb nm i c out bad)
  (setq tb (tblnext "LAYER" T))
  (while tb
    (setq nm (cdr (assoc 2 tb)) bad nil i 1)
    (while (<= i (strlen nm))
      (if (> (ascii (substr nm i 1)) 127) (setq bad T))
      (setq i (1+ i)))
    (if bad (setq out (cons nm out)))
    (setq tb (tblnext "LAYER")))
  (reverse out)
)

;;; -----------------------------------------------------------------------------
;;; 3. MAIN
;;; -----------------------------------------------------------------------------
(defun c:KEXPORT ( / nm res errs warns bad xr nl ss ndrop tb lay
                     old-echo old-undo ans units)
  (if (not *ktima-layers*)
    (progn
      (princ "\nKEXPORT: load epoleodomia.lsp first.")
      (princ))
    (progn
      (princ "\n=== KEXPORT - pre-flight for the submitted DXF ===")

      ;; --- 3.1 filename -------------------------------------------------------
      (setq nm (getstring T "\nBase filename WITHOUT extension (e.g. dgm_spetses_v01): "))
      (setq res   (kx:check-name nm)
            errs  (car res)
            warns (cadr res))
      (if errs
        (progn
          (princ "\n\n  FILENAME REJECTED (spec 4.3):")
          (foreach e errs (princ (strcat "\n    - " e)))))
      (if warns
        (progn
          (princ "\n\n  Filename warnings:")
          (foreach w warns (princ (strcat "\n    - " w)))))
      (if (not errs)
        (princ (strcat "\n  Filename OK -> " nm ".dxf  /  " nm ".pdf")))

      ;; --- 3.2 units ----------------------------------------------------------
      (setq units (getvar "INSUNITS"))
      (if (= units 6)
        (princ "\n  Units: meters. OK.")
        (princ (strcat "\n  UNITS: INSUNITS = " (itoa units)
                       " - spec 4.4 requires meters (6). Will be set.")))

      ;; --- 3.3 spec 4.5.1 violations -----------------------------------------
      (setq bad (kx:forbidden)
            xr  (kx:xrefs)
            nl  (kx:nonlatin))

      (if bad
        (progn
          (princ "\n\n  BLOCKING - blocks / images / wipeouts on PINAKAS I layers (4.5.1):")
          (foreach b bad (princ (strcat "\n" b)))
          (princ "\n  Fix these by hand (explode or redraw as LWPOLYLINE/TEXT) and re-run."))
        (princ "\n  No blocks/images/xrefs on PINAKAS I layers. OK."))

      (if xr
        (progn
          (princ "\n\n  Xrefs attached (will be detached):")
          (foreach x xr (princ (strcat "\n    - " x)))))

      (if nl
        (progn
          (princ "\n\n  Layers with non-latin names (4.5.1 asks for latin):")
          (foreach l nl (princ (strcat "\n    - " l)))
          (princ "\n    Tolerated on helper layers - the official examples do the same")
          (princ "\n    (KATHETES KTIMATOGRAFIKOU). Not tolerated on PINAKAS I layers.")))

      ;; --- 3.4 what gets dropped ---------------------------------------------
      (setq ss (ssget "_X" (list (cons 8 *kx-drop*))))
      (setq ndrop (if ss (sslength ss) 0))
      (princ (strcat "\n\n  To be removed: " (itoa ndrop)
                     " entities on EPOL_* / R_* layers"))
      (princ "\n    (GIS query output + rasters - not part of the diagram,")
      (princ "\n     and raster references cannot travel inside a DXF anyway)")

      ;; --- 3.5 go / no-go -----------------------------------------------------
      (if (or errs bad)
        (progn
          (princ "\n\n  ABORTED - fix the items above first. Drawing untouched.")
          (princ))
        (progn
          (initget "Yes No")
          (setq ans (getkword "\n\nProceed to clean the drawing? [Yes/No] <Yes>: "))
          (if (= ans "No")
            (progn (princ "\n  Cancelled. Drawing untouched.") (princ))
            (progn
              (setq old-echo (getvar "CMDECHO"))
              (setvar "CMDECHO" 0)
              (command "_.UNDO" "_Begin")

              ;; detach xrefs
              (foreach x xr
                (vl-catch-all-apply 'vl-cmdf (list "_.-XREF" "_Detach" x)))

              ;; make drop layers reachable, then erase their contents
              (setq tb (tblnext "LAYER" T))
              (while tb
                (setq lay (cdr (assoc 2 tb)))
                (if (wcmatch lay *kx-drop*)
                  (vl-catch-all-apply 'vl-cmdf
                    (list "_.-LAYER" "_Thaw" lay "_On" lay "_Unlock" lay "")))
                (setq tb (tblnext "LAYER")))

              (setq ss (ssget "_X" (list (cons 8 *kx-drop*))))
              (if ss (vl-catch-all-apply 'vl-cmdf (list "_.ERASE" ss "")))

              ;; units
              (setvar "INSUNITS" 6)

              ;; purge twice: image defs / empty layers / unreferenced blocks
              (vl-catch-all-apply 'vl-cmdf (list "_.-PURGE" "_All" "*" "_N"))
              (vl-catch-all-apply 'vl-cmdf (list "_.-PURGE" "_All" "*" "_N"))

              (command "_.UNDO" "_End")
              (setvar "CMDECHO" old-echo)

              (princ "\n\n  Drawing cleaned (NOT saved).")
              (princ "\n")
              (princ "\n=== NOW DO THIS ===")
              (princ "\n 1. Run KCHECK and confirm PASS for your diagram type.")
              (princ (strcat "\n 2. SAVEAS -> file type \"AutoCAD 2013/LT2013 DXF (*.dxf)\""))
              (princ (strcat "\n    -> filename: " nm ".dxf"))
              (princ "\n       (any DXF version 2004-2014 is accepted; 2013 is the newest)")
              (princ (strcat "\n 3. Plot the diagram to " nm ".pdf  (same base name, spec 4.3)"))
              (princ "\n 4. Digitally sign the PDF, then submit both files.")
              (princ "\n 5. Back here: press UNDO ONCE to restore the working drawing.")
              (princ "\n")
              (princ "\n Reminder: SAVEAS leaves you working INSIDE the .dxf - after step 5")
              (princ "\n reopen your .dwg, or SAVEAS back to dwg before you keep drafting.")
              (princ)
            )
          )
        )
      )
    )
  )
  (princ)
)

(princ "\nkexport.lsp v1 loaded.  Command: KEXPORT")
(princ)
