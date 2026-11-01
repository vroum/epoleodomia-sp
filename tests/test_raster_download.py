"""Real GeoTIFF/filesystem failure cases; no network or database required."""

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import numpy as np
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import Affine, from_origin
import requests

import download_rasters as dl


def tif_bytes(*, width=16, crs='EPSG:2100', transform=None):
    with MemoryFile() as memory:
        with memory.open(driver='GTiff',width=width,height=16,count=2,dtype='uint8',
                         crs=crs,transform=transform or from_origin(420000,4120000,1,1)) as dst:
            dst.write(np.ones((2,16,width),dtype='uint8'))
        return memory.read()


class Response:
    status_code = 200

    def __init__(self, content, *, length=None, fault=None):
        self.content = content
        self.headers = {'Content-Length': str(len(content) if length is None else length)}
        self.fault = fault
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def raise_for_status(self):
        if self.status_code != 200:
            raise requests.HTTPError('HTTP failure',response=self)

    def iter_content(self, chunk_size):
        yield self.content[:100]
        if self.fault:
            raise self.fault
        yield self.content[100:]


def source(raster_id=1, name='map.tif'):
    return dict(id=raster_id,fek='406Δ/1989',filename=name,url_georef='https://example.invalid/'+name,
                url_raw=None,download_status='pending',local_path_georef=None)


class RasterDownloadTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.path = self.root/'map.tif'
        self.old = tif_bytes(width=8)
        self.path.write_bytes(self.old)

    def download(self, response):
        with patch.object(dl.requests,'get',return_value=response),patch.object(dl,'RETRY_DELAY',0):
            return dl.download_file('https://example.invalid/map.tif',self.path)

    def assert_kept_old(self):
        self.assertEqual(self.path.read_bytes(),self.old)
        self.assertEqual(list(self.root.glob('.epol-*')),[])

    def test_valid_download_is_fully_validated_but_not_published_by_worker(self):
        response = Response(tif_bytes())
        result = self.download(response)
        self.assertTrue(result['success'],result)
        self.assertEqual(result['metadata']['crs_epsg'],2100)
        self.assertEqual(result['metadata']['width_px'],16)
        self.assertEqual(result['metadata']['bands'],2)
        self.assertEqual(self.path.read_bytes(),self.old)
        self.assertEqual(result['staged_path'].read_bytes(),response.content)
        self.assertTrue(response.closed)
        result['staged_path'].unlink()

    def test_stream_interruption_preserves_old_file_and_removes_partial(self):
        result = self.download(Response(tif_bytes(),fault=requests.ConnectionError('connection lost')))
        self.assertFalse(result['success'])
        self.assertIn('connection lost',result['error'])
        self.assert_kept_old()

    def test_content_length_mismatch_and_empty_body_are_rejected(self):
        for response in (Response(tif_bytes(),length=999999),Response(b'')):
            with self.subTest(length=response.headers):
                self.assertFalse(self.download(response)['success'])
                self.assert_kept_old()
                self.assertTrue(response.closed)

    def test_html_and_truncated_pixel_data_are_not_successful_downloads(self):
        for content in (b'<html>upstream error</html>',tif_bytes(width=512)[:-100]):
            with self.subTest(size=len(content)):
                result = self.download(Response(content))
                self.assertFalse(result['success'],result)
                self.assert_kept_old()

    def test_wrong_missing_crs_rotation_and_south_up_are_rejected(self):
        for kwargs in ({'crs':'EPSG:4326'},{'crs':None},
                       {'transform':Affine(1,.1,420000,0,-1,4120000)},
                       {'transform':Affine(1,0,420000,0,1,4120000)}):
            with self.subTest(kwargs=kwargs):
                self.assertFalse(self.download(Response(tif_bytes(**kwargs)))['success'])
                self.assert_kept_old()

    def test_http_404_is_not_retried_and_response_is_closed(self):
        response = Response(b'not found')
        response.status_code = 404
        with patch.object(dl.requests,'get',return_value=response) as get:
            self.assertFalse(dl.download_file('https://example.invalid/404',self.path)['success'])
        self.assertEqual(get.call_count,1)
        self.assertTrue(response.closed)
        self.assert_kept_old()

    def test_missing_rasterio_is_an_explicit_error(self):
        with patch.dict(sys.modules,{'rasterio':None}):
            with self.assertRaisesRegex(RuntimeError,'rasterio is required'):
                dl.require_rasterio()

    def test_windows_traversal_and_reserved_names_cannot_escape_root(self):
        for name in ('../map.tif',r'..\map.tif','C:map.tif','NUL.tif','map.tif.','map.tif ','x|y.tif'):
            with self.subTest(name=name),self.assertRaisesRegex(ValueError,'Unsafe'):
                dl.raster_destination(source(name=name),self.root)
        self.assertEqual(dl.raster_destination(source(),self.root)[1],'map.tif')
        self.assertEqual(dl.raster_destination(source(name='new.tif'),self.root)[1],'FEK_406D_1989/new.tif')

    def test_existing_flat_file_is_reused_without_a_second_copy(self):
        raster=source()
        raster['local_path_georef']='FEK_406D_1989/map.tif'
        self.assertEqual(dl.raster_destination(raster,self.root),(self.path,'map.tif'))
        nested=self.root/'FEK_406D_1989'/'map.tif'
        nested.parent.mkdir()
        nested.write_bytes(tif_bytes(width=32))
        self.assertEqual(dl.raster_destination(raster,self.root),(nested,'FEK_406D_1989/map.tif'))

    def test_unsafe_catalog_path_or_mismatched_filename_is_rejected(self):
        for path in ('../map.tif',r'C:\map.tif',r'\outside\map.tif','FEK/x.tif'):
            raster=source()
            raster['local_path_georef']=path
            with self.subTest(path=path),self.assertRaises(ValueError):
                dl.raster_destination(raster,self.root)

    def publication(self):
        result = self.download(Response(tif_bytes()))
        result.update(local_path=str(self.path),relative_path='FEK_406D_1989/map.tif')
        return result

    def test_successful_publication_replaces_file_and_cleans_staging_and_backup(self):
        result = self.publication()
        conn = MagicMock()
        with patch.object(dl,'update_catalog_downloaded') as update:
            dl.publish_download(conn,source(),result)
        self.assertEqual(dl.extract_raster_metadata(self.path)['width_px'],16)
        self.assertFalse(result['staged_path'].exists())
        self.assertEqual(list(self.root.glob('.epol-*')),[])
        self.assertFalse(update.call_args.kwargs['commit'])
        self.assertEqual(update.call_args.kwargs['source'],source())

    def test_database_failure_cannot_replace_old_file(self):
        result = self.publication()
        with patch.object(dl,'update_catalog_downloaded',side_effect=RuntimeError('database failure')):
            with self.assertRaisesRegex(RuntimeError,'database failure'):
                dl.publish_download(MagicMock(),source(),result)
        self.assert_kept_old()

    def test_commit_failure_restores_previous_file(self):
        result = self.publication()
        conn = MagicMock()
        conn.__exit__.side_effect = RuntimeError('commit failed')
        with patch.object(dl,'update_catalog_downloaded'):
            with self.assertRaisesRegex(RuntimeError,'commit failed'):
                dl.publish_download(conn,source(),result)
        self.assert_kept_old()

    def test_rename_failure_rolls_back_and_preserves_old_file(self):
        result = self.publication()
        with patch.object(dl,'update_catalog_downloaded'),patch.object(dl.os,'replace',side_effect=OSError('file in use')):
            with self.assertRaisesRegex(OSError,'file in use'):
                dl.publish_download(MagicMock(),source(),result)
        self.assert_kept_old()

    def test_restore_failure_retains_backup_and_reports_its_location(self):
        result = self.publication()
        conn = MagicMock()
        conn.__exit__.side_effect = RuntimeError('commit failed')
        replace = dl.os.replace
        def fail_restoration(src, dst):
            if Path(src).suffix == '.previous':
                raise OSError('file locked')
            return replace(src,dst)
        with patch.object(dl,'update_catalog_downloaded'),patch.object(dl.os,'replace',side_effect=fail_restoration):
            with self.assertRaisesRegex(RuntimeError,'previous file retained at'):
                dl.publish_download(conn,source(),result)
        backups=list(self.root.glob('*.previous'))
        self.assertEqual(len(backups),1)
        self.assertEqual(backups[0].read_bytes(),self.old)
        self.assertFalse(result['staged_path'].exists())

    def test_lost_database_connection_cleans_unpublished_parallel_downloads(self):
        conn = MagicMock()
        conn.rollback.side_effect = OSError('connection lost')
        rows=[source(1,'a.tif'),source(2,'b.tif')]
        with patch.object(dl,'GEOREF_DIR',self.root/'downloads'), \
                patch.object(dl,'get_db_connection',side_effect=[MagicMock(),conn]), \
                patch.object(dl,'get_pending_rasters',return_value=rows), \
                patch.object(dl.requests,'get',side_effect=lambda *a,**k:Response(tif_bytes())), \
                patch.object(dl,'publish_download',side_effect=RuntimeError('write failed')), \
                redirect_stdout(StringIO()):
            with self.assertRaisesRegex(OSError,'connection lost'):
                dl.sync_rasters(parallel=2)
        self.assertEqual(list(self.root.rglob('.epol-*')),[])

    def test_dry_run_creates_no_directory_or_writer_connection(self):
        root = self.root/'not-created'
        conn = MagicMock()
        with patch.object(dl,'GEOREF_DIR',root),patch.object(dl,'get_db_connection',return_value=conn) as connect, \
                patch.object(dl,'get_pending_rasters',return_value=[source()]), \
                patch.object(dl,'require_rasterio') as require,patch.object(dl.requests,'get') as get, \
                redirect_stdout(StringIO()):
            result = dl.sync_rasters(dry_run=True,raster_id=1,limit=1)
        self.assertEqual(result['total'],1)
        connect.assert_called_once_with(read_only=True)
        self.assertFalse(root.exists())
        require.assert_not_called()
        get.assert_not_called()

    def test_missing_dependency_fails_before_writer_connection_or_download(self):
        with patch.object(dl,'get_db_connection',return_value=MagicMock()) as connect, \
                patch.object(dl,'get_pending_rasters',return_value=[source()]), \
                patch.object(dl,'require_rasterio',side_effect=RuntimeError('rasterio is required')), \
                patch.object(dl.requests,'get') as get,redirect_stdout(StringIO()):
            with self.assertRaisesRegex(RuntimeError,'rasterio'):
                dl.sync_rasters()
        connect.assert_called_once_with(read_only=True)
        get.assert_not_called()

    def test_colliding_catalog_destinations_fail_before_download(self):
        with patch.object(dl,'get_db_connection',return_value=MagicMock()), \
                patch.object(dl,'get_pending_rasters',return_value=[source(),source(2)]), \
                patch.object(dl.requests,'get') as get:
            with self.assertRaisesRegex(ValueError,'same raster destination'):
                dl.sync_rasters()
        get.assert_not_called()

    def test_invalid_arguments_and_unimplemented_raw_mode_fail_before_connections(self):
        for kwargs in ({'parallel':0},{'limit':0},{'raster_id':-1},{'include_raw':True}):
            with self.subTest(kwargs=kwargs),patch.object(dl,'get_db_connection') as connect:
                with self.assertRaises(ValueError):
                    dl.sync_rasters(**kwargs)
                connect.assert_not_called()

    def test_cli_returns_failure_instead_of_silent_success(self):
        with patch.object(sys,'argv',['download_rasters.py','--limit','1']), \
                patch.object(dl,'sync_rasters',return_value={'failed':1}),redirect_stdout(StringIO()):
            self.assertEqual(dl.main(),1)

    def test_missing_repair_applies_limit_after_skipping_existing_downloaded_files(self):
        rows=[source(1),source(2,'new.tif'),source(3,'later.tif')]
        for row in rows:
            row['download_status']='downloaded'
        with patch.object(dl,'GEOREF_DIR',self.root),patch.object(dl,'get_db_connection',return_value=MagicMock()), \
                patch.object(dl,'get_pending_rasters',return_value=rows) as pending, \
                patch.object(dl.requests,'get') as get,redirect_stdout(StringIO()) as output:
            result=dl.sync_rasters(repair_missing=True,limit=1,dry_run=True)
        self.assertEqual(result['total'],1)
        self.assertIn('id=2',output.getvalue())
        self.assertNotIn('id=1',output.getvalue())
        self.assertNotIn('id=3',output.getvalue())
        self.assertIsNone(pending.call_args.kwargs['limit'])
        self.assertTrue(pending.call_args.kwargs['include_downloaded'])
        get.assert_not_called()

    def test_force_refresh_keeps_existing_rows_even_when_repair_is_enabled(self):
        row=source()
        row['download_status']='downloaded'
        with patch.object(dl,'GEOREF_DIR',self.root),patch.object(dl,'get_db_connection',return_value=MagicMock()), \
                patch.object(dl,'get_pending_rasters',return_value=[row]),redirect_stdout(StringIO()):
            result=dl.sync_rasters(repair_missing=True,force=True,dry_run=True,limit=1)
        self.assertEqual(result['total'],1)


if __name__ == '__main__':
    unittest.main()
