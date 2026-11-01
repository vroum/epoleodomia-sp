"""Journal business identities, rollback, access and HTTP queries in disposable PostGIS."""
from contextlib import closing
from dataclasses import replace
from datetime import date
import json
from unittest.mock import patch

import psycopg2

import setup_sync_history as setup
import sync_history as history
import sync_history_api as views
import sync_publication as publication
from sync_access import inspect_target, verify_access
from sync_safety import LoadError, FetchError
from database_sessions import read_only_snapshot
from tests import test_sync_publication_postgis as fixture
from tests.test_sync_publication_postgis import bundle, READER, GEOMETRY


class HistoryPostGISTests(fixture.PublicationFixture):
    """Use the same installation fixture with the optional journal enabled."""
    def setUp(self):
        super().setUp()
        self.query("ALTER TABLE sp_geodata.kaek_douleies_operating ADD COLUMN right_sn text; "
                   "UPDATE sp_geodata.kaek_douleies_operating SET right_sn='1'; "
                   "ALTER TABLE sp_geodata.kaek_apokleistikes_operating ADD COLUMN vp_num text; "
                   "UPDATE sp_geodata.kaek_apokleistikes_operating SET vp_num='1'; "
                   "UPDATE epoleodomia.building_regs_lot SET oros_type=right(title,1)")
        with self.owner.cursor() as cur:
            self.target = inspect_target(cur)
        setup.install(self.connect, self.target, READER)

    def history_bundle(self, version=1):
        result = []
        for layer in bundle(version):
            if layer.table == 'building_regs_lot':
                for feature in layer.payload['features']:
                    feature['properties']['OROS_TYPE'] = feature['properties']['TITLE'][-1]
            if layer.domain == 'ktima' and layer.table != 'kaek_parcels_operating':
                key = 'RIGHT_SN' if layer.table == 'kaek_douleies_operating' else 'VP_NUM'
                layer = replace(layer, fields=(*layer.fields, (key,'text')),
                                payload=[(*row[:-1], '1', row[-1]) for row in layer.payload])
            result.append(layer)
        return result

    def record(self, layers=None, mode='all'):
        layers = layers or self.history_bundle()
        return publication.run(mode, self.writer, apply=True,
                               collector=lambda selected: [l for l in layers if mode=='all' or l.domain==mode])

    def source_fingerprints(self):
        return {key: value for key,value in self.fingerprints().items() if key[0]!='epol_meta'}

    def test_forward_start_does_not_copy_existing_audits_and_idempotent_setup_preserves_start(self):
        self.assertEqual(self.query('SELECT count(*) FROM epoleodomia.sync_runs'), [(1,)])
        self.assertEqual(self.query('SELECT count(*) FROM epol_meta.sync_history_runs'), [(0,)])
        before = self.source_fingerprints()
        start = self.query('SELECT started_at FROM epol_meta.sync_history_config')
        setup.install(self.connect, self.target, READER)
        self.assertEqual(self.query('SELECT started_at FROM epol_meta.sync_history_config'), start)
        self.assertEqual(self.source_fingerprints(), before)
        with self.owner.cursor() as cur:
            verify_access(cur)
            setup.verify_reader(cur, READER)

    def test_reimport_has_zero_business_changes_including_duplicate_lot_ids(self):
        result = self.record()
        self.assertEqual(self.query('SELECT DISTINCT status FROM epol_meta.sync_history_runs'), [('committed',)])
        self.assertEqual(self.query('SELECT count(*) FROM epol_meta.sync_history_layers'), [(59,)])
        self.assertEqual(self.query('SELECT count(*) FROM epol_meta.sync_history_changes'), [(0,)])
        lot = next(item['history'] for item in result['tables'] if item['table']=='building_regs_lot')
        self.assertEqual(lot, dict(new=0,updated=0,removed=0,unchanged=2,geometry=0,source_id=0))

    def test_ten_cadastre_and_three_forest_additions_and_readonly_overview(self):
        layers = self.history_bundle()
        for i, layer in enumerate(layers):
            if layer.table=='kaek_parcels_operating':
                row = layer.payload[0]
                layers[i] = replace(layer,payload=[row]+[(n+100,'NEW-'+str(n),*row[2:]) for n in range(10)])
            if layer.table=='forest_maps':
                layer.payload['features'] = [{'type':'Feature','properties':{'OBJECTID':n+100},'geometry':GEOMETRY} for n in range(3)]
        result = self.record(layers)
        self.assertEqual(self.query('SELECT sum(new_count),sum(updated_count),sum(removed_count) FROM epol_meta.sync_history_layers'), [(13,0,0)])
        reader = self.reader_pool()
        try:
            with read_only_snapshot(reader) as query:
                data = views.overview(query,period='4m',start=None,end=None,domain='',changed_only=True,offset=0,limit=25)
                self.assertEqual(data['totals']['new'],13)
                self.assertEqual({r['table_name']:r['new'] for r in data['layers']}, {'kaek_parcels_operating':10,'forest_maps':3})
                detail = views.details(query,result['history_id'],domain='',table='',kind='',key='NEW-',offset=0,limit=4)
                self.assertEqual(detail['total_changes'],10)
                self.assertEqual(len(detail['changes']),4)
                self.assertEqual(detail['changes'][0]['change_type'],'new')
                query.cursor.execute('SHOW transaction_read_only')
                self.assertEqual(query.cursor.fetchone(),('on',))
        finally:
            reader.closeall()

    def test_source_id_renumbering_is_not_new_or_business_updated(self):
        layers = self.history_bundle(2)
        self.record(layers)
        self.assertEqual(self.query("SELECT count(*) FROM epol_meta.sync_history_changes WHERE change_type='source_id'"),[(3,)])
        self.assertEqual(self.query("SELECT sum(new_count),sum(updated_count),sum(removed_count),sum(source_id_count) FROM epol_meta.sync_history_layers WHERE domain='ktima'"),[(0,0,0,3)])

    def test_equal_overlay_counts_with_new_identity_are_addition_and_removal(self):
        layers = self.history_bundle()
        for i,layer in enumerate(layers):
            if layer.table=='kaek_douleies_operating':
                row=layer.payload[0]
                layers[i]=replace(layer,payload=[(*row[:-2],'2',row[-1])])
        self.record(layers,mode='ktima')
        self.assertEqual(self.query("SELECT new_count,removed_count,updated_count FROM epol_meta.sync_history_layers WHERE table_name='kaek_douleies_operating'"),[(1,1,0)])

    def test_ring_order_is_unchanged_but_geometry_shift_is_an_update(self):
        layers=self.history_bundle()
        for i,layer in enumerate(layers):
            if layer.table=='kaek_parcels_operating':
                ring=GEOMETRY['coordinates'][0]
                geometry={'type':'Polygon','coordinates':[[*ring[2:-1],*ring[:3]]]}
                row=layer.payload[0]
                layers[i]=replace(layer,payload=[(*row[:-1],json.dumps(geometry))])
        self.record(layers,mode='ktima')
        self.assertEqual(self.query('SELECT count(*) FROM epol_meta.sync_history_changes'),[(0,)])
        layers=self.history_bundle()
        for i,layer in enumerate(layers):
            if layer.table=='kaek_parcels_operating':
                geometry={'type':'Polygon','coordinates':[[[x+1,y] for x,y in GEOMETRY['coordinates'][0]]]}
                row=layer.payload[0]
                layers[i]=replace(layer,payload=[(*row[:-1],json.dumps(geometry))])
        self.record(layers,mode='ktima')
        self.assertEqual(self.query("SELECT change_type,geometry_changed,changed_fields FROM epol_meta.sync_history_changes"),[('updated',True,[])])

    def test_late_history_failure_rolls_back_sources_and_changes_but_records_failure(self):
        before=self.source_fingerprints()
        with patch.object(history,'complete',side_effect=RuntimeError('injected late journal error')), self.assertRaisesRegex(RuntimeError,'journal'):
            self.record(self.history_bundle(2))
        self.assertEqual(self.source_fingerprints(),before)
        self.assertEqual(self.query('SELECT count(*) FROM epol_meta.sync_history_changes'),[(0,)])
        self.assertEqual(self.query('SELECT count(*) FROM epol_meta.sync_history_layers'),[(0,)])
        self.assertEqual(self.query('SELECT status FROM epol_meta.sync_history_runs'),[('failed',)])

    def test_fetch_failure_is_visible_and_redacted_without_publication(self):
        before=self.source_fingerprints()
        with self.assertRaises(FetchError):
            publication.run('all',self.writer,apply=True,collector=lambda mode: (_ for _ in ()).throw(FetchError(self.writer.password)))
        self.assertEqual(self.source_fingerprints(),before)
        self.assertEqual(self.query('SELECT status,error_message FROM epol_meta.sync_history_runs'),[('failed','<redacted>')])

    def test_ambiguous_cadastre_key_cancels_whole_publication(self):
        before=self.source_fingerprints()
        layers=self.history_bundle(2)
        for i,layer in enumerate(layers):
            if layer.table=='kaek_parcels_operating':
                row=layer.payload[0]
                layers[i]=replace(layer,payload=[row,(99,*row[1:])])
        with self.assertRaisesRegex(LoadError,'Duplicate stable'):
            self.record(layers)
        self.assertEqual(self.source_fingerprints(),before)

    def test_failure_handler_cannot_overwrite_committed_outcome(self):
        result=self.record()
        history.fail(self.owner,result['history_id'],'lost response',unknown=True)
        self.assertEqual(self.query('SELECT status,error_message FROM epol_meta.sync_history_runs'),[('committed',None)])

    def test_actual_commit_with_lost_acknowledgement_stays_committed_in_journal(self):
        real_connect=psycopg2.connect
        connections=0
        class LostResponse:
            def __init__(self, conn):
                self.conn=conn
            def __getattr__(self,name):
                return getattr(self.conn,name)
            @property
            def autocommit(self):
                return self.conn.autocommit
            @autocommit.setter
            def autocommit(self,value):
                self.conn.autocommit=value
            def commit(self):
                self.conn.commit()
                raise psycopg2.OperationalError('injected lost acknowledgement after real commit')
        def connect(**kwargs):
            nonlocal connections
            connections+=1
            conn=real_connect(**kwargs)
            return LostResponse(conn) if connections==1 else conn
        with self.assertRaises(publication.CommitOutcomeUnknown):
            publication.run('all',self.writer,apply=True,collector=lambda mode:self.history_bundle(2),connect=connect)
        self.assertEqual(self.query('SELECT status,error_message FROM epol_meta.sync_history_runs'),[('committed',None)])
        self.assertGreater(self.query('SELECT count(*) FROM epol_meta.sync_history_changes')[0][0],0)

    def test_writer_cannot_edit_or_delete_existing_change_rows(self):
        self.record(self.history_bundle(2))
        with closing(psycopg2.connect(**self.writer.connection_kwargs())) as conn:
            conn.autocommit=True
            for statement in ('UPDATE epol_meta.sync_history_changes SET change_type=\'new\'',
                              'DELETE FROM epol_meta.sync_history_changes',
                              'UPDATE epol_meta.sync_history_config SET started_at=now()',
                              'CREATE TABLE epol_meta.unexpected(id int)'):
                with self.subTest(statement=statement),self.assertRaises(psycopg2.errors.InsufficientPrivilege):
                    with conn.cursor() as cur:
                        cur.execute(statement)

    def test_period_events_distinct_keys_source_filter_and_literal_search(self):
        # Two modifications of the same feature are two events, one identity.
        self.record(self.history_bundle(2))
        result=self.record(self.history_bundle(3))
        reader=self.reader_pool()
        try:
            with read_only_snapshot(reader) as query:
                data=views.overview(query,period='4m',start=None,end=None,domain='tee',changed_only=True,offset=0,limit=1)
                self.assertEqual(data['total_runs'],2)
                self.assertEqual(len(data['runs']),1)
                self.assertEqual(data['totals']['updated'],6)  # block + 2 lot variants each run
                block=next(row for row in data['layers'] if row['table_name']=='building_blocks')
                self.assertEqual((block['updated'],block['unique_records']),(2,1))
                data=views.overview(query,period='latest',start=None,end=None,domain='ktima',changed_only=True,offset=0,limit=25)
                self.assertEqual(data['totals']['updated'],0)
                self.assertEqual(data['layers'],[])
                for literal in ('%',"' OR true --",'_'):
                    detail=views.details(query,result['history_id'],domain='',table='',kind='',key=literal,offset=0,limit=25)
                    self.assertEqual(detail['total_changes'],0)
        finally:
            reader.closeall()

    def test_partial_installation_cannot_silently_disable_recording(self):
        self.query('DROP TABLE epol_meta.sync_history_config')
        before=self.source_fingerprints()
        with self.assertRaisesRegex(LoadError,'Incomplete'):
            self.record()
        self.assertEqual(self.source_fingerprints(),before)

    def test_setup_postcheck_failure_rolls_back_all_new_tables_and_grants(self):
        self.query('DROP TABLE epol_meta.sync_history_config,epol_meta.sync_history_changes,epol_meta.sync_history_layers,epol_meta.sync_history_runs CASCADE')
        before=self.source_fingerprints()
        with patch.object(setup,'verify_reader',side_effect=ValueError('injected reader postcheck')),self.assertRaisesRegex(ValueError,'reader postcheck'):
            setup.install(self.connect,self.target,READER)
        with self.owner.cursor() as cur:
            self.assertFalse(history.installed(cur))
            verify_access(cur)
        self.assertEqual(self.source_fingerprints(),before)
