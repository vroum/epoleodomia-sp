;;; ==========================================================================
;;; epol-bounds.lsp - BOUNDARIES - cadastral parcels & building blocks
;;; ==========================================================================
;;;
;;;   KAEK EKAEK OT EOBT KAEK_OP
;;;
;;; Part of EPOLEODOMIA GIS Tools v2.1. Do not load directly - load
;;; epoleodomia.lsp, which loads every module in the correct order.
;;; Contains 5 top-level forms.
;;; ==========================================================================

;;; =============================================================================
;;; BOUNDARY COMMANDS
;;; =============================================================================

;;; KAEK - Cadastral parcel with neighbors
(defun c:KAEK (/ pt url response)
  (princ "\n=== KAEK Number ===")

  (setq pt (epol:get-point "\nPick point inside parcel: "))
  (if pt
    (progn
      ;; Get only KAEK number (no geometry)
      (setq url (epol:build-url "/kaek/number"
                  (list (cons "x" (car pt)) (cons "y" (cadr pt)))))

      (setq response (epol:http-get url))

      (if response
        (progn
          (setq response (vl-string-trim "\r\n " response))
          (if (= response "NOT_FOUND")
            (princ "\nNo KAEK parcel found at this location.")
            (progn
              (princ (strcat "\nKAEK: " response))
              ;; Draw KAEK number as text at picked point
              (epol:get-layer "EPOL_KAEK")
              (entmake
                (list
                  '(0 . "TEXT")
                  (cons 8 "EPOL_KAEK")
                  (cons 10 pt)
                  (cons 40 2.0)
                  (cons 1 response)
                  (cons 72 1)
                  (cons 11 pt)
                  (cons 73 2)
                )
              )
            )
          )
        )
        (princ "\nError: Could not retrieve data.")
      )
    )
    (princ "\nCancelled.")
  )
  (princ)
)

