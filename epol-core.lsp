;;; ==========================================================================
;;; epol-core.lsp - CORE - config, HTTP, parsing, layers, drawing & table primitives
;;; ==========================================================================
;;;
;;;   Shared foundation for every other module. Load first: it defines
;;;   *epol-api-url*, *qgis-root*, *epol-layers* and all epol: helpers.
;;;
;;; Part of EPOLEODOMIA GIS Tools v2.1. Do not load directly - load
;;; epoleodomia.lsp, which loads every module in the correct order.
;;; Contains 35 top-level forms.
;;; ==========================================================================

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
