;;; ==========================================================================
;;; epol-site.lsp - SITE ANALYSIS - building regulations & environmental constraints
;;; ==========================================================================
;;;
;;;   OROITABLE ETABLE EREPORT ENOTES ARCHEO CHURCH NATURA AIGIALOS REMATA
;;;
;;; Part of EPOLEODOMIA GIS Tools v2.1. Do not load directly - load
;;; epoleodomia.lsp, which loads every module in the correct order.
;;; Contains 12 top-level forms.
;;; ==========================================================================

;;; =============================================================================
;;; SITE ANALYSIS COMMANDS
;;; =============================================================================

;;; OROITABLE - Full building regulations table (like the AutoCAD table format)
;;; Displays comprehensive info: ΔΙΑΤΑΓΜΑΤΑ, ΚΑΤΑ ΚΑΝΟΝΑ per τομέας, ΕΓΚΡΙΣΕΙΣ,
;;; ΛΟΙΠΑ, ΛΟΙΠΟΙ ΠΕΡΙΟΡΙΣΜΟΙ, ΚΑΤΑ ΠΑΡΕΚΚΛΙΣΗ
(defun c:OROITABLE (/ pt url response)
  (princ "\n=== Full Building Regulations Table (Oroi Domisis) ===")

  (setq pt (epol:get-point "\nPick point to generate regulations table: "))
  (if pt
    (progn
      (princ (strcat "\nQuerying at: " (rtos (car pt) 2 2) ", " (rtos (cadr pt) 2 2)))

      ;; Use oroitable/text endpoint for full table
      (setq url (epol:build-url "/oroitable/text"
                  (list (cons "x" (car pt)) (cons "y" (cadr pt)))))

      (princ "\nContacting API...")
      (setq response (epol:http-get url))

      (if (and response (> (strlen response) 0))
        (progn
          ;; Print to command line (replace \P with newlines for readability)
          (princ "\n")
          (princ (vl-string-subst "\n" "\\P" response))
          ;; Draw MTEXT annotation at clicked point
          (epol:get-layer "EPOL_TEXT")
          (epol:draw-text pt response "EPOL_TEXT")
        )
        (princ "\nError: Could not retrieve data. Is the API server running?")
      )
    )
    (princ "\nCancelled.")
  )
  (princ)
)

;;; ARCHEO - Archaeological information
(defun c:ARCHEO (/ pt url response)
  (princ "\n=== Archaeological Sites ===")

  (setq pt (epol:get-point "\nPick point to check archaeology: "))
  (if pt
    (progn
      (princ (strcat "\nQuerying at: " (rtos (car pt) 2 2) ", " (rtos (cadr pt) 2 2)))

      (setq url (epol:build-url "/archeo/text"
                  (list (cons "x" (car pt)) (cons "y" (cadr pt)))))

      (princ "\nContacting API...")
      (setq response (epol:http-get url))

      (if (and response (> (strlen response) 0))
        (progn
          (princ "\n")
          (princ (vl-string-subst "\n" "\\P" response))
          (epol:get-layer "EPOL_TEXT")
          (epol:draw-text pt response "EPOL_TEXT")
        )
        (princ "\nError: Could not retrieve data. Is the API server running?")
      )
    )
    (princ "\nCancelled.")
  )
  (princ)
)

;;; CHURCH - Distance to closest church
(defun c:CHURCH (/ pt url response)
  (princ "\n=== Closest Church ===")

  (setq pt (epol:get-point "\nPick point to find closest church: "))
  (if pt
    (progn
      (setq url (epol:build-url "/church/text"
                  (list (cons "x" (car pt)) (cons "y" (cadr pt)))))
      (princ "\nContacting API...")
      (setq response (epol:http-get url))

      (if (and response (> (strlen response) 0))
        (progn
          (princ "\n")
          (princ (vl-string-subst "\n" "\\P" response))
          (epol:get-layer "EPOL_TEXT")
          (epol:draw-text pt response "EPOL_TEXT")
        )
        (princ "\nError: Could not retrieve data. Is the API server running?")
      )
    )
    (princ "\nCancelled.")
  )
  (princ)
)

;;; NATURA - Natura 2000 / forest information
(defun c:NATURA (/ pt url response)
  (princ "\n=== Natura 2000 & Forest Map ===")

  (setq pt (epol:get-point "\nPick point to check environmental restrictions: "))
  (if pt
    (progn
      (princ (strcat "\nQuerying at: " (rtos (car pt) 2 2) ", " (rtos (cadr pt) 2 2)))

      (setq url (epol:build-url "/natura/text"
                  (list (cons "x" (car pt)) (cons "y" (cadr pt)))))

      (princ "\nContacting API...")
      (setq response (epol:http-get url))

      (if (and response (> (strlen response) 0))
        (progn
          (princ "\n")
          (princ (vl-string-subst "\n" "\\P" response))
          (epol:get-layer "EPOL_TEXT")
          (epol:draw-text pt response "EPOL_TEXT")
        )
        (princ "\nError: Could not retrieve data. Is the API server running?")
      )
    )
    (princ "\nCancelled.")
  )
  (princ)
)

