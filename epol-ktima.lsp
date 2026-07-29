;;; ==========================================================================
;;; epol-ktima.lsp - KTIMATOLOGIO - official electronic diagram tools (TD / DGM / TDGM)
;;; ==========================================================================
;;;
;;;   KLAYERS KPST KGEOM KGEOMV KVERT KGRID AIGDRAW KCHECK
;;;
;;; Part of EPOLEODOMIA GIS Tools v2.1. Do not load directly - load
;;; epoleodomia.lsp, which loads every module in the correct order.
;;; Contains 28 top-level forms.
;;; ==========================================================================

;;; =============================================================================
;;; KTIMATOLOGIO ELECTRONIC DIAGRAM TOOLS (KLAYERS / KPST)
;;; =============================================================================

;;; Official layers from PINAKAS I (Elliniko Ktimatologio): name, color, linetype.
;;; Source: tekmhriwsh/PINAKAS_I_LAYERS_MODEL_AN_EK DXF (colors verified).
;;; PST / VST_PST / EAS_PST are helper layers from the official examples.
(setq *ktima-layers*
  '(("PST_KAEK"        16 "Continuous")
    ("PST"              8 "Continuous")
    ("ROAD"             2 "Continuous")
    ("OT"              80 "Continuous")
    ("BOUND_IMPL"      42 "Continuous")
    ("BOUND_UNIMPL"    61 "Continuous")
    ("BLD"            163 "Continuous")
    ("TOPO_PROP"       30 "Continuous")
    ("TOPO_PROP_NEW"  224 "Continuous")
    ("LINE_XM"          1 "JIS_02_2.0")
    ("LINE_XM_VST"      1 "JIS_02_2.0")
    ("VST"            233 "Continuous")
    ("VST_FINAL"        4 "Continuous")
    ("VST_PST"          8 "Continuous")
    ("EAS"            233 "Continuous")
    ("EAS_FINAL"        4 "Continuous")
    ("EAS_PST"          8 "Continuous")
    ("MINE"           157 "Continuous")
    ("MINE_FINAL"       4 "Continuous")
    ("DGM_PROP_FINAL"   4 "Continuous")
    ("AREA_D"           4 "Continuous")
    ("AREA_A"           6 "Continuous")
    ("OBJ"              3 "Continuous")
    ("DBOUND_PROP"      7 "Continuous")
    ("DBOUND_RYM"      80 "Continuous")
    ("DBOUND_AIG"       1 "Continuous")
    ("DBOUND_PRL"       2 "Continuous")
    ("DBOUND_PAIG"    152 "Continuous")
    ("DBOUND_REM"     141 "Continuous")
    ("DBOUND_APAL"     84 "Continuous")
  )
)

;;; KLAYERS - Create all official Ktimatologio diagram layers
(defun c:KLAYERS (/ n l)
  (setq n 0)
  (foreach l *ktima-layers*
    (if (not (tblsearch "LAYER" (car l)))
      (progn
        (epol:make-klayer (car l) (cadr l) (caddr l))
        (setq n (1+ n))
      )
    )
  )
  (princ (strcat "\nKLAYERS: created " (itoa n) " new layers ("
                 (itoa (length *ktima-layers*)) " official layers total)."))
  (princ "\nNote: layer 'Kathetes KD' (Greek name, katargisi kathetwn only)")
  (princ "\n      must be created manually when needed.")
  (princ)
)

;;; KPST - Draw PST_KAEK background from the operating cadastre
;;; Parcels + KAEK labels as plain TEXT (spec: never MTEXT), AX -> VST_PST,
;;; douleies -> EAS_PST. For submission, verify against the official KD.
(defun c:KPST (/ pt url response clean lines line parts main-kaek
                coords th cur-kaek ctr count-p count-v count-e)
  (princ "\n=== PST_KAEK background (operating cadastre) ===")
  (princ "\nNOTE: authoritative source for submission is the official KD (DXF).")

  (setq pt (epol:get-point "\nPick point inside the parcel: "))
  (if pt
    (progn
      (setq url (epol:build-url "/kaek/pst"
                  (list (cons "x" (car pt)) (cons "y" (cadr pt)))))
      (princ "\nContacting API...")
      (setq response (epol:http-get url))

      (if (and response (> (strlen response) 0))
        (progn
          (setq clean (epol:remove-cr response))
          (setq lines (epol:split clean "\n"))
          (setq parts (epol:split (car lines) "|"))

          (if (= (car parts) "OK")
            (progn
              (setq main-kaek (nth 1 parts))

              ;; Official layers (created only if missing)
              (epol:make-klayer "PST_KAEK" 16 "Continuous")
              (epol:make-klayer "VST_PST"   8 "Continuous")
              (epol:make-klayer "EAS_PST"   8 "Continuous")

              (setq th (/ (getvar "VIEWSIZE") 80.0))
              (setq cur-kaek "")
              (setq count-p 0 count-v 0 count-e 0)

              (foreach line (cdr lines)
                (if (and line (> (strlen line) 3))
                  (progn
                    (setq parts (epol:split line "|"))
                    (cond

                      ;; P|kaek|coords — parcel ring on PST_KAEK
                      ((and (= (car parts) "P") (>= (length parts) 3))
                        (setq coords (epol:parse-coords (nth 2 parts)))
                        (if coords
                          (progn
                            (epol:draw-polygon coords "PST_KAEK")
                            ;; Label each parcel once — on its first (largest) ring.
                            ;; Plain centred TEXT (72/73) — MTEXT is a spec error.
                            (if (/= (nth 1 parts) cur-kaek)
                              (progn
                                (setq cur-kaek (nth 1 parts))
                                (setq ctr (epol:polygon-centroid coords))
                                (if ctr
                                  (epol:tbl-text-ctr (car ctr) (cadr ctr)
                                                     th cur-kaek "PST_KAEK"))
                                (setq count-p (1+ count-p))
                              )
                            )
                          )
                        )
                      )

                      ;; V|num|coords — apokleistiki xrisi on VST_PST
                      ((and (= (car parts) "V") (>= (length parts) 3))
                        (setq coords (epol:parse-coords (nth 2 parts)))
                        (if coords
                          (progn
                            (epol:draw-polygon coords "VST_PST")
                            (setq ctr (epol:polygon-centroid coords))
                            (if ctr
                              (epol:tbl-text-ctr (car ctr) (cadr ctr) (* th 0.7)
                                                 (strcat "AX " (nth 1 parts))
                                                 "VST_PST"))
                            (setq count-v (1+ count-v))
                          )
                        )
                      )

                      ;; E|num|coords — douleia on EAS_PST
                      ((and (= (car parts) "E") (>= (length parts) 3))
                        (setq coords (epol:parse-coords (nth 2 parts)))
                        (if coords
                          (progn
                            (epol:draw-polygon coords "EAS_PST")
                            (setq ctr (epol:polygon-centroid coords))
                            (if ctr
                              (epol:tbl-text-ctr (car ctr) (cadr ctr) (* th 0.7)
                                                 (strcat "D " (nth 1 parts))
                                                 "EAS_PST"))
                            (setq count-e (1+ count-e))
                          )
                        )
                      )
                    )
                  )
                )
              )

              (princ (strcat "\n\nPST_KAEK: " (itoa count-p)
                             " parcels drawn (main: " main-kaek ")"))
              (if (> count-v 0)
                (princ (strcat "\n  + " (itoa count-v) " AX polygons -> VST_PST")))
              (if (> count-e 0)
                (princ (strcat "\n  + " (itoa count-e) " douleies -> EAS_PST")))
            )
            (princ (strcat "\n" (car lines)))
          )
        )
        (princ "\nError: Could not retrieve data. Is the API server running?")
      )
    )
    (princ "\nCancelled.")
  )
  (princ)
)

