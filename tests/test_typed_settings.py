import base64
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from src.env_types import fields, validate, dotenv_values, load_dotenv, split_key
from src.pia.service import Apps, WorkspaceService
from src.plugin_migration import migrate_connectors
from src.workspace_store import WorkspaceStore


class TypedSettingsTests(unittest.TestCase):
    def test_types_empty_values_and_strict_validation(self):
        for kind in ('BOOL','INT','FLOAT','PATH','FILE','SECRET'):
            self.assertEqual(validate('VALUE__'+kind,''),'')
        for kind,value in [('BOOL','yes'),('INT','1.5'),('FLOAT','nan'),('FLOAT','inf'),('PATH','missing-folder'),('FILE','missing-file')]:
            with self.subTest(kind=kind,value=value),self.assertRaises(ValueError):validate('VALUE__'+kind,value)
        self.assertEqual(validate('VALUE__BOOL','false'),'false')
        self.assertEqual(validate('VALUE__INT','-42'),'-42')
        self.assertEqual(validate('VALUE__FLOAT','1.25e-3'),'1.25e-3')
        self.assertEqual(split_key('UNKNOWN__CUSTOM'),('UNKNOWN__CUSTOM','string'))

    def test_legacy_values_and_typed_runtime_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);example=root/'.env.example';current=root/'.env'
            example.write_text('ACTIVE__BOOL=true\nCOUNT__INT=3\nKEY__SECRET=\n')
            current.write_text('ACTIVE=1\nCOUNT=2\nCOUNT__INT=8\nKEY=secret\nCUSTOM=hello\n')
            values=dict(fields(example,current))
            self.assertEqual(values,{'ACTIVE__BOOL':'true','COUNT__INT':'8','KEY__SECRET':'secret','CUSTOM':'hello'})
            self.assertEqual(dotenv_values(current)['COUNT'],'8')
            with patch.dict(os.environ,{'COUNT__INT':'9'},clear=True):
                load_dotenv(current)
                self.assertEqual(os.environ['COUNT'],'9')
            current.write_text('COUNT__INT=\nACTIVE__BOOL=\n')
            with patch.dict(os.environ,{},clear=True):
                load_dotenv(current)
                self.assertNotIn('COUNT',os.environ)
                self.assertNotIn('ACTIVE',os.environ)

    def test_settings_validate_before_writing_and_allow_clear_secret(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);current=root/'.env';current.write_text('COUNT=2\nSECRET=abc\n')
            service=WorkspaceService.__new__(WorkspaceService)
            service.settings=lambda:[dict(id='general',fields=[dict(name='COUNT__INT',sensitive=False),dict(name='SECRET__SECRET',sensitive=True)])]
            with patch('src.pia.service.CONFIG_DIR',root):
                with self.assertRaises(ValueError):service.save_settings('general',{'SECRET__SECRET':'new','COUNT__INT':'oops'})
                self.assertEqual(current.read_text(),'COUNT=2\nSECRET=abc\n')
                service.save_settings('general',{'COUNT__INT':'4','SECRET__SECRET':''})
                self.assertEqual(dotenv_values(current),{'COUNT':'4','SECRET':''})
                self.assertNotIn('\nCOUNT=',current.read_text())

    def test_managed_upload_and_rejected_credentials_do_not_replace_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);service=WorkspaceService.__new__(WorkspaceService)
            name='GOOGLE_APPLICATION_CREDENTIALS__FILE'
            service.settings=lambda:[dict(id='Connectors/google',fields=[dict(name=name,type='file')])]
            service.plugin_folders=lambda:[('Connectors/google',root)]
            payload=dict(section='Connectors/google',name=name,filename='private.json',data=base64.b64encode(json.dumps({'type':'service_account','client_email':'fixture@example.invalid','private_key':'fixture-only'}).encode()).decode())
            response=service.upload_setting(payload);target=Path(response['path'])
            self.assertEqual(target,root/'files/google_GOOGLE_APPLICATION_CREDENTIALS.json')
            self.assertEqual(dotenv_values(root/'.env')['GOOGLE_APPLICATION_CREDENTIALS'],str(target))
            original=target.read_bytes();payload['data']=base64.b64encode(b'{}').decode()
            with self.assertRaises(ValueError):service.upload_setting(payload)
            self.assertEqual(target.read_bytes(),original)
            payload['name']='UNDECLARED__FILE'
            with self.assertRaises(ValueError):service.upload_setting(payload)

    def test_manifest_and_language_preferences(self):
        for app in Apps().records():
            meta=json.loads((app['folder']/'pia.json').read_text(encoding='utf-8'))
            self.assertEqual(app['name'],meta['nome'])
            self.assertTrue((app['folder']/'web'/meta['about']).is_file())
            self.assertTrue((app['folder']/'lang/pt-BR.json').is_file())
        with tempfile.TemporaryDirectory() as directory:
            store=WorkspaceStore(Path(directory)/'workspace.db')
            service=WorkspaceService(backend=SimpleNamespace(store=store))
            self.assertEqual(service.dispatch('GET','/preferences',{},{}),{'language':'pt-BR'})
            self.assertEqual(service.dispatch('POST','/preferences',{'language':'en'},{}),{'language':'en'})
            with self.assertRaises(ValueError):service.dispatch('POST','/preferences',{'language':'invalid'}, {})

    def test_connector_upgrade_preserves_existing_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);old=root/'Plugins/Plugins/google';new=root/'Plugins/Connectors/google'
            (old/'secrets').mkdir(parents=True);new.mkdir(parents=True)
            (old/'.env').write_text('VALUE=old');(new/'.env').write_text('VALUE=new')
            (old/'secrets/key.json').write_text('fixture');(old/'unused.py').write_text('ignored')
            migrate_connectors(root)
            self.assertEqual((new/'.env').read_text(),'VALUE=new')
            self.assertEqual((new/'secrets/key.json').read_text(),'fixture')
            self.assertFalse((new/'unused.py').exists())


if __name__=='__main__':unittest.main()
