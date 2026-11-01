-- Schema-only test fixture from the reviewed 2026-10-27 backup. No source rows.
--
-- PostgreSQL database dump
--


-- Dumped from database version 18.1 (Debian 18.1-1.pgdg13+2)
-- Dumped by pg_dump version 18.1 (Debian 18.1-1.pgdg13+2)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: find_rasters_at_point(numeric, numeric); Type: FUNCTION; Schema: epoleodomia; Owner: docker
--

CREATE FUNCTION epoleodomia.find_rasters_at_point(x_coord numeric, y_coord numeric) RETURNS TABLE(id integer, fek character varying, filename character varying, local_path character varying, resolution_m numeric)
    LANGUAGE plpgsql
    AS $$
BEGIN
    RETURN QUERY
    SELECT
        rc.id,
        rc.fek,
        rc.filename,
        rc.local_path_georef,
        rc.resolution_x
    FROM epoleodomia.raster_catalog rc
    WHERE rc.download_status = 'downloaded'
      AND rc.bbox IS NOT NULL
      AND ST_Contains(rc.bbox, ST_SetSRID(ST_MakePoint(x_coord, y_coord), 2100))
    ORDER BY rc.resolution_x;  -- Best resolution first
END;
$$;


ALTER FUNCTION epoleodomia.find_rasters_at_point(x_coord numeric, y_coord numeric) OWNER TO docker;

--
-- Name: oroi_domisis_at(public.geometry, numeric); Type: FUNCTION; Schema: epoleodomia; Owner: docker
--

CREATE FUNCTION epoleodomia.oroi_domisis_at(g public.geometry, min_overlap numeric DEFAULT 50.0) RETURNS TABLE(max_height_m numeric, num_orofon integer, height_fek character varying, height_pct numeric, synt_kalypsis numeric, coverage_fek character varying, coverage_pct numeric, syntelestis_domisis numeric, sd_tomeas character varying, sd_fek character varying, sd_source text, sd_pct numeric, elax_embado_m2 numeric, elax_prosop_m numeric, lot_fek character varying, lot_pct numeric, oik_systima character varying, system_fek character varying, xrisi_gen character varying, xrisi_eid character varying, land_use_pct numeric, zones_found integer, zones_accepted integer, best_pct numeric, worst_accepted_pct numeric, coverage_status text)
    LANGUAGE sql STABLE PARALLEL SAFE
    AS $_$
    WITH q AS (SELECT $1 AS g, ST_Area($1) AS a, $2 AS thr),
    h AS (SELECT x.max_height_m, x.num_orofon, x.fek,
                 round((100*ST_Area(ST_Intersection(x.geom,q.g))/NULLIF(q.a,0))::numeric,1) pct
          FROM q, epoleodomia.building_regs_height x
          WHERE ST_Intersects(x.geom,q.g) AND NOT COALESCE(x.is_deleted,false)
          ORDER BY ST_Area(ST_Intersection(x.geom,q.g)) DESC LIMIT 1),
    c AS (SELECT x.synt_kalypsis, x.fek,
                 round((100*ST_Area(ST_Intersection(x.geom,q.g))/NULLIF(q.a,0))::numeric,1) pct
          FROM q, epoleodomia.building_regs_coverage x
          WHERE ST_Intersects(x.geom,q.g) AND NOT COALESCE(x.is_deleted,false)
          ORDER BY ST_Area(ST_Intersection(x.geom,q.g)) DESC LIMIT 1),
    f AS (SELECT x.sd_timh, x.sd_tomeas, x.fek,
                 round((100*ST_Area(ST_Intersection(x.geom,q.g))/NULLIF(q.a,0))::numeric,1) pct
          FROM q, epoleodomia.building_regs_coefficient x
          WHERE ST_Intersects(x.geom,q.g) AND NOT COALESCE(x.is_deleted,false)
          ORDER BY ST_Area(ST_Intersection(x.geom,q.g)) DESC LIMIT 1),
    z AS (SELECT x.sd_timh, x.sd_tomeas, x.fek,
                 round((100*ST_Area(ST_Intersection(x.geom,q.g))/NULLIF(q.a,0))::numeric,1) pct
          FROM q, epoleodomia.building_regs_coefficient_zones x
          WHERE ST_Intersects(x.geom,q.g) AND NOT COALESCE(x.is_deleted,false)
          ORDER BY ST_Area(ST_Intersection(x.geom,q.g)) DESC LIMIT 1),
    l AS (SELECT x.elax_embado_m2, x.elax_prosop_m, x.fek,
                 round((100*ST_Area(ST_Intersection(x.geom,q.g))/NULLIF(q.a,0))::numeric,1) pct
          FROM q, epoleodomia.building_regs_lot x
          WHERE ST_Intersects(x.geom,q.g) AND NOT COALESCE(x.is_deleted,false)
            AND x.oros_type::text = 'ΚΑΤΑ ΚΑΝΟΝΑ'
          ORDER BY ST_Area(ST_Intersection(x.geom,q.g)) DESC LIMIT 1),
    s AS (SELECT x.oik_systima, x.fek,
                 round((100*ST_Area(ST_Intersection(x.geom,q.g))/NULLIF(q.a,0))::numeric,1) pct
          FROM q, epoleodomia.building_regs_system x
          WHERE ST_Intersects(x.geom,q.g) AND NOT COALESCE(x.is_deleted,false)
          ORDER BY ST_Area(ST_Intersection(x.geom,q.g)) DESC LIMIT 1),
    lu AS (SELECT x.per_cat_gen, x.per_cat_eid,
                 round((100*ST_Area(ST_Intersection(x.geom,q.g))/NULLIF(q.a,0))::numeric,1) pct
          FROM q, epoleodomia.land_uses_ers x
          WHERE ST_Intersects(x.geom,q.g) AND NOT COALESCE(x.is_deleted,false)
          ORDER BY ST_Area(ST_Intersection(x.geom,q.g)) DESC LIMIT 1),
    -- εντός/εκτός ορίου εγκεκριμένου σχεδίου (τα μεγάλα γενικά διατάγματα)
    plan AS (SELECT EXISTS (
               SELECT 1 FROM q, epoleodomia.approved_plan_boundaries a
               WHERE NOT COALESCE(a.is_deleted,false) AND ST_Area(a.geom) > 100000
                 AND ST_Intersects(ST_PointOnSurface(q.g), a.geom)) AS entos),
    agg AS (
      SELECT (SELECT thr FROM q) AS thr,
             ARRAY[ (SELECT pct FROM h), (SELECT pct FROM c), (SELECT pct FROM f),
                    (SELECT pct FROM l), (SELECT pct FROM s), (SELECT pct FROM lu) ] AS pcts
    ),
    m AS (
      SELECT thr,
             (SELECT count(*)::int FROM unnest(pcts) p WHERE p IS NOT NULL)             AS n_found,
             (SELECT count(*)::int FROM unnest(pcts) p WHERE p >= thr)                  AS n_ok,
             (SELECT max(p)        FROM unnest(pcts) p)                                 AS best,
             (SELECT min(p)        FROM unnest(pcts) p WHERE p >= thr)                  AS worst_ok
      FROM agg
    )
    SELECT
      CASE WHEN h.pct  >= m.thr THEN h.max_height_m END,
      CASE WHEN h.pct  >= m.thr THEN h.num_orofon   END,
      h.fek, h.pct,
      CASE WHEN c.pct  >= m.thr THEN c.synt_kalypsis END,
      c.fek, c.pct,
      CASE WHEN COALESCE(f.pct, z.pct) >= m.thr THEN COALESCE(f.sd_timh, z.sd_timh) END,
      CASE WHEN COALESCE(f.pct, z.pct) >= m.thr THEN COALESCE(f.sd_tomeas, z.sd_tomeas) END,
      COALESCE(f.fek, z.fek),
      CASE WHEN f.sd_timh IS NOT NULL THEN 'per_block'
           WHEN z.sd_timh IS NOT NULL THEN 'zone' END,
      COALESCE(f.pct, z.pct),
      CASE WHEN l.pct  >= m.thr THEN l.elax_embado_m2 END,
      CASE WHEN l.pct  >= m.thr THEN l.elax_prosop_m  END,
      l.fek, l.pct,
      CASE WHEN s.pct  >= m.thr THEN s.oik_systima END,
      s.fek,
      CASE WHEN lu.pct >= m.thr THEN lu.per_cat_gen END,
      CASE WHEN lu.pct >= m.thr THEN lu.per_cat_eid END,
      lu.pct,
      m.n_found, m.n_ok, m.best, m.worst_ok,
      CASE
        WHEN m.n_found = 0 AND NOT plan.entos
          THEN 'ΕΚΤΟΣ ΣΧΕΔΙΟΥ — καμία ζώνη στη βάση· ισχύει ΠΔ 24.5.1985 + κατά περίπτωση ΖΟΕ/αιγιαλός/δασικό. ΔΕΝ καλύπτεται από τα δεδομένα.'
        WHEN m.n_found = 0
          THEN 'ΕΝΤΟΣ ΣΧΕΔΙΟΥ αλλά ΚΑΜΙΑ ζώνη όρων — κενό δεδομένων, έλεγχος στο ΦΕΚ.'
        WHEN m.n_ok = 0
          THEN 'ΑΒΕΒΑΙΟ — καμία ζώνη πάνω από το κατώφλι (μέγιστη κάλυψη ' || m.best || '%). Καμία τιμή δεν δίνεται.'
        WHEN m.n_ok < m.n_found
          THEN 'ΜΕΡΙΚΟ — ' || m.n_ok || '/' || m.n_found || ' διαστάσεις πάνω από το κατώφλι· οι υπόλοιπες NULL.'
        WHEN m.worst_ok < 99
          THEN 'ΜΟΙΡΑΣΜΕΝΟ — πατά σε δύο ζώνες (ελάχιστη κάλυψη ' || m.worst_ok || '%), έλεγχος στο ΦΕΚ.'
        ELSE 'ΠΛΗΡΕΣ'
      END
    FROM m
    CROSS JOIN plan
    LEFT JOIN h  ON true LEFT JOIN c ON true LEFT JOIN f ON true
    LEFT JOIN z  ON true LEFT JOIN l ON true LEFT JOIN s ON true
    LEFT JOIN lu ON true;
$_$;


ALTER FUNCTION epoleodomia.oroi_domisis_at(g public.geometry, min_overlap numeric) OWNER TO docker;

--
-- Name: FUNCTION oroi_domisis_at(g public.geometry, min_overlap numeric); Type: COMMENT; Schema: epoleodomia; Owner: docker
--