;;; =============================================================================
;;; KGEOM - Boundary correction engine (diorthwsh oriwn) — GEO.M core
;;; =============================================================================
;;; Select the surveyed TOPO_PROP closed polyline -> the API/PostGIS computes
;;; subject parcel, D/A pieces, final parcels and the metavolwn table.
;;; Slivers below the tolerance (m2) are dropped and reported.
(if (not *kgeom-tol*) (setq *kgeom-tol* 0.5))

;;; Extract "x,y;x,y;..." from an LWPOLYLINE entity (locale-safe numbers)
(defun kgeom:poly-coords (ed / out g)
  (setq out "")
  (foreach g ed
    (if (= 10 (car g))
      (setq out (strcat out
                        (if (= out "") "" ";")
                        (epol:num-to-str (cadr g)) ","
                        (epol:num-to-str (caddr g))))
    )
  )
  out
)

(defun c:KGEOM (/ sel ent ed inp url response clean lines line parts
                 coords ctr th thl body count-d count-a count-f
                 tbl-rows tpt tw tbl-th subject)
  (princ "\n=== KGEOM - Diorthwsh oriwn (GEO.M) ===")

  (setq sel (entsel "\nSelect the surveyed TOPO_PROP closed polyline: "))
  (if sel
    (progn
      (setq ent (car sel))
      (setq ed (entget ent))
      (cond
        ((/= (cdr (assoc 0 ed)) "LWPOLYLINE")
          (princ "\nError: entity is not an LWPOLYLINE."))
        ((/= 1 (logand 1 (cdr (assoc 70 ed))))
          (princ "\nError: polyline is not CLOSED."))
        (T
          (progn
            (setq inp (getreal (strcat "\nSliver tolerance in m2 <"
                                       (rtos *kgeom-tol* 2 2) ">: ")))
            (if inp (setq *kgeom-tol* inp))

            (setq body (kgeom:poly-coords ed))
            (setq url (epol:build-url "/geom/diorthosi"
                        (list (cons "tol" *kgeom-tol*))))
            (princ "\nComputing geometry (PostGIS)...")
            (setq response (epol:http-post url body))

            (if (and response (> (strlen response) 0))
              (if (= (substr response 1 6) "ERROR|")
                (princ (strcat "\n" response))
                (progn
                  (setq clean (epol:remove-cr response))
                  (setq lines (epol:split clean "\n"))
                  (setq parts (epol:split (car lines) "|"))
                  (setq subject (nth 1 parts))

                  ;; Official layers
                  (epol:make-klayer "AREA_D"         4 "Continuous")
                  (epol:make-klayer "AREA_A"         6 "Continuous")
                  (epol:make-klayer "DGM_PROP_FINAL" 4 "Continuous")

                  (setq th  (/ (getvar "VIEWSIZE") 80.0))   ; kaek labels
                  (setq thl (/ (getvar "VIEWSIZE") 60.0))   ; D/A labels
                  (setq count-d 0 count-a 0 count-f 0)
                  (setq tbl-rows "")

                  (foreach line (cdr lines)
                    (if (and line (> (strlen line) 3))
                      (progn
                        (setq parts (epol:split line "|"))
                        (cond

                          ;; D|label|from|area|coords  /  A|label|to|area|coords
                          ((or (= (car parts) "D") (= (car parts) "A"))
                            (if (>= (length parts) 5)
                              (progn
                                (setq coords (epol:parse-coords (nth 4 parts)))
                                (if coords
                                  (progn
                                    (epol:draw-polygon coords
                                      (if (= (car parts) "D") "AREA_D" "AREA_A"))
                                    (setq ctr (epol:polygon-centroid coords))
                                    (if ctr
                                      (epol:tbl-text-ctr (car ctr) (cadr ctr) thl
                                        (nth 1 parts)
                                        (if (= (car parts) "D") "AREA_D" "AREA_A")))
                                    (if (= (car parts) "D")
                                      (setq count-d (1+ count-d))
                                      (setq count-a (1+ count-a)))
                                  )
                                )
                              )
                            )
                          )

                          ;; F|kaek|area|coords — final parcels
                          ((= (car parts) "F")
                            (if (>= (length parts) 4)
                              (progn
                                (setq coords (epol:parse-coords (nth 3 parts)))
                                (if coords
                                  (progn
                                    (epol:draw-polygon coords "DGM_PROP_FINAL")
                                    (setq count-f (1+ count-f))
                                  )
                                )
                              )
                            )
                          )

                          ;; TBL|... — metavolwn table rows
                          ((= (car parts) "TBL")
                            (setq tbl-rows
                              (strcat tbl-rows
                                      (if (= tbl-rows "") "" "\n")
                                      (substr line 5))))
                        )
                      )
                    )
                  )

                  (princ (strcat "\n\nKGEOM subject: " subject))
                  (princ (strcat "\n  D pieces: " (itoa count-d)
                                 "   A pieces: " (itoa count-a)
                                 "   final rings: " (itoa count-f)))

                  ;; Place the metavolwn table (uses the ETABLE scale memory)
                  (if (> (strlen tbl-rows) 0)
                    (progn
                      (setq tpt (epol:get-point "\nPick placement point for the table: "))
                      (if tpt
                        (progn
                          (setq tw (* (/ *epol-tbl-width* 1000.0) *epol-tbl-scale*))
                          (setq tbl-th (/ tw 50.0))
                          (epol:get-layer "EPOL_TABLE")
                          (epol:get-layer "EPOL_TABLE_HDR")
                          (epol:draw-table-rows tbl-rows tpt tw tbl-th)
                          (princ "\nTable placed.")
                        )
                        (princ "\nTable skipped.")
                      )
                    )
                  )
                  (princ "\nReview the balance line in the table before using the result.")
                )
              )
              (princ "\nError: Could not retrieve data. Is the API server running?")
            )
          )
        )
      )
    )
    (princ "\nCancelled.")
  )
  (princ)
)