;;; EKAEK - Draw KAEK parcel polygon + neighbors (1η Ανάρτηση)
;;; Click point → inline API response → parse and draw
;;; Format: OK|kaek|area_m2|perim_m, MAIN|coords, NB|coords
(defun c:EKAEK (/ pt url response clean lines header-parts
                 kaek-num area-val perim-val
                 count-nb count-dx centroid label-text line coords
                 dx-parts dx-num dx-ctr)
  (princ "\n=== KAEK Parcels (1η Αναρτηση) ===")
  (princ "\nClick inside a parcel to draw it + neighbors...")

  (setq pt (epol:get-point "\nPick point inside parcel: "))
  (if pt
    (progn
      (setq url (epol:build-url "/kaek/simple"
                  (list (cons "x" (car pt)) (cons "y" (cadr pt)))))

      (princ "\nContacting API...")
      (setq response (epol:http-get url))

      (if (and response (> (strlen response) 0))
        (progn
          (setq clean (epol:remove-cr response))
          (setq lines (epol:split clean "\n"))

          ;; First line: OK|kaek|area_m2|perimeter_m
          (setq header-parts (epol:split (car lines) "|"))

          (if (and header-parts (= (car header-parts) "OK"))
            (progn
              (setq kaek-num  (nth 1 header-parts))
              (setq area-val  (nth 2 header-parts))
              (setq perim-val (nth 3 header-parts))

              (princ (strcat "\n  KAEK: " kaek-num
                             "  E=" area-val "m2"
                             "  P=" perim-val "m"))

              ;; Ensure layers exist (colors from *epol-layers* config)
              (epol:get-layer "EPOL_KAEK")
              (epol:get-layer "EPOL_KAEK_NB")
              (epol:get-layer "EPOL_KAEK_TXT")
              (epol:get-layer "EPOL_KAEK_DX")

              (setq count-nb 0)
              (setq count-dx 0)
              (setq centroid nil)

              ;; Process MAIN / NB / AX (αποκλ. χρήση) / DX (δουλεία) lines
              (foreach line (cdr lines)
                (if (and line (> (strlen line) 3))
                  (progn
                    (cond
                      ((= (substr line 1 5) "MAIN|")
                        (setq coords (epol:parse-coords (substr line 6)))
                        (if coords
                          (progn
                            (epol:draw-polygon coords "EPOL_KAEK")
                            ;; Only set centroid for the first (largest) ring
                            (if (not centroid)
                              (setq centroid (epol:polygon-centroid coords))
                            )
                          )
                        )
                      )
                      ((= (substr line 1 3) "NB|")
                        (setq coords (epol:parse-coords (substr line 4)))
                        (if coords
                          (progn
                            (epol:draw-polygon coords "EPOL_KAEK_NB")
                            (setq count-nb (1+ count-nb))
                          )
                        )
                      )
                      ((or (= (substr line 1 3) "AX|") (= (substr line 1 3) "DX|"))
                        ;; AX|num|coords / DX|num|coords
                        (setq dx-parts (epol:split (substr line 4) "|"))
                        (if (>= (length dx-parts) 2)
                          (progn
                            (setq dx-num  (nth 0 dx-parts))
                            (setq coords  (epol:parse-coords (nth 1 dx-parts)))
                            (if coords
                              (progn
                                (epol:draw-polygon coords "EPOL_KAEK_DX")
                                (setq dx-ctr (epol:polygon-centroid coords))
                                (if dx-ctr
                                  (epol:draw-text dx-ctr
                                    ;; Latin "AX"/"D" — Greek literals in LISP
                                    ;; strings break (UTF-8 file vs ANSI loader)
                                    (strcat (if (= (substr line 1 3) "AX|") "AX " "D ")
                                            dx-num)
                                    "EPOL_KAEK_DX"))
                                (setq count-dx (1+ count-dx))
                              )
                            )
                          )
                        )
                      )
                    )
                  )
                )
              )

              ;; Label at centroid
              (if centroid
                (progn
                  (setq label-text
                    (strcat "KAEK: " kaek-num
                            "\\PE: " area-val " m2"
                            "\\PP: " perim-val " m"))
                  (epol:draw-text centroid label-text "EPOL_KAEK_TXT")
                )
              )

              (princ (strcat "\n\nDrawn KAEK " kaek-num " + " (itoa count-nb) " neighbors"))
              (if (> count-dx 0)
                (princ (strcat "\n  + " (itoa count-dx)
                               " rights polygons AX/D (layer EPOL_KAEK_DX)")))
            )
            (princ "\nNo cadastral parcel found at this location.")
          )
        )
        (princ "\nError: Could not retrieve data.")
      )
    )
    (princ "\nCancelled.")
  )
  (princ)
)

;;; OT - Building block number (same style as KAEK)
(defun c:OT (/ pt url response ot-num ot-text)
  (princ "\n=== O.T. Number ===")

  (setq pt (epol:get-point "\nPick point inside building block: "))
  (if pt
    (progn
      ;; Get only OT number (no geometry)
      (setq url (epol:build-url "/ot/number"
                  (list (cons "x" (car pt)) (cons "y" (cadr pt)))))

      (setq response (epol:http-get url))

      (if response
        (progn
          (setq response (vl-string-trim "\r\n " response))
          (if (= response "NOT_FOUND")
            (princ "\nNo building block found at this location.")
            (progn
              (setq ot-num response)
              (princ (strcat "\nO.T. " ot-num))

              ;; Draw O.T. number as text at picked point (same as KAEK)
              (epol:make-layer "EPOL_OT" 7)  ; White
              (setq ot-text (strcat "O.T. " ot-num))
              (entmake
                (list
                  '(0 . "TEXT")
                  (cons 8 "EPOL_OT")
                  (cons 10 pt)
                  (cons 40 2.0)       ; same height as KAEK
                  (cons 1 ot-text)
                  (cons 72 1)         ; center
                  (cons 11 pt)
                  (cons 73 2)         ; middle
                )
              )
            )
          )
        )
        (princ "\nError: Could not retrieve data.")
      )
    )
    (princ "\nCancelled.")
  )
  (princ)
)

