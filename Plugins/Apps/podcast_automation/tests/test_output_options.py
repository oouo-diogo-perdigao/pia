"""Output selections change actual processing and publication, not only UI flags."""
import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock,patch
from podcast_automation import main,settings
EXAMPLE=json.loads((Path(__file__).resolve().parents[1]/'docs/examples/config.example.json').read_text(encoding='utf-8'))
class OutputTests(unittest.TestCase):
    def test_defaults_and_mandatory_mp3(self):
        with patch.object(settings,'get_config',return_value={}):self.assertTrue(all(settings.output_formats().values()))
        with patch.object(settings,'get_config',return_value={'outputs':{'mp3':False,'srt':False}}):
            self.assertTrue(settings.output_formats()['mp3']);self.assertFalse(settings.output_formats()['srt'])
    def process(self,selection):
        with TemporaryDirectory() as temporary:
            root=Path(temporary);audio_path=root/'episode.mp3';audio_path.write_bytes(b'audio');script=root/'episode.txt';srt=root/'episode.srt';vtt=root/'episode.vtt';summary=root/'episode.resumo.json'
            config=copy.deepcopy(EXAMPLE);config['outputs']=selection
            audio=Mock(campanha='Campaign',narrador='Narrator',personagens=[],jogadores=[],ouvintes=[],rss='campaign/rss.xml',session=1,episode=1,arquivos_participantes=[],grupos_transcricao={},edit_timeline=[])
            audio.mix.return_value=str(root/'mix.wav');audio.build.return_value=str(audio_path);audio.renomear_arquivos.return_value={'audio_mix_path':str(root/'mix.wav'),'audio_path':str(audio_path)}
            whisper=Mock()
            def write(path):path.write_text('text');return str(path)
            whisper.gravar_roteiro.side_effect=lambda:write(script);whisper.gravar_srt.side_effect=lambda:write(srt);whisper.gravar_vtt.side_effect=lambda:write(vtt)
            whisper.renomear_arquivos.return_value={'srt_path':str(srt),'vtt_path':str(vtt),'roteiro_path':str(script)}
            generator=Mock();generator.gerar_resumo.side_effect=lambda:(write(summary),'short','complete');generator.renomear_arquivos.return_value={'resumo_json_path':str(summary)}
            drive=Mock();drive.download_file.return_value=root/'recording.zip';storage=Mock();updater=Mock()
            updater.updateRssTranscriptionFiles.return_value={'success':True,'folders':[{'folder':'campaign'}]}
            with patch.object(main,'get_config',return_value=config),patch.object(settings,'get_config',return_value=config),patch.object(main,'AudioManager',return_value=audio) as manager,patch.object(main,'GeradorResumoSessao',return_value=generator) as generate,patch.object(main,'extrair_zip',return_value=str(root)),patch.object(main,'criar_assinatura',return_value={}),patch.object(main,'localizar_duplicada',return_value=None),patch.object(main,'limpar_temporarios'),patch.object(main,'announce_publication'):
                manager.obter_duracao_audio.return_value=7200
                main.configure();main.processar_sessao({'name':'recording.zip','id':'recording'},drive,storage,updater,whisper,[])
            uploaded=[Path(call.args[0]).name for call in storage.sendObject.call_args_list]
            return whisper,generate,uploaded,script.exists()
    def test_mp3_only_skips_transcription_and_llm(self):
        whisper,generate,uploaded,_=self.process({name:False for name in ('resumo.json','srt','vtt','txt')})
        whisper.build.assert_not_called();generate.assert_not_called();self.assertEqual(uploaded,['episode.mp3'])
    def test_srt_only_avoids_other_derivatives(self):
        whisper,generate,uploaded,_=self.process({'resumo.json':False,'srt':True,'vtt':False,'txt':False})
        whisper.gravar_srt.assert_called_once();whisper.gravar_vtt.assert_not_called();whisper.gravar_roteiro.assert_not_called();generate.assert_not_called()
        self.assertEqual(uploaded,['episode.mp3','episode.srt'])
    def test_summary_can_use_internal_script_without_exporting_txt(self):
        whisper,generate,uploaded,script_exists=self.process({'resumo.json':True,'srt':False,'vtt':False,'txt':False})
        whisper.gravar_roteiro.assert_called_once();generate.assert_called_once();self.assertFalse(script_exists)
        self.assertEqual(uploaded,['episode.mp3','episode.resumo.json'])
if __name__=='__main__':unittest.main()
