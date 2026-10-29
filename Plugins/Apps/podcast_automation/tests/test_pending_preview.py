import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from Plugins.Apps.podcast_automation import web_api
from Plugins.Connectors.google.drive import Drive

class PendingPreviewTests(unittest.TestCase):
    def test_paginated_read_only_queue_ignores_processed_and_non_zip(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);(root/'config').mkdir()
            (root/'config/config.json').write_text(json.dumps({'integrations':{'google_account':'work','google_folder':'folder'}}))
            with patch.object(web_api,'ROOT',root),patch('Plugins.Connectors.google.drive.Drive') as constructor:
                drive=constructor.return_value
                drive.accounts.return_value=[{'id':'work'}];drive.account.return_value='work'
                drive.folder_path.return_value='Meu Drive / RPG / Gravações'
                drive.list.side_effect=[{'files':[{'id':'1','name':'old-ok.ZIP'},{'id':'2','name':'new.zip'}],'nextPageToken':'next'}, {'files':[{'id':'3','name':'old-ok-omitido.zip'},{'id':'4','name':'cover.png'},{'id':'5','name':'another.zip'}]}]
                result=web_api.handle('pending-preview',{},SimpleNamespace(backend=SimpleNamespace(resources=Mock())))
                self.assertEqual([file['name'] for file in result['pending']],['new.zip','another.zip'])
                self.assertEqual(result['processed'],2)
                self.assertEqual(result['folder_path'],'Meu Drive / RPG / Gravações')
                self.assertEqual(drive.list.call_args.kwargs['cursor'],'next')
                drive.download.assert_not_called();drive.rename.assert_not_called()

    def test_local_queue_and_empty_folder_need_no_external_connection(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);(root/'config').mkdir();(root/'config/config.json').write_text('{}')
            (root/'.env').write_text('DRIVE_PROCESS=false\nLOCAL_DRIVE_FOLDER=recordings\n')
            folder=root/'recordings';folder.mkdir()
            for name in ('new.zip','old-ok.zip','ignored.txt'):(folder/name).touch()
            with patch.object(web_api,'ROOT',root):
                result=web_api.handle('pending-preview',{},None)
            self.assertEqual(len(result['pending']),1)
            self.assertEqual(result['processed'],1)
            self.assertEqual(result['folder_path'],str(folder))

    def test_drive_path_resolves_names_from_ancestors_and_detects_cycles(self):
        drive=Drive(Mock());responses=[]
        for value in ({'name':'Gravações','parents':['rpg']},{'name':'RPG','parents':['root']},{'name':'Meu Drive'}):
            response=Mock();response.__enter__=Mock(return_value=response);response.__exit__=Mock();response.json.return_value=value;responses.append(response)
        with patch.object(drive,'request',side_effect=responses):
            self.assertEqual(drive.folder_path('folder','work'),'Meu Drive / RPG / Gravações')
        responses[0].json.return_value={'name':'Loop','parents':['folder']}
        with patch.object(drive,'request',return_value=responses[0]),self.assertRaises(ValueError):drive.folder_path('folder','work')