;;; EOBT - Draw OT (building block) polygon + neighbors
;;; Response format from /ot/simple:
;;;   OK|ot_num|fek|area_m2|perimeter_m
;;;   MAIN|x1,y1;x2,y2;...
;;;   NB|x1,y1;x2,y2;...   (one line per neighbor)
(defun c:EOBT (/ pt url response clean lines header-parts
                ot-num fek-val area-val perim-val
                count-nb centroid label-text line prefix coords)
  (princ "\n=== O.T. Polygons ===")
  (princ "\nClick inside a building block to draw it + neighbors...")

  (setq pt (epol:get-point "\nPick point inside building block: "))
  (if pt
    (progn
      (setq url (epol:build-url "/ot/simple"
                  (list (cons "x" (car pt)) (cons "y" (cadr pt)))))

      (princ "\nContacting API...")
      (setq response (epol:http-get url))

      (if (and response (> (strlen response) 0))
        (progn
          (setq clean (epol:remove-cr response))
          (setq lines (epol:split clean "\n"))

          ;; First line: OK|ot_num|fek|area_m2|perimeter_m
          (setq header-parts (epol:split (car lines) "|"))

          (if (and header-parts (= (car header-parts) "OK"))
            (progn
              (setq ot-num   (nth 1 header-parts))
              (setq fek-val  (nth 2 header-parts))
              (setq area-val (nth 3 header-parts))
              (setq perim-val (nth 4 header-parts))

              (princ (strcat "\n  O.T.: " ot-num))
              (if (and fek-val (> (strlen fek-val) 0))
                (princ (strcat "  ΦΕΚ: " fek-val))
              )

              ;; Ensure layers exist (colors from *epol-layers* config)
              (epol:get-layer "EPOL_OT")
              (epol:get-layer "EPOL_OT_NB")

              (setq count-nb 0)
              (setq centroid nil)

              ;; Process MAIN and NB lines
              (foreach line (cdr lines)
                (if (and line (> (strlen line) 3))
                  (progn
                    (setq prefix (substr line 1 5))

                    (cond
                      ;; Main OT polygon
                      ((= (substr line 1 5) "MAIN|")
                        (setq coords (epol:parse-coords (substr line 6)))
                        (if coords
                          (progn
                            (epol:draw-polygon coords "EPOL_OT")
                            (setq centroid (epol:polygon-centroid coords))
                          )
                        )
                      )
                      ;; Neighbor OT polygon
                      ((= (substr line 1 3) "NB|")
                        (setq coords (epol:parse-coords (substr line 4)))
                        (if coords
                          (progn
                            (epol:draw-polygon coords "EPOL_OT_NB")
                            (setq count-nb (1+ count-nb))
                          )
                        )
                      )
                    )
                  )
                )
              )

              ;; Label at centroid
              (if centroid
                (progn
                  (setq label-text
                    (strcat "O.T. " ot-num
                            "\\PE: " area-val " m2"
                            "\\PP: " perim-val " m"))
                  (epol:draw-text centroid label-text "EPOL_TEXT")
                )
              )

              (princ (strcat "\n\nDrawn O.T. " ot-num " + " (itoa count-nb) " neighbors"))
            )
            ;; ERROR response
            (princ (strcat "\nNo building block found at this location."))
          )
        )
        (princ "\nError: Could not retrieve data.")
      )
    )
    (princ "\nCancelled.")
  )
  (princ)
)

