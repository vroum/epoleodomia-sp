"""Cadastral summaries must expose attribute edits and source-ID changes."""
from pathlib import Path
import tempfile
from unittest.mock import patch

import sync_kaek_operating as cad
from tests.support import OfflineCase


class CadastreDigestTests(OfflineCase):
    def report(self,**extra):
        result={'table':'kaek_parcels_operating','counts_only':False,
                'new':[],'removed':[],'geom_changed':[],'use_changed':[]}
        result.update(extra)
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(cad,'__file__',str(Path(directory)/'sync_kaek_operating.py')):
            return cad.write_changes_report([result]).read_text(encoding='utf-8')

    def test_property_counts_and_nullable_attribute_edits_are_visible(self):
        text=self.report(attributes_changed=[{'kaek':'TEST-KAEK','fields':{
            'prop_hor':{'old':13,'new':12},'prop_vert':{'old':None,'new':0}}}])
        self.assertIn('TEST-KAEK',text)
        self.assertIn('prop_hor: 13 → 12',text)
        self.assertIn('prop_vert: null → 0',text)
        self.assertNotIn('Καμία αλλαγή',text)

    def test_source_id_reassignment_is_not_a_new_or_removed_kaek(self):
        text=self.report(source_ids_changed=[('TEST-KAEK',1,101)])
        self.assertIn('OBJECTID',text)
        self.assertIn('TEST-KAEK: 1 → 101',text)
        self.assertNotIn('Νέα ΚΑΕΚ',text)
        self.assertNotIn('Διαγραμμένα ΚΑΕΚ',text)
        self.assertNotIn('Καμία αλλαγή',text)

    def test_old_diff_shape_with_no_changes_remains_supported(self):
        self.assertIn('Καμία αλλαγή',self.report())
