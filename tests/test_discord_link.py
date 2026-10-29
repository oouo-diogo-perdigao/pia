import asyncio
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from Plugins.Connectors.discord.service import Discord
from Plugins.Connectors.discord.runtime import DiscordRuntime


def response(data, status=200):
    result=Mock(status_code=status)
    result.json.return_value=data
    return result


class DiscordLinkTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        (self.root/'.env').write_text('DISCORD_BOT_TOKEN__SECRET=test-secret\nDISCORD_BOT_ID=99\nDISCORD_LINK_ENABLED__BOOL=true\n')
        self.session=Mock()
        self.bot=Discord(self.root,self.session)
        self.session.get.return_value=response({'id':'123','guild_id':'456','type':0,'name':'publicacoes'})
        self.args=dict(guild='456',channel='123',user='789',permissions=8,app_permissions=3072,application='99')

    def test_admin_link_persists_and_send_uses_default(self):
        result=self.bot.link(**self.args)
        self.assertIn('DISCORD_CHANNEL_ID=123',result['text'])
        self.assertEqual(self.bot.public()['channel'],'123')
        self.assertEqual(self.bot.binding()['guild'],'456')
        self.session.post.return_value=response({'id':'777'})
        self.assertEqual(self.bot.send('Publicado')['channel'],'123')
        self.assertTrue(self.session.post.call_args.args[0].endswith('/channels/123/messages'))
        self.assertEqual(self.session.post.call_args.kwargs['json']['allowed_mentions'],{'parse':[]})

    def test_rejects_nonadmin_dm_wrong_app_and_insufficient_bot_permissions(self):
        for change in [dict(permissions=0),dict(guild=None),dict(application='98'),dict(app_permissions=1024)]:
            with self.subTest(change=change),self.assertRaises(PermissionError):self.bot.link(**{**self.args,**change})
        self.assertFalse((self.root/'config.json').exists())
        self.session.get.assert_not_called()

    def test_allowlist_and_server_lock_cannot_be_bypassed(self):
        with (self.root/'.env').open('a') as out:out.write('DISCORD_ADMIN_USER_IDS=789,101\n')
        with self.assertRaises(PermissionError):self.bot.link(**{**self.args,'user':'888'})
        self.bot.link(**self.args)
        with self.assertRaises(PermissionError):self.bot.link(**{**self.args,'guild':'999'})
        self.assertEqual(self.bot.public()['channel'],'123')
        self.bot.unlink()
        self.assertEqual(self.bot.public()['channel'],'')
        self.assertEqual(self.bot.binding(),{})

    def test_disabled_or_wrong_channel_does_not_write(self):
        self.session.get.return_value=response({'id':'123','guild_id':'456','type':11})
        with self.assertRaises(ValueError):self.bot.link(**self.args)
        self.assertNotIn('DISCORD_CHANNEL_ID',self.bot.config())
        self.bot.enable(False)
        with self.assertRaises(PermissionError):self.bot.link(**self.args)

    def test_multiple_channels_preserve_the_linked_server_restriction(self):
        def get(url,**kwargs):
            if '/guilds/' in url:return response({'id':'456','name':'Servidor de teste'})
            channel=url.rsplit('/',1)[-1]
            return response({'id':channel,'guild_id':'456','type':0,'name':'canal-'+channel})
        self.session.get.side_effect=get
        self.bot.link(**self.args)
        self.bot.link(**{**self.args,'channel':'124'})
        self.assertEqual({item['channel'] for item in self.bot.channels()},{'123','124'})
        self.assertTrue(all(item['guild_name']=='Servidor de teste' for item in self.bot.channels()))
        with self.assertRaises(PermissionError):self.bot.link(**{**self.args,'guild':'999'})

    def test_registration_upserts_only_link_with_admin_permissions(self):
        self.session.get.return_value=response({'id':'99','interactions_endpoint_url':None})
        self.session.post.return_value=response({'id':'111'})
        self.assertEqual(self.bot.register_link()['id'],'111')
        request=self.session.post.call_args
        self.assertTrue(request.args[0].endswith('/applications/99/commands'))
        self.assertEqual(request.kwargs['json']['default_member_permissions'],'8')
        self.assertEqual(request.kwargs['json']['contexts'],[0])
        self.assertEqual(request.kwargs['json']['integration_types'],[0])
        self.session.put.assert_not_called()

    def test_registration_does_not_override_existing_http_endpoint(self):
        self.session.get.return_value=response({'id':'99','interactions_endpoint_url':'https://existing.example.invalid'})
        with self.assertRaises(ValueError):self.bot.register_link()
        self.session.post.assert_not_called()

    def test_failed_send_has_http_code_details_and_redacted_log(self):
        self.session.post.return_value=response({'code':50013,'message':'Missing Permissions test-secret','errors':{'channel_id':{'_errors':[{'message':'denied'}]}}},403)
        with self.assertRaises(RuntimeError) as error:self.bot.send('teste','123')
        text=str(error.exception)
        self.assertIn('HTTP 403',text)
        self.assertIn('50013',text)
        self.assertIn('denied',text)
        self.assertNotIn('test-secret',text)
        self.assertNotIn('test-secret',self.bot.logs())
        self.assertIn('[REDACTED]',self.bot.logs())
        self.session.post.return_value.close.assert_called_once()


class GatewayInteractionTests(unittest.IsolatedAsyncioTestCase):
    async def test_deferred_private_ack_duplicate_and_nonadmin_rejection(self):
        bot=Mock()
        bot.clean.side_effect=lambda value:str(value)
        bot.link.return_value={'text':'DISCORD_CHANNEL_ID=123'}
        runtime=DiscordRuntime(bot)
        reply=SimpleNamespace(defer=AsyncMock(),is_done=lambda:True,send_message=AsyncMock())
        interaction=SimpleNamespace(id=1,type=SimpleNamespace(value=2),data={'name':'link'},token='interaction-private-token',
            response=reply,followup=SimpleNamespace(send=AsyncMock()),guild_id=456,channel_id=123,user=SimpleNamespace(id=789),
            permissions=SimpleNamespace(value=8),app_permissions=SimpleNamespace(value=3072),application_id=99)
        await runtime.interaction(interaction)
        reply.defer.assert_awaited_once_with(ephemeral=True,thinking=True)
        self.assertTrue(interaction.followup.send.call_args.kwargs['ephemeral'])
        self.assertEqual(bot.link.call_args.kwargs['permissions'],8)
        await runtime.interaction(interaction)
        bot.link.assert_called_once()
        interaction.id=2
        bot.link.side_effect=PermissionError('Somente administradores interaction-private-token')
        await runtime.interaction(interaction)
        self.assertIn('Somente administradores',interaction.followup.send.call_args.args[0])
        self.assertNotIn('interaction-private-token',interaction.followup.send.call_args.args[0])