;;; ENOTES - Auto-filled ΠΑΡΑΤΗΡΗΣΕΙΣ for topographic diagrams (notary notes)
;;; Template: notes_template.txt next to api_server.py — edit wording there.
(defun c:ENOTES (/ pt ppt url response)
  (princ "\n=== Topographic Notes (PARATHRHSEIS) ===")

  (setq pt (epol:get-point "\nPick point inside the parcel: "))
  (if pt
    (progn
      (setq url (epol:build-url "/notes/parcel"
                  (list (cons "x" (car pt)) (cons "y" (cadr pt)))))
      (princ "\nContacting API...")
      (setq response (epol:http-get url))

      (if (and response (> (strlen response) 0))
        (if (= (substr response 1 6) "ERROR|")
          (princ (strcat "\n" response))
          (progn
            (setq ppt (epol:get-point "\nPick placement point for the notes: "))
            (if ppt
              (progn
                (epol:get-layer "EPOL_TEXT")
                (epol:draw-text ppt response "EPOL_TEXT")
                (princ "\nNotes placed. Fill in the ______ fields (symbolaio)")
                (princ "\nand review any ### ELEGXOS ### lines before printing.")
              )
              (princ "\nCancelled.")
            )
          )
        )
        (princ "\nError: Could not retrieve data. Is the API server running?")
      )
    )
    (princ "\nCancelled.")
  )
  (princ)
)

;;; AIGIALOS - Shoreline distance
(defun c:AIGIALOS (/ pt url response)
  (princ "\n=== Shoreline Distance (Aigialos) ===")

  (setq pt (epol:get-point "\nPick point to check shoreline distance: "))
  (if pt
    (progn
      (princ (strcat "\nQuerying at: " (rtos (car pt) 2 2) ", " (rtos (cadr pt) 2 2)))

      (setq url (epol:build-url "/aigialos/text"
                  (list (cons "x" (car pt)) (cons "y" (cadr pt)))))

      (princ "\nContacting API...")
      (setq response (epol:http-get url))

      (if response
        (progn
          (epol:make-layer "EPOL_TEXT" 7)
          (epol:draw-text pt response "EPOL_TEXT")
          (princ "\nShoreline info displayed.")
        )
        (princ "\nError: Could not retrieve data.")
      )
    )
    (princ "\nCancelled.")
  )
  (princ)
)

;;; REMATA - Stream/flood line information
(defun c:REMATA (/ pt url response)
  (princ "\n=== Streams & Flood Lines (Remata) ===")

  (setq pt (epol:get-point "\nPick point to check stream distances: "))
  (if pt
    (progn
      (princ (strcat "\nQuerying at: " (rtos (car pt) 2 2) ", " (rtos (cadr pt) 2 2)))

      (setq url (epol:build-url "/remata/text"
                  (list (cons "x" (car pt)) (cons "y" (cadr pt)))))

      (princ "\nContacting API...")
      (setq response (epol:http-get url))

      (if response
        (progn
          (epol:make-layer "EPOL_TEXT" 7)
          (epol:draw-text pt response "EPOL_TEXT")
          (princ "\nStream info displayed.")
        )
        (princ "\nError: Could not retrieve data.")
      )
    )
    (princ "\nCancelled.")
  )
  (princ)
)

;;; =============================================================================
;;; ETABLE / EREPORT — shared scale setup + query/draw workflow
;;; =============================================================================
;;; Persistent scale memory (global)
(if (not *epol-tbl-scale*)   (setq *epol-tbl-scale*   500))

(if (not *epol-tbl-width*)   (setq *epol-tbl-width*    80))

;;; Internal: ask for scale/width, compute tw+th, query URL, draw table
(defun epol:run-table-cmd (cmd-label api-url-path
                           / inp tw th qpt pt url response tbl-h)
  (princ (strcat "\n=== " cmd-label " ==="))

  (setq inp (getint (strcat "\nDrawing scale 1:<" (itoa *epol-tbl-scale*) ">: ")))
  (if inp (setq *epol-tbl-scale* inp))
  (setq inp (getreal (strcat "\nTable width on paper (mm) <" (rtos *epol-tbl-width* 2 0) ">: ")))
  (if inp (setq *epol-tbl-width* inp))

  (setq tw (* (/ *epol-tbl-width* 1000.0) *epol-tbl-scale*))
  (setq th (/ tw 50.0))
  (princ (strcat "\n  Model width: " (rtos tw 2 1)
                 " m   Text: " (rtos (* th 1000.0 (/ 1.0 *epol-tbl-scale*)) 2 1) " mm"))

  (setq qpt (epol:get-point "\nClick on plot to query: "))
  (if qpt
    (progn
      (setq url (epol:build-url api-url-path
                  (list (cons "x" (car qpt)) (cons "y" (cadr qpt)))))
      (princ "\nContacting API...")
      (setq response (epol:http-get url))

      (if (and response (> (strlen response) 0)
               (not (= (substr response 1 5) "ERROR")))
        (progn
          (epol:get-layer "EPOL_TABLE")
          (epol:get-layer "EPOL_TABLE_HDR")
          (setq pt (epol:get-point "\nClick to place table (top-left corner): "))
          (if pt
            (progn
              (setq tbl-h (epol:draw-table-rows response pt tw th))
              (princ (strcat "\nDone — " (rtos tbl-h 2 1) " m tall x " (rtos tw 2 1) " m wide."))
            )
            (princ "\nPlacement cancelled.")
          )
        )
        (princ "\nError: No data returned. Is the API server running?")
      )
    )
    (princ "\nCancelled.")
  )
  (princ)
)

(defun c:ETABLE ()
  (epol:run-table-cmd "Oroi Domisis Table" "/oroitable/rows")
)

;;; =============================================================================
;;; EREPORT — Full planning report table for the operating-cadastre parcel
;;;   Finds the λειτουργούν γεωτεμάχιο at the clicked point, then reports
;;;   distances measured from the PARCEL polygon (not the point) and
;;;   Natura/forest/archaeology as % of parcel overlap.
;;;   Building regulations stay at the clicked point.
;;; =============================================================================
(defun c:EREPORT ()
  (epol:run-table-cmd "Full Planning Report (Parcel)" "/report/parcel")
)