;;; =============================================================================
;;; KGEOMV - Kathetes correction (diorthwsh kathetwn) — GEO.M
;;; =============================================================================
;;; Select the surveyed kathetes polylines one by one; for each, give the
;;; vp number and (optionally) the title area/xiliosta from the systash.
;;; The API clips to the parcel, matches cadastre AX, draws VST_FINAL +
;;; LINE_XM_VST and the comparison table (title / cadastre / measured).
(defun c:KGEOMV (/ sel ent ed body n num ta tx inp url response clean
                  lines line parts coords ctr th count-f count-l
                  tbl-rows tpt tw tbl-th kaek)
  (princ "\n=== KGEOMV - Diorthwsh kathetwn (GEO.M) ===")
  (princ "\nSelect surveyed kathetes (closed polylines), Enter when done.")

  (setq body "" n 0)
  (while (setq sel (entsel (strcat "\nSelect kathet #" (itoa (1+ n))
                                   " (or Enter to finish): ")))
    (setq ent (car sel))
    (setq ed (entget ent))
    (cond
      ((/= (cdr (assoc 0 ed)) "LWPOLYLINE")
        (princ "  -> not an LWPOLYLINE, skipped."))
      ((/= 1 (logand 1 (cdr (assoc 70 ed))))
        (princ "  -> polyline not CLOSED, skipped."))
      (T
        (progn
          (setq n (1+ n))
          (setq num (getstring (strcat "\n  vp number <"
                                       (if (< n 10) (strcat "0" (itoa n)) (itoa n))
                                       ">: ")))
          (if (= num "")
            (setq num (if (< n 10) (strcat "0" (itoa n)) (itoa n))))
          (setq ta (getreal "\n  Title area m2 (Enter = unknown): "))
          (setq tx (getreal "\n  Title xiliosta (Enter = unknown): "))
          (setq body (strcat body
                             (if (= body "") "" "\n")
                             "V|" num "|"
                             (if ta (epol:num-to-str ta) "") "|"
                             (if tx (epol:num-to-str tx) "") "|"
                             (kgeom:poly-coords ed)))
        )
      )
    )
  )

  (if (= body "")
    (princ "\nNothing selected — cancelled.")
    (progn
      (setq inp (getreal (strcat "\nTolerance m2 <" (rtos *kgeom-tol* 2 2) ">: ")))
      (if inp (setq *kgeom-tol* inp))

      (setq url (epol:build-url "/geom/kathetes" (list (cons "tol" *kgeom-tol*))))
      (princ "\nComputing geometry (PostGIS)...")
      (setq response (epol:http-post url body))

      (if (and response (> (strlen response) 0))
        (if (= (substr response 1 6) "ERROR|")
          (princ (strcat "\n" response))
          (progn
            (setq clean (epol:remove-cr response))
            (setq lines (epol:split clean "\n"))
            (setq parts (epol:split (car lines) "|"))
            (setq kaek (nth 1 parts))

            (epol:make-klayer "VST_FINAL"    4 "Continuous")
            (epol:make-klayer "LINE_XM_VST"  1 "JIS_02_2.0")

            (setq th (/ (getvar "VIEWSIZE") 70.0))
            (setq count-f 0 count-l 0)
            (setq tbl-rows "")

            (foreach line (cdr lines)
              (if (and line (> (strlen line) 2))
                (progn
                  (setq parts (epol:split line "|"))
                  (cond

                    ;; VF|num|area|coords — final katheti
                    ((= (car parts) "VF")
                      (if (>= (length parts) 4)
                        (progn
                          (setq coords (epol:parse-coords (nth 3 parts)))
                          (if coords
                            (progn
                              (epol:draw-polygon coords "VST_FINAL")
                              (setq ctr (epol:polygon-centroid coords))
                              (if ctr
                                (epol:tbl-text-ctr (car ctr) (cadr ctr) th
                                                   (nth 1 parts) "VST_FINAL"))
                              (setq count-f (1+ count-f))
                            )
                          )
                        )
                      )
                    )

                    ;; L|coords — change line (open)
                    ((= (car parts) "L")
                      (if (>= (length parts) 2)
                        (progn
                          (setq coords (epol:parse-coords (nth 1 parts)))
                          (if (and coords (> (length coords) 1))
                            (progn
                              (epol:draw-open-pline coords "LINE_XM_VST")
                              (setq count-l (1+ count-l))
                            )
                          )
                        )
                      )
                    )

                    ((= (car parts) "TBL")
                      (setq tbl-rows
                        (strcat tbl-rows
                                (if (= tbl-rows "") "" "\n")
                                (substr line 5))))
                  )
                )
              )
            )

            (princ (strcat "\n\nKGEOMV parcel: " kaek))
            (princ (strcat "\n  VST_FINAL: " (itoa count-f)
                           "   LINE_XM_VST: " (itoa count-l)))

            (if (> (strlen tbl-rows) 0)
              (progn
                (setq tpt (epol:get-point "\nPick placement point for the table: "))
                (if tpt
                  (progn
                    (setq tw (* (/ *epol-tbl-width* 1000.0) *epol-tbl-scale*))
                    (setq tbl-th (/ tw 50.0))
                    (epol:get-layer "EPOL_TABLE")
                    (epol:get-layer "EPOL_TABLE_HDR")
                    (epol:draw-table-rows tbl-rows tpt tw tbl-th)
                    (princ "\nTable placed.")
                  )
                  (princ "\nTable skipped.")
                )
              )
            )
            (princ "\nReview the warnings (if any) in the table before submission.")
          )
        )
        (princ "\nError: Could not retrieve data. Is the API server running?")
      )
    )
  )
  (princ)
)

;;; =============================================================================
;;; KVERT - Vertex kit: circles + numbering + coordinate table
;;; =============================================================================
;;; Works on OPEN and CLOSED polylines (aigialos lines are open!).
;;; Cleans the vertex list first: consecutive duplicates (zero-length
;;; segments) and the closing duplicate vertex are removed with a tolerance,
;;; and the count of removed points is reported. Spec (egkyklios 2022):
;;; circles ~2.5mm paper, numbering prefix+N, 3-decimal coordinate table.
(if (not *kvert-num*) (setq *kvert-num* 1))

;;; rtos with 3 decimals, period decimal separator (locale-safe)
(defun kvert:n3 (num / str pos)
  (setq str (rtos num 2 3))
  (while (setq pos (vl-string-search "," str))
    (setq str (vl-string-subst "." "," str))
  )
  str
)

