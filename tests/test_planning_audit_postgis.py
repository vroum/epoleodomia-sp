"""Spatial audit evidence is read-only and distinguishes contacts and lot variants."""
from contextlib import closing

import audit_planning_data as review
from tests import test_sync_publication_postgis as fixture


class PlanningAuditPostGISTests(fixture.PublicationFixture):
    def setUp(self):
        super().setUp()
        # The shared fixture installs TEE only. Supply the optional raster
        # contract as an empty view, without introducing another catalog.
        self.query('''CREATE TABLE sp_geodata.raster_exclusions(
            collection text,doc_ref text,reason text,added_at timestamptz);
            CREATE VIEW sp_geodata.v_all_rasters AS SELECT NULL::text doc_ref,
                NULL::integer nominal_scale,NULL::numeric georef_rms,
                NULL::geometry(Geometry,2100) query_geom,NULL::text role,
                'fek'::text collection WHERE false''')

    def add_coefficient(self,objectid,wkt,*,deleted=False):
        self.query('''INSERT INTO epoleodomia.building_regs_coefficient
            (objectid,sd_tomeas,sd_timh,fek,is_deleted,geom)
            VALUES (%s,%s,%s,'TEST',%s,ST_GeomFromText(%s,2100))''',
            (objectid,str(objectid),objectid/10,deleted,wkt))

    def pairs(self,table='building_regs_coefficient'):
        with closing(self.connect(options='-c default_transaction_read_only=on')) as conn,conn.cursor() as cur:
            result=review.sector_pairs(cur,table,review.REGULATIONS[table])
            cur.execute('SHOW transaction_read_only')
            self.assertEqual(cur.fetchone(),('on',))
            return result

    def test_area_overlap_reports_both_candidates_without_picking_one(self):
        self.add_coefficient(1,'POLYGON((0 0,10 0,10 10,0 10,0 0))')
        self.add_coefficient(2,'POLYGON((5 0,15 0,15 10,5 10,5 0))')
        pair,=self.pairs()
        self.assertEqual(pair['kind'],'area_overlap')
        self.assertEqual(pair['overlap_m2'],50)
        self.assertTrue(pair['different_report_attributes'])
        self.assertEqual(pair['sample_contains_count'],2)

    def test_shared_boundary_and_point_contact_are_not_area_overlaps(self):
        self.add_coefficient(1,'POLYGON((0 0,10 0,10 10,0 10,0 0))')
        self.add_coefficient(2,'POLYGON((10 0,20 0,20 10,10 10,10 0))')
        self.add_coefficient(3,'POLYGON((20 10,30 10,30 20,20 20,20 10))')
        pairs=self.pairs()
        self.assertEqual({p['kind'] for p in pairs},{'shared_boundary','point_contact'})
        boundary=next(p for p in pairs if p['kind']=='shared_boundary')
        self.assertEqual(boundary['overlap_m2'],0)
        self.assertEqual(boundary['shared_line_m'],10)
        self.assertEqual(boundary['sample_contains_count'],0)
        self.assertEqual(boundary['sample_covers_count'],2)

    def test_deleted_rows_are_ignored_and_source_values_are_not_corrected(self):
        self.add_coefficient(1,'POLYGON((0 0,10 0,10 10,0 10,0 0))')
        self.add_coefficient(2,'POLYGON((0 0,10 0,10 10,0 10,0 0))',deleted=True)
        before=self.fingerprints()
        self.assertEqual(self.pairs(),[])
        self.assertEqual(self.fingerprints(),before)

    def test_lot_rule_and_exception_are_not_counted_as_a_conflict(self):
        self.query('DELETE FROM epoleodomia.building_regs_lot')
        for objectid,kind in ((1,'rule'),(2,'exception'),(3,'rule')):
            self.query('''INSERT INTO epoleodomia.building_regs_lot(objectid,oros_type,geom)
                VALUES (%s,%s,ST_GeomFromText('POLYGON((0 0,10 0,10 10,0 10,0 0))',2100))''',(objectid,kind))
        pair,=self.pairs('building_regs_lot')
        self.assertEqual((pair['objectid_a'],pair['objectid_b']),(1,3))
        self.assertEqual(pair['sample_contains_count'],2)

    def test_complete_audit_enforces_readonly_and_preserves_every_table(self):
        before=self.fingerprints()
        with closing(self.connect()) as conn:
            result=review.audit(conn)
        self.assertTrue(result['read_only'])
        self.assertFalse(result['legal_precedence_determined'])
        self.assertEqual(self.fingerprints(),before)
