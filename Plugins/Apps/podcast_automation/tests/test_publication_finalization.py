"""A failed feed is not a completed publication and must remain retryable."""
import unittest
from unittest.mock import Mock, patch
from podcast_automation import main


class PublicationFinalizationTests(unittest.TestCase):
    def test_failed_or_missing_campaign_preserves_source_and_local_files(self):
        for result in ({'success':False,'errors':[{'erro':'storage failed'}]},
                       {'success':True,'folders':[]}, None):
            with self.subTest(result=result):
                drive=Mock(); storage=Mock(); updater=Mock()
                updater.updateRssTranscriptionFiles.return_value=result
                item={'rss_key':'campaign/rss.xml'}
                processed=[]
                with patch.object(main,'limpar_temporarios') as cleanup, patch.object(main,'emit'), patch.object(main,'stage'):
                    with self.assertRaisesRegex(RuntimeError,'preservados'):
                        main.finalizar_publicacao(item,drive,storage,updater,processed,{})
                    cleanup.assert_not_called()
                drive.rename_processed.assert_not_called()
                self.assertEqual(processed,[])

    def test_success_including_unchanged_feed_finalizes_once(self):
        drive=Mock(); storage=Mock(); updater=Mock()
        updater.updateRssTranscriptionFiles.return_value={'success':True,'folders':[{'folder':'campaign','rss_updated':False,'transcripts_updated':False}]}
        item=dict(rss_key='campaign/rss.xml',id='id',name='source.zip',pasta_extraida='extracted',local_zip='source.zip',nome_sessao='Episode',campanha='Campaign')
        processed=[]
        with patch.object(main,'limpar_temporarios') as cleanup, patch.object(main,'emit'), patch.object(main,'stage'), patch.object(main,'announce_publication'):
            main.finalizar_publicacao(item,drive,storage,updater,processed,{'id':1})
            cleanup.assert_called_once_with('extracted','source.zip')
        drive.rename_processed.assert_called_once_with('id','source.zip')
        self.assertEqual(processed,[{'id':1}])
