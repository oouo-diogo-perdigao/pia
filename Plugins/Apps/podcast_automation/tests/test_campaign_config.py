import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from xml.etree import ElementTree as ET

from podcast_automation import settings
from podcast_automation.audioManager import AudioManager
from podcast_automation.rssTranscriptionUpdate import RssTranscriptionUpdater

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = json.loads((ROOT / 'docs/examples/config.example.json').read_text(encoding='utf-8'))


class CampaignConfigTests(unittest.TestCase):
    def test_current_example_is_valid(self):
        with patch.dict(os.environ, {'PODCAST_CONFIG': str(ROOT / 'docs/examples/config.example.json')}):
            settings.get_config.cache_clear()
            try:
                self.assertEqual(settings.get_config()['campaign_details'], EXAMPLE['campaign_details'])
            finally:
                settings.get_config.cache_clear()

    def test_invalid_campaigns_are_rejected(self):
        for change in ({'players': []}, {'players': {'Player': {}}}, {'closed': 'false'},
                       {'rss_key': 'campaigns/../rss.xml'}, {'rss_key': 'rss.xml'}):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                data = copy.deepcopy(EXAMPLE)
                next(iter(data['campaign_details'].values())).update(change)
                path = Path(directory) / 'config.json'
                path.write_text(json.dumps(data))
                with patch.dict(os.environ, {'PODCAST_CONFIG': str(path)}):
                    settings.get_config.cache_clear()
                    try:
                        with self.assertRaises(ValueError):
                            settings.get_config()
                    finally:
                        settings.get_config.cache_clear()

    def participants(self, campaigns, sizes):
        manager = AudioManager.__new__(AudioManager)
        manager.PersonagensDoJogo = campaigns
        manager.arquivos_participantes = list(sizes)
        manager.identificar_pessoa = lambda name: name
        with patch('podcast_automation.audioManager.os.path.getsize', side_effect=sizes.__getitem__):
            return manager.deduzir_participantes()

    def test_players_are_nested_and_metadata_is_not_a_player(self):
        result = self.participants({'Narrador': {
            'Campanha': 'Mesa', 'rss_key': 'campaigns/mesa/rss.xml',
            'title': 'Título do podcast', 'players': {'Jogador': 'Herói'},
        }}, {'Narrador': 100, 'Jogador': 90, 'title': 80})
        self.assertEqual(result[0], 'Narrador')
        self.assertEqual(result[1], ['Jogador', 'title'])
        self.assertEqual(result[2], ['Herói', 'title'])

    def test_alternative_narrator_uses_nested_players(self):
        result = self.participants({
            'A': {'Campanha': 'Mesa A', 'rss_key': 'campaigns/a/rss.xml', 'players': {'C': 'Herói C'}},
            'B': {'Campanha': 'Mesa B', 'rss_key': 'campaigns/b/rss.xml', 'players': {'A': 'Herói A', 'C': 'Outro C'}},
        }, {'A': 100, 'B': 90, 'C': 80})
        self.assertEqual(result[0], 'B')
        self.assertEqual(result[2], ['Herói A', 'Outro C'])
        self.assertEqual(result[4:], ('Mesa B', 'campaigns/b/rss.xml'))


