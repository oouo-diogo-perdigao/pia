"""No models/network: recovery must reread real audio positions, not guess times."""
from types import SimpleNamespace
from unittest.mock import Mock,patch
import types
import sys
import unittest
from src.stt_recovery import RecoveryOptions,RepetitionRecoveryError,find_repetition,recover_segments

class Samples:
    """Small lazy PCM fixture; avoids native-library reloads in dependency-stub tests."""
    def __init__(self,size,start=0):self.size=size;self.start=start
    def __len__(self):return self.size
    def __getitem__(self,item):
        if isinstance(item,slice):
            begin,end,step=item.indices(self.size)
            assert step==1
            return Samples(end-begin,self.start+begin)
        return self.start+item
    def clip(self,*args):return self
    def __mul__(self,value):return self
    def astype(self,value):return self
    def tobytes(self):return b'\x00\x00'*self.size

def seg(start,end,text,words=None):
    result={'start':start,'end':end,'text':text}
    if words is not None:result['words']=[dict(start=a,end=b,word=t) for a,b,t in words]
    return result
class RecoveryTests(unittest.TestCase):
    def test_five_repeats_allowed_six_detected_unicode_punctuation_and_phrases(self):
        self.assertIsNone(find_repetition([seg(0,5,'Tá, '*5)]))
        p=find_repetition([seg(0,8,'Bom. Tá, ta! TÁ? tá. ta, tá.')])
        self.assertEqual((p.segment,p.token),(0,1))
        self.assertIsNotNone(find_repetition([seg(0,30,'eu não sei. '*6)]))
        self.assertIsNone(find_repetition([seg(0,30,'ela disse sim depois mudou de ideia e disse não')]))
    def test_keep_good_words_inside_failed_segment_and_original_pauses(self):
        initial=[seg(0,2,'Introdução.'),seg(10,20,'Parte boa. '+'Tá, '*6,[(10,10.5,' Parte'),(10.6,11,' boa.')]+[(12+i,12.5+i,' Tá,') for i in range(6)])]
        retry=Mock(return_value={'offset':12,'segments':[seg(.5,2,'Continuação real.')]})
        result=recover_segments(iter(initial),30,retry)
        self.assertEqual(retry.call_args.args,(12,30,1))
        self.assertEqual(result,[{'id':0,'start':0,'end':2,'text':'Introdução.'},{'id':1,'start':10,'end':11,'text':'Parte boa.'},{'id':2,'start':12.5,'end':14,'text':'Continuação real.'}])
    def test_without_word_times_redecode_whole_suspect_segment_not_estimated_prefix(self):
        retry=Mock(return_value={'offset':10,'segments':[seg(0,5,'Parte boa e continuação.') ]})
        result=recover_segments([seg(0,2,'Antes'),seg(10,30,'Parte boa '+('tá '*6))],40,retry)
        self.assertEqual(retry.call_args.args[0],10)
        self.assertEqual(result[1]['text'],'Parte boa e continuação.')
    def test_repeated_utterances_across_segments_restart_at_first_not_sixth(self):
        initial=[seg(0,2,'Antes.')]+[seg(5+i*3,6+i*3,'aham') for i in range(6)]
        retry=Mock(return_value={'offset':5,'segments':[seg(10,12,'Fala recuperada.')]})
        result=recover_segments(iter(initial),40,retry)
        self.assertEqual(retry.call_args.args[0],5)
        self.assertEqual(result[-1]['start'],15)
        self.assertEqual(len(result),2)
    def test_persistent_loop_is_bounded_and_never_returned_as_success(self):
        bad=seg(0,5,'tá '*6);retry=Mock(return_value={'segments':[bad],'offset':0})
        with self.assertRaisesRegex(RepetitionRecoveryError,'persistente'):
            recover_segments([bad],20,retry,options=RecoveryOptions(max_retries=2))
        self.assertEqual(retry.call_count,2)
    def test_new_failure_offsets_are_relative_to_original_file(self):
        responses=[{'offset':10,'segments':[seg(1,3,'Primeiro reparo.'),seg(10,15,'aham '*6)]},{'offset':20,'segments':[seg(2,4,'Segundo reparo.')]}]
        retry=Mock(side_effect=responses)
        result=recover_segments([seg(0,5,'Antes.'),seg(10,15,'tá '*6)],40,retry)
        self.assertEqual([call.args[0] for call in retry.call_args_list],[10,20])
        self.assertEqual([s['start'] for s in result],[0,11,22])
    def test_recovery_windows_keep_boundary_words_once_and_do_not_compress_pauses(self):
        real=[(11,12,'um'),(25,26,'dois'),(40,41,'três'),(59,60,'quatro'),(69.5,71,'cinco'),(85,86,'seis'),(110,111,'sete'),(129.5,131,'oito'),(150,151,'nove'),(175,176,'dez')]
        calls=[]
        def retry(start,end,attempt):
            calls.append((start,end))
            words=[(a-start,min(b,end)-start,' '+text) for a,b,text in real if start<=a<end]
            output=[seg(words[0][0],words[-1][1],''.join(w[2] for w in words).strip(),words)] if words else []
            return {'offset':start,'segments':output}
        result=recover_segments([seg(0,5,'Antes.'),seg(10,15,'tá '*6)],180,retry)
        self.assertGreater(len(calls),1)
        self.assertEqual(' '.join(s['text'] for s in result),'Antes. '+' '.join(w[2] for w in real))
        self.assertTrue(any(s['end']==71 for s in result) or any(s['start']<=69.5 and s['end']>=71 for s in result))
        self.assertEqual(result[-1]['end'],176)
        for start,_ in calls:self.assertFalse(any(a<start<b for a,b,_ in real))
    def test_silence_after_failed_segment_valid_and_disabled_mode_keeps_original(self):
        bad=[seg(0,2,'Antes'),seg(4,10,'tá '*6)]
        result=recover_segments(bad,20,lambda *args:{'segments':[]})
        self.assertEqual([s['text'] for s in result],['Antes'])
        retry=Mock();result=recover_segments(bad,20,retry,options=RecoveryOptions(enabled=False))
        retry.assert_not_called();self.assertEqual(len(result),2)
    def test_retry_generator_is_closed_as_soon_as_repetition_is_detected(self):
        closed=[]
        def looping():
            try:
                for index in range(100000):yield seg(0,1,'aham')
            finally:closed.append(True)
        with self.assertRaises(RepetitionRecoveryError):
            recover_segments([seg(0,5,'tá '*6)],10,lambda *args:{'segments':looping()},options=RecoveryOptions(max_retries=1))
        self.assertEqual(closed,[True])
    def test_tiny_fake_progress_cannot_create_unbounded_requests(self):
        calls=[]
        def retry(start,end,attempt):
            calls.append(start)
            return {'offset':start,'segments':[seg(0,.01,'palavra'+str(len(calls)))]}
        with self.assertRaisesRegex(RepetitionRecoveryError,'global'):
            recover_segments([seg(0,1,'tá '*6)],120,retry,options=RecoveryOptions(max_retries=1,max_repairs=1))
        self.assertLessEqual(len(calls),10)
    def test_no_audio_after_invalid_end_marker_is_clear_failure(self):
        with self.assertRaisesRegex(RepetitionRecoveryError,'sem áudio restante'):
            recover_segments([seg(10,10,'tá '*6)],10,Mock())
    def test_remote_text_without_segments_is_not_converted_to_silence(self):
        from test_transcription import hybrid
        manager=hybrid.STTManager.__new__(hybrid.STTManager)
        with self.assertRaisesRegex(ValueError,'timestamps'):
            manager._recover_groq_result(b'audio',{'duration':10,'text':'Uma fala real','segments':[]})
    def test_actual_local_adapter_crops_samples_and_preserves_full_duration(self):
        from test_transcription import voice
        agent=voice.VoiceAgent.__new__(voice.VoiceAgent);agent.model=Mock()
        initial=[SimpleNamespace(**seg(0,2,'Antes')),SimpleNamespace(**seg(10,15,'tá '*6))]
        repair=[SimpleNamespace(**seg(4,5,'Recuperado.'))]
        agent.model.transcribe.side_effect=[(iter(initial),SimpleNamespace(duration=30,language='pt')),(iter(repair),SimpleNamespace(duration=20,language='pt'))]
        audio=types.ModuleType('faster_whisper.audio');samples=Samples(30*16000);audio.decode_audio=Mock(return_value=samples)
        with patch.dict(sys.modules,{'faster_whisper.audio':audio}):result=agent.transcribe_chunk(b'encoded',language=None,return_metadata=True)
        sent=agent.model.transcribe.call_args.args[0]
        self.assertEqual(sent[0],8*16000);self.assertEqual(len(sent),22*16000)
        self.assertEqual(result['duration'],30);self.assertEqual(result['segments'][-1]['start'],12)
        self.assertFalse(agent.model.transcribe.call_args.kwargs['condition_on_previous_text'])
        self.assertTrue(agent.model.transcribe.call_args.kwargs['word_timestamps'])
        self.assertEqual(agent.model.transcribe.call_args.kwargs['language'],'pt')
    def test_remote_recovery_failure_retains_local_fallback(self):
        from test_transcription import hybrid,local
        manager=hybrid.STTManager.__new__(hybrid.STTManager);manager.providers=('groq','local');manager._provider_available=Mock(return_value=True);manager._disable_provider_temporarily=Mock()
        bad={'text':'tá '*6,'duration':20,'segments':[seg(0,5,'tá '*6)]}
        manager._transcribe_groq_litellm=Mock(return_value=bad)
        audio=types.ModuleType('faster_whisper.audio');audio.decode_audio=Mock(return_value=Samples(20*16000))
        with patch.dict(sys.modules,{'faster_whisper.audio':audio}),patch.object(local.STTManager,'transcribe_request',return_value={'ok':True,'text':'Correto.','duration':20,'segments':[seg(12,14,'Correto.')]}) as fallback:
            result=manager.transcribe_request(b'audio',require_timestamps=True)
        self.assertEqual(result['provider'],'local');self.assertEqual(result['segments'][0]['start'],12)
        fallback.assert_called_once()
if __name__=='__main__':unittest.main()
