"""Read-only evidence for FEK raster exclusions and regulation-sector conflicts.

Reports observed geometry/attributes, not which decree prevails legally.
No schema changes, corrections, syncs or exclusion edits are supported.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path

import psycopg2
from psycopg2 import sql

from settings import PROJECT_DIR, load_settings


FEKS = ('740Δ/1981', '176Δ/1970', '275Δ/1970')
REGULATIONS = {
    'building_regs_coefficient': ('sd_tomeas','sd_timh','sd_klimakotos','sd_comment','fek'),
    'building_regs_height': ('max_height_m','num_orofon','oror_max_height_comment','fek'),
    'building_regs_coverage': ('synt_kalypsis','remarks','fek'),
    'building_regs_lot': ('elax_embado_m2','elax_prosop_m','oros_type','date_pareklisis','remarks','fek'),
    'building_regs_system': ('oik_systima','fek'),
}


def rows(cur, statement, params=()):
    cur.execute(statement, params)
    columns = [column.name for column in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def _attributes(alias, columns):
    return sql.SQL('jsonb_build_object({})').format(sql.SQL(',').join(
        sql.SQL('{},{}.{}').format(sql.Literal(column),sql.Identifier(alias),sql.Identifier(column))
        for column in columns))


def sector_pairs(cur, table, columns):
    # Same lot OBJECTID can legitimately have rule/exception variants. Only
    # compare within the same oros_type; unlike types are not spatial conflicts.
    same_variant = sql.SQL('AND a.oros_type IS NOT DISTINCT FROM b.oros_type') if table=='building_regs_lot' else sql.SQL('')
    point_variant = sql.SQL("AND r.oros_type IS NOT DISTINCT FROM (attributes_a->>'oros_type')") if table=='building_regs_lot' else sql.SQL('')
    statement = sql.SQL('''WITH pairs AS (
        SELECT a.objectid objectid_a,b.objectid objectid_b,a.id row_a,b.id row_b,
            {attrs_a} attributes_a,{attrs_b} attributes_b,
            ST_Intersection(ST_MakeValid(a.geom),ST_MakeValid(b.geom)) intersection
        FROM epoleodomia.{table} a JOIN epoleodomia.{table} b ON a.id<b.id AND a.geom && b.geom
        WHERE NOT COALESCE(a.is_deleted,false) AND NOT COALESCE(b.is_deleted,false)
          AND ST_Intersects(ST_MakeValid(a.geom),ST_MakeValid(b.geom)) {variant}
        ), measured AS (
        SELECT *,ST_Area(intersection) overlap_m2,ST_Length(ST_CollectionExtract(intersection,2)) shared_line_m
        FROM pairs)
        SELECT objectid_a,objectid_b,row_a,row_b,attributes_a,attributes_b,
            attributes_a IS DISTINCT FROM attributes_b different_report_attributes,
            overlap_m2,shared_line_m,
            CASE WHEN overlap_m2>0 THEN 'area_overlap' WHEN shared_line_m>0 THEN 'shared_boundary' ELSE 'point_contact' END kind,
            ST_X(p) sample_x,ST_Y(p) sample_y,
            (SELECT count(*) FROM epoleodomia.{table} r
             WHERE NOT COALESCE(r.is_deleted,false) AND ST_Contains(r.geom,p) {point_variant}) sample_contains_count,
            (SELECT count(*) FROM epoleodomia.{table} r
             WHERE NOT COALESCE(r.is_deleted,false) AND ST_Covers(r.geom,p) {point_variant}) sample_covers_count
        FROM measured CROSS JOIN LATERAL (
            SELECT CASE WHEN overlap_m2>0 THEN ST_PointOnSurface(ST_CollectionExtract(intersection,3))
                        WHEN shared_line_m>0 THEN ST_LineInterpolatePoint(ST_GeometryN(ST_CollectionExtract(intersection,2),1),0.5)
                        ELSE ST_PointOnSurface(intersection) END p) sample
        ORDER BY overlap_m2 DESC,shared_line_m DESC,row_a,row_b''').format(
        attrs_a=_attributes('a',columns),attrs_b=_attributes('b',columns),
        table=sql.Identifier(table),variant=same_variant,point_variant=point_variant)
    return rows(cur, statement)


def audit(conn):
    with conn.cursor() as cur:
        cur.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        cur.execute("SET LOCAL statement_timeout='60s'")
        cur.execute("SET LOCAL lock_timeout='5s'")
        cur.execute('SELECT current_user,current_database(),current_setting(\'transaction_read_only\')')
        account,database,readonly=cur.fetchone()
        if readonly!='on':
            raise RuntimeError('Read-only session required')
        result={'captured_at':datetime.now(timezone.utc).isoformat(),'account':account,'database':database,
                'read_only':True,'legal_precedence_determined':False}
        result['exclusions']=rows(cur,'SELECT collection,doc_ref,reason,added_at FROM sp_geodata.raster_exclusions ORDER BY collection,doc_ref')
        result['raster_summary']=rows(cur,'''SELECT doc_ref,count(*) sheets,min(nominal_scale) min_scale,
            max(nominal_scale) max_scale,min(georef_rms) min_rms,max(georef_rms) max_rms,
            min(ST_Area(query_geom)) min_sheet_area_m2,max(ST_Area(query_geom)) max_sheet_area_m2,
            array_agg(DISTINCT role) roles FROM sp_geodata.v_all_rasters
            WHERE collection='fek' AND doc_ref=ANY(%s) GROUP BY doc_ref ORDER BY doc_ref''',(list(FEKS),))
        result['municipality_overlap']=rows(cur,'''WITH footprints AS (
            SELECT doc_ref,ST_UnaryUnion(ST_Collect(ST_MakeValid(query_geom))) geom
            FROM sp_geodata.v_all_rasters WHERE collection='fek' AND doc_ref=ANY(%s) GROUP BY doc_ref)
            SELECT f.doc_ref,m.objectid municipality_objectid,m.ypes_name municipality,
                ST_Area(f.geom) footprint_union_m2,
                ST_Area(ST_Intersection(f.geom,ST_MakeValid(m.geom))) overlap_m2,
                ST_Distance(f.geom,ST_MakeValid(m.geom)) distance_m
            FROM footprints f CROSS JOIN epoleodomia.municipalities_2021 m
            WHERE NOT COALESCE(m.is_deleted,false) ORDER BY f.doc_ref,m.objectid''',(list(FEKS),))
        result['source_documents']=rows(cur,'''SELECT fek,fek_file_url,title,count(*) sheets,
            min(init_diagr_scale_denominator) min_scale,max(init_diagr_scale_denominator) max_scale
            FROM epoleodomia.planning_diagrams WHERE fek=ANY(%s) AND NOT COALESCE(is_deleted,false)
            GROUP BY fek,fek_file_url,title ORDER BY fek''',(list(FEKS),))
        result['regulations']={}
        for table,columns in REGULATIONS.items():
            counts=rows(cur,sql.SQL('''SELECT count(*) active_rows,
                count(*) FILTER (WHERE geom IS NULL) missing_geometry,
                count(*) FILTER (WHERE NOT ST_IsValid(geom)) invalid_geometry
                FROM epoleodomia.{} WHERE NOT COALESCE(is_deleted,false)''').format(sql.Identifier(table)))[0]
            pairs=sector_pairs(cur,table,columns)
            result['regulations'][table]={'counts':counts,'pairs':pairs}
        return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=PROJECT_DIR/'logs'/(
        'planning_data_audit_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'.json'))
    args=parser.parse_args(argv)
    database=load_settings().database
    with closing(psycopg2.connect(**database.connection_kwargs(),options='-c default_transaction_read_only=on')) as conn:
        result=audit(conn)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
    print('Read-only planning data evidence: '+str(args.output))
    for name,item in result['regulations'].items():
        pairs=item['pairs']
        print(f"{name}: active={item['counts']['active_rows']}, area overlaps={sum(p['kind']=='area_overlap' for p in pairs)}, shared boundaries={sum(p['kind']=='shared_boundary' for p in pairs)}")
    return 0


if __name__=='__main__':
    raise SystemExit(main())
