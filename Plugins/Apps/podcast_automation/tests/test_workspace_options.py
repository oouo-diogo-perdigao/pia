"""Persistence and published reader contracts, without accessing external accounts."""
import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from Plugins.Apps.podcast_automation import web_api
from podcast_automation import notification
from podcast_automation.transcripts_page import render

EXAMPLE=json.loads((Path(__file__).resolve().parents[1]/'docs/examples/config.example.json').read_text(encoding='utf-8'))

class WorkspaceOptionsTests(unittest.TestCase):
    def test_selected_folder_and_bucket_survive_reload_and_campaign_save(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);(root/'config').mkdir()
            (root/'config/config.json').write_text(json.dumps(EXAMPLE),encoding='utf-8')
            with patch.object(web_api,'ROOT',root):
                stale=web_api.handle('config',{},None)
                options={'google_account':'work','google_folder':'nested-folder','google_folder_name':'Gravações RPG','storage_account':'r2-work','storage_bucket':'podcasts'}
                web_api.handle('save-options',{'outputs':{'txt':True},'integrations':options},None)
                reloaded=web_api.handle('config',{},None)
                self.assertEqual(reloaded['integrations'],{**EXAMPLE.get('integrations',{}),**options})
                # Even an editor opened before selecting the folder cannot revert it.
                stale['processing']['fixture_change']=True
                web_api.handle('save-config',{'value':stale},None)
                saved=web_api.handle('config',{},None)
                self.assertEqual(saved['integrations']['google_folder'],'nested-folder')
                self.assertEqual(saved['integrations']['google_account'],'work')
                self.assertEqual(saved['integrations']['storage_bucket'],'podcasts')
                self.assertTrue(saved['processing']['fixture_change'])

    def test_discord_announcement_contains_only_available_published_links(self):
        links={'MP3':'https://example.invalid/audio.mp3','Transcrição TXT':'https://example.invalid/audio.txt','RSS':'https://example.invalid/rss.xml','Transcrições gerais':'https://example.invalid/transcripts.html'}
        with patch.object(notification,'get_config',return_value={'integrations':{'discord_notify':True,'discord_channels':['123','456']}}),patch('Plugins.Connectors.discord.service.Discord') as bot:
            self.assertTrue(notification.announce_publication('Sessão','Campanha',links))
            self.assertEqual(bot.return_value.send.call_count,2)
            for call in bot.return_value.send.call_args_list:
                for url in links.values():self.assertIn(url,call.args[0])

    def test_reader_contains_every_transcript_with_escaped_content_and_tools(self):
        episodes=[dict(title='Sessão <1>',content='Fala única '+str(i)+'\n<script>alert("bad")</script>') for i in range(3)]
        page=render(episodes,'https://example.invalid/cover.png',{'title':'Mesa <RPG>'})
        self.assertEqual(page.count('class="transcript"'),3)
        for i in range(3):self.assertIn('Fala única '+str(i),page)
        self.assertNotIn('<script>alert("bad")</script>',page)
        self.assertIn('&lt;script&gt;',page)
        self.assertIn('id="search"',page)
        self.assertIn('id="copy-selected"',page)
        self.assertIn('aria-label="Sessões"',page)
        self.assertIn('session-3',page)
        self.assertNotIn('<script src=',page)

    def test_discord_splits_long_announcements_without_truncating_links(self):
        links={name:'https://example.invalid/'+name+'x'*900 for name in ('MP3','TXT','RSS','HTML')}
        with patch.object(notification,'get_config',return_value={'integrations':{'discord_notify':True,'discord_channels':['123']}}),patch('Plugins.Connectors.discord.service.Discord') as bot:
            self.assertTrue(notification.announce_publication('Sessão','Campanha',links))
            calls=bot.return_value.send.call_args_list
            self.assertGreater(len(calls),1)
            combined='\n'.join(call.args[0] for call in calls)
            for url in links.values():self.assertIn(url,combined)
            self.assertTrue(all(len(call.args[0])<=2000 for call in calls))
