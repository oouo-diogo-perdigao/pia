"""Shared integrations: isolated account storage, migration, paging and app access."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock,patch
import base64
import io
import json
import unittest
from dotenv import dotenv_values
from Plugins.Connectors.object_storage.service import ObjectStorage
from Plugins.Connectors.google.drive import Drive
from Plugins.Connectors.discord.service import Discord
from src.plugin_migration import migrate
from src import app_access
from src.pia.service import Apps

class Vault:
    def __init__(self):self.data={}
    def get(self,key):return self.data.get(key)
    def set(self,key,value):self.data[key]=value
    def delete(self,key):self.data.pop(key,None)

class SharedPluginTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.vault=Vault();self.client=Mock();self.factory=Mock(return_value=self.client)
        self.storage=ObjectStorage(self.root,self.vault,self.factory)
    def account(self,name='Personal',**kwargs):
        return self.storage.save_account(dict(name=name,provider='s3',endpoint='https://s3.example.invalid',region='auto',bucket='bucket',public_url='https://cdn.example.invalid',access_key=name,secret_key='secret-'+name,**kwargs))['id']
    def test_multiple_accounts_secrets_only_in_vault_and_blank_preserves(self):
        first=self.account();second=self.account('Work')
        self.assertEqual(len(self.storage.accounts()),2)
        self.assertNotIn('secret-',(self.root/'config.json').read_text())
        self.assertNotIn('secret_key',json.dumps(self.storage.accounts()))
        self.storage.save_account(dict(self.storage.account(first),secret_key='',access_key=''))
        self.storage.client(first)
        self.assertEqual(self.factory.call_args.kwargs['aws_access_key_id'],'Personal')
        self.storage.client(second)
        self.assertEqual(self.factory.call_args.kwargs['aws_access_key_id'],'Work')
        self.storage.remove_account(first)
        self.assertNotIn('storage:'+first,self.vault.data)
    def test_pagination_folder_delete_and_failed_copy_does_not_remove_source(self):
        account=self.account()
        self.client.list_objects_v2.side_effect=[{'Contents':[{'Key':'folder/one'}],'IsTruncated':True,'NextContinuationToken':'next'},{'Contents':[{'Key':'folder/two'}]}]
        self.client.delete_objects.return_value={}
        self.storage.delete(['folder/'],account)
        keys=self.client.delete_objects.call_args.kwargs['Delete']['Objects']
        self.assertEqual(keys,[{'Key':'folder/one'},{'Key':'folder/two'}])
        self.assertEqual(self.client.list_objects_v2.call_args.kwargs['ContinuationToken'],'next')
        self.client.copy.side_effect=RuntimeError('failed')
        with self.assertRaises(RuntimeError):self.storage.copy('one','two',account,move=True)
        self.client.delete_object.assert_not_called()
    def test_cross_account_copy_streams_content_and_keeps_metadata(self):
        first=self.account();second=self.account('Work');source=Mock();dest=Mock();body=io.BytesIO(b'payload')
        source.get_object.return_value={'Body':body,'ContentType':'audio/mpeg','Metadata':{'source':'test'}}
        with patch.object(self.storage,'client',side_effect=lambda account:source if account==first else dest):
            self.storage.copy('one','two',first,target_account=second,move=True)
        dest.upload_fileobj.assert_called_once()
        self.assertEqual(dest.upload_fileobj.call_args.kwargs['ExtraArgs']['ContentType'],'audio/mpeg')
        source.delete_object.assert_called_once()
        self.assertTrue(body.closed)
    def test_list_page_and_public_url(self):
        account=self.account()
        self.client.list_objects_v2.return_value={'CommonPrefixes':[{'Prefix':'folder/'}],'Contents':[{'Key':'file.txt','Size':8}],'NextContinuationToken':'next'}
        result=self.storage.list(account,prefix='fi',cursor='token',limit=12)
        self.assertEqual(result['cursor'],'next')
        self.assertEqual(self.client.list_objects_v2.call_args.kwargs['Delimiter'],'/')
        self.assertEqual(self.storage.public_url('a b/c.mp3',account),'https://cdn.example.invalid/a%20b/c.mp3')
    def test_drive_plugin_listing_download_and_rename_share_selected_account(self):
        resources=Mock();resources.accounts.return_value=[{'id':'work'}];resources._access_token.return_value='fixture'
        response=Mock(status_code=200);response.__enter__=Mock(return_value=response);response.__exit__=Mock();response.json.return_value={'files':[{'id':'folder','name':'Folder'}]};response.iter_content.return_value=[b'zip-content']
        resources.session.request.return_value=response
        drive=Drive(resources,root=self.root)
        self.assertEqual(drive.list('work',folders_only=True,cursor='next')['files'][0]['id'],'folder')
        request=resources.session.request.call_args
        self.assertEqual(request.kwargs['headers']['Authorization'],'Bearer fixture')
        self.assertIn('folder',request.kwargs['params']['q'])
        target=drive.download('file',self.root/'a.zip','work');self.assertEqual(target.read_bytes(),b'zip-content')
        drive.rename('file','a-ok.zip','work')
        self.assertEqual(resources.session.request.call_args.args[0],'PATCH')
    def test_discord_uses_bot_token_not_application_url(self):
        (self.root/'.env').write_text('DISCORD_BOT_TOKEN=fixture\nDISCORD_BOT_URL=https://discord.com/oauth2/authorize\nDISCORD_CHANNEL_ID=123\n')
        session=Mock();session.post.return_value.status_code=200;session.post.return_value.json.return_value={'id':'message'}
        bot=Discord(self.root,session);self.assertNotIn('TOKEN',json.dumps(bot.public()))
        self.assertEqual(bot.send('Episode published')['id'],'message')
        self.assertEqual(session.post.call_args.args[0],'https://discord.com/api/v10/channels/123/messages')
        self.assertEqual(session.post.call_args.kwargs['json']['allowed_mentions'],{'parse':[]})
    def test_migration_separates_integrations_and_keeps_app_settings(self):
        app=self.root/'Plugins/Apps/podcast_automation';app.mkdir(parents=True)
        credentials=app/'key.json';credentials.write_text('{"client_email":"fixture"}')
        (app/'.env').write_text('GOOGLE_APPLICATION_CREDENTIALS=key.json\nGOOGLE_DRIVE_FOLDER_ID=folder\nOBJECT_STORAGE_ACCESS_KEY_ID=key\nOBJECT_STORAGE_SECRET_ACCESS_KEY=secret\nDISCORD_BOT_TOKEN=bot\nLLM_API_KEY=obsolete\nWHISPER_MODEL=medium\nDRIVE_PROCESS=true\n')
        migrate(self.root);migrate(self.root)
        self.assertEqual(dict(dotenv_values(app/'.env')),{'DRIVE_PROCESS':'true'})
        google=dotenv_values(self.root/'Plugins/Connectors/google/.env')
        self.assertTrue(Path(google['GOOGLE_APPLICATION_CREDENTIALS']).is_file())
        self.assertEqual(dotenv_values(self.root/'Plugins/Connectors/object_storage/.env')['OBJECT_STORAGE_SECRET_ACCESS_KEY'],'secret')
        self.assertEqual(dotenv_values(self.root/'Plugins/Connectors/discord/.env')['DISCORD_BOT_TOKEN'],'bot')
    def test_internal_app_capability_is_scoped_loopback_and_revoked(self):
        context=app_access.issue('podcast_automation');token=json.loads(context)['token']
        request=SimpleNamespace(headers={'X-PIA-App-Token':token},client_address=('127.0.0.1',123),path='/v1/chat/completions')
        try:
            self.assertTrue(app_access.authorized(request))
            request.headers['Origin']='http://localhost:8762';self.assertFalse(app_access.authorized(request));request.headers.pop('Origin')
            request.client_address=('192.0.2.1',123);self.assertFalse(app_access.authorized(request));request.client_address=('127.0.0.1',123)
            request.path='/v1/images/generations';self.assertFalse(app_access.authorized(request));request.path='/v1/chat/completions'
        finally:app_access.revoke(context)
        self.assertFalse(app_access.authorized(request))
    def test_large_upload_chunks_are_contiguous_and_cleaned(self):
        module=Apps().load('object_storage');context=SimpleNamespace(jobs={});fake=Mock();fake.bucket.return_value='bucket';fake.key.side_effect=lambda key:key
        captured=[]
        fake.upload.side_effect=lambda path,*args,**kwargs:captured.append(Path(path).read_bytes())
        with patch.object(module,'storage',return_value=fake),patch.object(module,'BASE_DIR',self.root):
            record=module.handle('upload-begin',{'account':'a','bucket':'bucket','key':'test.bin','size':6},context)
            module.handle('upload-chunk',{'id':record['id'],'offset':0,'data':base64.b64encode(b'abc').decode()},context)
            with self.assertRaises(ValueError):module.handle('upload-chunk',{'id':record['id'],'offset':0,'data':base64.b64encode(b'abc').decode()},context)
            module.handle('upload-chunk',{'id':record['id'],'offset':3,'data':base64.b64encode(b'def').decode()},context)
            result=module.handle('upload-finish',record,context);job=context.jobs[result['job']]
            with job.changed:job.changed.wait_for(lambda:job.status!='running',timeout=5)
            self.assertEqual(job.status,'done',job.error);self.assertEqual(captured,[b'abcdef'])
            self.assertFalse(list((self.root/'cache/storage-uploads').glob('*')))
if __name__=='__main__':unittest.main()