COMMENT ON FUNCTION epoleodomia.oroi_domisis_at(g public.geometry, min_overlap numeric) IS 'v2 (29.08.2026). Όροι δόμησης στη θέση της γεωμετρίας (ΕΓΣΑ87/2100). Κάθε διάσταση επιλέγεται με μέγιστη επικάλυψη ΚΑΙ πρέπει να ξεπερνά το min_overlap (default 50%) — αλλιώς η τιμή είναι NULL. Το coverage_status εξηγεί ΠΑΝΤΑ γιατί: ΠΛΗΡΕΣ / ΜΟΙΡΑΣΜΕΝΟ / ΜΕΡΙΚΟ / ΑΒΕΒΑΙΟ / ΕΝΤΟΣ ΣΧΕΔΙΟΥ-κενό / ΕΚΤΟΣ ΣΧΕΔΙΟΥ. Η εκτός σχεδίου δόμηση (ΠΔ 24.5.1985) ΔΕΝ υπάρχει στα δεδομένα και δηλώνεται ρητά.';


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: ab_zones_attica; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.ab_zones_attica (
    id integer NOT NULL,
    objectid integer,
    zone_type character varying(50),
    zone_name character varying(255),
    geom public.geometry(Polygon,2100),
    fetched_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE epoleodomia.ab_zones_attica OWNER TO docker;

--
-- Name: ab_zones_attica_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.ab_zones_attica_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.ab_zones_attica_id_seq OWNER TO docker;

--
-- Name: ab_zones_attica_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.ab_zones_attica_id_seq OWNED BY epoleodomia.ab_zones_attica.id;


--
-- Name: addresses; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.addresses (
    id integer NOT NULL,
    objectid integer,
    addr character varying(108),
    num character varying(10),
    munic character varying(80),
    geom public.geometry(Point,2100),
    fetched_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone,
    is_deleted boolean DEFAULT false,
    deleted_at timestamp without time zone
);


ALTER TABLE epoleodomia.addresses OWNER TO docker;

--
-- Name: addresses_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.addresses_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.addresses_id_seq OWNER TO docker;

--
-- Name: addresses_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.addresses_id_seq OWNED BY epoleodomia.addresses.id;


--
-- Name: approved_plan_boundaries; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.approved_plan_boundaries (
    id integer NOT NULL,
    objectid integer,
    fek character varying(255),
    fek_file_url character varying(2000),
    publ_date character varying(10),
    apof_eidos character varying(255),
    title character varying(2000),
    number_ character varying(100),
    sign_date character varying(10),
    kall_dhm_name character varying(40),
    geom public.geometry(Geometry,2100),
    fetched_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone,
    is_deleted boolean DEFAULT false,
    deleted_at timestamp without time zone,
    apof_theme character varying
);


ALTER TABLE epoleodomia.approved_plan_boundaries OWNER TO docker;

--
-- Name: approved_plan_boundaries_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.approved_plan_boundaries_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.approved_plan_boundaries_id_seq OWNER TO docker;

--
-- Name: approved_plan_boundaries_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.approved_plan_boundaries_id_seq OWNED BY epoleodomia.approved_plan_boundaries.id;


--
-- Name: archaeological_sites_lines; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.archaeological_sites_lines (
    id integer NOT NULL,
    objectid integer,
    name character varying(500),
    ota character varying(500),
    foreas character varying(500),
    shape_len double precision,
    geom public.geometry(LineString,2100),
    fetched_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE epoleodomia.archaeological_sites_lines OWNER TO docker;

--
-- Name: archaeological_sites_lines_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.archaeological_sites_lines_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.archaeological_sites_lines_id_seq OWNER TO docker;

--
-- Name: archaeological_sites_lines_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.archaeological_sites_lines_id_seq OWNED BY epoleodomia.archaeological_sites_lines.id;


--
-- Name: archaeological_sites_points; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.archaeological_sites_points (
    id integer NOT NULL,
    objectid integer,
    name character varying(500),
    ota character varying(500),
    foreas character varying(500),
    geom public.geometry(Point,2100),
    fetched_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE epoleodomia.archaeological_sites_points OWNER TO docker;

--
-- Name: archaeological_sites_points_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.archaeological_sites_points_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.archaeological_sites_points_id_seq OWNER TO docker;

--
-- Name: archaeological_sites_points_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.archaeological_sites_points_id_seq OWNED BY epoleodomia.archaeological_sites_points.id;


--
-- Name: archaeological_sites_polygons; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.archaeological_sites_polygons (
    id integer NOT NULL,
    objectid integer,
    name character varying(500),
    ota character varying(500),
    foreas character varying(500),
    shape_area double precision,
    shape_len double precision,
    geom public.geometry(Polygon,2100),
    fetched_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone,
    is_deleted boolean DEFAULT false,
    deleted_at timestamp without time zone
);


ALTER TABLE epoleodomia.archaeological_sites_polygons OWNER TO docker;

--
-- Name: archaeological_sites_polygons_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.archaeological_sites_polygons_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.archaeological_sites_polygons_id_seq OWNER TO docker;

--
-- Name: archaeological_sites_polygons_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.archaeological_sites_polygons_id_seq OWNED BY epoleodomia.archaeological_sites_polygons.id;


--
-- Name: archaeological_zones_pl; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.archaeological_zones_pl (
    id integer NOT NULL,
    objectid integer,
    fek character varying(255),
    fek_file_url character varying(2000),
    publ_date character varying(10),
    zone_name character varying(255),
    zone_type character varying(255),
    apof_eidos character varying(255),
    title character varying(2000),
    number_ character varying(100),
    sign_date character varying(10),
    kall_dhm_name character varying(40),
    key_flag integer,
    geom public.geometry(Polygon,2100),
    fetched_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE epoleodomia.archaeological_zones_pl OWNER TO docker;

--
-- Name: archaeological_zones_pl_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.archaeological_zones_pl_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.archaeological_zones_pl_id_seq OWNER TO docker;

--
-- Name: archaeological_zones_pl_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.archaeological_zones_pl_id_seq OWNED BY epoleodomia.archaeological_zones_pl.id;


--
-- Name: block_vertices; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.block_vertices (
    id integer NOT NULL,
    objectid integer,
    fek character varying(255),
    fek_file_url character varying(2000),
    publ_date character varying(10),
    ot_koryf_name character varying(50),
    x_coord double precision,
    y_coord double precision,
    apof_eidos character varying(255),
    title character varying(2000),
    number_ character varying(100),
    sign_date character varying(10),
    georef_diagram_url character varying(2000),
    initial_diagram_url character varying(2000),
    kall_dhm_name character varying(40),
    key_flag integer,
    key_auto character varying(255),
    geom public.geometry(Point,2100),
    fetched_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone,
    is_deleted boolean DEFAULT false,
    deleted_at timestamp without time zone
);


ALTER TABLE epoleodomia.block_vertices OWNER TO docker;

--
-- Name: block_vertices_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.block_vertices_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.block_vertices_id_seq OWNER TO docker;

--
-- Name: block_vertices_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.block_vertices_id_seq OWNED BY epoleodomia.block_vertices.id;


--
-- Name: building_blocks; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.building_blocks (
    id integer NOT NULL,
    objectid integer,
    fek character varying(255),
    fek_file_url character varying(2000),
    publ_date character varying(10),
    ot_num character varying(12),
    apof_eidos character varying(255),
    title character varying(2000),
    number_ character varying(100),
    sign_date character varying(10),
    georef_diagram_url character varying(2000),
    initial_diagram_url character varying(2000),
    kall_dhm_name character varying(40),
    key_flag integer,
    geom public.geometry(Polygon,2100),
    fetched_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone,
    is_deleted boolean DEFAULT false,
    deleted_at timestamp without time zone,
    label_point public.geometry(Point,2100) GENERATED ALWAYS AS (public.st_pointonsurface(geom)) STORED
);


ALTER TABLE epoleodomia.building_blocks OWNER TO docker;

--
-- Name: building_blocks_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.building_blocks_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.building_blocks_id_seq OWNER TO docker;

--
-- Name: building_blocks_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.building_blocks_id_seq OWNED BY epoleodomia.building_blocks.id;


--
-- Name: building_lines; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.building_lines (
    id integer NOT NULL,
    objectid integer,
    fek character varying(255),
    fek_file_url character varying(2000),
    publ_date character varying(10),
    prasia_width integer,
    og_type character varying(255),
    apof_eidos character varying(255),
    title character varying(2000),
    number_ character varying(100),
    sign_date character varying(10),
    georef_diagram_url character varying(2000),
    initial_diagram_url character varying(2000),
    kall_dhm_name character varying(40),
    key_flag integer,
    rn double precision,
    shape_len double precision,
    geom public.geometry(LineString,2100),
    fetched_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone,
    is_deleted boolean DEFAULT false,
    deleted_at timestamp without time zone
);


ALTER TABLE epoleodomia.building_lines OWNER TO docker;

--
-- Name: building_lines_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.building_lines_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.building_lines_id_seq OWNER TO docker;

--
-- Name: building_lines_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.building_lines_id_seq OWNED BY epoleodomia.building_lines.id;


--
-- Name: building_regs_coefficient; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.building_regs_coefficient (
    id integer NOT NULL,
    objectid integer,
    fek character varying(151),
    fek_file_url character varying(2000),
    publ_date character varying(10),
    syntelesths_domhshs double precision,
    sd_comment character varying(2000),
    synthiki_txt character varying(2000),
    apof_eidos character varying(255),
    title character varying(2000),
    number_ character varying(100),
    sign_date character varying(10),
    kall_dhm_name character varying(40),
    geom public.geometry(Geometry,2100),
    fetched_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    sd_timh double precision,
    sd_tomeas character varying(255),
    sd_klimakotos character varying(255),
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone,
    is_deleted boolean DEFAULT false,
    deleted_at timestamp without time zone
);


ALTER TABLE epoleodomia.building_regs_coefficient OWNER TO docker;

--
-- Name: building_regs_coefficient_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.building_regs_coefficient_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.building_regs_coefficient_id_seq OWNER TO docker;

--
-- Name: building_regs_coefficient_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.building_regs_coefficient_id_seq OWNED BY epoleodomia.building_regs_coefficient.id;


--
-- Name: building_regs_coefficient_zones; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.building_regs_coefficient_zones (
    id integer NOT NULL,
    objectid integer,
    fek character varying(50),
    fek_file_url character varying(500),
    publ_date character varying(20),
    sd_timh double precision,
    sd_tomeas character varying(100),
    sd_klimakotos character varying(10),
    sd_comment text,
    apof_eidos character varying(200),
    title text,
    number_ character varying(100),
    sign_date character varying(20),
    kall_dhm_name character varying(100),
    geom public.geometry(Geometry,2100),
    fetched_at timestamp without time zone DEFAULT now(),
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone,
    is_deleted boolean DEFAULT false,
    deleted_at timestamp without time zone
);


ALTER TABLE epoleodomia.building_regs_coefficient_zones OWNER TO docker;

--
-- Name: TABLE building_regs_coefficient_zones; Type: COMMENT; Schema: epoleodomia; Owner: docker
--

COMMENT ON TABLE epoleodomia.building_regs_coefficient_zones IS 'Zone-level Συντελεστής Δόμησης from UDM_SERVICE_YPD Layer 20. Contains per-ΤΟΜΕΑΣ building coefficient values with detailed commentary on exceptions and conditions. Complements building_regs_coefficient which has per-block data.';


--
-- Name: building_regs_coefficient_zones_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.building_regs_coefficient_zones_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.building_regs_coefficient_zones_id_seq OWNER TO docker;

--
-- Name: building_regs_coefficient_zones_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.building_regs_coefficient_zones_id_seq OWNED BY epoleodomia.building_regs_coefficient_zones.id;


--
-- Name: building_regs_coverage; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.building_regs_coverage (
    id integer NOT NULL,
    objectid integer,
    fek character varying(151),
    fek_file_url character varying(2000),
    publ_date character varying(10),
    kalypsi_pct double precision,
    kalypsi_comment character varying(2000),
    synthiki_txt character varying(2000),
    apof_eidos character varying(255),
    title character varying(2000),
    number_ character varying(100),
    sign_date character varying(10),
    kall_dhm_name character varying(40),
    geom public.geometry(Geometry,2100),
    fetched_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    synt_kalypsis double precision,
    max_embado_m2 integer,
    remarks character varying(2000),
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone,
    is_deleted boolean DEFAULT false,
    deleted_at timestamp without time zone
);


ALTER TABLE epoleodomia.building_regs_coverage OWNER TO docker;

--
-- Name: building_regs_coverage_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.building_regs_coverage_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.building_regs_coverage_id_seq OWNER TO docker;

--
-- Name: building_regs_coverage_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.building_regs_coverage_id_seq OWNED BY epoleodomia.building_regs_coverage.id;


--
-- Name: building_regs_height; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.building_regs_height (
    id integer NOT NULL,
    objectid integer,
    fek character varying(151),
    fek_file_url character varying(2000),
    publ_date character varying(10),
    max_height_m double precision,
    oror_max_height_comment character varying(2000),
    num_orofon integer,
    oror_num_orofon_comment character varying(2000),
    synthiki_txt character varying(2000),
    apof_eidos character varying(255),
    title character varying(2000),
    number_ character varying(100),
    sign_date character varying(10),
    kall_dhm_name character varying(40),
    geom public.geometry(Geometry,2100),
    fetched_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone,
    is_deleted boolean DEFAULT false,
    deleted_at timestamp without time zone
);


ALTER TABLE epoleodomia.building_regs_height OWNER TO docker;

--
-- Name: building_regs_height_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.building_regs_height_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.building_regs_height_id_seq OWNER TO docker;

--
-- Name: building_regs_height_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.building_regs_height_id_seq OWNED BY epoleodomia.building_regs_height.id;


--
-- Name: building_regs_lot; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.building_regs_lot (
    id integer NOT NULL,
    objectid integer,
    fek character varying(151),
    fek_file_url character varying(2000),
    publ_date character varying(10),
    artiothta_m2 double precision,
    artiothta_comment character varying(2000),
    prosopsi_m double precision,
    prosopsi_comment character varying(2000),
    synthiki_txt character varying(2000),
    apof_eidos character varying(255),
    title character varying(2000),
    number_ character varying(100),
    sign_date character varying(10),
    kall_dhm_name character varying(40),
    geom public.geometry(Geometry,2100),
    fetched_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    elax_embado_m2 double precision,
    elax_prosop_m double precision,
    oros_type character varying(255),
    date_pareklisis character varying(10),
    remarks character varying(2000),
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone,
    is_deleted boolean DEFAULT false,
    deleted_at timestamp without time zone
);


ALTER TABLE epoleodomia.building_regs_lot OWNER TO docker;

--
-- Name: building_regs_lot_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.building_regs_lot_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.building_regs_lot_id_seq OWNER TO docker;

--
-- Name: building_regs_lot_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.building_regs_lot_id_seq OWNED BY epoleodomia.building_regs_lot.id;


--
-- Name: building_regs_system; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.building_regs_system (
    id integer NOT NULL,
    objectid integer,
    fek character varying(151),
    fek_file_url character varying(2000),
    publ_date character varying(10),
    oik_systima character varying(255),
    oik_systima_comment character varying(2000),
    synthiki_txt character varying(2000),
    apof_eidos character varying(255),
    title character varying(2000),
    number_ character varying(100),
    sign_date character varying(10),
    kall_dhm_name character varying(40),
    geom public.geometry(Geometry,2100),
    fetched_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone,
    is_deleted boolean DEFAULT false,
    deleted_at timestamp without time zone
);


ALTER TABLE epoleodomia.building_regs_system OWNER TO docker;

--
-- Name: building_regs_system_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.building_regs_system_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.building_regs_system_id_seq OWNER TO docker;

--
-- Name: building_regs_system_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.building_regs_system_id_seq OWNED BY epoleodomia.building_regs_system.id;


--
-- Name: census_blocks_2021; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.census_blocks_2021 (
    id integer NOT NULL,
    objectid integer,
    block_code character varying(50),
    pop_2021 integer,
    households_2021 integer,
    geom public.geometry(Polygon,2100),
    fetched_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone,
    is_deleted boolean DEFAULT false,
    deleted_at timestamp without time zone
);


ALTER TABLE epoleodomia.census_blocks_2021 OWNER TO docker;

--
-- Name: census_blocks_2021_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.census_blocks_2021_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.census_blocks_2021_id_seq OWNER TO docker;

--
-- Name: census_blocks_2021_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.census_blocks_2021_id_seq OWNED BY epoleodomia.census_blocks_2021.id;


--
-- Name: expropriation_zones; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.expropriation_zones (
    id integer NOT NULL,
    objectid integer,
    fek character varying(255),
    fek_file_url character varying(2000),
    publ_date character varying(10),
    zone_name character varying(255),
    apof_eidos character varying(255),
    title character varying(2000),
    number_ character varying(100),
    sign_date character varying(10),
    kall_dhm_name character varying(40),
    key_flag integer,
    geom public.geometry(Polygon,2100),
    fetched_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE epoleodomia.expropriation_zones OWNER TO docker;

--
-- Name: expropriation_zones_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.expropriation_zones_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.expropriation_zones_id_seq OWNER TO docker;

--
-- Name: expropriation_zones_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.expropriation_zones_id_seq OWNED BY epoleodomia.expropriation_zones.id;


--
-- Name: fek_no_diagrams; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.fek_no_diagrams (
    id integer NOT NULL,
    objectid integer,
    fek character varying(50),
    fek_file_url character varying(500),
    publ_date character varying(20),
    apof_eidos character varying(200),
    apof_theme character varying(200),
    title text,
    number_ character varying(100),
    sign_date character varying(20),
    diagram_cat character varying(100),
    geom public.geometry(Geometry,2100),
    fetched_at timestamp without time zone DEFAULT now(),
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone,
    is_deleted boolean DEFAULT false,
    deleted_at timestamp without time zone
);


ALTER TABLE epoleodomia.fek_no_diagrams OWNER TO docker;

--
-- Name: TABLE fek_no_diagrams; Type: COMMENT; Schema: epoleodomia; Owner: docker
--

COMMENT ON TABLE epoleodomia.fek_no_diagrams IS 'ΦΕΚ Χωρίς Διάγραμμα (TEE Layer 0 of FEK_NO_SXEDIA_DOCS). Regulatory acts that TEE could not georeference. Critical for identifying data gaps in building regulations.';


--
-- Name: fek_no_diagrams_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.fek_no_diagrams_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.fek_no_diagrams_id_seq OWNER TO docker;

--
-- Name: fek_no_diagrams_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.fek_no_diagrams_id_seq OWNED BY epoleodomia.fek_no_diagrams.id;


--
-- Name: forest_maps; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.forest_maps (
    id integer NOT NULL,
    objectid integer,
    region_name character varying(255),
    layer_id integer,
    forest_type character varying(255),
    status character varying(255),
    geom public.geometry(Geometry,2100),
    fetched_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone,
    is_deleted boolean DEFAULT false,
    deleted_at timestamp without time zone,
    forest_code character varying,
    nomos character varying,
    kathgoral1 character varying,
    kathgoral2 character varying,
    area_m2 double precision
);


ALTER TABLE epoleodomia.forest_maps OWNER TO docker;

--
-- Name: COLUMN forest_maps.area_m2; Type: COMMENT; Schema: epoleodomia; Owner: docker
--

COMMENT ON COLUMN epoleodomia.forest_maps.area_m2 IS 'Feature area in m² from TEE API (GISDATA.PER_ATTIKHS_KYROSH.AREA)';


--
-- Name: forest_maps_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.forest_maps_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.forest_maps_id_seq OWNER TO docker;

--
-- Name: forest_maps_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.forest_maps_id_seq OWNED BY epoleodomia.forest_maps.id;


--
-- Name: forest_maps_posted_attica_2021; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.forest_maps_posted_attica_2021 (
    id integer NOT NULL,
    objectid integer,
    ota character varying(20),
    nomos character varying(20),
    forest_type character varying(20),
    kathgoral1 character varying(20),
    kathgoral2 character varying(20),
    area_m2 double precision,
    geom public.geometry(Geometry,2100),
    fetched_at timestamp without time zone DEFAULT now(),
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone,
    is_deleted boolean DEFAULT false,
    deleted_at timestamp without time zone
);


ALTER TABLE epoleodomia.forest_maps_posted_attica_2021 OWNER TO docker;

--
-- Name: TABLE forest_maps_posted_attica_2021; Type: COMMENT; Schema: epoleodomia; Owner: docker
--

COMMENT ON TABLE epoleodomia.forest_maps_posted_attica_2021 IS 'Αναρτημένοι δασικοί χάρτες Αττικής 2021 (TEE Layer 31). Posted/draft forest classifications covering Spetses island. Not yet fully ratified.';


--
-- Name: forest_maps_posted_attica_2021_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.forest_maps_posted_attica_2021_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.forest_maps_posted_attica_2021_id_seq OWNER TO docker;

--
-- Name: forest_maps_posted_attica_2021_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.forest_maps_posted_attica_2021_id_seq OWNED BY epoleodomia.forest_maps_posted_attica_2021.id;


--
-- Name: forest_maps_posted_pelop_2022; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.forest_maps_posted_pelop_2022 (
    id integer NOT NULL,
    objectid integer,
    ota character varying(20),
    nomos character varying(20),
    forest_type character varying(20),
    kathgoral1 character varying(20),
    kathgoral2 character varying(20),
    area_m2 double precision,
    geom public.geometry(Geometry,2100),
    fetched_at timestamp without time zone DEFAULT now(),
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone,
    is_deleted boolean DEFAULT false,
    deleted_at timestamp without time zone
);


ALTER TABLE epoleodomia.forest_maps_posted_pelop_2022 OWNER TO docker;

--
-- Name: TABLE forest_maps_posted_pelop_2022; Type: COMMENT; Schema: epoleodomia; Owner: docker
--

COMMENT ON TABLE epoleodomia.forest_maps_posted_pelop_2022 IS 'Αναρτημένοι δασικοί χάρτες Πελοποννήσου 2022 (TEE Layer 26). Posted/draft forest classifications covering Ermionida mainland. Not yet fully ratified.';


--
-- Name: forest_maps_posted_pelop_2022_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.forest_maps_posted_pelop_2022_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.forest_maps_posted_pelop_2022_id_seq OWNER TO docker;

--
-- Name: forest_maps_posted_pelop_2022_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.forest_maps_posted_pelop_2022_id_seq OWNED BY epoleodomia.forest_maps_posted_pelop_2022.id;


--
-- Name: historic_sites_lines; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.historic_sites_lines (
    id integer NOT NULL,
    objectid integer,
    name character varying(500),
    ota character varying(500),
    foreas character varying(500),
    shape_len double precision,
    geom public.geometry(LineString,2100),
    fetched_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE epoleodomia.historic_sites_lines OWNER TO docker;

--
-- Name: historic_sites_lines_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.historic_sites_lines_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.historic_sites_lines_id_seq OWNER TO docker;

--
-- Name: historic_sites_lines_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.historic_sites_lines_id_seq OWNED BY epoleodomia.historic_sites_lines.id;


--
-- Name: historic_sites_points; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.historic_sites_points (
    id integer NOT NULL,
    objectid integer,
    name character varying(500),
    ota character varying(500),
    foreas character varying(500),
    geom public.geometry(Point,2100),
    fetched_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE epoleodomia.historic_sites_points OWNER TO docker;

--
-- Name: historic_sites_points_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.historic_sites_points_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.historic_sites_points_id_seq OWNER TO docker;

--
-- Name: historic_sites_points_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.historic_sites_points_id_seq OWNED BY epoleodomia.historic_sites_points.id;


--
-- Name: historic_sites_polygons; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.historic_sites_polygons (
    id integer NOT NULL,
    objectid integer,
    name character varying(500),
    ota character varying(500),
    foreas character varying(500),
    shape_area double precision,
    shape_len double precision,
    geom public.geometry(Polygon,2100),
    fetched_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE epoleodomia.historic_sites_polygons OWNER TO docker;

--
-- Name: historic_sites_polygons_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.historic_sites_polygons_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.historic_sites_polygons_id_seq OWNER TO docker;

--
-- Name: historic_sites_polygons_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.historic_sites_polygons_id_seq OWNED BY epoleodomia.historic_sites_polygons.id;


--
-- Name: land_uses_ers; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.land_uses_ers (
    id integer NOT NULL,
    objectid integer,
    fek character varying(255),
    fek_file_url character varying(2000),
    publ_date character varying(10),
    gen_xrhsh_flag character varying(255),
    gen_xrhsh_gps character varying(255),
    per_cat_gen character varying(255),
    per_cat_eid character varying(255),
    remarks character varying(1000),
    eidikh_coded_delim_values character varying(1000),
    apof_eidos character varying(255),
    title character varying(2000),
    number_ character varying(100),
    sign_date character varying(10),
    kall_dhm_name character varying(40),
    key_flag integer,
    geom public.geometry(Geometry,2100),
    fetched_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone,
    is_deleted boolean DEFAULT false,
    deleted_at timestamp without time zone
);


ALTER TABLE epoleodomia.land_uses_ers OWNER TO docker;

--
-- Name: land_uses_ers_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.land_uses_ers_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.land_uses_ers_id_seq OWNER TO docker;

--
-- Name: land_uses_ers_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.land_uses_ers_id_seq OWNED BY epoleodomia.land_uses_ers.id;


--
-- Name: land_uses_gps; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.land_uses_gps (
    id integer NOT NULL,
    objectid integer,
    fek character varying(255),
    fek_file_url character varying(2000),
    publ_date character varying(10),
    gen_xrhsh_flag character varying(255),
    gen_xrhsh_gps character varying(255),
    per_cat_gen character varying(255),
    per_cat_eid character varying(255),
    remarks character varying(1000),
    eidikh_coded_delim_values character varying(1000),
    apof_eidos character varying(255),
    title character varying(2000),
    number_ character varying(100),
    sign_date character varying(10),
    kall_dhm_name character varying(40),
    key_flag integer,
    geom public.geometry(Geometry,2100),
    fetched_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE epoleodomia.land_uses_gps OWNER TO docker;

--
-- Name: land_uses_gps_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.land_uses_gps_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.land_uses_gps_id_seq OWNER TO docker;

--
-- Name: land_uses_gps_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.land_uses_gps_id_seq OWNED BY epoleodomia.land_uses_gps.id;


--
-- Name: monuments_lines; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.monuments_lines (
    id integer NOT NULL,
    objectid integer,
    name character varying(500),
    ota character varying(500),
    foreas character varying(500),
    shape_len double precision,
    geom public.geometry(LineString,2100),
    fetched_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE epoleodomia.monuments_lines OWNER TO docker;

--
-- Name: monuments_lines_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.monuments_lines_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.monuments_lines_id_seq OWNER TO docker;

--
-- Name: monuments_lines_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.monuments_lines_id_seq OWNED BY epoleodomia.monuments_lines.id;


--
-- Name: monuments_points; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.monuments_points (
    id integer NOT NULL,
    objectid integer,
    name character varying(500),
    ota character varying(500),
    foreas character varying(500),
    geom public.geometry(Point,2100),
    fetched_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone,
    is_deleted boolean DEFAULT false,
    deleted_at timestamp without time zone
);


ALTER TABLE epoleodomia.monuments_points OWNER TO docker;

--
-- Name: monuments_points_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.monuments_points_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.monuments_points_id_seq OWNER TO docker;

--
-- Name: monuments_points_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.monuments_points_id_seq OWNED BY epoleodomia.monuments_points.id;


--
-- Name: monuments_polygons; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.monuments_polygons (
    id integer NOT NULL,
    objectid integer,
    name character varying(500),
    ota character varying(500),
    foreas character varying(500),
    shape_area double precision,
    shape_len double precision,
    geom public.geometry(Polygon,2100),
    fetched_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone,
    is_deleted boolean DEFAULT false,
    deleted_at timestamp without time zone
);


ALTER TABLE epoleodomia.monuments_polygons OWNER TO docker;

--
-- Name: monuments_polygons_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.monuments_polygons_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.monuments_polygons_id_seq OWNER TO docker;

--
-- Name: monuments_polygons_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.monuments_polygons_id_seq OWNED BY epoleodomia.monuments_polygons.id;


--
-- Name: municipal_communities_2021; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.municipal_communities_2021 (
    id integer NOT NULL,
    objectid integer,
    ypes_code character varying(20),
    ypes_name character varying(255),
    pop_2021 integer,
    geom public.geometry(Geometry,2100),
    fetched_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone,
    is_deleted boolean DEFAULT false,
    deleted_at timestamp without time zone
);


ALTER TABLE epoleodomia.municipal_communities_2021 OWNER TO docker;

--
-- Name: municipal_communities_2021_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.municipal_communities_2021_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.municipal_communities_2021_id_seq OWNER TO docker;

--
-- Name: municipal_communities_2021_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.municipal_communities_2021_id_seq OWNED BY epoleodomia.municipal_communities_2021.id;


--
-- Name: municipal_units_2021; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.municipal_units_2021 (
    id integer NOT NULL,
    objectid integer,
    ypes_code character varying(20),
    ypes_name character varying(255),
    pop_2021 integer,
    geom public.geometry(Geometry,2100),
    fetched_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone,
    is_deleted boolean DEFAULT false,
    deleted_at timestamp without time zone,
    globalid character varying
);


ALTER TABLE epoleodomia.municipal_units_2021 OWNER TO docker;

--
-- Name: municipal_units_2021_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.municipal_units_2021_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.municipal_units_2021_id_seq OWNER TO docker;

--
-- Name: municipal_units_2021_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.municipal_units_2021_id_seq OWNED BY epoleodomia.municipal_units_2021.id;


--
-- Name: municipalities_2021; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.municipalities_2021 (
    id integer NOT NULL,
    objectid integer,
    ypes_code character varying(20),
    ypes_name character varying(255),
    pop_2021 integer,
    geom public.geometry(Geometry,2100),
    fetched_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone,
    is_deleted boolean DEFAULT false,
    deleted_at timestamp without time zone
);


ALTER TABLE epoleodomia.municipalities_2021 OWNER TO docker;

--
-- Name: municipalities_2021_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.municipalities_2021_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.municipalities_2021_id_seq OWNER TO docker;

--
-- Name: municipalities_2021_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.municipalities_2021_id_seq OWNED BY epoleodomia.municipalities_2021.id;


--
-- Name: natura_2000; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.natura_2000 (
    id integer NOT NULL,
    objectid integer,
    sitecode character varying(50),
    sitename character varying(500),
    sitetype character varying(50),
    area_ha double precision,
    geom public.geometry(Polygon,2100),
    fetched_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE epoleodomia.natura_2000 OWNER TO docker;

--
-- Name: natura_2000_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.natura_2000_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.natura_2000_id_seq OWNER TO docker;

--
-- Name: natura_2000_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.natura_2000_id_seq OWNED BY epoleodomia.natura_2000.id;


--
-- Name: natural_landscapes_points; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.natural_landscapes_points (
    id integer NOT NULL,
    objectid integer,
    name character varying(500),
    ota character varying(500),
    foreas character varying(500),
    geom public.geometry(Point,2100),
    fetched_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE epoleodomia.natural_landscapes_points OWNER TO docker;

--
-- Name: natural_landscapes_points_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.natural_landscapes_points_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.natural_landscapes_points_id_seq OWNER TO docker;

--
-- Name: natural_landscapes_points_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.natural_landscapes_points_id_seq OWNED BY epoleodomia.natural_landscapes_points.id;


--
-- Name: natural_landscapes_polygons; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.natural_landscapes_polygons (
    id integer NOT NULL,
    objectid integer,
    name character varying(500),
    ota character varying(500),
    foreas character varying(500),
    shape_area double precision,
    shape_len double precision,
    geom public.geometry(Polygon,2100),
    fetched_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone,
    is_deleted boolean DEFAULT false,
    deleted_at timestamp without time zone
);


ALTER TABLE epoleodomia.natural_landscapes_polygons OWNER TO docker;

--
-- Name: natural_landscapes_polygons_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.natural_landscapes_polygons_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.natural_landscapes_polygons_id_seq OWNER TO docker;

--
-- Name: natural_landscapes_polygons_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.natural_landscapes_polygons_id_seq OWNED BY epoleodomia.natural_landscapes_polygons.id;


--
-- Name: other_planning_lines; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.other_planning_lines (
    id integer NOT NULL,
    objectid integer,
    fek character varying(255),
    fek_file_url character varying(2000),
    publ_date character varying(10),
    pol_gr_type character varying(255),
    apof_eidos character varying(255),
    title character varying(2000),
    number_ character varying(100),
    sign_date character varying(10),
    georef_diagram_url character varying(2000),
    initial_diagram_url character varying(2000),
    kall_dhm_name character varying(40),
    key_flag integer,
    geom public.geometry(LineString,2100),
    fetched_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone,
    is_deleted boolean DEFAULT false,
    deleted_at timestamp without time zone
);


ALTER TABLE epoleodomia.other_planning_lines OWNER TO docker;

--
-- Name: other_planning_lines_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.other_planning_lines_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.other_planning_lines_id_seq OWNER TO docker;

--
-- Name: other_planning_lines_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.other_planning_lines_id_seq OWNED BY epoleodomia.other_planning_lines.id;


--
-- Name: other_planning_zones; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.other_planning_zones (
    id integer NOT NULL,
    objectid integer,
    fek character varying(151),
    fek_file_url character varying(2000),
    publ_date character varying(10),
    zone_name character varying(255),
    zone_type character varying(255),
    apof_eidos character varying(255),
    title character varying(2000),
    number_ character varying(100),
    sign_date character varying(10),
    kall_dhm_name character varying(40),
    key_flag integer,
    geom public.geometry(Polygon,2100),
    fetched_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE epoleodomia.other_planning_zones OWNER TO docker;

--
-- Name: other_planning_zones_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.other_planning_zones_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.other_planning_zones_id_seq OWNER TO docker;

--
-- Name: other_planning_zones_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.other_planning_zones_id_seq OWNED BY epoleodomia.other_planning_zones.id;


--
-- Name: outside_plan_areas; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.outside_plan_areas (
    id integer NOT NULL,
    objectid integer,
    fek character varying(151),
    fek_file_url character varying(2000),
    publ_date character varying(10),
    text character varying(255),
    apof_eidos character varying(255),
    title character varying(2000),
    number_ character varying(100),
    sign_date character varying(10),
    kall_dhm_name character varying(40),
    key_flag integer,
    geom public.geometry(Polygon,2100),
    fetched_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE epoleodomia.outside_plan_areas OWNER TO docker;

--
-- Name: outside_plan_areas_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.outside_plan_areas_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.outside_plan_areas_id_seq OWNER TO docker;

--
-- Name: outside_plan_areas_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.outside_plan_areas_id_seq OWNED BY epoleodomia.outside_plan_areas.id;


--
-- Name: pd_protection_zones; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.pd_protection_zones (
    id integer NOT NULL,
    objectid integer,
    fek character varying(255),
    fek_file_url character varying(2000),
    zone_name character varying(255),
    protection_type character varying(255),
    geom public.geometry(Polygon,2100),
    fetched_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE epoleodomia.pd_protection_zones OWNER TO docker;

--
-- Name: pd_protection_zones_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.pd_protection_zones_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.pd_protection_zones_id_seq OWNER TO docker;

--
-- Name: pd_protection_zones_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.pd_protection_zones_id_seq OWNED BY epoleodomia.pd_protection_zones.id;


--
-- Name: pedestrian_zones; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.pedestrian_zones (
    id integer NOT NULL,
    objectid integer,
    fek character varying(255),
    fek_file_url character varying(2000),
    publ_date character varying(10),
    pz_xrhsh character varying(255),
    apof_eidos character varying(255),
    title character varying(2000),
    number_ character varying(100),
    sign_date character varying(10),
    georef_diagram_url character varying(2000),
    initial_diagram_url character varying(2000),
    kall_dhm_name character varying(40),
    key_flag integer,
    geom public.geometry(Polygon,2100),
    fetched_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone,
    is_deleted boolean DEFAULT false,
    deleted_at timestamp without time zone
);


ALTER TABLE epoleodomia.pedestrian_zones OWNER TO docker;

--
-- Name: pedestrian_zones_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.pedestrian_zones_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.pedestrian_zones_id_seq OWNER TO docker;

--
-- Name: pedestrian_zones_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.pedestrian_zones_id_seq OWNED BY epoleodomia.pedestrian_zones.id;


--
-- Name: planning_diagrams; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.planning_diagrams (
    id integer NOT NULL,
    objectid integer,
    fek character varying(255),
    fek_file_url character varying(2000),
    publ_date character varying(10),
    apof_eidos character varying(255),
    title character varying(2000),
    number_ character varying(100),
    sign_date character varying(10),
    comp_diagr_legend_number character varying(255),
    init_diagr_scale_denominator integer,
    ggrs87_diagr_georef_rms double precision,
    georef_diagram_url character varying(2000),
    initial_diagram_url character varying(2000),
    geom public.geometry(Polygon,2100),
    fetched_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone,
    is_deleted boolean DEFAULT false,
    deleted_at timestamp without time zone
);


ALTER TABLE epoleodomia.planning_diagrams OWNER TO docker;

--
-- Name: planning_diagrams_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.planning_diagrams_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.planning_diagrams_id_seq OWNER TO docker;

--
-- Name: planning_diagrams_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.planning_diagrams_id_seq OWNED BY epoleodomia.planning_diagrams.id;


--
-- Name: planning_lines; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.planning_lines (
    id integer NOT NULL,
    objectid integer,
    fek character varying(255),
    fek_file_url character varying(2000),
    publ_date character varying(10),
    road_width integer,
    prasia_width integer,
    rg_type character varying(255),
    apof_eidos character varying(255),
    title character varying(2000),
    number_ character varying(100),
    sign_date character varying(10),
    georef_diagram_url character varying(2000),
    initial_diagram_url character varying(2000),
    kall_dhm_name character varying(40),
    key_flag integer,
    geom public.geometry(LineString,2100),
    fetched_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone,
    is_deleted boolean DEFAULT false,
    deleted_at timestamp without time zone
);


ALTER TABLE epoleodomia.planning_lines OWNER TO docker;

--
-- Name: planning_lines_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.planning_lines_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.planning_lines_id_seq OWNER TO docker;

--
-- Name: planning_lines_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.planning_lines_id_seq OWNED BY epoleodomia.planning_lines.id;


--
-- Name: protected_buildings; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.protected_buildings (
    id integer NOT NULL,
    objectid integer,
    fek character varying(521),
    eidosfek character varying(500),
    type character varying(1000),
    thesmkat character varying(500),
    odos character varying(500),
    thesi character varying(500),
    x double precision,
    y double precision,
    apof_number character varying(255),
    sign_date character varying(10),
    geom public.geometry(Point,2100),
    fetched_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone,
    is_deleted boolean DEFAULT false,
    deleted_at timestamp without time zone
);


ALTER TABLE epoleodomia.protected_buildings OWNER TO docker;

--
-- Name: protected_buildings_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.protected_buildings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.protected_buildings_id_seq OWNER TO docker;

--
-- Name: protected_buildings_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.protected_buildings_id_seq OWNED BY epoleodomia.protected_buildings.id;


--
-- Name: protection_zones_lines; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.protection_zones_lines (
    id integer NOT NULL,
    objectid integer,
    name character varying(500),
    ota character varying(500),
    foreas character varying(500),
    shape_len double precision,
    geom public.geometry(LineString,2100),
    fetched_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE epoleodomia.protection_zones_lines OWNER TO docker;

--
-- Name: protection_zones_lines_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.protection_zones_lines_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.protection_zones_lines_id_seq OWNER TO docker;

--
-- Name: protection_zones_lines_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.protection_zones_lines_id_seq OWNED BY epoleodomia.protection_zones_lines.id;


--
-- Name: protection_zones_points; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.protection_zones_points (
    id integer NOT NULL,
    objectid integer,
    name character varying(500),
    ota character varying(500),
    foreas character varying(500),
    geom public.geometry(Point,2100),
    fetched_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE epoleodomia.protection_zones_points OWNER TO docker;

--
-- Name: protection_zones_points_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.protection_zones_points_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.protection_zones_points_id_seq OWNER TO docker;

--
-- Name: protection_zones_points_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.protection_zones_points_id_seq OWNED BY epoleodomia.protection_zones_points.id;


--
-- Name: protection_zones_polygons; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.protection_zones_polygons (
    id integer NOT NULL,
    objectid integer,
    name character varying(500),
    ota character varying(500),
    foreas character varying(500),
    shape_area double precision,
    shape_len double precision,
    geom public.geometry(Polygon,2100),
    fetched_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone,
    is_deleted boolean DEFAULT false,
    deleted_at timestamp without time zone
);


ALTER TABLE epoleodomia.protection_zones_polygons OWNER TO docker;

--
-- Name: protection_zones_polygons_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.protection_zones_polygons_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.protection_zones_polygons_id_seq OWNER TO docker;

--
-- Name: protection_zones_polygons_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.protection_zones_polygons_id_seq OWNED BY epoleodomia.protection_zones_polygons.id;


--
-- Name: public_spaces; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.public_spaces (
    id integer NOT NULL,
    objectid integer,
    fek character varying(255),
    fek_file_url character varying(2000),
    publ_date character varying(10),
    kx_koinoxr_kodikos character varying(255),
    kx_koinoxr_type character varying(255),
    apof_eidos character varying(255),
    title character varying(2000),
    number_ character varying(100),
    sign_date character varying(10),
    georef_diagram_url character varying(2000),
    initial_diagram_url character varying(2000),
    kall_dhm_name character varying(40),
    key_flag integer,
    geom public.geometry(Polygon,2100),
    fetched_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone,
    is_deleted boolean DEFAULT false,
    deleted_at timestamp without time zone
);


ALTER TABLE epoleodomia.public_spaces OWNER TO docker;

--
-- Name: public_spaces_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.public_spaces_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.public_spaces_id_seq OWNER TO docker;

--
-- Name: public_spaces_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.public_spaces_id_seq OWNED BY epoleodomia.public_spaces.id;


--
-- Name: raster_catalog; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.raster_catalog (
    id integer NOT NULL,
    planning_diagram_objectid integer,
    fek character varying(50),
    filename character varying(255) NOT NULL,
    url_georef text,
    url_raw text,
    local_path_georef character varying(500),
    local_path_raw character varying(500),
    file_size_bytes bigint,
    downloaded_at timestamp without time zone,
    download_status character varying(20) DEFAULT 'pending'::character varying,
    download_error text,
    last_checked timestamp without time zone,
    bbox public.geometry(Polygon,2100),
    width_px integer,
    height_px integer,
    bands integer,
    resolution_x numeric(10,4),
    resolution_y numeric(10,4),
    crs_epsg integer,
    nodata_value numeric,
    georef_rms numeric(10,4),
    original_scale integer,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


ALTER TABLE epoleodomia.raster_catalog OWNER TO docker;

--
-- Name: TABLE raster_catalog; Type: COMMENT; Schema: epoleodomia; Owner: docker
--

COMMENT ON TABLE epoleodomia.raster_catalog IS 'Catalog of TEE planning diagram raster files (TIFs)';


--
-- Name: COLUMN raster_catalog.url_georef; Type: COMMENT; Schema: epoleodomia; Owner: docker
--

COMMENT ON COLUMN epoleodomia.raster_catalog.url_georef IS 'URL to EGSA/GGRS87 georeferenced TIF';


--
-- Name: COLUMN raster_catalog.url_raw; Type: COMMENT; Schema: epoleodomia; Owner: docker
--

COMMENT ON COLUMN epoleodomia.raster_catalog.url_raw IS 'URL to original scanned image (not georeferenced)';


--
-- Name: COLUMN raster_catalog.georef_rms; Type: COMMENT; Schema: epoleodomia; Owner: docker
--

COMMENT ON COLUMN epoleodomia.raster_catalog.georef_rms IS 'Root Mean Square error of georeferencing in meters';


--
-- Name: COLUMN raster_catalog.original_scale; Type: COMMENT; Schema: epoleodomia; Owner: docker
--

COMMENT ON COLUMN epoleodomia.raster_catalog.original_scale IS 'Scale denominator of original map (e.g., 1000 = 1:1000)';


--
-- Name: raster_catalog_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.raster_catalog_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.raster_catalog_id_seq OWNER TO docker;

--
-- Name: raster_catalog_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.raster_catalog_id_seq OWNED BY epoleodomia.raster_catalog.id;


--
-- Name: settlement_boundaries; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.settlement_boundaries (
    id integer NOT NULL,
    objectid integer,
    fek character varying(151),
    fek_file_url character varying(2000),
    publ_date character varying(10),
    name character varying(255),
    apof_eidos character varying(255),
    title character varying(2000),
    number_ character varying(100),
    sign_date character varying(10),
    kall_dhm_name character varying(40),
    key_flag integer,
    geom public.geometry(Polygon,2100),
    fetched_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE epoleodomia.settlement_boundaries OWNER TO docker;

--
-- Name: settlement_boundaries_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.settlement_boundaries_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.settlement_boundaries_id_seq OWNER TO docker;

--
-- Name: settlement_boundaries_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.settlement_boundaries_id_seq OWNED BY epoleodomia.settlement_boundaries.id;


--
-- Name: settlements_2021; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.settlements_2021 (
    id integer NOT NULL,
    objectid integer,
    elstat_code character varying(20),
    name character varying(255),
    pop_2021 integer,
    geom public.geometry(Point,2100),
    fetched_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone,
    is_deleted boolean DEFAULT false,
    deleted_at timestamp without time zone
);


ALTER TABLE epoleodomia.settlements_2021 OWNER TO docker;

--
-- Name: settlements_2021_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.settlements_2021_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.settlements_2021_id_seq OWNER TO docker;

--
-- Name: settlements_2021_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.settlements_2021_id_seq OWNED BY epoleodomia.settlements_2021.id;


--
-- Name: shorelines; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.shorelines (
    id integer NOT NULL,
    objectid integer,
    fek character varying(255),
    fek_file_url character varying(2000),
    publ_date character varying(10),
    line_name character varying(255),
    line_type_aigial_paralia character varying(255),
    apof_eidos character varying(255),
    title character varying(2000),
    number_ character varying(100),
    sign_date character varying(10),
    georef_diagram_url character varying(2000),
    initial_diagram_url character varying(2000),
    kall_dhm_name character varying(40),
    key_flag integer,
    geom public.geometry(LineString,2100),
    fetched_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone,
    is_deleted boolean DEFAULT false,
    deleted_at timestamp without time zone
);


ALTER TABLE epoleodomia.shorelines OWNER TO docker;

--
-- Name: shorelines_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.shorelines_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.shorelines_id_seq OWNER TO docker;

--
-- Name: shorelines_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.shorelines_id_seq OWNED BY epoleodomia.shorelines.id;


--
-- Name: spetses island bb; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia."spetses island bb" (
    id integer NOT NULL,
    geom public.geometry(Polygon,2100),
    fid bigint,
    spetsesbbox character varying(50)
);


ALTER TABLE epoleodomia."spetses island bb" OWNER TO docker;

--
-- Name: spetses island bb_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia."spetses island bb_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia."spetses island bb_id_seq" OWNER TO docker;

--
-- Name: spetses island bb_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia."spetses island bb_id_seq" OWNED BY epoleodomia."spetses island bb".id;


--
-- Name: streams; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.streams (
    id integer NOT NULL,
    objectid integer,
    fek character varying(151),
    fek_file_url character varying(2000),
    publ_date character varying(10),
    line_name character varying(255),
    apof_eidos character varying(255),
    title character varying(2000),
    number_ character varying(100),
    sign_date character varying(10),
    georef_diagram_url character varying(2000),
    initial_diagram_url character varying(2000),
    kall_dhm_name character varying(40),
    key_flag integer,
    geom public.geometry(LineString,2100),
    fetched_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE epoleodomia.streams OWNER TO docker;

--
-- Name: streams_environmental; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.streams_environmental (
    id integer NOT NULL,
    objectid integer,
    name character varying(255),
    stream_type character varying(255),
    geom public.geometry(LineString,2100),
    fetched_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE epoleodomia.streams_environmental OWNER TO docker;

--
-- Name: streams_environmental_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.streams_environmental_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.streams_environmental_id_seq OWNER TO docker;

--
-- Name: streams_environmental_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.streams_environmental_id_seq OWNED BY epoleodomia.streams_environmental.id;


--
-- Name: streams_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.streams_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.streams_id_seq OWNER TO docker;

--
-- Name: streams_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.streams_id_seq OWNED BY epoleodomia.streams.id;


--
-- Name: sync_log; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.sync_log (
    id integer NOT NULL,
    table_name character varying(100) NOT NULL,
    service_name character varying(255),
    layer_id integer,
    records_fetched integer,
    sync_started_at timestamp without time zone,
    sync_completed_at timestamp without time zone,
    status character varying(50),
    error_message text
);


ALTER TABLE epoleodomia.sync_log OWNER TO docker;

--
-- Name: sync_log_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.sync_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.sync_log_id_seq OWNER TO docker;

--
-- Name: sync_log_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.sync_log_id_seq OWNED BY epoleodomia.sync_log.id;


--
-- Name: urban_units; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.urban_units (
    id integer NOT NULL,
    objectid integer,
    fek character varying(151),
    fek_file_url character varying(2000),
    publ_date character varying(10),
    pl_area_type character varying(255),
    apof_eidos character varying(255),
    title character varying(2000),
    number_ character varying(100),
    sign_date character varying(10),
    kall_dhm_name character varying(40),
    key_flag integer,
    geom public.geometry(Polygon,2100),
    fetched_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE epoleodomia.urban_units OWNER TO docker;

--
-- Name: urban_units_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.urban_units_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.urban_units_id_seq OWNER TO docker;

--
-- Name: urban_units_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.urban_units_id_seq OWNED BY epoleodomia.urban_units.id;


--
-- Name: v_addresses_with_blocks; Type: VIEW; Schema: epoleodomia; Owner: docker
--

CREATE VIEW epoleodomia.v_addresses_with_blocks AS
 SELECT a.id,
    a.addr AS address,
    a.num AS number,
    a.munic AS municipality,
    b.ot_num AS block_number,
    b.fek AS block_fek,
    a.geom,
    a.fetched_at
   FROM (epoleodomia.addresses a
     LEFT JOIN epoleodomia.building_blocks b ON (public.st_within(a.geom, b.geom)));


ALTER VIEW epoleodomia.v_addresses_with_blocks OWNER TO docker;

--
-- Name: VIEW v_addresses_with_blocks; Type: COMMENT; Schema: epoleodomia; Owner: docker
--

COMMENT ON VIEW epoleodomia.v_addresses_with_blocks IS 'Addresses with their containing building block information';


--
-- Name: v_building_blocks_full; Type: VIEW; Schema: epoleodomia; Owner: docker
--

CREATE VIEW epoleodomia.v_building_blocks_full AS
 SELECT b.id,
    b.objectid,
    b.ot_num,
    b.fek,
    b.fek_file_url,
    b.publ_date,
    b.kall_dhm_name,
    h.max_height_m,
    h.num_orofon,
    h.oror_max_height_comment AS height_comment,
    c.synt_kalypsis AS coverage_pct,
    f.sd_timh AS building_coefficient,
    f.sd_comment AS coefficient_comment,
    l.elax_embado_m2 AS min_lot_size_m2,
    l.elax_prosop_m AS min_frontage_m,
    s.oik_systima AS building_system,
    b.geom,
    b.fetched_at
   FROM (((((epoleodomia.building_blocks b
     LEFT JOIN epoleodomia.building_regs_height h ON (public.st_intersects(public.st_centroid(b.geom), h.geom)))
     LEFT JOIN epoleodomia.building_regs_coverage c ON (public.st_intersects(public.st_centroid(b.geom), c.geom)))
     LEFT JOIN epoleodomia.building_regs_coefficient f ON (public.st_intersects(public.st_centroid(b.geom), f.geom)))
     LEFT JOIN epoleodomia.building_regs_lot l ON (public.st_intersects(public.st_centroid(b.geom), l.geom)))
     LEFT JOIN epoleodomia.building_regs_system s ON (public.st_intersects(public.st_centroid(b.geom), s.geom)));


ALTER VIEW epoleodomia.v_building_blocks_full OWNER TO docker;

--
-- Name: v_building_blocks_regulations; Type: VIEW; Schema: epoleodomia; Owner: docker
--

CREATE VIEW epoleodomia.v_building_blocks_regulations AS
 SELECT b.id,
    b.objectid,
    b.ot_num,
    b.fek,
    b.fek_file_url,
    b.publ_date,
    b.kall_dhm_name,
    h.max_height_m,
    h.num_orofon,
    h.oror_max_height_comment AS height_comment,
    h.match_pct AS height_match_pct,
    c.synt_kalypsis AS coverage_pct,
    c.remarks AS coverage_remarks,
    c.match_pct AS coverage_match_pct,
    COALESCE(f.sd_timh, z.sd_timh) AS building_coefficient,
    COALESCE(f.sd_tomeas, z.sd_tomeas) AS sd_tomeas,
    COALESCE(f.sd_klimakotos, z.sd_klimakotos) AS sd_klimakotos,
    COALESCE(f.sd_comment, (z.sd_comment)::character varying) AS coefficient_comment,
        CASE
            WHEN (f.sd_timh IS NOT NULL) THEN 'per_block'::text
            WHEN (z.sd_timh IS NOT NULL) THEN 'zone'::text
            ELSE NULL::text
        END AS coefficient_source,
    COALESCE(f.match_pct, z.match_pct) AS coefficient_match_pct,
    lk.elax_embado_m2 AS min_lot_size_m2,
    lk.elax_prosop_m AS min_frontage_m,
    COALESCE(lk.oros_type, lp.oros_type) AS oros_type,
    lp.date_pareklisis,
    lp.remarks AS lot_remarks,
    lk.match_pct AS lot_match_pct,
    s.oik_systima AS building_system,
    s.match_pct AS system_match_pct,
    lu.per_cat_gen AS land_use_general,
    lu.per_cat_eid AS land_use_specific,
    lu.remarks AS land_use_remarks,
    lu.match_pct AS land_use_match_pct,
    b.label_point,
    b.geom
   FROM ((((((((epoleodomia.building_blocks b
     LEFT JOIN LATERAL ( SELECT x.max_height_m,
            x.num_orofon,
            x.oror_max_height_comment,
            round(((((100)::double precision * public.st_area(public.st_intersection(x.geom, b.geom))) / NULLIF(public.st_area(b.geom), (0)::double precision)))::numeric, 1) AS match_pct
           FROM epoleodomia.building_regs_height x
          WHERE (public.st_intersects(x.geom, b.geom) AND (NOT COALESCE(x.is_deleted, false)))
          ORDER BY (public.st_area(public.st_intersection(x.geom, b.geom))) DESC
         LIMIT 1) h ON (true))
     LEFT JOIN LATERAL ( SELECT x.synt_kalypsis,
            x.remarks,
            round(((((100)::double precision * public.st_area(public.st_intersection(x.geom, b.geom))) / NULLIF(public.st_area(b.geom), (0)::double precision)))::numeric, 1) AS match_pct
           FROM epoleodomia.building_regs_coverage x
          WHERE (public.st_intersects(x.geom, b.geom) AND (NOT COALESCE(x.is_deleted, false)))
          ORDER BY (public.st_area(public.st_intersection(x.geom, b.geom))) DESC
         LIMIT 1) c ON (true))
     LEFT JOIN LATERAL ( SELECT x.sd_timh,
            x.sd_tomeas,
            x.sd_klimakotos,
            x.sd_comment,
            round(((((100)::double precision * public.st_area(public.st_intersection(x.geom, b.geom))) / NULLIF(public.st_area(b.geom), (0)::double precision)))::numeric, 1) AS match_pct
           FROM epoleodomia.building_regs_coefficient x
          WHERE (public.st_intersects(x.geom, b.geom) AND (NOT COALESCE(x.is_deleted, false)))
          ORDER BY (public.st_area(public.st_intersection(x.geom, b.geom))) DESC
         LIMIT 1) f ON (true))
     LEFT JOIN LATERAL ( SELECT x.sd_timh,
            x.sd_tomeas,
            x.sd_klimakotos,
            x.sd_comment,
            round(((((100)::double precision * public.st_area(public.st_intersection(x.geom, b.geom))) / NULLIF(public.st_area(b.geom), (0)::double precision)))::numeric, 1) AS match_pct
           FROM epoleodomia.building_regs_coefficient_zones x
          WHERE (public.st_intersects(x.geom, b.geom) AND (NOT COALESCE(x.is_deleted, false)))
          ORDER BY (public.st_area(public.st_intersection(x.geom, b.geom))) DESC
         LIMIT 1) z ON (true))
     LEFT JOIN LATERAL ( SELECT x.elax_embado_m2,
            x.elax_prosop_m,
            x.oros_type,
            round(((((100)::double precision * public.st_area(public.st_intersection(x.geom, b.geom))) / NULLIF(public.st_area(b.geom), (0)::double precision)))::numeric, 1) AS match_pct
           FROM epoleodomia.building_regs_lot x
          WHERE (public.st_intersects(x.geom, b.geom) AND (NOT COALESCE(x.is_deleted, false)) AND ((x.oros_type)::text = 'ΚΑΤΑ ΚΑΝΟΝΑ'::text))
          ORDER BY (public.st_area(public.st_intersection(x.geom, b.geom))) DESC
         LIMIT 1) lk ON (true))
     LEFT JOIN LATERAL ( SELECT x.oros_type,
            x.date_pareklisis,
            x.remarks
           FROM epoleodomia.building_regs_lot x
          WHERE (public.st_intersects(x.geom, b.geom) AND (NOT COALESCE(x.is_deleted, false)) AND ((x.oros_type)::text = 'ΚΑΤΑ ΠΑΡΕΚΚΛΙΣΗ'::text))
          ORDER BY (public.st_area(public.st_intersection(x.geom, b.geom))) DESC
         LIMIT 1) lp ON (true))
     LEFT JOIN LATERAL ( SELECT x.oik_systima,
            round(((((100)::double precision * public.st_area(public.st_intersection(x.geom, b.geom))) / NULLIF(public.st_area(b.geom), (0)::double precision)))::numeric, 1) AS match_pct
           FROM epoleodomia.building_regs_system x
          WHERE (public.st_intersects(x.geom, b.geom) AND (NOT COALESCE(x.is_deleted, false)))
          ORDER BY (public.st_area(public.st_intersection(x.geom, b.geom))) DESC
         LIMIT 1) s ON (true))
     LEFT JOIN LATERAL ( SELECT x.per_cat_gen,
            x.per_cat_eid,
            x.remarks,
            round(((((100)::double precision * public.st_area(public.st_intersection(x.geom, b.geom))) / NULLIF(public.st_area(b.geom), (0)::double precision)))::numeric, 1) AS match_pct
           FROM epoleodomia.land_uses_ers x
          WHERE (public.st_intersects(x.geom, b.geom) AND (NOT COALESCE(x.is_deleted, false)))
          ORDER BY (public.st_area(public.st_intersection(x.geom, b.geom))) DESC
         LIMIT 1) lu ON (true))
  WHERE (NOT COALESCE(b.is_deleted, false));


ALTER VIEW epoleodomia.v_building_blocks_regulations OWNER TO docker;

--
-- Name: VIEW v_building_blocks_regulations; Type: COMMENT; Schema: epoleodomia; Owner: docker
--

COMMENT ON VIEW epoleodomia.v_building_blocks_regulations IS 'Όροι δόμησης ανά ΟΤ. Η ζώνη κάθε διάστασης επιλέγεται με ΜΕΓΙΣΤΗ ΕΠΙΚΑΛΥΨΗ ΕΠΙΦΑΝΕΙΑΣ με το ΟΤ (όχι με σημείο). Οι στήλες *_match_pct δίνουν το ποσοστό του ΟΤ που καλύπτει η επιλεγμένη ζώνη — τιμή κάτω από ~90 σημαίνει ΟΤ που πατά σε δύο ζώνες και θέλει έλεγχο. Το coverage_pct είναι ο συντελεστής κάλυψης, όχι γεωμετρική επικάλυψη.';


--
-- Name: v_fek_references; Type: VIEW; Schema: epoleodomia; Owner: docker
--

CREATE VIEW epoleodomia.v_fek_references AS
 SELECT DISTINCT fek,
    fek_file_url,
    publ_date,
    apof_eidos,
    title,
    number_,
    sign_date,
    kall_dhm_name
   FROM ( SELECT building_blocks.fek,
            building_blocks.fek_file_url,
            building_blocks.publ_date,
            building_blocks.apof_eidos,
            building_blocks.title,
            building_blocks.number_,
            building_blocks.sign_date,
            building_blocks.kall_dhm_name
           FROM epoleodomia.building_blocks
          WHERE (building_blocks.fek IS NOT NULL)
        UNION
         SELECT planning_lines.fek,
            planning_lines.fek_file_url,
            planning_lines.publ_date,
            planning_lines.apof_eidos,
            planning_lines.title,
            planning_lines.number_,
            planning_lines.sign_date,
            planning_lines.kall_dhm_name
           FROM epoleodomia.planning_lines
          WHERE (planning_lines.fek IS NOT NULL)
        UNION
         SELECT building_lines.fek,
            building_lines.fek_file_url,
            building_lines.publ_date,
            building_lines.apof_eidos,
            building_lines.title,
            building_lines.number_,
            building_lines.sign_date,
            building_lines.kall_dhm_name
           FROM epoleodomia.building_lines
          WHERE (building_lines.fek IS NOT NULL)
        UNION
         SELECT settlement_boundaries.fek,
            settlement_boundaries.fek_file_url,
            settlement_boundaries.publ_date,
            settlement_boundaries.apof_eidos,
            settlement_boundaries.title,
            settlement_boundaries.number_,
            settlement_boundaries.sign_date,
            settlement_boundaries.kall_dhm_name
           FROM epoleodomia.settlement_boundaries
          WHERE (settlement_boundaries.fek IS NOT NULL)
        UNION
         SELECT building_regs_height.fek,
            building_regs_height.fek_file_url,
            building_regs_height.publ_date,
            building_regs_height.apof_eidos,
            building_regs_height.title,
            building_regs_height.number_,
            building_regs_height.sign_date,
            building_regs_height.kall_dhm_name
           FROM epoleodomia.building_regs_height
          WHERE (building_regs_height.fek IS NOT NULL)
        UNION
         SELECT building_regs_coverage.fek,
            building_regs_coverage.fek_file_url,
            building_regs_coverage.publ_date,
            building_regs_coverage.apof_eidos,
            building_regs_coverage.title,
            building_regs_coverage.number_,
            building_regs_coverage.sign_date,
            building_regs_coverage.kall_dhm_name
           FROM epoleodomia.building_regs_coverage
          WHERE (building_regs_coverage.fek IS NOT NULL)
        UNION
         SELECT building_regs_coefficient.fek,
            building_regs_coefficient.fek_file_url,
            building_regs_coefficient.publ_date,
            building_regs_coefficient.apof_eidos,
            building_regs_coefficient.title,
            building_regs_coefficient.number_,
            building_regs_coefficient.sign_date,
            building_regs_coefficient.kall_dhm_name
           FROM epoleodomia.building_regs_coefficient
          WHERE (building_regs_coefficient.fek IS NOT NULL)
        UNION
         SELECT land_uses_gps.fek,
            land_uses_gps.fek_file_url,
            land_uses_gps.publ_date,
            land_uses_gps.apof_eidos,
            land_uses_gps.title,
            land_uses_gps.number_,
            land_uses_gps.sign_date,
            land_uses_gps.kall_dhm_name
           FROM epoleodomia.land_uses_gps
          WHERE (land_uses_gps.fek IS NOT NULL)
        UNION
         SELECT planning_diagrams.fek,
            planning_diagrams.fek_file_url,
            planning_diagrams.publ_date,
            planning_diagrams.apof_eidos,
            planning_diagrams.title,
            planning_diagrams.number_,
            planning_diagrams.sign_date,
            NULL::character varying
           FROM epoleodomia.planning_diagrams
          WHERE (planning_diagrams.fek IS NOT NULL)) combined
  ORDER BY fek;


ALTER VIEW epoleodomia.v_fek_references OWNER TO docker;

--
-- Name: VIEW v_fek_references; Type: COMMENT; Schema: epoleodomia; Owner: docker
--

COMMENT ON VIEW epoleodomia.v_fek_references IS 'Normalized view of all FEK (Government Gazette) references across tables';


--
-- Name: v_land_uses_summary; Type: VIEW; Schema: epoleodomia; Owner: docker
--

CREATE VIEW epoleodomia.v_land_uses_summary AS
 SELECT COALESCE(gps.id, ers.id) AS id,
    COALESCE(gps.gen_xrhsh_gps, ers.per_cat_gen) AS general_use,
    COALESCE(gps.per_cat_gen, ers.per_cat_gen) AS category_general,
    COALESCE(gps.per_cat_eid, ers.per_cat_eid) AS category_specific,
    COALESCE(gps.remarks, ers.remarks) AS remarks,
    COALESCE(gps.fek, ers.fek) AS fek,
    COALESCE(gps.kall_dhm_name, ers.kall_dhm_name) AS municipality,
    COALESCE(gps.geom, ers.geom) AS geom,
        CASE
            WHEN (gps.id IS NOT NULL) THEN 'GPS'::text
            ELSE 'ERS'::text
        END AS source
   FROM (epoleodomia.land_uses_gps gps
     FULL JOIN epoleodomia.land_uses_ers ers ON ((((gps.fek)::text = (ers.fek)::text) AND public.st_equals(gps.geom, ers.geom))));


ALTER VIEW epoleodomia.v_land_uses_summary OWNER TO docker;

--
-- Name: v_oroi_domisis_flags; Type: VIEW; Schema: epoleodomia; Owner: docker
--

CREATE VIEW epoleodomia.v_oroi_domisis_flags AS
 WITH b AS (
         SELECT building_blocks.id,
            building_blocks.ot_num,
            building_blocks.kall_dhm_name,
            building_blocks.fek,
            building_blocks.geom,
            public.st_area(building_blocks.geom) AS a,
            ((regexp_match((building_blocks.fek)::text, '/(\d{4})\s*$'::text))[1])::integer AS etos
           FROM epoleodomia.building_blocks
          WHERE (NOT COALESCE(building_blocks.is_deleted, false))
        ), z AS (
         SELECT b_1.id,
            ( SELECT round(((((100)::double precision * public.st_area(public.st_intersection(x.geom, b_1.geom))) / NULLIF(b_1.a, (0)::double precision)))::numeric, 1) AS round
                   FROM epoleodomia.building_regs_height x
                  WHERE (public.st_intersects(x.geom, b_1.geom) AND (NOT COALESCE(x.is_deleted, false)))
                  ORDER BY (public.st_area(public.st_intersection(x.geom, b_1.geom))) DESC
                 LIMIT 1) AS h_pct,
            ( SELECT round(((((100)::double precision * public.st_area(public.st_intersection(x.geom, b_1.geom))) / NULLIF(b_1.a, (0)::double precision)))::numeric, 1) AS round
                   FROM epoleodomia.building_regs_coefficient x
                  WHERE (public.st_intersects(x.geom, b_1.geom) AND (NOT COALESCE(x.is_deleted, false)))
                  ORDER BY (public.st_area(public.st_intersection(x.geom, b_1.geom))) DESC
                 LIMIT 1) AS sd_pct,
            ( SELECT round(((((100)::double precision * public.st_area(public.st_intersection(x.geom, b_1.geom))) / NULLIF(b_1.a, (0)::double precision)))::numeric, 1) AS round
                   FROM epoleodomia.building_regs_coverage x
                  WHERE (public.st_intersects(x.geom, b_1.geom) AND (NOT COALESCE(x.is_deleted, false)))
                  ORDER BY (public.st_area(public.st_intersection(x.geom, b_1.geom))) DESC
                 LIMIT 1) AS c_pct
           FROM b b_1
        ), praxeis AS (
         SELECT b_1.id,
            string_agg(((((((p.fek)::text || ' — '::text) || (COALESCE(p.apof_theme, ''::character varying))::text) || ' ('::text) || round(((((100)::double precision * public.st_area(public.st_intersection(p.geom, b_1.geom))) / b_1.a))::numeric, 0)) || '%)'::text), '
'::text ORDER BY (p.publ_date)::date) AS praxeis_info,
            string_agg(DISTINCT (p.fek_file_url)::text, '
'::text) AS fek_urls,
            max((p.publ_date)::date) AS teleftaia_praxi
           FROM (b b_1
             JOIN epoleodomia.approved_plan_boundaries p ON (((NOT COALESCE(p.is_deleted, false)) AND (public.st_area(p.geom) < (100000)::double precision) AND (EXTRACT(year FROM (p.publ_date)::date) > (b_1.etos)::numeric) AND public.st_intersects(p.geom, b_1.geom) AND (public.st_area(public.st_intersection(p.geom, b_1.geom)) > GREATEST(((0.10)::double precision * b_1.a), (250)::double precision)))))
          GROUP BY b_1.id
        )
 SELECT b.id,
    b.ot_num,
    b.kall_dhm_name AS dimos,
    b.fek AS fek_ot,
    round((b.a)::numeric, 1) AS emvadon_m2,
    pr.praxeis_info,
    pr.fek_urls,
    pr.teleftaia_praxi,
    LEAST(z.h_pct, z.sd_pct, z.c_pct) AS min_pct,
    array_remove(ARRAY[
        CASE
            WHEN (pr.id IS NOT NULL) THEN 'Σ1 νεότερη πράξη επί του ΟΤ'::text
            ELSE NULL::text
        END,
        CASE
            WHEN ((b.ot_num)::text ~ '[-/,]'::text) THEN 'Σ2 ένωση ΟΤ'::text
            ELSE NULL::text
        END,
        CASE
            WHEN (LEAST(COALESCE(z.h_pct, (100)::numeric), COALESCE(z.sd_pct, (100)::numeric), COALESCE(z.c_pct, (100)::numeric)) < (99)::numeric) THEN 'Σ3 πατά σε δύο ζώνες'::text
            ELSE NULL::text
        END,
        CASE
            WHEN (NOT public.st_intersects(public.st_centroid(b.geom), b.geom)) THEN 'Σ4 κεντροειδές εκτός'::text
            ELSE NULL::text
        END,
        CASE
            WHEN ((z.h_pct IS NULL) OR (z.sd_pct IS NULL) OR (z.c_pct IS NULL)) THEN 'Σ5 λείπουν όροι'::text
            ELSE NULL::text
        END], NULL::text) AS flags,
        CASE
            WHEN ((pr.id IS NOT NULL) OR ((b.ot_num)::text ~ '[-/,]'::text)) THEN 'ΑΝΟΙΞΕ ΤΟ ΦΕΚ'::text
            WHEN ((LEAST(COALESCE(z.h_pct, (100)::numeric), COALESCE(z.sd_pct, (100)::numeric), COALESCE(z.c_pct, (100)::numeric)) < (99)::numeric) OR (z.h_pct IS NULL) OR (z.sd_pct IS NULL) OR (z.c_pct IS NULL)) THEN 'ΕΛΕΓΞΕ'::text
            WHEN (NOT public.st_intersects(public.st_centroid(b.geom), b.geom)) THEN 'ΤΕΧΝΙΚΟ'::text
            ELSE NULL::text
        END AS epipedo,
    b.geom
   FROM ((b
     JOIN z ON ((z.id = b.id)))
     LEFT JOIN praxeis pr ON ((pr.id = b.id)))
  WHERE ((pr.id IS NOT NULL) OR ((b.ot_num)::text ~ '[-/,]'::text) OR (LEAST(COALESCE(z.h_pct, (100)::numeric), COALESCE(z.sd_pct, (100)::numeric), COALESCE(z.c_pct, (100)::numeric)) < (99)::numeric) OR (NOT public.st_intersects(public.st_centroid(b.geom), b.geom)) OR (z.h_pct IS NULL) OR (z.sd_pct IS NULL) OR (z.c_pct IS NULL));


ALTER VIEW epoleodomia.v_oroi_domisis_flags OWNER TO docker;

--
-- Name: VIEW v_oroi_domisis_flags; Type: COMMENT; Schema: epoleodomia; Owner: docker
--

COMMENT ON VIEW epoleodomia.v_oroi_domisis_flags IS 'v2 (28.08.2026): ΟΤ όπου τα δεδομένα ΤΕΕ δεν αρκούν χωρίς έλεγχο στο ΦΕΚ. Σ1 βασισμένη στα πραγματικά όρια πράξεων του approved_plan_boundaries (πράξεις < 100 στρ., τομή > max(10% ΟΤ, 250 m²), έτος ΦΕΚ πράξης > έτος ΦΕΚ του ΟΤ). praxeis_info: ΦΕΚ — θέμα (% τομής)· fek_urls: PDF. Δεν διορθώνει — σημαδεύει.';


--
-- Name: v_planning_lines_all; Type: VIEW; Schema: epoleodomia; Owner: docker
--

CREATE VIEW epoleodomia.v_planning_lines_all AS
 SELECT 'planning'::text AS line_type,
    planning_lines.rg_type AS subtype,
    planning_lines.fek,
    planning_lines.road_width,
    planning_lines.prasia_width,
    planning_lines.kall_dhm_name AS municipality,
    planning_lines.geom
   FROM epoleodomia.planning_lines
UNION ALL
 SELECT 'building'::text AS line_type,
    building_lines.og_type AS subtype,
    building_lines.fek,
    NULL::integer AS road_width,
    building_lines.prasia_width,
    building_lines.kall_dhm_name AS municipality,
    building_lines.geom
   FROM epoleodomia.building_lines
UNION ALL
 SELECT 'other'::text AS line_type,
    other_planning_lines.pol_gr_type AS subtype,
    other_planning_lines.fek,
    NULL::integer AS road_width,
    NULL::integer AS prasia_width,
    other_planning_lines.kall_dhm_name AS municipality,
    other_planning_lines.geom
   FROM epoleodomia.other_planning_lines;


ALTER VIEW epoleodomia.v_planning_lines_all OWNER TO docker;

--
-- Name: VIEW v_planning_lines_all; Type: COMMENT; Schema: epoleodomia; Owner: docker
--

COMMENT ON VIEW epoleodomia.v_planning_lines_all IS 'Combined view of all planning lines (planning, building, other)';


--
-- Name: v_protected_areas; Type: VIEW; Schema: epoleodomia; Owner: docker
--

CREATE VIEW epoleodomia.v_protected_areas AS
 SELECT 'archaeological_pl'::text AS protection_type,
    archaeological_zones_pl.zone_name AS name,
    archaeological_zones_pl.zone_type AS subtype,
    archaeological_zones_pl.fek,
    archaeological_zones_pl.kall_dhm_name AS municipality,
    archaeological_zones_pl.geom
   FROM epoleodomia.archaeological_zones_pl
UNION ALL
 SELECT 'archaeological_site'::text AS protection_type,
    archaeological_sites_polygons.name,
    NULL::character varying AS subtype,
    NULL::character varying AS fek,
    archaeological_sites_polygons.ota AS municipality,
    archaeological_sites_polygons.geom
   FROM epoleodomia.archaeological_sites_polygons
UNION ALL
 SELECT 'protection_zone'::text AS protection_type,
    protection_zones_polygons.name,
    NULL::character varying AS subtype,
    NULL::character varying AS fek,
    protection_zones_polygons.ota AS municipality,
    protection_zones_polygons.geom
   FROM epoleodomia.protection_zones_polygons
UNION ALL
 SELECT 'historic_site'::text AS protection_type,
    historic_sites_polygons.name,
    NULL::character varying AS subtype,
    NULL::character varying AS fek,
    historic_sites_polygons.ota AS municipality,
    historic_sites_polygons.geom
   FROM epoleodomia.historic_sites_polygons
UNION ALL
 SELECT 'natura_2000'::text AS protection_type,
    natura_2000.sitename AS name,
    natura_2000.sitetype AS subtype,
    NULL::character varying AS fek,
    NULL::character varying AS municipality,
    natura_2000.geom
   FROM epoleodomia.natura_2000;


ALTER VIEW epoleodomia.v_protected_areas OWNER TO docker;

--
-- Name: VIEW v_protected_areas; Type: COMMENT; Schema: epoleodomia; Owner: docker
--

COMMENT ON VIEW epoleodomia.v_protected_areas IS 'Combined view of all protected areas (archaeological, historic, natura)';


--
-- Name: v_rasters_by_fek; Type: VIEW; Schema: epoleodomia; Owner: docker
--

CREATE VIEW epoleodomia.v_rasters_by_fek AS
 SELECT fek,
    count(*) AS total_rasters,
    count(*) FILTER (WHERE ((download_status)::text = 'downloaded'::text)) AS downloaded,
    count(*) FILTER (WHERE ((download_status)::text = 'pending'::text)) AS pending,
    count(*) FILTER (WHERE ((download_status)::text = 'failed'::text)) AS failed,
    sum(file_size_bytes) FILTER (WHERE ((download_status)::text = 'downloaded'::text)) AS total_size_bytes,
    round(((sum(file_size_bytes) FILTER (WHERE ((download_status)::text = 'downloaded'::text)) / 1024.0) / 1024.0), 2) AS total_size_mb
   FROM epoleodomia.raster_catalog
  GROUP BY fek
  ORDER BY fek;


ALTER VIEW epoleodomia.v_rasters_by_fek OWNER TO docker;

--
-- Name: v_rasters_downloaded; Type: VIEW; Schema: epoleodomia; Owner: docker
--

CREATE VIEW epoleodomia.v_rasters_downloaded AS
 SELECT id,
    fek,
    filename,
    local_path_georef,
    file_size_bytes,
    width_px,
    height_px,
    resolution_x AS meters_per_pixel,
    crs_epsg,
    georef_rms,
    original_scale,
    downloaded_at,
    public.st_astext(bbox) AS bbox_wkt
   FROM epoleodomia.raster_catalog rc
  WHERE ((download_status)::text = 'downloaded'::text)
  ORDER BY fek, filename;


ALTER VIEW epoleodomia.v_rasters_downloaded OWNER TO docker;

--
-- Name: v_rasters_failed; Type: VIEW; Schema: epoleodomia; Owner: docker
--

CREATE VIEW epoleodomia.v_rasters_failed AS
 SELECT id,
    fek,
    filename,
    url_georef,
    download_error,
    last_checked
   FROM epoleodomia.raster_catalog
  WHERE ((download_status)::text = 'failed'::text)
  ORDER BY last_checked DESC;


ALTER VIEW epoleodomia.v_rasters_failed OWNER TO docker;

--
-- Name: v_rasters_pending; Type: VIEW; Schema: epoleodomia; Owner: docker
--

CREATE VIEW epoleodomia.v_rasters_pending AS
 SELECT id,
    fek,
    filename,
    url_georef,
    georef_rms,
    original_scale
   FROM epoleodomia.raster_catalog
  WHERE ((download_status)::text = 'pending'::text)
  ORDER BY fek, filename;


ALTER VIEW epoleodomia.v_rasters_pending OWNER TO docker;

--
-- Name: v_sync_status; Type: VIEW; Schema: epoleodomia; Owner: docker
--

CREATE VIEW epoleodomia.v_sync_status AS
 SELECT table_name,
    service_name,
    layer_id,
    records_fetched,
    status,
    sync_completed_at,
        CASE
            WHEN (sync_completed_at IS NULL) THEN 'Never synced'::text
            WHEN (sync_completed_at < (now() - '7 days'::interval)) THEN 'Stale (>7 days)'::text
            WHEN (sync_completed_at < (now() - '1 day'::interval)) THEN 'Recent (1-7 days)'::text
            ELSE 'Fresh (<1 day)'::text
        END AS freshness
   FROM epoleodomia.sync_log sl
  WHERE (id = ( SELECT max(sl2.id) AS max
           FROM epoleodomia.sync_log sl2
          WHERE ((sl2.table_name)::text = (sl.table_name)::text)))
  ORDER BY sync_completed_at DESC NULLS LAST;


ALTER VIEW epoleodomia.v_sync_status OWNER TO docker;

--
-- Name: VIEW v_sync_status; Type: COMMENT; Schema: epoleodomia; Owner: docker
--

COMMENT ON VIEW epoleodomia.v_sync_status IS 'Latest sync status for each table';


--
-- Name: zoe_zones; Type: TABLE; Schema: epoleodomia; Owner: docker
--

CREATE TABLE epoleodomia.zoe_zones (
    id integer NOT NULL,
    objectid integer,
    fek character varying(255),
    fek_file_url character varying(2000),
    zone_name character varying(255),
    zone_type character varying(255),
    geom public.geometry(Polygon,2100),
    fetched_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE epoleodomia.zoe_zones OWNER TO docker;

--
-- Name: zoe_zones_id_seq; Type: SEQUENCE; Schema: epoleodomia; Owner: docker
--

CREATE SEQUENCE epoleodomia.zoe_zones_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE epoleodomia.zoe_zones_id_seq OWNER TO docker;

--
-- Name: zoe_zones_id_seq; Type: SEQUENCE OWNED BY; Schema: epoleodomia; Owner: docker
--

ALTER SEQUENCE epoleodomia.zoe_zones_id_seq OWNED BY epoleodomia.zoe_zones.id;


--
-- Name: ab_zones_attica id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.ab_zones_attica ALTER COLUMN id SET DEFAULT nextval('epoleodomia.ab_zones_attica_id_seq'::regclass);


--
-- Name: addresses id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.addresses ALTER COLUMN id SET DEFAULT nextval('epoleodomia.addresses_id_seq'::regclass);


--
-- Name: approved_plan_boundaries id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.approved_plan_boundaries ALTER COLUMN id SET DEFAULT nextval('epoleodomia.approved_plan_boundaries_id_seq'::regclass);


--
-- Name: archaeological_sites_lines id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.archaeological_sites_lines ALTER COLUMN id SET DEFAULT nextval('epoleodomia.archaeological_sites_lines_id_seq'::regclass);


--
-- Name: archaeological_sites_points id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.archaeological_sites_points ALTER COLUMN id SET DEFAULT nextval('epoleodomia.archaeological_sites_points_id_seq'::regclass);


--
-- Name: archaeological_sites_polygons id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.archaeological_sites_polygons ALTER COLUMN id SET DEFAULT nextval('epoleodomia.archaeological_sites_polygons_id_seq'::regclass);


--
-- Name: archaeological_zones_pl id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.archaeological_zones_pl ALTER COLUMN id SET DEFAULT nextval('epoleodomia.archaeological_zones_pl_id_seq'::regclass);


--
-- Name: block_vertices id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.block_vertices ALTER COLUMN id SET DEFAULT nextval('epoleodomia.block_vertices_id_seq'::regclass);


--
-- Name: building_blocks id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.building_blocks ALTER COLUMN id SET DEFAULT nextval('epoleodomia.building_blocks_id_seq'::regclass);


--
-- Name: building_lines id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.building_lines ALTER COLUMN id SET DEFAULT nextval('epoleodomia.building_lines_id_seq'::regclass);


--
-- Name: building_regs_coefficient id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.building_regs_coefficient ALTER COLUMN id SET DEFAULT nextval('epoleodomia.building_regs_coefficient_id_seq'::regclass);


--
-- Name: building_regs_coefficient_zones id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.building_regs_coefficient_zones ALTER COLUMN id SET DEFAULT nextval('epoleodomia.building_regs_coefficient_zones_id_seq'::regclass);


--
-- Name: building_regs_coverage id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.building_regs_coverage ALTER COLUMN id SET DEFAULT nextval('epoleodomia.building_regs_coverage_id_seq'::regclass);


--
-- Name: building_regs_height id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.building_regs_height ALTER COLUMN id SET DEFAULT nextval('epoleodomia.building_regs_height_id_seq'::regclass);


--
-- Name: building_regs_lot id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.building_regs_lot ALTER COLUMN id SET DEFAULT nextval('epoleodomia.building_regs_lot_id_seq'::regclass);


--
-- Name: building_regs_system id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.building_regs_system ALTER COLUMN id SET DEFAULT nextval('epoleodomia.building_regs_system_id_seq'::regclass);


--
-- Name: census_blocks_2021 id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.census_blocks_2021 ALTER COLUMN id SET DEFAULT nextval('epoleodomia.census_blocks_2021_id_seq'::regclass);


--
-- Name: expropriation_zones id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.expropriation_zones ALTER COLUMN id SET DEFAULT nextval('epoleodomia.expropriation_zones_id_seq'::regclass);


--
-- Name: fek_no_diagrams id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.fek_no_diagrams ALTER COLUMN id SET DEFAULT nextval('epoleodomia.fek_no_diagrams_id_seq'::regclass);


--
-- Name: forest_maps id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.forest_maps ALTER COLUMN id SET DEFAULT nextval('epoleodomia.forest_maps_id_seq'::regclass);


--
-- Name: forest_maps_posted_attica_2021 id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.forest_maps_posted_attica_2021 ALTER COLUMN id SET DEFAULT nextval('epoleodomia.forest_maps_posted_attica_2021_id_seq'::regclass);


--
-- Name: forest_maps_posted_pelop_2022 id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.forest_maps_posted_pelop_2022 ALTER COLUMN id SET DEFAULT nextval('epoleodomia.forest_maps_posted_pelop_2022_id_seq'::regclass);


--
-- Name: historic_sites_lines id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.historic_sites_lines ALTER COLUMN id SET DEFAULT nextval('epoleodomia.historic_sites_lines_id_seq'::regclass);


--
-- Name: historic_sites_points id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.historic_sites_points ALTER COLUMN id SET DEFAULT nextval('epoleodomia.historic_sites_points_id_seq'::regclass);


--
-- Name: historic_sites_polygons id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.historic_sites_polygons ALTER COLUMN id SET DEFAULT nextval('epoleodomia.historic_sites_polygons_id_seq'::regclass);


--
-- Name: land_uses_ers id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.land_uses_ers ALTER COLUMN id SET DEFAULT nextval('epoleodomia.land_uses_ers_id_seq'::regclass);


--
-- Name: land_uses_gps id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.land_uses_gps ALTER COLUMN id SET DEFAULT nextval('epoleodomia.land_uses_gps_id_seq'::regclass);


--
-- Name: monuments_lines id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.monuments_lines ALTER COLUMN id SET DEFAULT nextval('epoleodomia.monuments_lines_id_seq'::regclass);


--
-- Name: monuments_points id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.monuments_points ALTER COLUMN id SET DEFAULT nextval('epoleodomia.monuments_points_id_seq'::regclass);


--
-- Name: monuments_polygons id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.monuments_polygons ALTER COLUMN id SET DEFAULT nextval('epoleodomia.monuments_polygons_id_seq'::regclass);


--
-- Name: municipal_communities_2021 id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.municipal_communities_2021 ALTER COLUMN id SET DEFAULT nextval('epoleodomia.municipal_communities_2021_id_seq'::regclass);


--
-- Name: municipal_units_2021 id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.municipal_units_2021 ALTER COLUMN id SET DEFAULT nextval('epoleodomia.municipal_units_2021_id_seq'::regclass);


--
-- Name: municipalities_2021 id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.municipalities_2021 ALTER COLUMN id SET DEFAULT nextval('epoleodomia.municipalities_2021_id_seq'::regclass);


--
-- Name: natura_2000 id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.natura_2000 ALTER COLUMN id SET DEFAULT nextval('epoleodomia.natura_2000_id_seq'::regclass);


--
-- Name: natural_landscapes_points id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.natural_landscapes_points ALTER COLUMN id SET DEFAULT nextval('epoleodomia.natural_landscapes_points_id_seq'::regclass);


--
-- Name: natural_landscapes_polygons id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.natural_landscapes_polygons ALTER COLUMN id SET DEFAULT nextval('epoleodomia.natural_landscapes_polygons_id_seq'::regclass);


--
-- Name: other_planning_lines id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.other_planning_lines ALTER COLUMN id SET DEFAULT nextval('epoleodomia.other_planning_lines_id_seq'::regclass);


--
-- Name: other_planning_zones id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.other_planning_zones ALTER COLUMN id SET DEFAULT nextval('epoleodomia.other_planning_zones_id_seq'::regclass);


--
-- Name: outside_plan_areas id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.outside_plan_areas ALTER COLUMN id SET DEFAULT nextval('epoleodomia.outside_plan_areas_id_seq'::regclass);


--
-- Name: pd_protection_zones id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.pd_protection_zones ALTER COLUMN id SET DEFAULT nextval('epoleodomia.pd_protection_zones_id_seq'::regclass);


--
-- Name: pedestrian_zones id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.pedestrian_zones ALTER COLUMN id SET DEFAULT nextval('epoleodomia.pedestrian_zones_id_seq'::regclass);


--
-- Name: planning_diagrams id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.planning_diagrams ALTER COLUMN id SET DEFAULT nextval('epoleodomia.planning_diagrams_id_seq'::regclass);


--
-- Name: planning_lines id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.planning_lines ALTER COLUMN id SET DEFAULT nextval('epoleodomia.planning_lines_id_seq'::regclass);


--
-- Name: protected_buildings id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.protected_buildings ALTER COLUMN id SET DEFAULT nextval('epoleodomia.protected_buildings_id_seq'::regclass);


--
-- Name: protection_zones_lines id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.protection_zones_lines ALTER COLUMN id SET DEFAULT nextval('epoleodomia.protection_zones_lines_id_seq'::regclass);


--
-- Name: protection_zones_points id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.protection_zones_points ALTER COLUMN id SET DEFAULT nextval('epoleodomia.protection_zones_points_id_seq'::regclass);


--
-- Name: protection_zones_polygons id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.protection_zones_polygons ALTER COLUMN id SET DEFAULT nextval('epoleodomia.protection_zones_polygons_id_seq'::regclass);


--
-- Name: public_spaces id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.public_spaces ALTER COLUMN id SET DEFAULT nextval('epoleodomia.public_spaces_id_seq'::regclass);


--
-- Name: raster_catalog id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.raster_catalog ALTER COLUMN id SET DEFAULT nextval('epoleodomia.raster_catalog_id_seq'::regclass);


--
-- Name: settlement_boundaries id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.settlement_boundaries ALTER COLUMN id SET DEFAULT nextval('epoleodomia.settlement_boundaries_id_seq'::regclass);


--
-- Name: settlements_2021 id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.settlements_2021 ALTER COLUMN id SET DEFAULT nextval('epoleodomia.settlements_2021_id_seq'::regclass);


--
-- Name: shorelines id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.shorelines ALTER COLUMN id SET DEFAULT nextval('epoleodomia.shorelines_id_seq'::regclass);


--
-- Name: spetses island bb id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia."spetses island bb" ALTER COLUMN id SET DEFAULT nextval('epoleodomia."spetses island bb_id_seq"'::regclass);


--
-- Name: streams id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.streams ALTER COLUMN id SET DEFAULT nextval('epoleodomia.streams_id_seq'::regclass);


--
-- Name: streams_environmental id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.streams_environmental ALTER COLUMN id SET DEFAULT nextval('epoleodomia.streams_environmental_id_seq'::regclass);


--
-- Name: sync_log id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.sync_log ALTER COLUMN id SET DEFAULT nextval('epoleodomia.sync_log_id_seq'::regclass);


--
-- Name: urban_units id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.urban_units ALTER COLUMN id SET DEFAULT nextval('epoleodomia.urban_units_id_seq'::regclass);


--
-- Name: zoe_zones id; Type: DEFAULT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.zoe_zones ALTER COLUMN id SET DEFAULT nextval('epoleodomia.zoe_zones_id_seq'::regclass);


--
-- Name: ab_zones_attica ab_zones_attica_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.ab_zones_attica
    ADD CONSTRAINT ab_zones_attica_pkey PRIMARY KEY (id);


--
-- Name: addresses addresses_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.addresses
    ADD CONSTRAINT addresses_pkey PRIMARY KEY (id);


--
-- Name: approved_plan_boundaries approved_plan_boundaries_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.approved_plan_boundaries
    ADD CONSTRAINT approved_plan_boundaries_pkey PRIMARY KEY (id);


--
-- Name: archaeological_sites_lines archaeological_sites_lines_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.archaeological_sites_lines
    ADD CONSTRAINT archaeological_sites_lines_pkey PRIMARY KEY (id);


--
-- Name: archaeological_sites_points archaeological_sites_points_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.archaeological_sites_points
    ADD CONSTRAINT archaeological_sites_points_pkey PRIMARY KEY (id);


--
-- Name: archaeological_sites_polygons archaeological_sites_polygons_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.archaeological_sites_polygons
    ADD CONSTRAINT archaeological_sites_polygons_pkey PRIMARY KEY (id);


--
-- Name: archaeological_zones_pl archaeological_zones_pl_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.archaeological_zones_pl
    ADD CONSTRAINT archaeological_zones_pl_pkey PRIMARY KEY (id);


--
-- Name: block_vertices block_vertices_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.block_vertices
    ADD CONSTRAINT block_vertices_pkey PRIMARY KEY (id);


--
-- Name: building_blocks building_blocks_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.building_blocks
    ADD CONSTRAINT building_blocks_pkey PRIMARY KEY (id);


--
-- Name: building_lines building_lines_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.building_lines
    ADD CONSTRAINT building_lines_pkey PRIMARY KEY (id);


--
-- Name: building_regs_coefficient building_regs_coefficient_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.building_regs_coefficient
    ADD CONSTRAINT building_regs_coefficient_pkey PRIMARY KEY (id);


--
-- Name: building_regs_coefficient_zones building_regs_coefficient_zones_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.building_regs_coefficient_zones
    ADD CONSTRAINT building_regs_coefficient_zones_pkey PRIMARY KEY (id);


--
-- Name: building_regs_coverage building_regs_coverage_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.building_regs_coverage
    ADD CONSTRAINT building_regs_coverage_pkey PRIMARY KEY (id);


--
-- Name: building_regs_height building_regs_height_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.building_regs_height
    ADD CONSTRAINT building_regs_height_pkey PRIMARY KEY (id);


--
-- Name: building_regs_lot building_regs_lot_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.building_regs_lot
    ADD CONSTRAINT building_regs_lot_pkey PRIMARY KEY (id);


--
-- Name: building_regs_system building_regs_system_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.building_regs_system
    ADD CONSTRAINT building_regs_system_pkey PRIMARY KEY (id);


--
-- Name: census_blocks_2021 census_blocks_2021_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.census_blocks_2021
    ADD CONSTRAINT census_blocks_2021_pkey PRIMARY KEY (id);


--
-- Name: expropriation_zones expropriation_zones_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.expropriation_zones
    ADD CONSTRAINT expropriation_zones_pkey PRIMARY KEY (id);


--
-- Name: fek_no_diagrams fek_no_diagrams_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.fek_no_diagrams
    ADD CONSTRAINT fek_no_diagrams_pkey PRIMARY KEY (id);


--
-- Name: forest_maps forest_maps_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.forest_maps
    ADD CONSTRAINT forest_maps_pkey PRIMARY KEY (id);


--
-- Name: forest_maps_posted_attica_2021 forest_maps_posted_attica_2021_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.forest_maps_posted_attica_2021
    ADD CONSTRAINT forest_maps_posted_attica_2021_pkey PRIMARY KEY (id);


--
-- Name: forest_maps_posted_pelop_2022 forest_maps_posted_pelop_2022_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.forest_maps_posted_pelop_2022
    ADD CONSTRAINT forest_maps_posted_pelop_2022_pkey PRIMARY KEY (id);


--
-- Name: historic_sites_lines historic_sites_lines_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.historic_sites_lines
    ADD CONSTRAINT historic_sites_lines_pkey PRIMARY KEY (id);


--
-- Name: historic_sites_points historic_sites_points_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.historic_sites_points
    ADD CONSTRAINT historic_sites_points_pkey PRIMARY KEY (id);


--
-- Name: historic_sites_polygons historic_sites_polygons_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.historic_sites_polygons
    ADD CONSTRAINT historic_sites_polygons_pkey PRIMARY KEY (id);


--
-- Name: land_uses_ers land_uses_ers_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.land_uses_ers
    ADD CONSTRAINT land_uses_ers_pkey PRIMARY KEY (id);


--
-- Name: land_uses_gps land_uses_gps_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.land_uses_gps
    ADD CONSTRAINT land_uses_gps_pkey PRIMARY KEY (id);


--
-- Name: monuments_lines monuments_lines_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.monuments_lines
    ADD CONSTRAINT monuments_lines_pkey PRIMARY KEY (id);


--
-- Name: monuments_points monuments_points_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.monuments_points
    ADD CONSTRAINT monuments_points_pkey PRIMARY KEY (id);


--
-- Name: monuments_polygons monuments_polygons_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.monuments_polygons
    ADD CONSTRAINT monuments_polygons_pkey PRIMARY KEY (id);


--
-- Name: municipal_communities_2021 municipal_communities_2021_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.municipal_communities_2021
    ADD CONSTRAINT municipal_communities_2021_pkey PRIMARY KEY (id);


--
-- Name: municipal_units_2021 municipal_units_2021_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.municipal_units_2021
    ADD CONSTRAINT municipal_units_2021_pkey PRIMARY KEY (id);


--
-- Name: municipalities_2021 municipalities_2021_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.municipalities_2021
    ADD CONSTRAINT municipalities_2021_pkey PRIMARY KEY (id);


--
-- Name: natura_2000 natura_2000_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.natura_2000
    ADD CONSTRAINT natura_2000_pkey PRIMARY KEY (id);


--
-- Name: natural_landscapes_points natural_landscapes_points_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.natural_landscapes_points
    ADD CONSTRAINT natural_landscapes_points_pkey PRIMARY KEY (id);


--
-- Name: natural_landscapes_polygons natural_landscapes_polygons_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.natural_landscapes_polygons
    ADD CONSTRAINT natural_landscapes_polygons_pkey PRIMARY KEY (id);


--
-- Name: other_planning_lines other_planning_lines_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.other_planning_lines
    ADD CONSTRAINT other_planning_lines_pkey PRIMARY KEY (id);


--
-- Name: other_planning_zones other_planning_zones_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.other_planning_zones
    ADD CONSTRAINT other_planning_zones_pkey PRIMARY KEY (id);


--
-- Name: outside_plan_areas outside_plan_areas_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.outside_plan_areas
    ADD CONSTRAINT outside_plan_areas_pkey PRIMARY KEY (id);


--
-- Name: pd_protection_zones pd_protection_zones_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.pd_protection_zones
    ADD CONSTRAINT pd_protection_zones_pkey PRIMARY KEY (id);


--
-- Name: pedestrian_zones pedestrian_zones_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.pedestrian_zones
    ADD CONSTRAINT pedestrian_zones_pkey PRIMARY KEY (id);


--
-- Name: planning_diagrams planning_diagrams_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.planning_diagrams
    ADD CONSTRAINT planning_diagrams_pkey PRIMARY KEY (id);


--
-- Name: planning_lines planning_lines_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.planning_lines
    ADD CONSTRAINT planning_lines_pkey PRIMARY KEY (id);


--
-- Name: protected_buildings protected_buildings_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.protected_buildings
    ADD CONSTRAINT protected_buildings_pkey PRIMARY KEY (id);


--
-- Name: protection_zones_lines protection_zones_lines_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.protection_zones_lines
    ADD CONSTRAINT protection_zones_lines_pkey PRIMARY KEY (id);


--
-- Name: protection_zones_points protection_zones_points_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.protection_zones_points
    ADD CONSTRAINT protection_zones_points_pkey PRIMARY KEY (id);


--
-- Name: protection_zones_polygons protection_zones_polygons_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.protection_zones_polygons
    ADD CONSTRAINT protection_zones_polygons_pkey PRIMARY KEY (id);


--
-- Name: public_spaces public_spaces_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.public_spaces
    ADD CONSTRAINT public_spaces_pkey PRIMARY KEY (id);


--
-- Name: raster_catalog raster_catalog_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.raster_catalog
    ADD CONSTRAINT raster_catalog_pkey PRIMARY KEY (id);


--
-- Name: settlement_boundaries settlement_boundaries_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.settlement_boundaries
    ADD CONSTRAINT settlement_boundaries_pkey PRIMARY KEY (id);


--
-- Name: settlements_2021 settlements_2021_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.settlements_2021
    ADD CONSTRAINT settlements_2021_pkey PRIMARY KEY (id);


--
-- Name: shorelines shorelines_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.shorelines
    ADD CONSTRAINT shorelines_pkey PRIMARY KEY (id);


--
-- Name: spetses island bb spetses island bb_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia."spetses island bb"
    ADD CONSTRAINT "spetses island bb_pkey" PRIMARY KEY (id);


--
-- Name: streams_environmental streams_environmental_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.streams_environmental
    ADD CONSTRAINT streams_environmental_pkey PRIMARY KEY (id);


--
-- Name: streams streams_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.streams
    ADD CONSTRAINT streams_pkey PRIMARY KEY (id);


--
-- Name: sync_log sync_log_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.sync_log
    ADD CONSTRAINT sync_log_pkey PRIMARY KEY (id);


--
-- Name: urban_units urban_units_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.urban_units
    ADD CONSTRAINT urban_units_pkey PRIMARY KEY (id);


--
-- Name: zoe_zones zoe_zones_pkey; Type: CONSTRAINT; Schema: epoleodomia; Owner: docker
--

ALTER TABLE ONLY epoleodomia.zoe_zones
    ADD CONSTRAINT zoe_zones_pkey PRIMARY KEY (id);


--
-- Name: idx_ab_zones_attica_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_ab_zones_attica_geom ON epoleodomia.ab_zones_attica USING gist (geom);


--
-- Name: idx_addresses_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_addresses_geom ON epoleodomia.addresses USING gist (geom);


--
-- Name: idx_addresses_munic; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_addresses_munic ON epoleodomia.addresses USING btree (munic);


--
-- Name: idx_approved_plan_boundaries_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_approved_plan_boundaries_geom ON epoleodomia.approved_plan_boundaries USING gist (geom);


--
-- Name: idx_archaeological_sites_lines_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_archaeological_sites_lines_geom ON epoleodomia.archaeological_sites_lines USING gist (geom);


--
-- Name: idx_archaeological_sites_points_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_archaeological_sites_points_geom ON epoleodomia.archaeological_sites_points USING gist (geom);


--
-- Name: idx_archaeological_sites_polygons_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_archaeological_sites_polygons_geom ON epoleodomia.archaeological_sites_polygons USING gist (geom);


--
-- Name: idx_archaeological_zones_pl_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_archaeological_zones_pl_geom ON epoleodomia.archaeological_zones_pl USING gist (geom);


--
-- Name: idx_block_vertices_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_block_vertices_geom ON epoleodomia.block_vertices USING gist (geom);


--
-- Name: idx_brc_zones_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_brc_zones_geom ON epoleodomia.building_regs_coefficient_zones USING gist (geom);


--
-- Name: idx_brc_zones_tomeas; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_brc_zones_tomeas ON epoleodomia.building_regs_coefficient_zones USING btree (sd_tomeas);


--
-- Name: idx_building_blocks_fek; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_building_blocks_fek ON epoleodomia.building_blocks USING btree (fek);


--
-- Name: idx_building_blocks_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_building_blocks_geom ON epoleodomia.building_blocks USING gist (geom);


--
-- Name: idx_building_blocks_kall_dhm; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_building_blocks_kall_dhm ON epoleodomia.building_blocks USING btree (kall_dhm_name);


--
-- Name: idx_building_blocks_label_point; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_building_blocks_label_point ON epoleodomia.building_blocks USING gist (label_point);


--
-- Name: idx_building_lines_fek; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_building_lines_fek ON epoleodomia.building_lines USING btree (fek);


--
-- Name: idx_building_lines_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_building_lines_geom ON epoleodomia.building_lines USING gist (geom);


--
-- Name: idx_building_regs_coefficient_fek; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_building_regs_coefficient_fek ON epoleodomia.building_regs_coefficient USING btree (fek);


--
-- Name: idx_building_regs_coefficient_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_building_regs_coefficient_geom ON epoleodomia.building_regs_coefficient USING gist (geom);


--
-- Name: idx_building_regs_coverage_fek; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_building_regs_coverage_fek ON epoleodomia.building_regs_coverage USING btree (fek);


--
-- Name: idx_building_regs_coverage_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_building_regs_coverage_geom ON epoleodomia.building_regs_coverage USING gist (geom);


--
-- Name: idx_building_regs_height_fek; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_building_regs_height_fek ON epoleodomia.building_regs_height USING btree (fek);


--
-- Name: idx_building_regs_height_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_building_regs_height_geom ON epoleodomia.building_regs_height USING gist (geom);


--
-- Name: idx_building_regs_lot_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_building_regs_lot_geom ON epoleodomia.building_regs_lot USING gist (geom);


--
-- Name: idx_building_regs_system_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_building_regs_system_geom ON epoleodomia.building_regs_system USING gist (geom);


--
-- Name: idx_census_blocks_2021_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_census_blocks_2021_geom ON epoleodomia.census_blocks_2021 USING gist (geom);


--
-- Name: idx_expropriation_zones_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_expropriation_zones_geom ON epoleodomia.expropriation_zones USING gist (geom);


--
-- Name: idx_fek_no_diagrams_fek; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_fek_no_diagrams_fek ON epoleodomia.fek_no_diagrams USING btree (fek);


--
-- Name: idx_fek_no_diagrams_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_fek_no_diagrams_geom ON epoleodomia.fek_no_diagrams USING gist (geom);


--
-- Name: idx_forest_maps_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_forest_maps_geom ON epoleodomia.forest_maps USING gist (geom);


--
-- Name: idx_forest_posted_attica_2021_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_forest_posted_attica_2021_geom ON epoleodomia.forest_maps_posted_attica_2021 USING gist (geom);


--
-- Name: idx_forest_posted_pelop_2022_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_forest_posted_pelop_2022_geom ON epoleodomia.forest_maps_posted_pelop_2022 USING gist (geom);


--
-- Name: idx_historic_sites_lines_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_historic_sites_lines_geom ON epoleodomia.historic_sites_lines USING gist (geom);


--
-- Name: idx_historic_sites_points_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_historic_sites_points_geom ON epoleodomia.historic_sites_points USING gist (geom);


--
-- Name: idx_historic_sites_polygons_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_historic_sites_polygons_geom ON epoleodomia.historic_sites_polygons USING gist (geom);


--
-- Name: idx_land_uses_ers_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_land_uses_ers_geom ON epoleodomia.land_uses_ers USING gist (geom);


--
-- Name: idx_land_uses_gps_fek; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_land_uses_gps_fek ON epoleodomia.land_uses_gps USING btree (fek);


--
-- Name: idx_land_uses_gps_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_land_uses_gps_geom ON epoleodomia.land_uses_gps USING gist (geom);


--
-- Name: idx_monuments_lines_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_monuments_lines_geom ON epoleodomia.monuments_lines USING gist (geom);


--
-- Name: idx_monuments_points_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_monuments_points_geom ON epoleodomia.monuments_points USING gist (geom);


--
-- Name: idx_monuments_polygons_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_monuments_polygons_geom ON epoleodomia.monuments_polygons USING gist (geom);


--
-- Name: idx_municipal_communities_2021_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_municipal_communities_2021_geom ON epoleodomia.municipal_communities_2021 USING gist (geom);


--
-- Name: idx_municipal_units_2021_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_municipal_units_2021_geom ON epoleodomia.municipal_units_2021 USING gist (geom);


--
-- Name: idx_municipalities_2021_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_municipalities_2021_geom ON epoleodomia.municipalities_2021 USING gist (geom);


--
-- Name: idx_natura_2000_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_natura_2000_geom ON epoleodomia.natura_2000 USING gist (geom);


--
-- Name: idx_natural_landscapes_points_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_natural_landscapes_points_geom ON epoleodomia.natural_landscapes_points USING gist (geom);


--
-- Name: idx_natural_landscapes_polygons_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_natural_landscapes_polygons_geom ON epoleodomia.natural_landscapes_polygons USING gist (geom);


--
-- Name: idx_other_planning_lines_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_other_planning_lines_geom ON epoleodomia.other_planning_lines USING gist (geom);


--
-- Name: idx_other_planning_zones_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_other_planning_zones_geom ON epoleodomia.other_planning_zones USING gist (geom);


--
-- Name: idx_outside_plan_areas_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_outside_plan_areas_geom ON epoleodomia.outside_plan_areas USING gist (geom);


--
-- Name: idx_pd_protection_zones_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_pd_protection_zones_geom ON epoleodomia.pd_protection_zones USING gist (geom);


--
-- Name: idx_pedestrian_zones_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_pedestrian_zones_geom ON epoleodomia.pedestrian_zones USING gist (geom);


--
-- Name: idx_planning_diagrams_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_planning_diagrams_geom ON epoleodomia.planning_diagrams USING gist (geom);


--
-- Name: idx_planning_lines_fek; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_planning_lines_fek ON epoleodomia.planning_lines USING btree (fek);


--
-- Name: idx_planning_lines_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_planning_lines_geom ON epoleodomia.planning_lines USING gist (geom);


--
-- Name: idx_protected_buildings_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_protected_buildings_geom ON epoleodomia.protected_buildings USING gist (geom);


--
-- Name: idx_protection_zones_lines_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_protection_zones_lines_geom ON epoleodomia.protection_zones_lines USING gist (geom);


--
-- Name: idx_protection_zones_points_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_protection_zones_points_geom ON epoleodomia.protection_zones_points USING gist (geom);


--
-- Name: idx_protection_zones_polygons_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_protection_zones_polygons_geom ON epoleodomia.protection_zones_polygons USING gist (geom);


--
-- Name: idx_public_spaces_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_public_spaces_geom ON epoleodomia.public_spaces USING gist (geom);


--
-- Name: idx_raster_catalog_bbox; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_raster_catalog_bbox ON epoleodomia.raster_catalog USING gist (bbox);


--
-- Name: idx_raster_catalog_fek; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_raster_catalog_fek ON epoleodomia.raster_catalog USING btree (fek);


--
-- Name: idx_raster_catalog_planning_diagram; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_raster_catalog_planning_diagram ON epoleodomia.raster_catalog USING btree (planning_diagram_objectid);


--
-- Name: idx_raster_catalog_status; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_raster_catalog_status ON epoleodomia.raster_catalog USING btree (download_status);


--
-- Name: idx_raster_catalog_url_unique; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE UNIQUE INDEX idx_raster_catalog_url_unique ON epoleodomia.raster_catalog USING btree (url_georef);


--
-- Name: idx_settlement_boundaries_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_settlement_boundaries_geom ON epoleodomia.settlement_boundaries USING gist (geom);


--
-- Name: idx_settlements_2021_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_settlements_2021_geom ON epoleodomia.settlements_2021 USING gist (geom);


--
-- Name: idx_shorelines_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_shorelines_geom ON epoleodomia.shorelines USING gist (geom);


--
-- Name: idx_streams_environmental_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_streams_environmental_geom ON epoleodomia.streams_environmental USING gist (geom);


--
-- Name: idx_streams_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_streams_geom ON epoleodomia.streams USING gist (geom);


--
-- Name: idx_urban_units_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_urban_units_geom ON epoleodomia.urban_units USING gist (geom);


--
-- Name: idx_zoe_zones_geom; Type: INDEX; Schema: epoleodomia; Owner: docker
--

CREATE INDEX idx_zoe_zones_geom ON epoleodomia.zoe_zones USING gist (geom);


--
-- Name: TABLE ab_zones_attica; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.ab_zones_attica TO ai_reader;


--
-- Name: TABLE addresses; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.addresses TO ai_reader;


--
-- Name: TABLE approved_plan_boundaries; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.approved_plan_boundaries TO ai_reader;


--
-- Name: TABLE archaeological_sites_lines; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.archaeological_sites_lines TO ai_reader;


--
-- Name: TABLE archaeological_sites_points; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.archaeological_sites_points TO ai_reader;


--
-- Name: TABLE archaeological_sites_polygons; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.archaeological_sites_polygons TO ai_reader;


--
-- Name: TABLE archaeological_zones_pl; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.archaeological_zones_pl TO ai_reader;


--
-- Name: TABLE block_vertices; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.block_vertices TO ai_reader;


--
-- Name: TABLE building_blocks; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.building_blocks TO ai_reader;


--
-- Name: TABLE building_lines; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.building_lines TO ai_reader;


--
-- Name: TABLE building_regs_coefficient; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.building_regs_coefficient TO ai_reader;


--
-- Name: TABLE building_regs_coefficient_zones; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.building_regs_coefficient_zones TO ai_reader;


--
-- Name: TABLE building_regs_coverage; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.building_regs_coverage TO ai_reader;


--
-- Name: TABLE building_regs_height; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.building_regs_height TO ai_reader;


--
-- Name: TABLE building_regs_lot; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.building_regs_lot TO ai_reader;


--
-- Name: TABLE building_regs_system; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.building_regs_system TO ai_reader;


--
-- Name: TABLE census_blocks_2021; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.census_blocks_2021 TO ai_reader;


--
-- Name: TABLE expropriation_zones; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.expropriation_zones TO ai_reader;


--
-- Name: TABLE fek_no_diagrams; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.fek_no_diagrams TO ai_reader;


--
-- Name: TABLE forest_maps; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.forest_maps TO ai_reader;


--
-- Name: TABLE forest_maps_posted_attica_2021; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.forest_maps_posted_attica_2021 TO ai_reader;


--
-- Name: TABLE forest_maps_posted_pelop_2022; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.forest_maps_posted_pelop_2022 TO ai_reader;


--
-- Name: TABLE historic_sites_lines; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.historic_sites_lines TO ai_reader;


--
-- Name: TABLE historic_sites_points; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.historic_sites_points TO ai_reader;


--
-- Name: TABLE historic_sites_polygons; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.historic_sites_polygons TO ai_reader;


--
-- Name: TABLE land_uses_ers; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.land_uses_ers TO ai_reader;


--
-- Name: TABLE land_uses_gps; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.land_uses_gps TO ai_reader;


--
-- Name: TABLE monuments_lines; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.monuments_lines TO ai_reader;


--
-- Name: TABLE monuments_points; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.monuments_points TO ai_reader;


--
-- Name: TABLE monuments_polygons; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.monuments_polygons TO ai_reader;


--
-- Name: TABLE municipal_communities_2021; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.municipal_communities_2021 TO ai_reader;


--
-- Name: TABLE municipal_units_2021; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.municipal_units_2021 TO ai_reader;


--
-- Name: TABLE municipalities_2021; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.municipalities_2021 TO ai_reader;


--
-- Name: TABLE natura_2000; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.natura_2000 TO ai_reader;


--
-- Name: TABLE natural_landscapes_points; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.natural_landscapes_points TO ai_reader;


--
-- Name: TABLE natural_landscapes_polygons; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.natural_landscapes_polygons TO ai_reader;


--
-- Name: TABLE other_planning_lines; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.other_planning_lines TO ai_reader;


--
-- Name: TABLE other_planning_zones; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.other_planning_zones TO ai_reader;


--
-- Name: TABLE outside_plan_areas; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.outside_plan_areas TO ai_reader;


--
-- Name: TABLE pd_protection_zones; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.pd_protection_zones TO ai_reader;


--
-- Name: TABLE pedestrian_zones; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.pedestrian_zones TO ai_reader;


--
-- Name: TABLE planning_diagrams; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.planning_diagrams TO ai_reader;


--
-- Name: TABLE planning_lines; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.planning_lines TO ai_reader;


--
-- Name: TABLE protected_buildings; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.protected_buildings TO ai_reader;


--
-- Name: TABLE protection_zones_lines; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.protection_zones_lines TO ai_reader;


--
-- Name: TABLE protection_zones_points; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.protection_zones_points TO ai_reader;


--
-- Name: TABLE protection_zones_polygons; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.protection_zones_polygons TO ai_reader;


--
-- Name: TABLE public_spaces; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.public_spaces TO ai_reader;


--
-- Name: TABLE raster_catalog; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.raster_catalog TO ai_reader;


--
-- Name: TABLE settlement_boundaries; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.settlement_boundaries TO ai_reader;


--
-- Name: TABLE settlements_2021; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.settlements_2021 TO ai_reader;


--
-- Name: TABLE shorelines; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.shorelines TO ai_reader;


--
-- Name: TABLE "spetses island bb"; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia."spetses island bb" TO ai_reader;


--
-- Name: TABLE streams; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.streams TO ai_reader;


--
-- Name: TABLE streams_environmental; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.streams_environmental TO ai_reader;


--
-- Name: TABLE sync_log; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.sync_log TO ai_reader;


--
-- Name: TABLE urban_units; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.urban_units TO ai_reader;


--
-- Name: TABLE v_addresses_with_blocks; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.v_addresses_with_blocks TO ai_reader;


--
-- Name: TABLE v_building_blocks_full; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.v_building_blocks_full TO ai_reader;


--
-- Name: TABLE v_building_blocks_regulations; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.v_building_blocks_regulations TO ai_reader;


--
-- Name: TABLE v_fek_references; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.v_fek_references TO ai_reader;


--
-- Name: TABLE v_land_uses_summary; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.v_land_uses_summary TO ai_reader;


--
-- Name: TABLE v_oroi_domisis_flags; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.v_oroi_domisis_flags TO ai_reader;


--
-- Name: TABLE v_planning_lines_all; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.v_planning_lines_all TO ai_reader;


--
-- Name: TABLE v_protected_areas; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.v_protected_areas TO ai_reader;


--
-- Name: TABLE v_rasters_by_fek; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.v_rasters_by_fek TO ai_reader;


--
-- Name: TABLE v_rasters_downloaded; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.v_rasters_downloaded TO ai_reader;


--
-- Name: TABLE v_rasters_failed; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.v_rasters_failed TO ai_reader;


--
-- Name: TABLE v_rasters_pending; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.v_rasters_pending TO ai_reader;


--
-- Name: TABLE v_sync_status; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.v_sync_status TO ai_reader;


--
-- Name: TABLE zoe_zones; Type: ACL; Schema: epoleodomia; Owner: docker
--

GRANT SELECT ON TABLE epoleodomia.zoe_zones TO ai_reader;


--
-- Name: DEFAULT PRIVILEGES FOR TABLES; Type: DEFAULT ACL; Schema: epoleodomia; Owner: docker
--

ALTER DEFAULT PRIVILEGES FOR ROLE docker IN SCHEMA epoleodomia GRANT SELECT ON TABLES TO ai_reader;


--
-- Name: DEFAULT PRIVILEGES FOR TABLES; Type: DEFAULT ACL; Schema: epoleodomia; Owner: postgres
--

ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA epoleodomia GRANT SELECT ON TABLES TO ai_reader;


--
-- PostgreSQL database dump complete
--


