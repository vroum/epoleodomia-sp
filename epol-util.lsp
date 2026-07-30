;;; ==========================================================================
;;; epol-util.lsp - UTILITIES - transparency, layer listing, help
;;; ==========================================================================
;;;
;;;   ETRANS ELAYERS EHELP
;;;
;;; Part of EPOLEODOMIA GIS Tools v2.1. Do not load directly - load
;;; epoleodomia.lsp, which loads every module in the correct order.
;;; Contains 3 top-level forms.
;;; ==========================================================================

;;; =============================================================================
;;; UTILITY COMMANDS
;;; =============================================================================

;;; ETRANS - Enable transparency on drone rasters
;;; ETRANS - transparency + fade on raster layers
;;;
;;; Was hardcoded to R_DJI_* and so did nothing for FEK/DE/ERASTER layers.
;;; Now covers every R_* layer.
;;;
;;; Note on what Transparency actually does: it makes the image's *transparent
;;; pixels* show through, so it needs an alpha channel, a palette transparent
;;; index, or a bitonal image. On a plain 1-band greyscale scan - which is what
;;; the GYS 1:5000 sheets are - there is nothing to make transparent and the
;;; call is a no-op. Fade is what helps there: it blends the image toward the
;;; background so your linework reads on top of it.
(defun c:ETRANS (/ ss i ent layer-name img-obj count fade inp)
  (princ "\n=== Raster Transparency / Fade ===")

  (initget 4)   ; allow zero, no negatives
  (setq inp (getint "\nFade 0-90 [0 = off] <50>: "))
  (setq fade (cond ((null inp) 50) ((> inp 90) 90) (T inp)))

  (setq count 0)
  (setq ss (ssget "_X" '((0 . "IMAGE"))))

  (if ss
    (progn
      (setq i 0)
      (while (< i (sslength ss))
        (setq ent (ssname ss i))
        (setq layer-name (cdr (assoc 8 (entget ent))))

        (if (wcmatch layer-name "R_*")
          (progn
            (setq img-obj (vlax-ename->vla-object ent))
            (if img-obj
              (progn
                (vl-catch-all-apply 'vla-put-Transparency
                                    (list img-obj :vlax-true))
                (vl-catch-all-apply 'vla-put-Fade (list img-obj fade))
                (setq count (1+ count))
              )
            )
          )
        )
        (setq i (1+ i))
      )
      (princ (strcat "\nTransparency on + fade " (itoa fade)
                     " applied to " (itoa count) " raster(s)."))
      (if (> count 0)
        (princ "\nTip: transparency needs alpha/palette/bitonal - on a plain")
      )
      (if (> count 0)
        (princ "\ngreyscale scan only the fade will be visible.")
      )
    )
    (princ "\nNo rasters found.")
  )
  (princ)
)

;;; ELAYERS - List epoleodomia layers
(defun c:ELAYERS (/ layer-data)
  (princ "\n=== Epoleodomia Layers ===")
  (setq layer-data (tblnext "LAYER" T))
  (while layer-data
    (if (or (wcmatch (cdr (assoc 2 layer-data)) "EPOL_*")
            (wcmatch (cdr (assoc 2 layer-data)) "R_*"))
      (princ (strcat "\n  " (cdr (assoc 2 layer-data))))
    )
    (setq layer-data (tblnext "LAYER"))
  )
  (princ "\n")
  (princ)
)

;;; EHELP - Show help
(defun c:EHELP ()
  (princ "\n")
  (princ "\n========================================")
  (princ "\n EPOLEODOMIA GIS TOOLS v2.1")
  (princ "\n========================================")
  (princ "\n")
  (princ "\n SITE ANALYSIS:")
  (princ "\n   EREPORT   - Full planning report table (parcel-based)")
  (princ "\n   ENOTES    - Topographic notes / PARATHRHSEIS (auto-filled)")
  (princ "\n   ETABLE    - Building regulations ruled table")
  (princ "\n   OROITABLE - Building regulations MTEXT annotation")
  (princ "\n   ARCHEO   - Archaeological sites")
  (princ "\n   CHURCH   - Closest church distance")
  (princ "\n   NATURA   - Natura 2000 / forest")
  (princ "\n   AIGIALOS - Shoreline distance")
  (princ "\n   REMATA   - Stream distances")
  (princ "\n")
  (princ "\n BOUNDARIES:")
  (princ "\n   KAEK     - Cadastral parcel number")
  (princ "\n   EKAEK    - Draw KAEK parcel + neighbors")
  (princ "\n   OT       - Building block number")
  (princ "\n   EOBT     - Draw OT polygon + neighbors")
  (princ "\n   KAEK_OP  - Draw operating cadastre parcel + neighbors")
  (princ "\n")
  (princ "\n KTIMATOLOGIO DIAGRAMS:")
  (princ "\n   KLAYERS  - Create official diagram layers (PINAKAS I)")
  (princ "\n   KPST     - PST_KAEK background from operating cadastre")
  (princ "\n   KCHECK   - Validate drawing vs diagram profile (TD/DGM/TDGM)")
  (princ "\n   KGEOM    - Diorthwsh oriwn: TOPO_PROP -> AREA_D/A + finals + table")
  (princ "\n   KGEOMV   - Diorthwsh kathetwn: AX polylines -> VST_FINAL + table")
  (princ "\n   KVERT    - Vertex circles + numbering + XY table")
  (princ "\n   KGRID    - Kannabos 10x10cm + perimeter coordinates")
  (princ "\n   AIGDRAW  - Existing aigialos/paralia lines in bbox (FEK labels)")
  (princ "\n")
  (princ "\n RASTERS:")
  (princ "\n   ERASTER  - Any catalogued sheet collection (role-filtered)")
  (princ "\n   FEK      - Planning diagram rasters")
  (princ "\n   DJI      - Drone orthophotos")
  (princ "\n   DE       - DE rasters")
  (princ "\n   CLIPR    - Clip raster to area")
  (princ "\n")
  (princ "\n UTILITIES:")
  (princ "\n   ETRANS   - Enable raster transparency")
  (princ "\n   ELAYERS  - List epoleodomia layers")
  (princ "\n   EHELP    - Show this help")
  (princ "\n")
  (princ "\n DATA SOURCES:")
  (princ "\n   epoleodomia: OT, planning, building regs")
  (princ "\n   sp_geodata:  KAEK, churches, streams, rasters")
  (princ "\n")
  (princ "\n API Server: http://127.0.0.1:8000")
  (princ "\n========================================")
  (princ "\n")
  (princ)
)
