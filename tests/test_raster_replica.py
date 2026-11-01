"""Real immutable archive/history and local restore failures, without live I/O."""
from pathlib import Path
import json
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import raster_replica as replica
from tests.test_raster_download import source,tif_bytes


class RasterReplicaTests(unittest.TestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root=Path(directory.name)
        self.local=self.root/'local'
        self.local.mkdir()
        self.nas=self.root/'nas'
        self.rows=[source()]
        self.file=self.local/'map.tif'
        self.file.write_bytes(tif_bytes())

    def publish(self):
        return replica.push(self.rows,self.local,self.nas,apply=True)

    def test_preview_validates_sources_without_creating_archive(self):
        result=replica.push(self.rows,self.local,self.nas)
        self.assertEqual(result['new_objects'],1)
        self.assertFalse(self.nas.exists())

    def test_identical_content_is_stored_once_and_manifest_keeps_both_identities(self):
        (self.local/'other.tif').write_bytes(self.file.read_bytes())
        self.rows.append(source(2,'other.tif'))
        result=self.publish()
        self.assertEqual((result['total'],result['objects'],result['copied']),(2,1,1))
        manifest=replica.read_manifest(self.nas)
        self.assertEqual(len(manifest['files']),2)
        self.assertEqual(len(list((self.nas/'objects').rglob('*.tif'))),1)
        self.assertFalse((self.nas/'.publish.lock').exists())

    def test_changed_content_creates_new_version_and_keeps_previous_bytes(self):
        self.publish()
        old=replica.read_manifest(self.nas)['files'][0]['sha256']
        previous=replica.object_path(self.nas,old).read_bytes()
        self.file.write_bytes(tif_bytes(width=32))
        self.publish()
        new=replica.read_manifest(self.nas)['files'][0]['sha256']
        self.assertNotEqual(old,new)
        self.assertEqual(replica.object_path(self.nas,old).read_bytes(),previous)
        self.assertEqual(len(list((self.nas/'manifests').glob('*.json'))),2)

    def test_corrupt_object_is_not_overwritten_or_published_as_latest(self):
        self.publish()
        old_latest=(self.nas/'latest.json').read_bytes()
        digest=replica.read_manifest(self.nas)['files'][0]['sha256']
        path=replica.object_path(self.nas,digest)
        path.write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError,'corrupt'):
            self.publish()
        self.assertEqual(path.read_bytes(),b'corrupt')
        self.assertEqual((self.nas/'latest.json').read_bytes(),old_latest)

    def test_failed_copy_does_not_replace_previous_complete_manifest(self):
        self.publish()
        previous=(self.nas/'latest.json').read_bytes()
        (self.local/'b.tif').write_bytes(tif_bytes(width=32))
        self.rows.append(source(2,'b.tif'))
        real=replica.copy_verified
        def fail_b(src,*args,**kwargs):
            if Path(src).name=='b.tif':
                raise OSError('NAS disconnected')
            return real(src,*args,**kwargs)
        with patch.object(replica,'copy_verified',side_effect=fail_b):
            with self.assertRaisesRegex(OSError,'disconnected'):
                self.publish()
        self.assertEqual((self.nas/'latest.json').read_bytes(),previous)
        self.assertFalse((self.nas/'.publish.lock').exists())
        self.assertEqual(list(self.nas.rglob('*.part')),[])

    def test_source_change_during_copy_is_detected_before_publication(self):
        real=replica.copy_verified
        def change_source(src,*args,**kwargs):
            self.file.write_bytes(tif_bytes(width=32))
            return real(src,*args,**kwargs)
        with patch.object(replica,'copy_verified',side_effect=change_source):
            with self.assertRaisesRegex(ValueError,'checksum mismatch'):
                self.publish()
        self.assertFalse((self.nas/'latest.json').exists())
        self.assertEqual(list(self.nas.rglob('*.part')),[])

    def test_pull_restores_missing_file_and_repeat_reuses_same_bytes(self):
        self.publish()
        cache=self.root/'cache'
        result=replica.pull(self.rows,cache,self.nas,apply=True)
        self.assertEqual((result['copied'],result['failed']),(1,0))
        target=cache/'FEK_406D_1989'/'map.tif'
        self.assertEqual(target.read_bytes(),self.file.read_bytes())
        repeated=replica.pull(self.rows,cache,self.nas,apply=True)
        self.assertEqual((repeated['copied'],repeated['reused']),(0,1))

    def test_pull_preview_creates_no_local_directory(self):
        self.publish()
        cache=self.root/'cache'
        result=replica.pull(self.rows,cache,self.nas)
        self.assertEqual(result['missing'],1)
        self.assertFalse(cache.exists())

    def test_single_file_recovery_does_not_require_or_restore_other_ids(self):
        (self.local/'other.tif').write_bytes(tif_bytes(width=32))
        self.rows.append(source(2,'other.tif'))
        self.publish()
        cache=self.root/'cache'
        result=replica.pull(self.rows,cache,self.nas,apply=True,raster_id=2)
        self.assertEqual((result['total'],result['copied'],result['failed']),(1,1,0))
        self.assertFalse((cache/'FEK_406D_1989'/'map.tif').exists())
        with self.assertRaisesRegex(ValueError,'absent'):
            replica.pull(self.rows,cache,self.nas,raster_id=999)

    def test_pull_never_overwrites_a_different_local_version(self):
        self.publish()
        self.file.write_bytes(tif_bytes(width=32))
        previous=self.file.read_bytes()
        result=replica.pull(self.rows,self.local,self.nas,apply=True)
        self.assertEqual(result['failed'],1)
        self.assertEqual(self.file.read_bytes(),previous)
        self.assertEqual(list(self.local.rglob('*.part')),[])

    def test_pull_rejects_stale_source_identity_without_creating_file(self):
        self.publish()
        self.rows[0]['url_georef']='https://example.invalid/changed.tif'
        cache=self.root/'cache'
        result=replica.pull(self.rows,cache,self.nas,apply=True)
        self.assertEqual(result['failed'],1)
        self.assertFalse(cache.exists())

    def test_invalid_manifest_checksums_names_and_duplicate_ids_are_rejected(self):
        self.publish()
        original=replica.read_manifest(self.nas)
        for kind in ('checksum','filename','duplicate'):
            manifest=json.loads(json.dumps(original))
            if kind=='checksum':
                manifest['files'][0]['sha256']='../../outside'
            elif kind=='filename':
                manifest['files'][0]['filename']='../outside.tif'
            else:
                manifest['files'].append(dict(manifest['files'][0]))
            (self.nas/'latest.json').write_text(json.dumps(manifest))
            with self.subTest(kind=kind),self.assertRaises(ValueError):
                replica.pull(self.rows,self.root/'cache',self.nas,apply=True)
        self.assertFalse((self.root/'cache').exists())

    def test_existing_publisher_lock_is_not_removed(self):
        self.nas.mkdir()
        lock=self.nas/'.publish.lock'
        lock.write_text('another writer')
        with self.assertRaises(FileExistsError):
            self.publish()
        self.assertEqual(lock.read_text(),'another writer')
        self.assertFalse((self.nas/'latest.json').exists())

    def test_concurrent_different_local_file_is_retained_and_staging_is_cleaned(self):
        target=self.root/'target.tif'
        other=tif_bytes(width=32)
        def race(staged,destination):
            Path(destination).write_bytes(other)
            raise FileExistsError('concurrent creator')
        with patch.object(replica,'publish_new',side_effect=race):
            with self.assertRaises(FileExistsError):
                replica.copy_verified(self.file,target,replica.sha256(self.file))
        self.assertEqual(target.read_bytes(),other)
        self.assertEqual(list(self.root.glob('*.part')),[])

    def test_catalog_connection_is_read_only_and_uses_unified_view(self):
        with patch.object(replica.psycopg2,'connect') as connect:
            replica.catalog_rows()
        self.assertIn('default_transaction_read_only=on',connect.call_args.kwargs['options'])
        cursor=connect.return_value.cursor.return_value.__enter__.return_value
        self.assertIn('sp_geodata.v_all_rasters',cursor.execute.call_args.args[0])
        self.assertEqual(cursor.execute.call_count,1)

    def test_cli_requires_explicit_unc_root_before_database_access(self):
        with patch.object(replica,'SETTINGS',SimpleNamespace(raster_nas_path=None)), \
                patch.object(replica,'catalog_rows') as read:
            self.assertEqual(replica.main(['push']),1)
        read.assert_not_called()
