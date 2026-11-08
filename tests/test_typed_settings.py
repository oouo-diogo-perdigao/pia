from src.settings_store import get_store
import base64
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from src.env_types import fields, validate, dotenv_values, split_key
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
                self.assertEqual(dotenv_values(current)['COUNT'],'8')
                self.assertNotIn('COUNT',os.environ)

    def test_settings_validate_before_writing_and_allow_clear_secret(self):
        service=WorkspaceService.__new__(WorkspaceService)
        definitions=[dict(name='COUNT',type='int',default='2'),dict(name='SECRET',type='secret',default='')]
        service.settings=lambda:[dict(id='general',fields=[dict(name='COUNT'),dict(name='SECRET')])]
        with patch('src.settings_store.schema',return_value=definitions):
            get_store().save('general',{'COUNT':'2','SECRET':'abc'})
            with self.assertRaises(ValueError):service.save_settings('general',{'SECRET':'new','COUNT':'oops'})
            self.assertEqual(get_store().values('general')['SECRET'],'abc')
            service.save_settings('general',{'COUNT':'4','SECRET':''})
            self.assertEqual(get_store().values('general')['COUNT'],'4')
            self.assertEqual(get_store().values('general')['SECRET'],'')
            self.assertNotIn(b'abc',get_store().path.read_bytes())

    def test_managed_upload_is_in_user_profile_and_invalid_data_preserves_file(self):
        from src.user_paths import user_path
        service=WorkspaceService.__new__(WorkspaceService);name='INPUT_FILE'
        service.settings=lambda:[dict(id='Connectors/agents',fields=[dict(name=name,type='file')])]
        definitions=[dict(name=name,type='file',default='')]
        payload=dict(section='Connectors/agents',name=name,filename='example.json',data=base64.b64encode(b'{"fixture":true}').decode())
        with patch('src.settings_store.schema',return_value=definitions):
            response=service.upload_setting(payload);target=Path(response['path'])
            self.assertEqual(target,user_path('files/Connectors_agents/agents_INPUT_FILE.json'))
            self.assertEqual(get_store().values('Connectors/agents')[name],str(target))
            original=target.read_bytes();payload['data']='invalid-base64'
            with self.assertRaises(ValueError):service.upload_setting(payload)
            self.assertEqual(target.read_bytes(),original)
            payload['name']='UNDECLARED'
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