;;; Collect existing vertex marks from the drawing: circles on XY_PTS matched
;;; to their nearest TEXT label. Returns list of (x y name-or-nil).
(defun kvert:existing-marks (/ ss i ed c r texts tss ted tp marks best bestd d t-ent)
  (setq marks nil texts nil)
  ;; all TEXT labels on XY_PTS: ((x y) . string)
  (setq tss (ssget "_X" '((0 . "TEXT") (8 . "XY_PTS"))))
  (if tss
    (progn
      (setq i (sslength tss))
      (repeat (sslength tss)
        (setq i (1- i))
        (setq ted (entget (ssname tss i)))
        (setq tp (cdr (assoc 10 ted)))
        (setq texts (cons (cons (list (car tp) (cadr tp))
                                (cdr (assoc 1 ted))) texts))
      )
    )
  )
  ;; circles on XY_PTS -> match nearest label within 4 radii
  (setq ss (ssget "_X" '((0 . "CIRCLE") (8 . "XY_PTS"))))
  (if ss
    (progn
      (setq i (sslength ss))
      (repeat (sslength ss)
        (setq i (1- i))
        (setq ed (entget (ssname ss i)))
        (setq c (cdr (assoc 10 ed)))
        (setq r (cdr (assoc 40 ed)))
        (setq best nil bestd (* r 4.0))
        (foreach t-ent texts
          (setq d (distance (list (car c) (cadr c)) (car t-ent)))
          (if (< d bestd) (setq bestd d best (cdr t-ent)))
        )
        (setq marks (cons (list (car c) (cadr c) best) marks))
      )
    )
  )
  marks
)

;;; Find a mark within tol of point p; returns (x y name) or nil
(defun kvert:find-mark (p marks tol / hit m)
  (setq hit nil)
  (foreach m marks
    (if (and (not hit)
             (< (distance p (list (car m) (cadr m))) tol))
      (setq hit m)
    )
  )
  hit
)

;;; Clean vertex list: returns (points n-removed closed?)
(defun kvert:clean (pts closed-flag tol / out prev p ndup was-closed lastp)
  (setq out nil ndup 0 prev nil)
  (foreach p pts
    (if (and prev (< (distance prev p) tol))
      (setq ndup (1+ ndup))
      (progn
        (setq out (cons p out))
        (setq prev p)
      )
    )
  )
  (setq out (reverse out))
  (setq was-closed (= 1 closed-flag))
  ;; Drawn-closed polyline: last vertex duplicates the first
  (if (> (length out) 1)
    (progn
      (setq lastp (last out))
      (if (< (distance (car out) lastp) tol)
        (progn
          (setq out (reverse (cdr (reverse out))))
          (setq ndup (1+ ndup))
          (setq was-closed T)
        )
      )
    )
  )
  (list out ndup was-closed)
)

(defun c:KVERT (/ sel ent ed pts g prefix inp start scale r th-txt
                 clean-res verts ndup closed n name body url response
                 lines line tbl-rows tpt tw tbl-th p lbl-pt
                 marks hit reused used nskip)
  (princ "\n=== KVERT - Vertex circles + numbering + XY table ===")

  (setq sel (entsel "\nSelect polyline (open or closed): "))
  (if sel
    (progn
      (setq ent (car sel))
      (setq ed (entget ent))
      (if (/= (cdr (assoc 0 ed)) "LWPOLYLINE")
        (princ "\nError: entity is not an LWPOLYLINE.")
        (progn
          ;; Collect raw vertices
          (setq pts nil)
          (foreach g ed
            (if (= 10 (car g))
              (setq pts (cons (list (cadr g) (caddr g)) pts))))
          (setq pts (reverse pts))

          ;; Clean: consecutive dups + closing dup (tol 5mm ground)
          (setq clean-res (kvert:clean pts (logand 1 (cdr (assoc 70 ed))) 0.005))
          (setq verts  (car clean-res))
          (setq ndup   (cadr clean-res))
          (setq closed (caddr clean-res))

          (if (> ndup 0)
            (princ (strcat "\n  Cleaned " (itoa ndup)
                           " duplicate/zero-length vertices (tol 5mm).")))
          (princ (strcat "\n  " (itoa (length verts)) " vertices, "
                         (if closed "CLOSED polygon" "OPEN line") "."))

          (if (< (length verts) 2)
            (princ "\nError: not enough vertices after cleaning.")
            (progn
              ;; Prompts (Greek prefix typed here works — runtime input)
              (setq prefix (getstring "\nVertex prefix <none>: "))
              (setq inp (getint (strcat "\nStart number <" (itoa *kvert-num*) ">: ")))
              (if inp (setq *kvert-num* inp))
              (setq inp (getint (strcat "\nDrawing scale 1:<" (itoa *epol-tbl-scale*) ">: ")))
              (if inp (setq *epol-tbl-scale* inp))
              (setq scale *epol-tbl-scale*)

              ;; Paper sizes: circle D=2.5mm, text h=2.0mm
              (setq r      (* 0.00125 scale))
              (setq th-txt (* 0.002   scale))
              (epol:make-klayer "XY_PTS" 7 "Continuous")

              ;; Existing marks in the drawing = shared-vertex registry
              (setq marks (kvert:existing-marks))
              (if marks
                (princ (strcat "\n  Found " (itoa (length marks))
                               " existing vertex marks in drawing.")))

              ;; Draw circles + labels, build table body.
              ;; A vertex on an existing mark reuses its name — no duplicates.
              (setq n *kvert-num*)
              (setq body "" reused 0 used nil nskip 0)
              (foreach p verts
                (setq hit (kvert:find-mark p marks 0.005))
                (cond
                  ;; Existing mark with a readable label: reuse name, draw nothing
                  ((and hit (caddr hit))
                    (setq name (caddr hit))
                    (setq reused (1+ reused)))
                  ;; Existing circle without label: keep circle, add new label
                  (hit
                    (setq name (strcat prefix (itoa n)))
                    (setq n (1+ n))
                    (setq lbl-pt (list (+ (car p) (* r 1.6))
                                       (+ (cadr p) (* r 1.6))))
                    (epol:tbl-text (car lbl-pt) (cadr lbl-pt) th-txt name "XY_PTS")
                    (setq marks (cons (list (car p) (cadr p) name) marks)))
                  ;; New vertex: circle + label
                  (T
                    (setq name (strcat prefix (itoa n)))
                    (setq n (1+ n))
                    (entmake (list '(0 . "CIRCLE")
                                   '(8 . "XY_PTS")
                                   (cons 10 (list (car p) (cadr p) 0.0))
                                   (cons 40 r)))
                    (setq lbl-pt (list (+ (car p) (* r 1.6))
                                       (+ (cadr p) (* r 1.6))))
                    (epol:tbl-text (car lbl-pt) (cadr lbl-pt) th-txt name "XY_PTS")
                    ;; register so repeated vertices within this run also unify
                    (setq marks (cons (list (car p) (cadr p) name) marks)))
                )
                ;; One table row per POINT, not per traversal: a polyline that
                ;; revisits a vertex (retraced segment) is usually a drawing
                ;; error — list the point once and warn loudly below.
                (if (member name used)
                  (setq nskip (1+ nskip))
                  (progn
                    (setq used (cons name used))
                    (setq body (strcat body
                                       (if (= body "") "" "\n")
                                       name "|" (kvert:n3 (car p)) "|" (kvert:n3 (cadr p))))
                  )
                )
              )
              (setq *kvert-num* n)   ; continue numbering on next call

              (princ (strcat "\n  " (itoa (- (length verts) reused))
                             " new marks drawn, " (itoa reused)
                             " shared vertices reused existing names."))
              (if (> nskip 0)
                (progn
                  (princ (strcat "\n  *** WARNING: polyline passes " (itoa nskip)
                                 " time(s) over already-numbered vertices ***"))
                  (princ "\n  *** Possible retraced/overlapping segment - CHECK THE DRAWING ***")
                  (princ "\n  (each point is listed once in the table)")
                )
              )

              ;; Coordinate table via API (Greek headers arrive correctly)
              (setq url (epol:build-url "/xytable"
                          (list (cons "label" (if (= prefix "") "" prefix)))))
              (setq response (epol:http-post url body))
              (if (and response (> (strlen response) 0)
                       (/= (substr response 1 6) "ERROR|"))
                (progn
                  (setq tbl-rows "")
                  (foreach line (epol:split (epol:remove-cr response) "\n")
                    (if (= (substr line 1 4) "TBL|")
                      (setq tbl-rows (strcat tbl-rows
                                             (if (= tbl-rows "") "" "\n")
                                             (substr line 5)))))
                  (if (> (strlen tbl-rows) 0)
                    (progn
                      (setq tpt (epol:get-point "\nPick placement point for the XY table: "))
                      (if tpt
                        (progn
                          (setq tw (* (/ *epol-tbl-width* 1000.0) scale))
                          (setq tbl-th (/ tw 50.0))
                          (epol:get-layer "EPOL_TABLE")
                          (epol:get-layer "EPOL_TABLE_HDR")
                          (epol:draw-table-rows tbl-rows tpt tw tbl-th)
                          (princ "\nTable placed.")
                        )
                        (princ "\nTable skipped.")
                      )
                    )
                  )
                )
                (princ "\nWarning: table not generated (API unreachable?) - circles/labels are drawn.")
              )
            )
          )
        )
      )
    )
    (princ "\nCancelled.")
  )
  (princ)
)

;;; =============================================================================
;;; KGRID - Kannabos 10x10 cm (crosses or full grid) + perimeter coordinates
;;; =============================================================================
;;; Per egkyklios YPOIK 21401/2022: grid every 10 cm on paper, coordinates
;;; written at both ends of every grid line. Nodes on round EGSA multiples.
(if (not *kgrid-style*) (setq *kgrid-style* "Crosses"))

(defun kgrid:line (x1 y1 x2 y2)
  (entmake (list '(0 . "LINE") '(8 . "GRID")
                 (cons 10 (list x1 y1 0.0))
                 (cons 11 (list x2 y2 0.0))))
)

(defun kgrid:label (x y txt th)
  (entmake (list '(0 . "TEXT") '(8 . "GRID")
                 (cons 10 (list x y 0.0))
                 (cons 40 th) (cons 1 txt)))
)

;;; Vertical label (rotated 90) for the X coordinates — per egkyklios image 1
(defun kgrid:vlabel (x y txt th)
  (entmake (list '(0 . "TEXT") '(8 . "GRID")
                 (cons 10 (list x y 0.0))
                 (cons 40 th) (cons 1 txt)
                 (cons 50 (/ pi 2.0))))
)

(defun c:KGRID (/ p1 p2 minx miny maxx maxy inp scale sp arm th off
                 x y x0 y0 txt est n)
  (princ "\n=== KGRID - Kannabos 10x10cm + coordinates ===")

  (setq p1 (epol:get-point "\nFirst corner of area: "))
  (if p1 (setq p2 (epol:get-point "\nOpposite corner: ")))
  (if (and p1 p2)
    (progn
      (setq minx (min (car p1) (car p2)) maxx (max (car p1) (car p2)))
      (setq miny (min (cadr p1) (cadr p2)) maxy (max (cadr p1) (cadr p2)))

      (setq inp (getint (strcat "\nDrawing scale 1:<" (itoa *epol-tbl-scale*) ">: ")))
      (if inp (setq *epol-tbl-scale* inp))
      (setq scale *epol-tbl-scale*)

      (initget "Crosses Full")
      (setq inp (getkword (strcat "\nGrid style [Crosses/Full] <" *kgrid-style* ">: ")))
      (if inp (setq *kgrid-style* inp))

      ;; paper sizes -> ground units
      (setq sp  (* 0.10   scale))   ; grid step: 10 cm paper
      (setq arm (* 0.005  scale))   ; cross half-arm: 5 mm
      (setq th  (* 0.0025 scale))   ; label text: 2.5 mm
      (setq off (* 0.004  scale))   ; label offset from frame

      (epol:make-klayer "GRID" 8 "Continuous")

      ;; first grid values >= min, on round multiples of the step
      (setq x0 (* sp (fix (/ minx sp))))
      (if (< x0 minx) (setq x0 (+ x0 sp)))
      (setq y0 (* sp (fix (/ miny sp))))
      (if (< y0 miny) (setq y0 (+ y0 sp)))

      (setq n 0)
      (if (= *kgrid-style* "Full")
        (progn
          (setq x x0)
          (while (<= x (+ maxx 0.001))
            (kgrid:line x miny x maxy)
            (setq x (+ x sp) n (1+ n)))
          (setq y y0)
          (while (<= y (+ maxy 0.001))
            (kgrid:line minx y maxx y)
            (setq y (+ y sp) n (1+ n)))
        )
        (progn   ;; crosses at every node
          (setq x x0)
          (while (<= x (+ maxx 0.001))
            (setq y y0)
            (while (<= y (+ maxy 0.001))
              (kgrid:line (- x arm) y (+ x arm) y)
              (kgrid:line x (- y arm) x (+ y arm))
              (setq y (+ y sp) n (1+ n)))
            (setq x (+ x sp)))
        )
      )

      ;; perimeter labels: X bottom+top VERTICAL (rot 90), Y left+right horizontal
      (setq x x0)
      (while (<= x (+ maxx 0.001))
        (setq txt (itoa (fix (+ x 0.5))))
        (setq est (* (strlen txt) th 0.6))
        ;; rotated 90: baseline runs +Y, glyphs extend -X, so shift +th/2 to centre
        (kgrid:vlabel (+ x (/ th 2.0)) (- miny off est) txt th)  ; bottom: ends at frame
        (kgrid:vlabel (+ x (/ th 2.0)) (+ maxy off) txt th)      ; top: starts at frame
        (setq x (+ x sp)))
      (setq y y0)
      (while (<= y (+ maxy 0.001))
        (setq txt (itoa (fix (+ y 0.5))))
        (setq est (* (strlen txt) th 0.6))
        (kgrid:label (- minx off est) (- y (/ th 2.0)) txt th)   ; left
        (kgrid:label (+ maxx off) (- y (/ th 2.0)) txt th)       ; right
        (setq y (+ y sp)))

      (princ (strcat "\nKGRID: " (itoa n) " "
                     (if (= *kgrid-style* "Full") "grid lines" "crosses")
                     " on layer GRID (step "
                     (rtos sp 2 0) " m ground / 10 cm paper at 1:"
                     (itoa scale) ")."))
    )
    (princ "\nCancelled.")
  )
  (princ)
)

;;; =============================================================================
;;; AIGDRAW - Draw existing aigialos/paralia lines from the curated DB
;;; =============================================================================
;;; Source: sp_geodata.Aigialos_Paralia (79 lines, full FEK 1969-2018).
;;; Official layers per PINAKAS I: DBOUND_AIG (red) / DBOUND_PRL (yellow) /
;;; DBOUND_PAIG (blue). Labels carry the line type + FEK.
(defun c:AIGDRAW (/ bbox url response clean lines line parts coords
                   lay lbl mid th count-a count-p count-o)
  (princ "\n=== AIGDRAW - Existing aigialos/paralia lines ===")

  (setq bbox (epol:get-bbox "\nPick first corner: " "\nPick opposite corner: "))
  (if bbox
    (progn
      (setq url (epol:build-url "/aigialos/simple"
                  (list (cons "minx" (caar bbox))
                        (cons "miny" (cadar bbox))
                        (cons "maxx" (caadr bbox))
                        (cons "maxy" (cadadr bbox)))))
      (princ "\nContacting API...")
      (setq response (epol:http-get url))

      (if (and response (> (strlen response) 0))
        (progn
          (setq clean (epol:remove-cr response))
          (setq lines (epol:split clean "\n"))

          ;; Official layers (colors from PINAKAS I)
          (epol:make-klayer "DBOUND_AIG"    1 "Continuous")
          (epol:make-klayer "DBOUND_PRL"    2 "Continuous")
          (epol:make-klayer "DBOUND_PAIG" 152 "Continuous")

          (setq th (/ (getvar "VIEWSIZE") 90.0))
          (setq count-a 0 count-p 0 count-o 0)

          (foreach line (cdr lines)
            (if (and line (> (strlen line) 2))
              (progn
                (setq parts (epol:split line "|"))
                (if (and (= (car parts) "G") (>= (length parts) 4))
                  (progn
                    (setq lay (nth 1 parts))
                    (setq lbl (nth 2 parts))
                    (setq coords (epol:parse-coords (nth 3 parts)))
                    (if (and coords (> (length coords) 1))
                      (progn
                        (epol:draw-open-pline coords lay)
                        ;; label at the middle vertex, same layer
                        (setq mid (nth (/ (length coords) 2) coords))
                        (epol:tbl-text (car mid) (cadr mid) th lbl lay)
                        (cond
                          ((= lay "DBOUND_AIG")  (setq count-a (1+ count-a)))
                          ((= lay "DBOUND_PRL")  (setq count-p (1+ count-p)))
                          (T                     (setq count-o (1+ count-o)))
                        )
                      )
                    )
                  )
                )
              )
            )
          )

          (princ (strcat "\n\nAIGDRAW: " (itoa count-a) " aigialos, "
                         (itoa count-p) " paralia, "
                         (itoa count-o) " palaios aigialos lines drawn."))
          (if (= (+ count-a count-p count-o) 0)
            (princ "\nNo lines found in this area."))
        )
        (princ "\nError: Could not retrieve data. Is the API server running?")
      )
    )
    (princ "\nCancelled.")
  )
  (princ)
)

;;; =============================================================================
;;; KCHECK - Validator for Ktimatologio electronic diagrams
;;; =============================================================================
;;; Implements the layer/entity checks of the guide (tekmhriwsh/KTIMATOLOGIO_
;;; ELECTRONIC_DIAGRAMS_GUIDE.md §8.1/§8.3). Topology checks (snap, node
;;; preservation, area balance) are the next phase (Python/ezdxf on the DXF).

;;; Profiles: (id name required any-groups forbidden recommended)
;;; "required" layers must exist AND contain entities.
;;; "any-groups" = list of groups; at least ONE layer of EACH group must
;;; have entities (per teyxos v1.3 §4.5.2 — e.g. AREA_D *or* AREA_A suffice).
(setq *kcheck-profiles*
  '((1  "TD ektos sxediou"
        ("TOPO_PROP" "PST_KAEK") (("BOUND_IMPL" "BOUND_UNIMPL"))
        ("TOPO_PROP_NEW" "LINE_XM" "DGM_PROP_FINAL") ())
    (2  "TD entos sxediou"
        ("TOPO_PROP" "PST_KAEK" "DBOUND_RYM") (("BOUND_IMPL" "BOUND_UNIMPL"))
        ("TOPO_PROP_NEW" "LINE_XM" "DGM_PROP_FINAL") ("OT" "ROAD"))
    (3  "DGM katatmhshs"
        ("TOPO_PROP" "TOPO_PROP_NEW" "PST_KAEK" "LINE_XM" "DGM_PROP_FINAL")
        (("BOUND_IMPL" "BOUND_UNIMPL")) () ())
    (4  "DGM synenwshs"
        ("TOPO_PROP" "TOPO_PROP_NEW" "PST_KAEK" "DGM_PROP_FINAL")
        (("BOUND_IMPL" "BOUND_UNIMPL")) ("LINE_XM") ())
    (5  "DGM systashs douleias"
        ("TOPO_PROP" "PST_KAEK" "EAS" "EAS_FINAL")
        (("BOUND_IMPL" "BOUND_UNIMPL")) () ())
    (6  "DGM systashs kathetwn"
        ("TOPO_PROP" "VST" "PST_KAEK" "LINE_XM_VST" "VST_FINAL")
        (("BOUND_IMPL" "BOUND_UNIMPL")) () ())
    (7  "DGM katatmhshs + systashs kathetwn"
        ("TOPO_PROP" "TOPO_PROP_NEW" "VST" "PST_KAEK" "LINE_XM"
         "DGM_PROP_FINAL" "LINE_XM_VST" "VST_FINAL")
        (("BOUND_IMPL" "BOUND_UNIMPL")) () ())
    (8  "DGM katarghshs kathetwn"
        ("TOPO_PROP" "PST_KAEK" "DGM_PROP_FINAL") ()
        ("VST" "VST_FINAL") ())
    ;; §4.5.2γ: AREA_D *ή* AREA_A αρκεί (όχι υποχρεωτικά και τα δύο)
    (9  "DGM diorthwshs oriwn"
        ("TOPO_PROP" "PST_KAEK" "DGM_PROP_FINAL")
        (("BOUND_IMPL" "BOUND_UNIMPL") ("AREA_D" "AREA_A"))
        ("TOPO_PROP_NEW" "LINE_XM") ())
    (10 "DGM diorthwshs kathetwn"
        ("TOPO_PROP" "VST" "PST_KAEK" "LINE_XM_VST" "VST_FINAL")
        (("BOUND_IMPL" "BOUND_UNIMPL")) ()
        ("VST_PST"))
    (11 "DGM diorthwshs douleias"
        ("TOPO_PROP" "PST_KAEK" "EAS" "EAS_FINAL")
        (("BOUND_IMPL" "BOUND_UNIMPL")) () ("EAS_PST"))
    (12 "DGM eswterikou polygwnou"
        ("TOPO_PROP" "PST_KAEK" "DGM_PROP_FINAL")
        (("BOUND_IMPL" "BOUND_UNIMPL") ("AREA_D" "AREA_A"))
        ("TOPO_PROP_NEW" "LINE_XM") ())
    (13 "TDGM diorthwshs oriwn (dikografo)"
        ("TOPO_PROP" "PST_KAEK" "DGM_PROP_FINAL")
        (("BOUND_IMPL" "BOUND_UNIMPL") ("AREA_D" "AREA_A"))
        ("TOPO_PROP_NEW" "LINE_XM") ())
    (14 "TDGM metaforas theshs"
        ("TOPO_PROP" "PST_KAEK" "PST" "AREA_D" "DGM_PROP_FINAL")
        (("BOUND_IMPL" "BOUND_UNIMPL")) ("TOPO_PROP_NEW") ())
    (15 "TDGM dhmiourgias neou gewtemaxiou"
        ("TOPO_PROP" "PST_KAEK" "AREA_D" "DGM_PROP_FINAL")
        (("BOUND_IMPL" "BOUND_UNIMPL")) ("TOPO_PROP_NEW") ())
  )
)

;;; Layers whose polylines must be CLOSED
;;; BLD is an official PINAKAS I layer (a/a 15): closed polygon per building
;;; + TEXT numbering — not a "visual example layer" as the older guide said.
(setq *kcheck-poly-layers*
  '("TOPO_PROP" "TOPO_PROP_NEW" "PST_KAEK" "PST" "DGM_PROP_FINAL"
    "AREA_D" "AREA_A" "EAS" "EAS_FINAL" "EAS_PST"
    "VST" "VST_FINAL" "VST_PST" "MINE" "MINE_FINAL" "BLD"))

;;; Polygon layers where TEXT labels are expected (KAEK / building numbers)
(setq *kcheck-text-ok-layers* '("PST_KAEK" "BLD"))

;;; Layers whose polylines must be OPEN
(setq *kcheck-line-layers* '("LINE_XM" "LINE_XM_VST"))

;;; Layers that must contain only plain TEXT
(setq *kcheck-textonly-layers* '("OT" "ROAD"))

;;; Layers where MTEXT is forbidden but polylines+TEXT are fine (a/a 4-8 incl.)
(setq *kcheck-mixed-layers*
  '("DBOUND_PROP" "DBOUND_RYM" "DBOUND_AIG" "DBOUND_PRL"
    "DBOUND_PAIG" "DBOUND_REM" "DBOUND_APAL"))

;;; Count entities on a layer in Model space (optional entity-type filter)
(defun kcheck:count (lay etype / flt ss)
  (setq flt (list (cons 8 lay) (cons 410 "Model")))
  (if etype (setq flt (cons (cons 0 etype) flt)))
  (setq ss (ssget "_X" flt))
  (if ss (sslength ss) 0)
)

;;; Scan one layer; kind = "POLY" | "LINE" | "TEXTONLY" | "MIXED".
;;; Returns list of error strings.
(defun kcheck:scan (lay kind / ss i ed et h errs closed verts)
  (setq errs nil)
  (setq ss (ssget "_X" (list (cons 8 lay) (cons 410 "Model"))))
  (if ss
    (progn
      (setq i (sslength ss))
      (repeat (sslength ss)
        (setq i (1- i))
        (setq ed (entget (ssname ss i)))
        (setq et (cdr (assoc 0 ed)))
        (setq h  (cdr (assoc 5 ed)))
        (cond

          ((= kind "POLY")
            (cond
              ((= et "LWPOLYLINE")
                (setq closed (= 1 (logand 1 (cdr (assoc 70 ed)))))
                (setq verts  (cdr (assoc 90 ed)))
                (if (not closed)
                  (setq errs (cons (strcat "[" lay "] OPEN polyline - must be CLOSED (handle " h ")") errs)))
                (if (< verts 3)
                  (setq errs (cons (strcat "[" lay "] degenerate polyline, <3 vertices (handle " h ")") errs)))
              )
              ((= et "TEXT")
                (if (not (member lay *kcheck-text-ok-layers*))
                  (setq errs (cons (strcat "[" lay "] unexpected TEXT (handle " h ")") errs))))
              ((= et "MTEXT")
                (setq errs (cons (strcat "[" lay "] MTEXT forbidden - use plain TEXT (handle " h ")") errs)))
              ((member et '("INSERT" "IMAGE" "WIPEOUT"))
                (setq errs (cons (strcat "[" lay "] " et " forbidden on PINAKAS I layers (§4.5.1: no blocks/images) (handle " h ")") errs)))
              ((member et '("POLYLINE" "LINE" "SPLINE" "ELLIPSE" "CIRCLE" "ARC" "HATCH"))
                (setq errs (cons (strcat "[" lay "] " et " not allowed - use closed LWPolyline (handle " h ")") errs)))
            )
          )

          ((= kind "LINE")
            (cond
              ((= et "LWPOLYLINE")
                (if (= 1 (logand 1 (cdr (assoc 70 ed))))
                  (setq errs (cons (strcat "[" lay "] CLOSED polyline - change line must be OPEN (handle " h ")") errs))))
              ((= et "LINE")
                (setq errs (cons (strcat "[" lay "] LINE entity - spec wants open LWPolyline (handle " h ")") errs)))
              (T
                (setq errs (cons (strcat "[" lay "] " et " not allowed (handle " h ")") errs)))
            )
          )

          ((= kind "TEXTONLY")
            (cond
              ((= et "TEXT") nil)
              ((= et "MTEXT")
                (setq errs (cons (strcat "[" lay "] MTEXT forbidden - use plain TEXT (handle " h ")") errs)))
              (T
                (setq errs (cons (strcat "[" lay "] " et " unexpected - layer holds TEXT labels only (handle " h ")") errs)))
            )
          )

          ((= kind "MIXED")
            (if (= et "MTEXT")
              (setq errs (cons (strcat "[" lay "] MTEXT forbidden - use plain TEXT (handle " h ")") errs)))
          )
        )
      )
    )
  )
  errs
)

;;; KCHECK - Validate current drawing against a diagram profile
(defun c:KCHECK (/ p prof choice errors warnings lay n grp)
  (princ "\n=== KCHECK - Ktimatologio diagram validator ===")
  (princ "\n  1 TD ektos sxediou            2 TD entos sxediou")
  (princ "\n  3 DGM katatmhshs              4 DGM synenwshs")
  (princ "\n  5 DGM systashs douleias       6 DGM systashs kathetwn")
  (princ "\n  7 DGM katatm.+kathetwn        8 DGM katarghshs kathetwn")
  (princ "\n  9 DGM diorthwshs oriwn       10 DGM diorthwshs kathetwn")
  (princ "\n 11 DGM diorthwshs douleias    12 DGM eswterikou polygwnou")
  (princ "\n 13 TDGM diorthwshs oriwn      14 TDGM metaforas theshs")
  (princ "\n 15 TDGM neou gewtemaxiou")
  (setq choice (getint "\nSelect profile [1-15]: "))
  (setq prof (assoc choice *kcheck-profiles*))

  (if (not prof)
    (princ "\nInvalid profile.")
    (progn
      (princ (strcat "\nChecking as: " (nth 1 prof) " ...\n"))
      (setq errors nil warnings nil)

      ;; 1. Required layers: must exist and contain entities
      (foreach lay (nth 2 prof)
        (if (= 0 (kcheck:count lay nil))
          (setq errors (cons (strcat "[" lay "] REQUIRED layer missing or empty") errors))))

      ;; 2. Any-groups: at least one layer of each group must have entities
      (foreach grp (nth 3 prof)
        (setq n 0)
        (foreach lay grp (setq n (+ n (kcheck:count lay nil))))
        (if (= 0 n)
          (setq errors (cons (strcat "At least one of ("
                                     (car grp)
                                     (if (cadr grp) (strcat " / " (cadr grp)) "")
                                     ") must have entities") errors))))

      ;; 3. Forbidden layers: must be empty
      (foreach lay (nth 4 prof)
        (if (> (kcheck:count lay nil) 0)
          (setq errors (cons (strcat "[" lay "] FORBIDDEN for this profile but contains entities") errors))))

      ;; 4. Recommended layers: warn if empty
      (foreach lay (nth 5 prof)
        (if (= 0 (kcheck:count lay nil))
          (setq warnings (cons (strcat "[" lay "] recommended but empty (add if applicable)") warnings))))

      ;; 5. Entity-level checks.
      ;; CRITICAL layers (geometry/finals/change lines) -> ERRORS.
      ;; Presentation layers (BLD, OT, ROAD, DBOUND_*) -> WARNINGS: spec
      ;; deviations, but field-verified that the official validator has
      ;; accepted files with them (KHD issued) — flag, don't fail.
      (foreach lay *kcheck-poly-layers*
        (if (= lay "BLD")
          (setq warnings (append (kcheck:scan lay "POLY") warnings))
          (setq errors (append (kcheck:scan lay "POLY") errors))))
      (foreach lay *kcheck-line-layers*
        (setq errors (append (kcheck:scan lay "LINE") errors)))
      (foreach lay *kcheck-textonly-layers*
        (setq warnings (append (kcheck:scan lay "TEXTONLY") warnings)))
      (foreach lay *kcheck-mixed-layers*
        (setq warnings (append (kcheck:scan lay "MIXED") warnings)))

      ;; 6. PST_KAEK label presence: polylines without any KAEK TEXT
      (if (and (> (kcheck:count "PST_KAEK" "LWPOLYLINE") 0)
               (= 0 (kcheck:count "PST_KAEK" "TEXT")))
        (setq errors (cons "[PST_KAEK] polygons exist but no KAEK TEXT label found" errors)))

      ;; 7. Official §4.5.2 layer pairings (teyxos v1.3)
      (if (and (> (kcheck:count "LINE_XM" nil) 0)
               (= 0 (kcheck:count "DGM_PROP_FINAL" nil)))
        (setq errors (cons "[LINE_XM] present but DGM_PROP_FINAL empty (§4.5.2 pairing)" errors)))
      (if (and (> (kcheck:count "LINE_XM_VST" nil) 0)
               (= 0 (kcheck:count "VST_FINAL" nil)))
        (setq errors (cons "[LINE_XM_VST] present but VST_FINAL empty (§4.5.2 pairing)" errors)))
      (if (and (> (kcheck:count "VST_FINAL" nil) 0)
               (= 0 (kcheck:count "LINE_XM_VST" nil)))
        (setq errors (cons "[VST_FINAL] present but LINE_XM_VST empty (§4.5.2 pairing)" errors)))

      ;; 8. Profile-8 manual reminder (Greek layer name not checkable from LISP)
      (if (= choice 8)
        (setq warnings (cons "Layer 'KATHETES KTIMATOGRAFIKOU' (Greek name, official DXF examples) cannot be auto-checked - verify manually" warnings)))

      ;; ── Report ──────────────────────────────────────────────────────────
      (princ "\n------------------------------------------------")
      (if errors
        (progn
          (princ (strcat "\nERRORS (" (itoa (length errors)) "):"))
          (foreach e (reverse errors) (princ (strcat "\n  - " e)))
        )
        (princ "\nNo errors.")
      )
      (if warnings
        (progn
          (princ (strcat "\nWARNINGS (" (itoa (length warnings)) "):"))
          (foreach e (reverse warnings) (princ (strcat "\n  - " e)))
        )
      )
      (princ "\n------------------------------------------------")
      (princ (strcat "\nKCHECK verdict: "
                     (if errors "FAIL - fix errors before export/submission"
                                "PASS (layer & entity level)")))
      (if (not errors)
        (princ "\nNote: topology checks (snap, node preservation) are not covered yet."))
    )
  )
  (princ)
)
