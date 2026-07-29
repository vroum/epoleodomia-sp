;;; =============================================================================
;;; EPOLEODOMIA.LSP - GIS Tools for AutoCAD Civil 3D
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

(vl-load-com)

;;; =============================================================================
;;; CONFIGURATION
;;; =============================================================================

(setq *epol-api-url* "http://127.0.0.1:8000")

;;; GDAL paths - auto-detected from QGIS installation
;;; Searches "C:\Program Files\QGIS *" for the newest version
(defun epol:find-qgis (/ base dirs best best-ver dir ver)
  (setq base "C:\\Program Files")
  (setq dirs (vl-directory-files base "QGIS *" -1))
  (setq best nil best-ver "")
  (foreach dir dirs
    (setq ver (substr dir 6)) ; strip "QGIS " prefix
    (if (> ver best-ver)
      (setq best-ver ver  best dir)
    )
  )
  (if best
    (strcat base "\\" best)
    nil
  )
)

(setq *qgis-root* (epol:find-qgis))
(if *qgis-root*
  (progn
    (setq *gdal-path* (strcat *qgis-root* "\\bin\\"))
    (setq *gdal-translate* (strcat *gdal-path* "gdal_translate.exe"))
    (setq *gdal-warp* (strcat *gdal-path* "gdalwarp.exe"))
    (princ (strcat "\nQGIS found: " *qgis-root*))
  )
  (princ "\nWarning: QGIS not found in Program Files. GDAL commands will not work.")
)

;;; Layer configuration: (layer-name . color-number)
(setq *epol-layers*
  '(("EPOL_KAEK"        . 4)    ; Cyan - main KAEK parcel
    ("EPOL_KAEK_NB"     . 8)    ; Gray - neighbor parcels
    ("EPOL_OT"          . 4)    ; Cyan - building blocks
    ("EPOL_OT_NB"       . 8)    ; Gray - neighbor blocks
    ("EPOL_KAEK_OP"     . 2)    ; Yellow - operating cadastre parcel
    ("EPOL_KAEK_OP_NB"  . 8)    ; Gray - operating cadastre neighbors
    ("EPOL_KAEK_DX"     . 6)    ; Magenta - δουλείες / αποκλειστικές χρήσεις
    ("EPOL_ARCHEO"      . 30)   ; Orange - archaeology
    ("EPOL_RASTER"      . 7)    ; White - rasters
    ("EPOL_CLIP"        . 6)    ; Magenta - clip boundaries
    ("EPOL_TEXT"        . 7)    ; White - text annotations
    ("EPOL_TABLE"       . 7)    ; White - table borders + data text
    ("EPOL_TABLE_HDR"   . 4)    ; Cyan  - table title/header text
    ("EPOL_KAEK_TXT"    . 7)    ; White - KAEK labels
  )
)

;;; =============================================================================
;;; HTTP UTILITIES
;;; =============================================================================

;;; Make HTTP GET request using WinHttp
;;; Returns response body as string, or nil on error
(defun epol:http-get (url / http response status err-result resp-body)
  (setq response nil)
  (setq http (vl-catch-all-apply 'vlax-create-object '("WinHttp.WinHttpRequest.5.1")))

  (if (and http (not (vl-catch-all-error-p http)))
    (progn
      ;; Open connection (synchronous)
      (setq err-result (vl-catch-all-apply 'vlax-invoke-method (list http 'Open "GET" url :vlax-false)))
      (if (vl-catch-all-error-p err-result)
        (princ (strcat "\nOpen Error: " (vl-catch-all-error-message err-result)))
      )

      ;; Set timeout (10 seconds)
      (vl-catch-all-apply 'vlax-invoke-method (list http 'SetTimeouts 10000 10000 10000 10000))

      ;; Send request
      (setq err-result (vl-catch-all-apply 'vlax-invoke-method (list http 'Send)))
      (if (vl-catch-all-error-p err-result)
        (princ (strcat "\nSend Error: " (vl-catch-all-error-message err-result)))
      )

      ;; Check status
      (setq status (vl-catch-all-apply 'vlax-get-property (list http 'Status)))
      (if (and (not (vl-catch-all-error-p status)) (= status 200))
        (progn
          (setq response (vlax-get-property http 'ResponseText))
        )
        (progn
          (princ (strcat "\nHTTP Error: " (if (numberp status) (itoa status) "Connection failed")))
          (princ (strcat "\nURL: " url))
          ;; Try to get response body for error details
          (setq resp-body (vl-catch-all-apply 'vlax-get-property (list http 'ResponseText)))
          (if (and (not (vl-catch-all-error-p resp-body))
                   resp-body
                   (= (type resp-body) 'STR))
            (princ (strcat "\nServer says: " (if (> (strlen resp-body) 200) (substr resp-body 1 200) resp-body)))
          )
        )
      )
      (vlax-release-object http)
    )
    (princ "\nError: Could not create HTTP client. Is WinHttp available?")
  )
  response
)

