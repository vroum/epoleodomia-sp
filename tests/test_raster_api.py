"""FEK flat/catalog paths and the actual raster HTTP protocols, without live I/O."""

from pathlib import Path
import asyncio
import json
import tempfile
from types import SimpleNamespace
from urllib.parse import urlencode
from unittest.mock import patch

import api_server as api
import download_rasters as dl
from tests.support import OfflineCase
from tests.test_raster_download import Response, tif_bytes


BBOX={'minx':0,'miny':0,'maxx':1,'maxy':1}


class ASGIClient:
    """Exercise real routing/serialization without a live listener or httpx."""
    def get(self,path,*,params):
        messages=[]
        async def receive():
            return {'type':'http.request','body':b'','more_body':False}
        async def send(message):
            messages.append(message)
        scope=dict(type='http',asgi={'version':'3.0'},http_version='1.1',method='GET',
                   scheme='http',path=path,raw_path=path.encode(),root_path='',
                   query_string=urlencode(params).encode(),headers=[],
                   client=('127.0.0.1',1234),server=('test',80))
        asyncio.run(api.app(scope,receive,send))
        status=next(m['status'] for m in messages if m['type']=='http.response.start')
        text=b''.join(m.get('body',b'') for m in messages if m['type']=='http.response.body').decode()
        return SimpleNamespace(status_code=status,text=text,json=lambda:json.loads(text))


class RasterAPITests(OfflineCase):
    def setUp(self):
        super().setUp()
        directory=tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root=Path(directory.name)
        self.start_patch(patch.object(api,'RASTER_BASE_PATH',str(self.root)))
        self.start_patch(patch.object(api,'FEK_LOCAL_PATH',str(self.root)))
        self.query=self.start_patch(patch.object(api,'execute_query'))
        self.client=ASGIClient()
        (self.root/'map.tif').write_bytes(tif_bytes())

    def test_unified_json_resolves_fek_relative_paths_and_keeps_other_collections(self):
        self.query.return_value=[
            ('fek','fek',1,'map.tif','FEK_1/map.tif','working',1000,1,0,'1Δ/1981',123,0,0,1,1),
            ('dji','dji',2,'drone.tif',r'O:\drone\drone.tif','working',None,.1,None,None,10,0,0,1,1)]
        response=self.client.get('/rasters/sheets',params=BBOX)
        self.assertEqual(response.status_code,200)
        body=response.json()
        self.assertEqual(body['count'],2)
        self.assertEqual(body['paths'],[str(self.root/'map.tif'),r'O:\drone\drone.tif'])
        self.assertTrue(body['sheets'][0]['available'])
        self.assertEqual(self.query.call_args.args[1][4],['working'])
        self.assertIn('sp_geodata.v_all_rasters',self.query.call_args.args[0])

    def test_unified_simple_returns_loadable_fek_and_preserves_six_field_protocol(self):
        self.query.return_value=[
            ('FEK_1/map.tif','fek','1Δ/1981',1000,0,'working'),
            ('FEK_2/missing.tif','fek','2Δ/1981',1000,1,'working'),
            (r'O:\drone\drone.tif','dji',None,None,None,'working')]
        response=self.client.get('/rasters/sheets/simple',params=BBOX)
        lines=response.text.splitlines()
        self.assertEqual(len(lines),2)
        self.assertEqual(lines[0],f'{self.root/"map.tif"}|fek|1D/1981|1000|0.00|working')
        self.assertTrue(all(len(line.split('|'))==6 for line in lines))
        self.assertEqual(self.query.call_args.args[1][4],['working'])

    def test_legacy_json_uses_working_view_and_reports_actual_file_availability(self):
        self.query.return_value=[(1,'1Δ/1981','title','map.tif','FEK_1/map.tif',16,16,1,1000,0)]
        response=self.client.get('/rasters/fek',params=BBOX)
        self.assertEqual(response.json()['paths'],[str(self.root/'map.tif')])
        self.assertTrue(response.json()['rasters'][0]['available'])
        self.assertIn("v.role='working'",self.query.call_args.args[0])
        self.assertIn('sp_geodata.v_all_rasters',self.query.call_args.args[0])

    def test_fek_simple_uses_flat_or_nested_files_and_url_fallback(self):
        nested=self.root/'FEK_2'/'nested.tif'
        nested.parent.mkdir()
        nested.write_bytes(tif_bytes())
        self.query.return_value=[
            ('map.tif','1Δ/1981',1000,0,'https://source/map.tif','FEK_1/map.tif'),
            ('nested.tif','2Δ/1981',1000,1,'https://source/nested.tif','FEK_2/nested.tif'),
            ('missing.tif','3Δ/1981',1000,1,'https://source/missing.tif','FEK_3/missing.tif')]
        lines=self.client.get('/rasters/fek/simple',params=BBOX).text.splitlines()
        self.assertEqual(len(lines),3)
        self.assertEqual([line.split('|')[-1] for line in lines],['LOCAL','LOCAL','URL'])
        self.assertEqual(lines[1].split('|')[0],str(nested))
        self.assertIn("v.role='working'",self.query.call_args.args[0])

    def test_unregistered_or_excluded_url_cannot_start_download(self):
        self.query.return_value=[]
        url='https://unregistered.invalid/map.tif'
        body=self.client.get('/rasters/fek/download',params={'url':url}).json()
        self.assertEqual(body['status'],'error')
        self.http.assert_not_called()
        self.assertEqual(self.query.call_args.args[1],(url,))
        self.assertIn("v.role='working'",self.query.call_args.args[0])
        self.connect.assert_not_called()

    def test_existing_file_is_validated_without_downloading_or_database_writes(self):
        self.query.return_value=[('map.tif','FEK_1/map.tif')]
        body=self.client.get('/rasters/fek/download',params={'url':'https://source/map.tif'}).json()
        self.assertEqual(body,{'status':'exists','path':str(self.root/'map.tif')})
        self.http.assert_not_called()
        self.query.assert_called_once()
        self.connect.assert_not_called()

    def test_on_demand_download_reuses_validated_staging_pipeline(self):
        self.query.return_value=[('new.tif','FEK_1/new.tif')]
        with patch.object(dl.requests,'get',return_value=Response(tif_bytes())):
            body=self.client.get('/rasters/fek/download',params={'url':'https://source/new.tif'}).json()
        self.assertEqual(body['status'],'downloaded')
        self.assertEqual(dl.extract_raster_metadata(body['path'])['crs_epsg'],2100)
        self.assertEqual(list(self.root.rglob('.epol-*')),[])
        self.query.assert_called_once()
        self.connect.assert_not_called()

    def test_invalid_download_returns_error_without_publishing_a_file(self):
        self.query.return_value=[('new.tif','FEK_1/new.tif')]
        with patch.object(dl.requests,'get',return_value=Response(b'<html>bad TIFF</html>')), \
                patch.object(dl,'RETRY_DELAY',0):
            body=self.client.get('/rasters/fek/download',params={'url':'https://source/new.tif'}).json()
        self.assertEqual(body['status'],'error')
        self.assertFalse((self.root/'FEK_1'/'new.tif').exists())
        self.assertEqual(list(self.root.rglob('.epol-*')),[])
        self.connect.assert_not_called()
