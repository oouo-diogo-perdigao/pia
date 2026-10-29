import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
from src.pia.service import WorkspaceService
from Plugins.Connectors.google.drive import Drive

class ConnectorWorkspaceTests(unittest.TestCase):
    def test_google_uses_authorized_oauth_accounts_even_with_legacy_file(self):
        with TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'.env').write_text('GOOGLE_APPLICATION_CREDENTIALS=old.json\n')
            (root/'old.json').write_text('{"client_email":"old@example.invalid"}')
            resources=Mock();resources.accounts.return_value=[{'id':'personal'},{'id':'work'}]
            resources._access_token.return_value='fixture'
            drive=Drive(resources,root)
            self.assertEqual(drive.accounts(),resources.accounts.return_value)
            self.assertEqual(drive.headers('work'),{'Authorization':'Bearer fixture'})
            resources._access_token.assert_called_once_with('google','work')
            with self.assertRaises(ValueError):drive.headers('service-account')

    def test_inspection_includes_each_plugin_and_clears_only_selected_nested_log(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);service=WorkspaceService.__new__(WorkspaceService)
            service.plugin_folders=lambda:[('Apps/podcast_automation',root),('Bot/secretaria',root),('Connectors/google',root)]
            with patch('src.pia.service.BASE_DIR',root):
                logs=service._dispatch('GET','/logs',{}, {})
                self.assertEqual(len(logs),3)
                target=root/'logs/plugins/Bot/secretaria.log';target.write_text('fixture')
                other=root/'logs/plugins/Connectors/google.log';other.write_text('keep')
                service._dispatch('POST','/logs/clear',{'name':'plugins/Bot/secretaria.log'}, {})
                self.assertEqual(target.read_text(),'');self.assertEqual(other.read_text(),'keep')
                for name in ('../outside.log',str(root/'outside.log')):
                    with self.assertRaises(ValueError):service._dispatch('POST','/logs/clear',{'name':name}, {})