;;; Make HTTP POST request (plain-text body). Returns response string or nil.
(defun epol:http-post (url body / http response status err-result resp-body)
  (setq response nil)
  (setq http (vl-catch-all-apply 'vlax-create-object '("WinHttp.WinHttpRequest.5.1")))
  (if (and http (not (vl-catch-all-error-p http)))
    (progn
      (setq err-result (vl-catch-all-apply 'vlax-invoke-method
                         (list http 'Open "POST" url :vlax-false)))
      (if (vl-catch-all-error-p err-result)
        (princ (strcat "\nOpen Error: " (vl-catch-all-error-message err-result))))
      (vl-catch-all-apply 'vlax-invoke-method
        (list http 'SetRequestHeader "Content-Type" "text/plain"))
      (vl-catch-all-apply 'vlax-invoke-method
        (list http 'SetTimeouts 10000 10000 30000 60000))
      (setq err-result (vl-catch-all-apply 'vlax-invoke-method (list http 'Send body)))
      (if (vl-catch-all-error-p err-result)
        (princ (strcat "\nSend Error: " (vl-catch-all-error-message err-result))))
      (setq status (vl-catch-all-apply 'vlax-get-property (list http 'Status)))
      (if (and (not (vl-catch-all-error-p status)) (= status 200))
        (setq response (vlax-get-property http 'ResponseText))
        (progn
          (princ (strcat "\nHTTP Error: " (if (numberp status) (itoa status) "Connection failed")))
          (setq resp-body (vl-catch-all-apply 'vlax-get-property (list http 'ResponseText)))
          (if (and (not (vl-catch-all-error-p resp-body)) resp-body (= (type resp-body) 'STR))
            (princ (strcat "\nServer says: "
                           (if (> (strlen resp-body) 200) (substr resp-body 1 200) resp-body))))
        )
      )
      (vlax-release-object http)
    )
    (princ "\nError: Could not create HTTP client.")
  )
  response
)

;;; Convert number to string with period decimal separator (locale-safe)
;;; This ensures URLs always use period regardless of system locale
(defun epol:num-to-str (num / str pos)
  (if (not (numberp num))
    (vl-princ-to-string num)
    (progn
      (setq str (rtos num 2 6))
      ;; Replace comma with period (for Greek/European locales)
      (setq pos (vl-string-search "," str))
      (while pos
        (setq str (vl-string-subst "." "," str))
        (setq pos (vl-string-search "," str))
      )
      str
    )
  )
)

;;; Build API URL with query parameters
;;; params is a list of (key . value) pairs
(defun epol:build-url (endpoint params / url first-param)
  (setq url (strcat *epol-api-url* endpoint))
  (setq first-param T)
  (foreach param params
    (if (cdr param)  ; Only add if value is not nil
      (progn
        (setq url (strcat url
                          (if first-param "?" "&")
                          (car param) "="
                          (if (numberp (cdr param))
                            (epol:num-to-str (cdr param))
                            (cdr param))))
        (setq first-param nil)
      )
    )
  )
  url
)

;;; =============================================================================
;;; JSON PARSING UTILITIES
;;; =============================================================================
;;; Note: Most endpoints use pipe-delimited /simple format.
;;; Only epol:extract-json-value is used (for raster download responses).

;;; =============================================================================
;;; COORDINATE PARSING
;;; =============================================================================

;;; Remove all carriage returns from string
(defun epol:remove-cr (str / pos)
  (while (setq pos (vl-string-search "\r" str))
    (setq str (strcat (substr str 1 pos) (substr str (+ pos 2))))
  )
  str
)

;;; Split string by delimiter, returns list of strings
(defun epol:split (str delim / result pos prev-pos part delim-len)
  (setq result nil)
  (setq prev-pos 0)
  (setq delim-len (strlen delim))
  (while (setq pos (vl-string-search delim str prev-pos))
    (setq part (substr str (1+ prev-pos) (- pos prev-pos)))
    (setq result (cons part result))
    (setq prev-pos (+ pos delim-len))
  )
  ;; Add last part
  (if (<= prev-pos (strlen str))
    (setq result (cons (substr str (1+ prev-pos)) result))
  )
  (reverse result)
)

;;; Parse simple coordinate string "x1,y1;x2,y2;x3,y3" into list of points
(defun epol:parse-coords (coord-str / result pairs pair comma-pos x y)
  (setq result nil)
  (if (and coord-str (> (strlen coord-str) 0))
    (progn
      (setq pairs (epol:split coord-str ";"))
      (foreach pair pairs
        (if (and pair (> (strlen pair) 0))
          (progn
            (setq comma-pos (vl-string-search "," pair))
            (if comma-pos
              (progn
                (setq x (atof (substr pair 1 comma-pos)))
                (setq y (atof (substr pair (+ comma-pos 2))))
                (setq result (cons (list x y) result))
              )
            )
          )
        )
      )
    )
  )
  (reverse result)
)

;;; =============================================================================
;;; LAYER MANAGEMENT
;;; =============================================================================

;;; Sanitize a string for use as layer name - keep only ASCII safe characters
;;; Removes Greek characters and other non-ASCII, keeps only A-Z, a-z, 0-9, _, -
(defun epol:sanitize-layer-name (name / result i char code safe-chars)
  (if (not name)
    ""
    (progn
      (setq result "")
      (setq i 1)
      (while (<= i (strlen name))
        (setq char (substr name i 1))
        (setq code (ascii char))
        ;; Keep only: A-Z (65-90), a-z (97-122), 0-9 (48-57), _ (95), - (45)
        (if (or (and (>= code 65) (<= code 90))   ; A-Z
                (and (>= code 97) (<= code 122))  ; a-z
                (and (>= code 48) (<= code 57))   ; 0-9
                (= code 95)                        ; _
                (= code 45))                       ; -
          (setq result (strcat result char))
        )
        (setq i (1+ i))
      )
      ;; If result is empty, return "UNKNOWN"
      (if (= result "")
        "UNKNOWN"
        result
      )
    )
  )
)

;;; Create layer if it doesn't exist, with specified color
(defun epol:make-layer (layer-name color-num / safe-name)
  ;; Sanitize layer name to avoid encoding issues
  (setq safe-name (epol:sanitize-layer-name layer-name))
  (if (not (tblsearch "LAYER" safe-name))
    (progn
      (command "_.LAYER" "_New" safe-name "_Color" (itoa color-num) safe-name "")
    )
  )
  safe-name
)

;;; Get or create a configured layer
(defun epol:get-layer (layer-key / layer-info)
  (setq layer-info (assoc layer-key *epol-layers*))
  (if layer-info
    (epol:make-layer (car layer-info) (cdr layer-info))
    (epol:make-layer layer-key 7)  ; Default to white
  )
)

;;; =============================================================================
;;; DRAWING UTILITIES
;;; =============================================================================


;;; Create MTEXT at a point with given content
;;; text-str uses \P for line breaks (MTEXT paragraph separator)
;;; Uses entmake to avoid MTEXT command width-point ambiguity
(defun epol:draw-text (point-pos text-str layer-name / text-height ins)
  (epol:get-layer layer-name)
  (setq text-height (/ (getvar "VIEWSIZE") 60.0))
  (setq ins (list (car point-pos) (cadr point-pos) 0.0))
  (entmake
    (list
      '(0 . "MTEXT")
      (cons 8  layer-name)
      '(100 . "AcDbEntity")
      '(100 . "AcDbMText")
      (cons 10 ins)               ; insertion point
      (cons 40 text-height)       ; text height
      (cons 41 0.0)               ; width 0 = no wrap
      (cons 71 1)                 ; attachment: top-left
      (cons 72 1)                 ; direction: left to right
      (cons 1  text-str)          ; content — \P for line breaks
    )
  )
)

;;; =============================================================================
;;; USER INPUT UTILITIES
;;; =============================================================================

;;; Get a point from user, returns (x y) or nil
(defun epol:get-point (prompt / pt)
  (setq pt (getpoint prompt))
  (if pt (list (car pt) (cadr pt)) nil)
)

;;; Get a bounding box from user (two corners)
;;; Returns ((minx miny) (maxx maxy)) or nil
(defun epol:get-bbox (prompt1 prompt2 / pt1 pt2 minx miny maxx maxy)
  (setq pt1 (getpoint prompt1))
  (if pt1
    (progn
      (setq pt2 (getcorner pt1 prompt2))
      (if pt2
        (progn
          (setq minx (min (car pt1) (car pt2)))
          (setq miny (min (cadr pt1) (cadr pt2)))
          (setq maxx (max (car pt1) (car pt2)))
          (setq maxy (max (cadr pt1) (cadr pt2)))
          (list (list minx miny) (list maxx maxy))
        )
        nil
      )
    )
    nil
  )
)

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

;;; Draw a closed polygon using entmake (LWPOLYLINE)
;;; Bypasses the command interpreter entirely — faster and more reliable
;;; than (command "_.PLINE") for large vertex counts.
(defun epol:draw-polygon (point-list layer-name / ent-data pt)
  (if (and point-list (> (length point-list) 2))
    (progn
      ;; Build entity data list: header + one (10 x y) pair per vertex
      (setq ent-data
        (list
          '(0  . "LWPOLYLINE")
          (cons 8  layer-name)          ; layer
          '(100 . "AcDbEntity")
          '(100 . "AcDbPolyline")
          (cons 90 (length point-list)) ; vertex count
          '(70 . 1)                     ; closed flag
          '(43 . 0.0)                   ; constant width
        )
      )
      ;; Append vertex group codes (10 = 2D point)
      (foreach pt point-list
        (setq ent-data
          (append ent-data
            (list (cons 10 (list (car pt) (cadr pt))))
          )
        )
      )
      (entmake ent-data)
      (entlast)
    )
    nil
  )
)

;;; Calculate simple centroid of polygon (average of vertices)
(defun epol:polygon-centroid (point-list / sum-x sum-y n)
  (setq sum-x 0.0 sum-y 0.0 n 0)
  (foreach pt point-list
    (setq sum-x (+ sum-x (car pt)))
    (setq sum-y (+ sum-y (cadr pt)))
    (setq n (1+ n))
  )
  (if (> n 0)
    (list (/ sum-x n) (/ sum-y n))
    nil
  )
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

;;; Ensure a linetype is loaded (from acadiso.lin); fall back to Continuous
(defun epol:ensure-ltype (lt / old)
  (if (not (tblsearch "LTYPE" lt))
    (progn
      (setq old (getvar "CMDECHO"))
      (setvar "CMDECHO" 0)
      (vl-catch-all-apply 'vl-cmdf (list "_.-LINETYPE" "_L" lt "acadiso.lin" ""))
      (setvar "CMDECHO" old)
    )
  )
  (if (tblsearch "LTYPE" lt) lt "Continuous")
)

;;; Create one official layer via entmake (no current-layer side effects)
(defun epol:make-klayer (name color lt)
  (if (not (tblsearch "LAYER" name))
    (entmake
      (list '(0 . "LAYER")
            '(100 . "AcDbSymbolTableRecord")
            '(100 . "AcDbLayerTableRecord")
            (cons 2 name)
            '(70 . 0)
            (cons 62 color)
            (cons 6 (epol:ensure-ltype lt))))
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

;;; Draw an OPEN LWPOLYLINE (for LINE_XM_VST change lines)
(defun epol:draw-open-pline (point-list layer-name / ent-data pt)
  (if (and point-list (> (length point-list) 1))
    (progn
      (setq ent-data
        (list '(0 . "LWPOLYLINE") (cons 8 layer-name)
              '(100 . "AcDbEntity") '(100 . "AcDbPolyline")
              (cons 90 (length point-list))
              '(70 . 0)                    ; OPEN
              '(43 . 0.0)))
      (foreach pt point-list
        (setq ent-data (append ent-data (list (cons 10 pt)))))
      (entmake ent-data)
    )
  )
)

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

;;; =============================================================================
;;; TABLE DRAWING HELPERS (used by ETABLE)
;;; =============================================================================

;;; Draw a closed rectangle (LWPOLYLINE) top-left (x1,y1) → bottom-right (x2,y2)
(defun epol:tbl-rect (x1 y1 x2 y2 layer-name)
  (entmake
    (list '(0 . "LWPOLYLINE") (cons 8 layer-name)
          '(100 . "AcDbEntity") '(100 . "AcDbPolyline")
          '(90 . 4) '(70 . 1) '(43 . 0.0)
          (cons 10 (list x1 y1))
          (cons 10 (list x2 y1))
          (cons 10 (list x2 y2))
          (cons 10 (list x1 y2))))
)

;;; Single-line TEXT, left-aligned, baseline at (x,y)
(defun epol:tbl-text (x y th text-str layer-name)
  (entmake
    (list '(0 . "TEXT")
          (cons 8  layer-name)
          (cons 10 (list x y 0.0))
          (cons 40 th)
          (cons 1  text-str)))
)

;;; Single-line TEXT that never overflows max-w: if the estimated string
;;; width (~0.6 x th per char) exceeds the cell, a width factor (DXF 41)
;;; compresses the glyphs to fit. Floor 0.45 to stay readable.
(defun epol:tbl-text-fit (x y th text-str max-w layer-name / est wf)
  (setq est (* (strlen text-str) th 0.60))
  (setq wf 1.0)
  (if (and (> est 0.0) (> est max-w))
    (setq wf (/ max-w est)))
  (if (< wf 0.45) (setq wf 0.45))
  (entmake
    (list '(0 . "TEXT")
          (cons 8  layer-name)
          (cons 10 (list x y 0.0))
          (cons 40 th)
          (cons 41 wf)
          (cons 1  text-str)))
)

;;; Single-line TEXT, horizontally + vertically centred at (x,y)
;;; Group 72=1 (centre), 73=2 (middle) — alignment point = group 11
(defun epol:tbl-text-ctr (x y th text-str layer-name)
  (entmake
    (list '(0 . "TEXT")
          (cons 8  layer-name)
          (cons 10 (list x y 0.0))   ; start point (ignored for justified text)
          (cons 11 (list x y 0.0))   ; alignment point
          (cons 40 th)
          (cons 1  text-str)
          (cons 72 1)                 ; horizontal: centre
          (cons 73 2)))               ; vertical:   middle
)

;;; MTEXT with word-wrap — used for long MERGED footnotes
;;; Subclass markers required for reliable entmake on all AutoCAD versions
(defun epol:tbl-mtext (x y w th text-str layer-name)
  (entmake
    (list '(0 . "MTEXT")
          (cons 8  layer-name)
          '(100 . "AcDbEntity")
          '(100 . "AcDbMText")
          (cons 10 (list x y 0.0))
          (cons 40 th)   ; text height
          (cons 41 w)    ; reference column width (wrap)
          (cons 71 1)    ; attachment: 1=top-left
          (cons 72 1)    ; drawing direction: left-to-right
          (cons 1  text-str)))
)

;;; =============================================================================
;;; TABLE DRAWING ENGINE — shared by ETABLE and EREPORT
;;; =============================================================================
;;; Parses TYPE|col1|col2 response and draws a ruled table at point pt.
;;; tw = model-space table width (m), th = text height (m)
(defun epol:draw-table-rows (response pt tw th
                              / pad cell-h hdr-h title-h merged-h col1-w
                                tx ty cur-y text-y cell-bot cx1
                                clean rows row parts rtype c1 c2)
  (setq pad      (* th 0.4))
  (setq cell-h   (* th 2.6))
  (setq hdr-h    (* th 2.0))
  (setq title-h  (* th 3.8))
  (setq merged-h (* th 4.5))
  (setq col1-w   (* tw 0.30))
  (setq tx    (car pt))
  (setq ty    (cadr pt))
  (setq cur-y ty)

  (setq clean (epol:remove-cr response))
  (setq rows  (epol:split clean "\n"))

  (foreach row rows
    (if (and row (> (strlen row) 2))
      (progn
        (setq parts (epol:split row "|"))
        (setq rtype (if parts (nth 0 parts) ""))
        (setq c1 (if (>= (length parts) 2) (nth 1 parts) ""))
        (setq c2 (if (>= (length parts) 3) (nth 2 parts) ""))

        (cond

          ((= rtype "TITLE")
            (setq cell-bot (- cur-y title-h))
            (epol:tbl-rect tx cur-y (+ tx tw) cell-bot "EPOL_TABLE")
            (epol:tbl-text-ctr
              (+ tx (/ tw 2.0)) (- cur-y (/ title-h 2.0))
              (* th 1.4) c1 "EPOL_TABLE_HDR")
            (if (and c2 (> (strlen c2) 0))
              (epol:tbl-text
                (+ tx pad) (- cur-y pad (* th 0.75))
                (* th 0.75) c2 "EPOL_TABLE_HDR"))
            (setq cur-y cell-bot))

          ((= rtype "HEADER")
            (setq cell-bot (- cur-y hdr-h))
            (epol:tbl-rect tx cur-y (+ tx tw) cell-bot "EPOL_TABLE")
            (epol:tbl-text-fit
              (+ tx pad) (- (/ (+ cur-y cell-bot) 2.0) (* th 0.42))
              (* th 0.85) c1 (- tw (* pad 2)) "EPOL_TABLE_HDR")
            (setq cur-y cell-bot))

          ((= rtype "ROW")
            (setq cell-bot (- cur-y cell-h))
            (setq cx1 (+ tx col1-w))
            (epol:tbl-rect tx  cur-y cx1       cell-bot "EPOL_TABLE")
            (epol:tbl-rect cx1 cur-y (+ tx tw) cell-bot "EPOL_TABLE")
            (setq text-y (- (/ (+ cur-y cell-bot) 2.0) (* th 0.40)))
            (if (and c1 (> (strlen c1) 0))
              (epol:tbl-text-fit (+ tx pad)  text-y (* th 0.80) c1
                                 (- col1-w (* pad 2)) "EPOL_TABLE"))
            (if (and c2 (> (strlen c2) 0))
              (epol:tbl-text-fit (+ cx1 pad) text-y (* th 0.80) c2
                                 (- (- tw col1-w) (* pad 2)) "EPOL_TABLE"))
            (setq cur-y cell-bot))

          ((= rtype "MERGED")
            (if (and c1 (> (strlen c1) 0))
              (progn
                (setq cell-bot (- cur-y merged-h))
                (epol:tbl-rect tx cur-y (+ tx tw) cell-bot "EPOL_TABLE")
                (epol:tbl-mtext
                  (+ tx pad) (- cur-y pad)
                  (- tw (* pad 2)) (* th 0.72)
                  c1 "EPOL_TABLE")
                (setq cur-y cell-bot))))

        ) ; end cond
      )
    )
  ) ; end foreach

  ;; Return total height drawn
  (- ty cur-y)
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

;;; =============================================================================
;;; ETABLE — Building regulations table
;;; =============================================================================
;;; Persistent scale memory across ETABLE calls (global)
(if (not *epol-tbl-scale*)   (setq *epol-tbl-scale*   500))
(if (not *epol-tbl-width*)   (setq *epol-tbl-width*    80))

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

;;; =============================================================================
;;; RASTER COMMANDS
;;; =============================================================================

;;; FEK - Load planning diagram rasters
;;; Uses /rasters/fek/simple endpoint which returns pipe-delimited data:
;;; path|fek_display|fek_ascii|scale|rms|source
;;; source: LOCAL (file on disk) or URL (needs download from TEE)
(defun c:FEK (/ bbox url response lines line-data
                rpath fek-display fek-ascii scale rms source
                count loaded-list table-pt fek-layer-name
                url-list local-path download-url download-response)
  (princ "\n=== Planning Diagram Rasters (FEK) ===")
  (princ "\nSelect area to load rasters...")

  (setq bbox (epol:get-bbox "\nPick first corner: " "\nPick opposite corner: "))
  (if bbox
    (progn
      ;; Use simple endpoint for better encoding handling
      (setq url (epol:build-url "/rasters/fek/simple"
                  (list (cons "minx" (caar bbox))
                        (cons "miny" (cadar bbox))
                        (cons "maxx" (caadr bbox))
                        (cons "maxy" (cadadr bbox)))))

      (princ "\nContacting API...")
      (setq response (epol:http-get url))

      (if response
        (progn
          ;; Parse simple pipe-delimited response
          (setq response (epol:remove-cr response))
          (setq lines (epol:split response "\n"))
          (setq count 0)
          (setq loaded-list nil)
          (setq url-list nil)

          ;; Process each line: path|fek_display|fek_ascii|scale|rms|source
          (foreach line lines
            (if (and line (> (strlen line) 0))
              (progn
                (setq line-data (epol:split line "|"))
                (if (>= (length line-data) 6)
                  (progn
                    (setq rpath (nth 0 line-data))
                    (setq fek-display (nth 1 line-data))
                    (setq fek-ascii (nth 2 line-data))
                    (setq scale (if (and (nth 3 line-data) (/= (nth 3 line-data) ""))
                                  (atof (nth 3 line-data))
                                  nil))
                    (setq rms (if (and (nth 4 line-data) (/= (nth 4 line-data) ""))
                                (atof (nth 4 line-data))
                                nil))
                    (setq source (nth 5 line-data))

                    ;; Create layer name from ASCII-safe FEK
                    (setq fek-layer-name nil)
                    (if (and fek-ascii (/= fek-ascii ""))
                      (setq fek-layer-name (strcat "R_FEK_"
                                             (vl-string-translate "/" "_"
                                               (vl-string-translate " " "_" fek-ascii))))
                    )

                    ;; Check source type
                    (if (= source "LOCAL")
                      (progn
                        ;; Load local raster
                        (if (epol:load-raster rpath "FEK" fek-layer-name)
                          (progn
                            (setq count (1+ count))
                            (setq loaded-list (cons (list fek-ascii scale rms) loaded-list))
                          )
                        )
                      )
                      ;; URL source - try to download first
                      (progn
                        (princ (strcat "\n  Downloading from TEE: " (vl-filename-base rpath) "..."))
                        (setq download-url (epol:build-url "/rasters/fek/download"
                                             (list (cons "url" rpath))))
                        (setq download-response (epol:http-get download-url))
                        (if (and download-response
                                 (vl-string-search "downloaded" download-response))
                          (progn
                            ;; Extract local path from response and load
                            (setq local-path (epol:extract-json-value download-response "path"))
                            (if (and local-path (epol:load-raster local-path "FEK" fek-layer-name))
                              (progn
                                (setq count (1+ count))
                                (setq loaded-list (cons (list fek-ascii scale rms) loaded-list))
                              )
                            )
                          )
                          (progn
                            ;; Download failed, add to URL list for reference
                            (setq url-list (cons (list fek-ascii rpath) url-list))
                            (princ " FAILED")
                          )
                        )
                      )
                    )
                  )
                )
              )
            )
          )

          ;; Display summary
          (princ (strcat "\n\nLoaded " (itoa count) " rasters."))

          ;; Report any URLs that failed to download
          (if url-list
            (progn
              (princ (strcat "\n" (itoa (length url-list)) " rasters could not be downloaded:"))
              (foreach item url-list
                (princ (strcat "\n  " (car item) ": " (cadr item)))
              )
            )
          )

          ;; Ask user where to place table
          (if loaded-list
            (progn
              (setq table-pt (getpoint "\nPick insertion point for FEK table: "))
              (if table-pt
                (epol:create-fek-table (reverse loaded-list) table-pt)
                (princ "\nTable cancelled.")
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

;;; Extract a value from simple JSON response
;;; json-str: JSON string like {"status": "downloaded", "path": "C:\\..."}
;;; key: key to extract (e.g., "path")
(defun epol:extract-json-value (json-str key / start-pos end-pos value)
  (setq key (strcat "\"" key "\""))
  (setq start-pos (vl-string-search key json-str))
  (if start-pos
    (progn
      ;; Find the value after ": "
      (setq start-pos (vl-string-search "\"" json-str (+ start-pos (strlen key) 1)))
      (if start-pos
        (progn
          (setq start-pos (1+ start-pos))
          (setq end-pos (vl-string-search "\"" json-str start-pos))
          (if end-pos
            (setq value (substr json-str (1+ start-pos) (- end-pos start-pos)))
          )
        )
      )
    )
  )
  ;; Unescape backslashes
  (if value
    (vl-string-translate "\\\\" "\\" value)
    nil
  )
)

;;; Create FEK table in drawing
;;; data-list: list of (fek scale rms) tuples
;;; ins-pt: insertion point (x y)
(defun epol:create-fek-table (data-list ins-pt / row-height col-widths
                                         num-rows total-width x0 y0
                                         layer-name oldlayer oldcmdecho
                                         row col-x fek scale-str rms-str
                                         text-height)
  (if (and data-list ins-pt)
    (progn
      ;; Table dimensions (in drawing units)
      (setq text-height (/ (getvar "VIEWSIZE") 80.0))
      (setq row-height (* text-height 1.8))
      (setq col-widths (list (* text-height 12) (* text-height 6) (* text-height 5)))  ; FEK, Scale, RMS
      (setq total-width (apply '+ col-widths))
      (setq num-rows (1+ (length data-list)))  ; +1 for header

      (setq x0 (car ins-pt))
      (setq y0 (cadr ins-pt))

      ;; Setup layer
      (setq layer-name (epol:get-layer "EPOL_TEXT"))
      (setq oldlayer (getvar "CLAYER"))
      (setq oldcmdecho (getvar "CMDECHO"))
      (setvar "CLAYER" layer-name)
      (setvar "CMDECHO" 0)

      ;; Draw table grid
      (epol:draw-table-grid x0 y0 col-widths row-height num-rows)

      ;; Add header row
      (epol:add-table-text x0 y0 (nth 0 col-widths) row-height "FEK" text-height)
      (epol:add-table-text (+ x0 (nth 0 col-widths)) y0 (nth 1 col-widths) row-height "Scale" text-height)
      (epol:add-table-text (+ x0 (nth 0 col-widths) (nth 1 col-widths)) y0 (nth 2 col-widths) row-height "RMS" text-height)

      ;; Add data rows
      (setq row 1)
      (foreach info data-list
        (setq fek (if (car info) (car info) "-"))
        (setq scale-str (if (cadr info)
                          (strcat "1:" (itoa (fix (cadr info))))
                          "-"))
        (setq rms-str (if (caddr info)
                        (rtos (caddr info) 2 2)
                        "-"))

        (setq col-x x0)
        (epol:add-table-text col-x (- y0 (* row row-height)) (nth 0 col-widths) row-height fek text-height)
        (setq col-x (+ col-x (nth 0 col-widths)))
        (epol:add-table-text col-x (- y0 (* row row-height)) (nth 1 col-widths) row-height scale-str text-height)
        (setq col-x (+ col-x (nth 1 col-widths)))
        (epol:add-table-text col-x (- y0 (* row row-height)) (nth 2 col-widths) row-height rms-str text-height)

        (setq row (1+ row))
      )

      ;; Restore settings
      (setvar "CLAYER" oldlayer)
      (setvar "CMDECHO" oldcmdecho)

      (princ "\nFEK table created.")
    )
  )
)

;;; Draw table grid lines
(defun epol:draw-table-grid (x0 y0 col-widths row-height num-rows /
                              total-width total-height i col-x)
  (setq total-width (apply '+ col-widths))
  (setq total-height (* num-rows row-height))

  ;; Horizontal lines
  (setq i 0)
  (while (<= i num-rows)
    (command "_.LINE"
             (list x0 (- y0 (* i row-height)))
             (list (+ x0 total-width) (- y0 (* i row-height)))
             "")
    (setq i (1+ i))
  )

  ;; Vertical lines
  (setq col-x x0)
  (command "_.LINE" (list col-x y0) (list col-x (- y0 total-height)) "")
  (foreach w col-widths
    (setq col-x (+ col-x w))
    (command "_.LINE" (list col-x y0) (list col-x (- y0 total-height)) "")
  )
)

;;; Add text to a table cell (centered) using MTEXT for Unicode support
(defun epol:add-table-text (x y cell-width cell-height txt text-height /
                             center-x center-y)
  (setq center-x (+ x (/ cell-width 2.0)))
  (setq center-y (- y (/ cell-height 2.0)))

  ;; Use MTEXT for better Greek character support
  (command "_.MTEXT" (list center-x center-y) "_H" text-height "_J" "MC" "_W" "0" txt "")
)

;;; Parse raster info (fek, scale, rms) from JSON response
;;; Returns list of (fek scale rms) tuples
(defun epol:parse-rasters-info (json-str / result rasters-start pos fek scale rms
                                          fek-start fek-end scale-start rms-start
                                          num-val next-obj-pos)
  (setq result nil)
  (setq rasters-start (vl-string-search "\"rasters\":" json-str))
  (if rasters-start
    (progn
      (setq pos rasters-start)
      ;; Find each raster object and extract fek, scale, rms
      (while (setq pos (vl-string-search "\"fek\":" json-str pos))
        (setq fek nil scale nil rms nil)

        ;; Find the end of this object (next { or end of array)
        (setq next-obj-pos (vl-string-search "},{" json-str pos))
        (if (not next-obj-pos) (setq next-obj-pos (+ pos 500)))

        ;; Extract fek (string value)
        (setq fek-start (vl-string-search "\"" json-str (+ pos 6)))
        (if fek-start
          (progn
            (setq fek-end (vl-string-search "\"" json-str (1+ fek-start)))
            (if fek-end
              (setq fek (substr json-str (+ fek-start 2) (- fek-end fek-start 1)))
            )
          )
        )

        ;; Extract scale (numeric value) - search within this object only
        (setq scale-start (vl-string-search "\"scale\":" json-str pos))
        (if (and scale-start (< scale-start next-obj-pos))
          (progn
            (setq num-val (epol:extract-json-number json-str (+ scale-start 8)))
            (if num-val (setq scale num-val))
          )
        )

        ;; Extract rms (numeric value) - search within this object only
        (setq rms-start (vl-string-search "\"rms\":" json-str pos))
        (if (and rms-start (< rms-start next-obj-pos))
          (progn
            (setq num-val (epol:extract-json-number json-str (+ rms-start 6)))
            (if num-val (setq rms num-val))
          )
        )

        (if fek
          (setq result (cons (list fek scale rms) result))
        )
        (setq pos (1+ pos))
      )
    )
  )
  (reverse result)
)

;;; Extract a numeric value from JSON starting at position
;;; Returns the number or nil if not found/null
(defun epol:extract-json-number (json-str start-pos / i char num-str result)
  (setq i start-pos)
  (setq num-str "")

  ;; Skip whitespace and colon if present
  (while (and (< i (strlen json-str))
              (member (substr json-str (1+ i) 1) '(" " "\t" ":")))
    (setq i (1+ i))
  )

  ;; Check for null
  (if (= (substr json-str (1+ i) 4) "null")
    (setq result nil)
    (progn
      ;; Collect number characters
      (setq char (substr json-str (1+ i) 1))
      (while (and (< i (strlen json-str))
                  (or (and (>= (ascii char) 48) (<= (ascii char) 57))  ; 0-9
                      (= char ".")
                      (= char "-")
                      (= char "+")
                      (= char "e")
                      (= char "E")))
        (setq num-str (strcat num-str char))
        (setq i (1+ i))
        (setq char (substr json-str (1+ i) 1))
      )

      (if (> (strlen num-str) 0)
        (setq result (atof num-str))
        (setq result nil)
      )
    )
  )
  result
)

;;; DJI - Load drone orthophotos
(defun c:DJI (/ bbox url response paths count)
  (princ "\n=== DJI Drone Orthophotos ===")
  (princ "\nSelect area to load drone imagery...")

  (setq bbox (epol:get-bbox "\nPick first corner: " "\nPick opposite corner: "))
  (if bbox
    (progn
      (setq url (epol:build-url "/rasters/dji"
                  (list (cons "minx" (caar bbox))
                        (cons "miny" (cadar bbox))
                        (cons "maxx" (caadr bbox))
                        (cons "maxy" (cadadr bbox)))))

      (princ "\nContacting API...")
      (setq response (epol:http-get url))

      (if response
        (progn
          (setq paths (epol:parse-paths response))
          (setq count 0)

          (foreach rpath paths
            (if (epol:load-raster rpath "DJI" nil)
              (setq count (1+ count))
            )
          )

          (princ (strcat "\nLoaded " (itoa count) " orthophotos."))
        )
        (princ "\nError: Could not retrieve data.")
      )
    )
    (princ "\nCancelled.")
  )
  (princ)
)

;;; Parse paths array from JSON response
(defun epol:parse-paths (json-str / paths-start paths-end paths-str path-list
                                    current-pos quote-start quote-end current-path)
  (setq path-list nil)

  ;; Find "paths" array
  (setq paths-start (vl-string-search "\"paths\"" json-str))
  (if paths-start
    (progn
      (setq paths-start (vl-string-search "[" json-str paths-start))
      (if paths-start
        (progn
          (setq paths-end (vl-string-search "]" json-str paths-start))
          (if paths-end
            (progn
              (setq paths-str (substr json-str (+ paths-start 2) (- paths-end paths-start 1)))

              ;; Parse quoted strings
              (setq current-pos 0)
              (while (setq quote-start (vl-string-search "\"" paths-str current-pos))
                (setq quote-end (vl-string-search "\"" paths-str (1+ quote-start)))
                (if quote-end
                  (progn
                    (setq current-path (substr paths-str (+ quote-start 2) (- quote-end quote-start 1)))
                    (if (and current-path (/= current-path ""))
                      (setq path-list (cons current-path path-list))
                    )
                    (setq current-pos (1+ quote-end))
                  )
                  (setq current-pos (1+ (strlen paths-str)))
                )
              )
            )
          )
        )
      )
    )
  )
  (reverse path-list)
)

;;; Load a single raster file
;;; rpath: full path to raster file
;;; raster-type: prefix for layer naming (FEK, DJI, DE, CLIP)
;;; custom-layer: optional - if provided, use this as layer name instead of auto-generating
(defun epol:load-raster (rpath raster-type custom-layer / rpath-win layer-name img-name
                                             lastent newent oldcmdecho oldfdia img-obj)
  ;; Fix path format
  (setq rpath-win (vl-string-translate "/" "\\" rpath))
  (while (vl-string-search "\\\\" rpath-win)
    (setq rpath-win (vl-string-subst "\\" "\\\\" rpath-win))
  )

  (setq img-name (vl-filename-base rpath-win))

  ;; Use custom layer name if provided, otherwise generate from filename
  (if (and custom-layer (> (strlen custom-layer) 0))
    (setq layer-name custom-layer)
    (setq layer-name (strcat "R_" raster-type "_" (vl-string-translate " " "_" img-name)))
  )

  (if (findfile rpath-win)
    (progn
      (princ (strcat "\n  Loading: " img-name))

      ;; Create layer
      (epol:make-layer layer-name 7)

      ;; Remember last entity
      (setq lastent (entlast))

      ;; Suppress dialogs
      (setq oldcmdecho (getvar "CMDECHO"))
      (setq oldfdia (getvar "FILEDIA"))
      (setvar "CMDECHO" 0)
      (setvar "FILEDIA" 0)

      ;; Insert raster
      (command "_.MAPIINSERT" rpath-win "N")

      ;; Restore settings
      (setvar "FILEDIA" oldfdia)
      (setvar "CMDECHO" oldcmdecho)

      ;; Move to layer and enable transparency for DJI
      (setq newent (entlast))
      (if (not (equal lastent newent))
        (progn
          (command "_.CHPROP" newent "" "_Layer" layer-name "")

          ;; Enable transparency for DJI rasters
          (if (= raster-type "DJI")
            (progn
              (setq img-obj (vlax-ename->vla-object newent))
              (if img-obj
                (vl-catch-all-apply 'vla-put-Transparency (list img-obj :vlax-true))
              )
            )
          )
          (princ " OK")
          T
        )
        (progn
          (princ " FAILED")
          nil
        )
      )
    )
    (progn
      (princ (strcat "\n  NOT FOUND: " rpath-win))
      nil
    )
  )
)

;;; DE - Load DE (Diagramma Efarmogis) rasters
(defun c:DE (/ bbox url response paths count)
  (princ "\n=== DE Rasters (Diagramma Efarmogis) ===")
  (princ "\nSelect area to load DE rasters...")

  (setq bbox (epol:get-bbox "\nPick first corner: " "\nPick opposite corner: "))
  (if bbox
    (progn
      (setq url (epol:build-url "/rasters/de"
                  (list (cons "minx" (caar bbox))
                        (cons "miny" (cadar bbox))
                        (cons "maxx" (caadr bbox))
                        (cons "maxy" (cadadr bbox)))))

      (princ "\nContacting API...")
      (setq response (epol:http-get url))

      (if response
        (progn
          (setq paths (epol:parse-paths response))
          (setq count 0)

          (foreach rpath paths
            (if (epol:load-raster rpath "DE" nil)
              (setq count (1+ count))
            )
          )

          (princ (strcat "\nLoaded " (itoa count) " DE rasters."))
        )
        (princ "\nError: Could not retrieve data.")
      )
    )
    (princ "\nCancelled.")
  )
  (princ)
)

;;; CLIPR - Clip raster to selected area
(defun c:CLIPR (/ bbox output-dir ss i ent layer-name img-path rasters
                  minx miny maxx maxy clip-path cmd-str result)
  (princ "\n=== Clip Raster to Area ===")

  ;; Check if drawing is saved
  (if (= (getvar "DWGPREFIX") "")
    (progn
      (princ "\n*** Please save your drawing first! ***")
      (princ "\n    Clipped rasters will be saved in the drawing folder.")
      (princ)
    )
    (progn
      (princ "\nSelect rasters to clip, then define clip area...")

      ;; Select rasters
      (setq ss (ssget '((0 . "IMAGE"))))

      (if ss
        (progn
          ;; Get clip area
          (setq bbox (epol:get-bbox "\nPick first corner of clip area: "
                                    "\nPick opposite corner: "))

          (if bbox
            (progn
              (setq minx (caar bbox))
              (setq miny (cadar bbox))
              (setq maxx (caadr bbox))
              (setq maxy (cadadr bbox))
              (setq output-dir (getvar "DWGPREFIX"))

              ;; Draw clip boundary
              (epol:make-layer "EPOL_CLIP" 6)
              (epol:draw-polygon (list (list minx miny) (list maxx miny)
                                       (list maxx maxy) (list minx maxy))
                                "EPOL_CLIP")

              ;; Process each selected raster
              (setq i 0)
              (while (< i (sslength ss))
                (setq ent (ssname ss i))
                (setq img-path (epol:get-image-path ent))

                (if (and img-path (/= img-path ""))
                  (progn
                    (setq clip-path (strcat output-dir
                                           (vl-filename-base img-path)
                                           "_clip.tif"))

                    (princ (strcat "\n  Clipping: " (vl-filename-base img-path)))

                    ;; Build GDAL command
                    (setq cmd-str (strcat
                                    "\"" *gdal-translate* "\""
                                    " -projwin " (rtos minx 2 6) " " (rtos maxy 2 6)
                                    " " (rtos maxx 2 6) " " (rtos miny 2 6)
                                    " -of GTiff"
                                    " \"" img-path "\""
                                    " \"" clip-path "\""))

                    ;; Execute
                    (setq result (epol:run-gdal cmd-str))

                    (if (and result (findfile clip-path))
                      (progn
                        (epol:load-raster clip-path "CLIP" nil)
                        (princ " OK")
                      )
                      (princ " FAILED")
                    )
                  )
                )
                (setq i (1+ i))
              )

              (princ "\nClipping complete.")
            )
            (princ "\nCancelled - no clip area defined.")
          )
        )
        (princ "\nNo rasters selected.")
      )
    )
  )
  (princ)
)

;;; Get image file path from IMAGE entity
(defun epol:get-image-path (ent / ent-data img-def-ename img-def-obj img-path)
  (setq ent-data (entget ent))
  (setq img-def-ename (cdr (assoc 340 ent-data)))
  (if img-def-ename
    (progn
      (setq img-def-obj (vl-catch-all-apply 'vlax-ename->vla-object (list img-def-ename)))
      (if (and img-def-obj (not (vl-catch-all-error-p img-def-obj)))
        (progn
          (setq img-path (vl-catch-all-apply 'vla-get-ImageFile (list img-def-obj)))
          (if (vl-catch-all-error-p img-path) "" img-path)
        )
        ""
      )
    )
    ""
  )
)

;;; Run GDAL command with QGIS environment
(defun epol:run-gdal (cmd-str / wsh result exit-code full-cmd qgis-root)
  (setq qgis-root *qgis-root*)
  (setq full-cmd (strcat
                   "set PATH=" qgis-root "\\bin;%PATH% && "
                   "set GDAL_DATA=" qgis-root "\\share\\gdal && "
                   "set PROJ_LIB=" qgis-root "\\share\\proj && "
                   cmd-str))

  (setq wsh (vl-catch-all-apply 'vlax-create-object '("WScript.Shell")))

  (if (and wsh (not (vl-catch-all-error-p wsh)))
    (progn
      (setq result (vl-catch-all-apply
                     'vlax-invoke-method
                     (list wsh 'Run (strcat "cmd /c " full-cmd) 0 :vlax-true)))
      (vlax-release-object wsh)

      (if (vl-catch-all-error-p result)
        nil
        (= result 0)
      )
    )
    nil
  )
)

;;; =============================================================================
;;; UTILITY COMMANDS
;;; =============================================================================

;;; ETRANS - Enable transparency on drone rasters
(defun c:ETRANS (/ ss i ent layer-name img-obj count)
  (princ "\n=== Enable Raster Transparency ===")

  (setq count 0)
  (setq ss (ssget "_X" '((0 . "IMAGE"))))

  (if ss
    (progn
      (setq i 0)
      (while (< i (sslength ss))
        (setq ent (ssname ss i))
        (setq layer-name (cdr (assoc 8 (entget ent))))

        ;; Only DJI rasters
        (if (wcmatch layer-name "R_DJI_*")
          (progn
            (setq img-obj (vlax-ename->vla-object ent))
            (if img-obj
              (progn
                (vl-catch-all-apply 'vla-put-Transparency (list img-obj :vlax-true))
                (setq count (1+ count))
              )
            )
          )
        )
        (setq i (1+ i))
      )
      (princ (strcat "\nEnabled transparency on " (itoa count) " rasters."))
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
  (princ "\n EPOLEODOMIA GIS TOOLS v2.0")
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

;;; =============================================================================
;;; LOAD MESSAGE
;;; =============================================================================

(princ "\n")
(princ "\n========================================")
(princ "\n EPOLEODOMIA GIS TOOLS v2.0 LOADED")
(princ "\n========================================")
(princ "\n Type EHELP for command list")
(princ "\n API: http://127.0.0.1:8000")
(princ "\n========================================")
(princ "\n")
(princ)
