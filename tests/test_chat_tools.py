"""Image tool contracts, local settings/log safety and secretary preferences."""
import base64
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from PIL import Image
from src.chat_tools import ChatTools,image_intent
from src.pia.service import WorkspaceService
from src.workspace_store import WorkspaceStore
from Plugins.Bot.secretaria import Secretary

class ChatToolTests(unittest.TestCase):
    def test_explicit_image_intent_and_non_actions(self):
        for text in ('Gere a imagem de uma garota de anime','Crie uma imagem de uma casa','Por favor, desenhe um gato','Você pode gerar uma imagem de anime?','Draw a cat'):
            self.assertTrue(image_intent(text),text)
        for text in ('Como gerar uma imagem?','Não gere uma imagem','Crie um texto sobre imagem','Gere um prompt para criar uma imagem','Explique geração de imagens','Olá'):
            self.assertFalse(image_intent(text),text)
    def test_image_response_persisted_and_capability_revoked(self):
        stream=io.BytesIO();Image.new('RGB',(2,2),'blue').save(stream,'PNG')
        session=Mock();session.post.return_value=Mock(status_code=200,json=Mock(return_value={'data':[{'b64_json':base64.b64encode(stream.getvalue()).decode()}]}))
        with TemporaryDirectory() as temporary,patch('src.chat_tools.app_access.revoke',wraps=__import__('src.app_access',fromlist=['revoke']).revoke) as revoke:
            tools=ChatTools(root=temporary,session=session)
            result=tools.execute('Gere uma imagem de teste')
            self.assertIn('](/api/pia/chat/assets/',result)
            self.assertEqual(len(list(Path(temporary).glob('*.png'))),1)
            self.assertTrue(session.post.call_args.args[0].endswith('/v1/images/generations'))
            self.assertNotIn('Authorization',session.post.call_args.kwargs['headers'])
            revoke.assert_called_once()
    def test_failure_does_not_claim_an_image(self):
        session=Mock();session.post.return_value=Mock(status_code=503,json=Mock(return_value={'error':{'message':'Provider offline'}}))
        with TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(RuntimeError,'503.*Provider offline'):ChatTools(root=temporary,session=session).generate_image('test')
            self.assertFalse(list(Path(temporary).iterdir()))
    def test_log_clear_truncates_only_selected_logs_and_blocks_escape(self):
        with TemporaryDirectory() as temporary:
            root=Path(temporary);logs=root/'logs';logs.mkdir();(logs/'one.log').write_text('one');(logs/'two.log').write_text('two');outside=root/'other.log';outside.write_text('private')
            service=WorkspaceService(backend=SimpleNamespace(store=WorkspaceStore(root/'chat.sqlite')))
            with patch('src.pia.service.BASE_DIR',root):
                with self.assertRaises(ValueError):service.dispatch('POST','/logs/clear',{'name':'../other.log'},{})
                service.dispatch('POST','/logs/clear',{'name':'one.log'},{});self.assertEqual((logs/'one.log').read_text(),'');self.assertEqual((logs/'two.log').read_text(),'two')
                service.dispatch('POST','/logs/clear',{'all':True},{});self.assertEqual((logs/'two.log').read_text(),'');self.assertEqual(outside.read_text(),'private')
    def test_settings_omit_empty_plugins(self):
        with TemporaryDirectory() as temporary:
            root=Path(temporary);empty=root/'empty';full=root/'full';empty.mkdir();full.mkdir();(full/'.env.example').write_text('EXAMPLE_KEY=')
            service=WorkspaceService(backend=SimpleNamespace(store=WorkspaceStore(root/'chat.sqlite')))
            with patch.object(service,'plugin_folders',return_value=[('Apps/empty',empty),('Plugins/full',full)]),patch('src.settings_store.schema',side_effect=lambda section:[{'name':'KEY','type':'secret','default':''}] if section=='Plugins/full' else []):
                self.assertEqual([s['id'] for s in service.settings()],['Plugins/full'])
    def test_secretary_readable_filters_custom_compatibility_and_colors(self):
        with TemporaryDirectory() as temporary:
            root=Path(temporary);store=WorkspaceStore(root/'chat.sqlite');resources=Mock();resources.accounts.return_value=[]
            bot=Secretary(resources,store,Mock(),config_path=root/'bot.json')
            bot.configure({'email_filter':'inbox_unread','avatar_primary':'#123abc'})
            self.assertEqual(bot.config()['email_query'],'is:unread in:inbox')
            self.assertEqual(bot.config()['avatar_primary'],'#123abc')
            bot.configure({'email_query':'from:example@example.invalid'})
            self.assertEqual(bot.config()['email_filter'],'custom')
            with self.assertRaises(ValueError):bot.configure({'avatar_primary':'url(javascript:alert(1))'})
if __name__=='__main__':unittest.main()
