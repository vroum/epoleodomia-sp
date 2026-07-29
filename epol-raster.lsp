;;; ==========================================================================
;;; epol-raster.lsp - RASTERS - planning diagrams, drone orthophotos, GDAL clipping
;;; ==========================================================================
;;;
;;;   FEK DJI DE CLIPR
;;;
;;; Part of EPOLEODOMIA GIS Tools v2.1. Do not load directly - load
;;; epoleodomia.lsp, which loads every module in the correct order.
;;; Contains 9 top-level forms.
;;; ==========================================================================

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

;;; =============================================================================
;;; ERASTER - generic sheet loader (sp_geodata.raster_sheets / v_all_rasters)
;;; =============================================================================
;;; Loads locally georeferenced map sheets: GYS 1:5000, aigialos diagrams,
;;; historic plans, and - through the same view - the FEK / DJI / DE
;;; collections. Registered by ingest_rasters.py.
;;;
;;; Why this exists alongside FEK/DJI/DE: those three query three different
;;; tables with three different schemas. This one queries v_all_rasters, so a
;;; new collection needs no new command.
;;;
;;; Two things it does that the older commands do not:
;;;   - filters on role, so a 1:200000 index sheet with 288 m RMS never lands
;;;     on top of your drawing unless you ask for it by name
;;;   - returns finest scale first, which is the correct draw order
;;;
;;; Layer naming: R_<COLLECTION>_<doc_ref>, ASCII-transliterated server side.

(setq *eraster-collection* "ALL")   ; remembered between calls

(defun c:ERASTER (/ bbox inp url response lines line parts
                    rpath coll docref scale rms role
                    lay count skipped roles)

  (princ "\n=== Raster Sheets ===")

  ;; --- which collection --------------------------------------------------
  (princ (strcat "\nCollection [ALL/gys5000/aigialos/historic/fek/dji/de] <"
                 *eraster-collection* ">: "))
  (setq inp (getstring))
  (if (/= inp "") (setq *eraster-collection* inp))
  (setq coll *eraster-collection*)

  ;; --- which roles -------------------------------------------------------
  (initget "Working All Context Historical")
  (setq inp (getkword
              "\nRole [Working/Context/Historical/All] <Working>: "))
  (setq roles
    (cond
      ((= inp "All")        "working,context,historical")
      ((= inp "Context")    "context")
      ((= inp "Historical") "historical")
      (T                    "working")
    )
  )

  (princ "\nSelect area to load sheets...")
  (setq bbox (epol:get-bbox "\nPick first corner: " "\nPick opposite corner: "))

  (if (null bbox)
    (princ "\nCancelled.")
    (progn
      (setq url (epol:build-url "/rasters/sheets/simple"
                  (append
                    (list (cons "minx" (caar bbox))
                          (cons "miny" (cadar bbox))
                          (cons "maxx" (caadr bbox))
                          (cons "maxy" (cadadr bbox)))
                    (list (cons "role" roles))
                    (if (/= (strcase coll) "ALL")
                      (list (cons "collection" coll))
                    )
                  )))

      (princ "\nContacting API...")
      (setq response (epol:http-get url))

      (if (null response)
        (princ "\nError: could not retrieve data. Is the API running?")
        (progn
          (setq response (epol:remove-cr response))
          (setq lines (epol:split response "\n"))
          (setq count 0  skipped 0)

          ;; path|collection|doc_ref_ascii|scale|rms|role
          (foreach line lines
            (if (and line (> (strlen line) 0))
              (progn
                (setq parts (epol:split line "|"))
                (if (>= (length parts) 6)
                  (progn
                    (setq rpath  (nth 0 parts)
                          coll   (nth 1 parts)
                          docref (nth 2 parts)
                          scale  (nth 3 parts)
                          rms    (nth 4 parts)
                          role   (nth 5 parts))

                    (setq lay (strcat "R_" (strcase coll)))
                    (if (and docref (/= docref ""))
                      (setq lay (strcat lay "_"
                                  (vl-string-translate "/" "_"
                                    (vl-string-translate " " "_" docref))))
                    )

                    (princ (strcat "\n  " (strcase coll)
                             (if (and scale (/= scale "")) (strcat "  1:" scale) "")
                             (if (and rms (/= rms "")) (strcat "  RMS " rms "m") "")
                             (if (/= role "working") (strcat "  [" role "]") "")))

                    (if (epol:load-raster rpath coll lay)
                      (setq count (1+ count))
                      (progn
                        (setq skipped (1+ skipped))
                        (princ "   <- FAILED to attach")
                      )
                    )
                  )
                  (setq skipped (1+ skipped))
                )
              )
            )
          )

          (princ (strcat "\n\nLoaded " (itoa count) " sheet(s)"))
          (if (> skipped 0)
            (princ (strcat ", " (itoa skipped) " failed/skipped")))
          (if (= count 0)
            (princ (strcat "\nNothing matched. Try Role=All, or check that "
                           "ingest_rasters.py has registered the collection.")))
          (princ ".")
        )
      )
    )
  )
  (princ)
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