class ConfiguredFeedTests(unittest.TestCase):
    def setUp(self):
        self.config = copy.deepcopy(EXAMPLE)
        self.open = copy.deepcopy(next(iter(self.config['campaign_details'].values())))
        self.open.update({'Campanha': 'Mesa aberta', 'rss_key': 'custom/aberta/rss.xml', 'closed': False})
        self.closed = {**self.open, 'rss_key': 'custom/fechada/rss.xml', 'closed': True}
        self.config['campaign_details'] = {'Narrador': self.open, 'Outro': self.closed}
        self.config_patch = patch('podcast_automation.rssTranscriptionUpdate.get_config', return_value=self.config)
        self.config_patch.start()
        self.temp_cache = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_cache.cleanup)
        self.env_patch = patch.dict(os.environ, {'OWNER_EMAIL': 'test@example.invalid', 'SKIP_CLOSED': 'true', 'FEED_CACHE_DIR': self.temp_cache.name, 'FEED_FORCE_REBUILD': 'false'})
        self.env_patch.start()
        self.store = MagicMock()
        self.saved = {}
        self.store.getObjectIfExists.side_effect = self.saved.get
        # Match ObjectStorageManager's actual signature, including keyword names.
        self.store.putObject.side_effect = lambda key, data, content_type: self.saved.update({key: data})
        # Arquivos descendentes, mesmo devolvidos pelo prefixo S3, não pertencem à mesa pai.
        self.sources = [
            {'Key': 'custom/aberta/episode.mp3'}, {'Key': 'custom/aberta/episode.txt'},
            {'Key': 'custom/aberta/outro-podcast/private.mp3'},
            {'Key': 'custom/aberta/outro-podcast/private.txt'},
        ]
        for obj in self.sources:
            obj['ETag'] = 'original'
        self.store.list_objects.side_effect = self.list_objects
        self.updater = RssTranscriptionUpdater(self.store)
        self.updater.build_episode = MagicMock(return_value={})
        self.updater.build_transcription = MagicMock(return_value={})
        self.updater.build_feed_xml = MagicMock(side_effect=lambda episodes, cover, details: json.dumps(details))
        self.updater.build_feed_html = MagicMock(side_effect=lambda episodes, cover, details: json.dumps(details))

    def list_objects(self, prefix):
        return self.sources + [
            {'Key': key, 'ETag': hashlib.md5(value).hexdigest(), 'Size': len(value)}
            for key, value in self.saved.items() if key.startswith(prefix)
        ]

    def tearDown(self):
        self.config_patch.stop()
        self.env_patch.stop()

    def test_only_configured_open_folder_is_accessed(self):
        result = self.updater.updateRssTranscriptionFiles()
        self.assertTrue(result['success'])
        self.assertEqual(result['foldersProcessed'], 1)
        self.assertTrue(self.store.list_objects.call_args_list)
        self.assertTrue(all(call.args == ('custom/aberta/',) for call in self.store.list_objects.call_args_list))
        self.store.getObject.assert_not_called()  # nenhum details.json remoto
        self.assertEqual(set(self.saved), {'custom/aberta/rss.xml', 'custom/aberta/transcripts.html'})
        self.updater.build_episode.assert_called_once()
        self.updater.build_transcription.assert_called_once()
        self.assertEqual(self.updater.build_episode.call_args.args[0]['Key'], 'custom/aberta/episode.mp3')

    def test_explicit_unknown_folder_is_ignored_even_with_override(self):
        with patch.dict(os.environ, {'SKIP_CLOSED': 'false'}):
            self.assertEqual(self.updater.updateRssTranscriptionFiles('campaigns/desconhecida')['foldersProcessed'], 0)
            self.updater.rebuild_podcast_feed('campaigns/desconhecida')
        self.store.list_objects.assert_not_called()
        self.store.getObjectIfExists.assert_not_called()
        self.store.putObject.assert_not_called()

    def test_closed_folder_is_skipped_and_override_remains_scoped(self):
        self.updater.updateRssTranscriptionFiles('custom/fechada')
        self.store.list_objects.assert_not_called()
        with patch.dict(os.environ, {'SKIP_CLOSED': 'false'}):
            self.updater.updateRssTranscriptionFiles('custom/fechada')
        self.assertTrue(all(call.args == ('custom/fechada/',) for call in self.store.list_objects.call_args_list))

    def test_local_metadata_change_rebuilds_but_identical_content_is_not_uploaded(self):
        self.updater.updateRssTranscriptionFiles('custom/aberta')
        self.store.putObject.reset_mock()
        self.updater.updateRssTranscriptionFiles('custom/aberta')
        self.store.putObject.assert_not_called()
        self.open['description'] = 'Descrição alterada apenas no config.json'
        self.updater.updateRssTranscriptionFiles('custom/aberta')
        self.assertEqual(self.store.putObject.call_count, 2)
        self.assertEqual(json.loads(self.saved['custom/aberta/rss.xml'])['description'], self.open['description'])

    def test_unchanged_folder_skips_reads_and_rendering_across_instances(self):
        self.updater.updateRssTranscriptionFiles('custom/aberta')
        # Um processo novo deve poder reaproveitar o cache em disco.
        new = RssTranscriptionUpdater(self.store)
        self.store.reset_mock()
        new.build_episode = MagicMock(side_effect=AssertionError('Não deve reler episódios'))
        new.build_transcription = MagicMock(side_effect=AssertionError('Não deve reler roteiros'))
        result = new.updateRssTranscriptionFiles('custom/aberta')
        self.assertTrue(result['success'])
        self.store.list_objects.assert_called_once_with('custom/aberta/')
        self.store.getObjectIfExists.assert_not_called()
        self.store.putObject.assert_not_called()
        new.build_episode.assert_not_called()
        new.build_transcription.assert_not_called()

    def test_changed_or_deleted_input_invalidates_folder(self):
        self.updater.updateRssTranscriptionFiles('custom/aberta')
        self.updater.build_episode.reset_mock()
        self.sources[0]['ETag'] = 'replaced'
        self.updater.updateRssTranscriptionFiles('custom/aberta')
        self.updater.build_episode.assert_called_once()
        self.updater.build_episode.reset_mock()
        self.sources.pop(1)  # Exclusão de roteiro também invalida o snapshot.
        self.updater.updateRssTranscriptionFiles('custom/aberta')
        self.updater.build_episode.assert_called_once()

    def test_deleted_output_is_recreated(self):
        self.updater.updateRssTranscriptionFiles('custom/aberta')
        del self.saved['custom/aberta/rss.xml']
        self.updater.updateRssTranscriptionFiles('custom/aberta')
        self.assertIn('custom/aberta/rss.xml', self.saved)

    def test_force_rebuild_bypasses_fast_skip(self):
        self.updater.updateRssTranscriptionFiles('custom/aberta')
        self.updater.build_episode.reset_mock()
        with patch.dict(os.environ, {'FEED_FORCE_REBUILD': 'true'}):
            self.updater.updateRssTranscriptionFiles('custom/aberta')
        self.updater.build_episode.assert_called_once()

    def test_durations_persist_and_invalidate_with_audio_version(self):
        audio = {'Key': 'custom/aberta/audio.mp3', 'ETag': 'one'}
        self.updater.get_audio_duration = MagicMock(return_value=120)
        self.assertEqual(self.updater.cached_audio_duration(audio, 'https://example.invalid/audio'), 120)
        self.updater.cache.save()
        new = RssTranscriptionUpdater(self.store)
        new.get_audio_duration = MagicMock(return_value=180)
        self.assertEqual(new.cached_audio_duration(audio, 'https://example.invalid/audio'), 120)
        new.get_audio_duration.assert_not_called()
        audio['ETag'] = 'two'
        self.assertEqual(new.cached_audio_duration(audio, 'https://example.invalid/audio'), 180)
        new.get_audio_duration.assert_called_once()

    def test_failed_duration_is_not_cached(self):
        audio = {'Key': 'custom/aberta/audio.mp3', 'ETag': 'one'}
        self.updater.get_audio_duration = MagicMock(side_effect=[None, 120])
        self.assertIsNone(self.updater.cached_audio_duration(audio, 'https://example.invalid/audio'))
        self.assertEqual(self.updater.cached_audio_duration(audio, 'https://example.invalid/audio'), 120)
        self.assertEqual(self.updater.get_audio_duration.call_count, 2)

    def test_duration_failure_prevents_whole_folder_fast_skip(self):
        self.updater.get_audio_duration = MagicMock(return_value=None)
        def episode(*args):
            self.updater.cached_audio_duration(self.sources[0], 'https://example.invalid/audio')
            return {}
        self.updater.build_episode.side_effect = episode
        self.updater.updateRssTranscriptionFiles('custom/aberta')
        self.assertNotIn('custom/aberta', self.updater.cache.data['folders'])
        self.updater.updateRssTranscriptionFiles('custom/aberta')
        self.assertEqual(self.updater.get_audio_duration.call_count, 2)

    def test_upload_failure_does_not_mark_folder_as_current(self):
        self.store.putObject.side_effect = RuntimeError('Falha simulada')
        result = self.updater.updateRssTranscriptionFiles('custom/aberta')
        self.assertFalse(result['success'])
        self.assertNotIn('custom/aberta', self.updater.cache.data['folders'])

    def test_external_feed_change_invalidates_cache(self):
        self.updater.updateRssTranscriptionFiles('custom/aberta')
        self.saved['custom/aberta/rss.xml'] = b'conteudo externo'
        self.updater.updateRssTranscriptionFiles('custom/aberta')
        self.assertNotEqual(self.saved['custom/aberta/rss.xml'], b'conteudo externo')

    def test_other_bucket_does_not_reuse_folder_cache(self):
        self.updater.updateRssTranscriptionFiles('custom/aberta')
        with patch.object(self.store, 'identity', {'bucket':'outro-bucket'}):
            other = RssTranscriptionUpdater(self.store)
        self.assertNotEqual(other.cache.path, self.updater.cache.path)
        self.assertEqual(other.cache.data['folders'], {})

    def test_unwritable_cache_does_not_fail_rebuild(self):
        regular_file = Path(self.temp_cache.name) / 'not-a-directory'
        regular_file.write_text('arquivo')
        self.updater.cache.path = regular_file / 'cache.json'
        self.assertTrue(self.updater.updateRssTranscriptionFiles('custom/aberta')['success'])

    def test_corrupt_cache_is_ignored(self):
        self.updater.cache.path.parent.mkdir(parents=True, exist_ok=True)
        self.updater.cache.path.write_text('{invalid')
        new = RssTranscriptionUpdater(self.store)
        self.assertEqual(new.cache.data, {'folders': {}, 'durations': {}})

    def test_real_feed_uses_local_title_description_author_and_explicit(self):
        details = {**self.open, 'title': 'Título & teste', 'description': 'Descrição local',
                   'author': 'Autor local', 'explicit': True}
        xml = RssTranscriptionUpdater.build_feed_xml(self.updater, [], None, details)
        channel = ET.fromstring(xml).find('channel')
        self.assertEqual(channel.findtext('title'), details['title'])
        self.assertEqual(channel.findtext('description'), details['description'])
        self.assertEqual(channel.findtext('{http://www.itunes.com/dtds/podcast-1.0.dtd}author'), 'Autor local')
        self.assertEqual(channel.findtext('{http://www.itunes.com/dtds/podcast-1.0.dtd}explicit'), 'yes')


class StorageFailureTests(unittest.TestCase):
    def test_s3_errors_propagate_instead_of_marking_cache_successful(self):
        from botocore.exceptions import ClientError
        from podcast_automation.objectStorageManager import ObjectStorageManager
        manager = ObjectStorageManager.__new__(ObjectStorageManager)
        manager.plugin = MagicMock()
        manager.account = "fixture"
        manager.bucket = "test-bucket"
        failure = ClientError({'Error': {'Code': 'AccessDenied', 'Message': 'Test'}}, 'Test')
        manager.plugin.objects.side_effect = failure
        manager.plugin.put.side_effect = failure
        with patch.dict(os.environ, {'OBJECT_STORAGE_BUCKET_NAME': 'test-bucket'}), patch('podcast_automation.objectStorageManager.get_config', return_value=EXAMPLE):
            with self.assertRaises(ClientError):
                manager.list_objects('configured/')
            with self.assertRaises(ClientError):
                manager.putObject('configured/rss.xml', b'<rss/>')


if __name__ == '__main__':
    unittest.main()
