"""A stale loop must not be accepted merely because a participant JSON exists."""
import json
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock
import unittest
from podcast_automation.transcritorWhisper import TranscritorWhisper
class CacheTests(unittest.TestCase):
    def run_cache(self,rows,healthy,certificate=None):
        with TemporaryDirectory() as temporary:
            file=Path(temporary)/'participant.json';file.write_text(json.dumps(rows))
            if certificate:
                digest=hashlib.sha256(file.read_bytes()).hexdigest() if certificate=='matching' else 'stale'
                file.with_suffix('.stt-validated.json').write_text(json.dumps({'version':2,'sha256':digest}))
            transcriber=TranscritorWhisper.__new__(TranscritorWhisper);transcriber.cache_rebuilt=False
            transcriber.grupos_transcricao={'Kojiro':['original.flac']};transcriber.json_paths={'Kojiro':str(file)}
            transcriber.carregar_modelo=Mock(side_effect=RuntimeError('pending-retranscription'))
            if healthy:
                transcriber.processar_participantes();transcriber.carregar_modelo.assert_not_called()
                self.assertFalse(transcriber.cache_rebuilt)
            else:
                with self.assertRaisesRegex(RuntimeError,'pending-retranscription'):transcriber.processar_participantes()
                self.assertTrue(transcriber.cache_rebuilt)
                self.assertEqual(json.loads(file.read_text()),rows)
    def test_healthy_and_silent_caches_reused(self):
        self.run_cache([{'inicio':0,'fim':2,'texto':'Uma fala normal.'}],True);self.run_cache([],True)
    def test_repeated_and_invalid_cache_retranscribed_without_early_deletion(self):
        self.run_cache([{'inicio':0,'fim':20,'texto':'tá '*6}],False)
        self.run_cache([{'inicio':0,'fim':20,'texto':'aham'} for _ in range(6)],False)
        self.run_cache([{'texto':'sem timestamps'}],False)
    def test_audio_validated_cache_requires_matching_content_hash(self):
        rows=[{'inicio':0,'fim':20,'texto':'Não, '*6}]
        self.run_cache(rows,True,'matching')
        self.run_cache(rows,False,'stale')
    def test_existing_zero_duration_cache_keeps_text_in_subtitles(self):
        with TemporaryDirectory() as temporary:
            path=Path(temporary)/'participant.json'
            path.write_text(json.dumps([dict(inicio=12,fim=12,autor='Caio',texto='Fim da fala.')]))
            transcriber=TranscritorWhisper.__new__(TranscritorWhisper)
            transcriber.json_paths={'Caio':str(path)};transcriber.edit_timeline=[]
            rows=transcriber.ler_segmentos()
            self.assertEqual(rows[0].inicio,12)
            self.assertAlmostEqual(rows[0].fim,12.02)
            cues=transcriber.mesclar_falas_sobrepostas()
            self.assertEqual(cues[0][2],['Fim da fala.'])
if __name__=='__main__':unittest.main()