;;; KAEK_OP - Draw operating cadastre parcel + neighbors
;;; Uses /kaek/operating — data from sp_geodata.kaek_parcels_operating
;;; (Hellenic Cadastre λειτουργία, synced from AGOL)
;;; Response format:
;;;   OK|kaek|area_m2|perimeter_m|main_use
;;;   MAIN|x1,y1;x2,y2;...
;;;   NB|x1,y1;x2,y2;...
(defun c:KAEK_OP (/ pt url response clean lines header-parts
                   kaek-num area-val perim-val main-use
                   count-nb count-dx centroid label-text line coords
                   dx-parts dx-num dx-ctr)
  (princ "\n=== KAEK Operating Cadastre ===")
  (princ "\nClick inside a parcel to draw it + neighbors (operating cadastre)...")

  (setq pt (epol:get-point "\nPick point inside parcel: "))
  (if pt
    (progn
      (setq url (epol:build-url "/kaek/operating"
                  (list (cons "x" (car pt)) (cons "y" (cadr pt)))))

      (princ "\nContacting API...")
      (setq response (epol:http-get url))

      (if (and response (> (strlen response) 0))
        (progn
          (setq clean (epol:remove-cr response))
          (setq lines (epol:split clean "\n"))

          ;; First line: OK|kaek|area_m2|perimeter_m|main_use
          (setq header-parts (epol:split (car lines) "|"))

          (if (and header-parts (= (car header-parts) "OK"))
            (progn
              (setq kaek-num  (nth 1 header-parts))
              (setq area-val  (nth 2 header-parts))
              (setq perim-val (nth 3 header-parts))
              (setq main-use  (nth 4 header-parts))

              (princ (strcat "\n  KAEK (op): " kaek-num))
              (if (and main-use (> (strlen main-use) 0))
                (princ (strcat "  Use: " main-use))
              )

              ;; Ensure layers exist (colors from *epol-layers* config)
              (epol:get-layer "EPOL_KAEK_OP")
              (epol:get-layer "EPOL_KAEK_OP_NB")
              (epol:get-layer "EPOL_KAEK_DX")

              (setq count-nb 0)
              (setq count-dx 0)
              (setq centroid nil)

              ;; Process MAIN / NB / AX (αποκλ. χρήση) / DX (δουλεία) lines
              (foreach line (cdr lines)
                (if (and line (> (strlen line) 3))
                  (progn
                    (cond
                      ((= (substr line 1 5) "MAIN|")
                        (setq coords (epol:parse-coords (substr line 6)))
                        (if coords
                          (progn
                            (epol:draw-polygon coords "EPOL_KAEK_OP")
                            ;; Only set centroid for the first (largest) ring
                            (if (not centroid)
                              (setq centroid (epol:polygon-centroid coords))
                            )
                          )
                        )
                      )
                      ((= (substr line 1 3) "NB|")
                        (setq coords (epol:parse-coords (substr line 4)))
                        (if coords
                          (progn
                            (epol:draw-polygon coords "EPOL_KAEK_OP_NB")
                            (setq count-nb (1+ count-nb))
                          )
                        )
                      )
                      ((or (= (substr line 1 3) "AX|") (= (substr line 1 3) "DX|"))
                        ;; AX|num|coords / DX|num|coords
                        (setq dx-parts (epol:split (substr line 4) "|"))
                        (if (>= (length dx-parts) 2)
                          (progn
                            (setq dx-num  (nth 0 dx-parts))
                            (setq coords  (epol:parse-coords (nth 1 dx-parts)))
                            (if coords
                              (progn
                                (epol:draw-polygon coords "EPOL_KAEK_DX")
                                (setq dx-ctr (epol:polygon-centroid coords))
                                (if dx-ctr
                                  (epol:draw-text dx-ctr
                                    ;; Latin "AX"/"D" — Greek literals in LISP
                                    ;; strings break (UTF-8 file vs ANSI loader)
                                    (strcat (if (= (substr line 1 3) "AX|") "AX " "D ")
                                            dx-num)
                                    "EPOL_KAEK_DX"))
                                (setq count-dx (1+ count-dx))
                              )
                            )
                          )
                        )
                      )
                    )
                  )
                )
              )

              ;; Label at centroid
              (if centroid
                (progn
                  (setq label-text
                    (strcat "KAEK(op): " kaek-num
                            "\\PE: " area-val " m2"
                            "\\PP: " perim-val " m"))
                  (if (and main-use (> (strlen main-use) 0))
                    (setq label-text (strcat label-text "\\P" main-use))
                  )
                  (epol:draw-text centroid label-text "EPOL_TEXT")
                )
              )

              (princ (strcat "\n\nDrawn KAEK(op) " kaek-num " + " (itoa count-nb) " neighbors"))
              (if (> count-dx 0)
                (princ (strcat "\n  + " (itoa count-dx)
                               " rights polygons AX/D (layer EPOL_KAEK_DX)")))
            )
            (princ "\nNo operating cadastre parcel found at this location.")
          )
        )
        (princ "\nError: Could not retrieve data.")
      )
    )
    (princ "\nCancelled.")
  )
  (princ)
)
