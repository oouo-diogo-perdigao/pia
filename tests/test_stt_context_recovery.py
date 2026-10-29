"""Only audio-backed, bounded repetitions with real word intervals are accepted."""
import unittest
from src.stt_recovery import find_repetition,segment_dict,trim_left_context


class ContextRecoveryTests(unittest.TestCase):
    def repeated(self,count=6,duration=.3):
        return segment_dict(dict(start=0,end=count,text='Não, '*count,
            words=[dict(start=i,end=i+duration,word=' Não,') for i in range(count)]))

    def test_short_repeat_requires_audio_retry_and_positive_word_times(self):
        row=self.repeated()
        self.assertIsNotNone(find_repetition([row]))
        row['_audio_retry']=True
        self.assertIsNone(find_repetition([row]))
        self.assertIsNotNone(find_repetition([{**self.repeated(duration=0),'_audio_retry':True}]))
        self.assertIsNotNone(find_repetition([{**self.repeated(30),'_audio_retry':True}]))

    def test_paused_acknowledgements_are_not_one_continuous_loop(self):
        self.assertIsNone(find_repetition([dict(start=i*10,end=i*10+1,text='aham') for i in range(20)]))

    def test_context_trim_uses_complete_words_and_original_times(self):
        row=segment_dict(dict(start=8,end=13,text='Antes. Depois.',words=[dict(start=8,end=9,word=' Antes.'),dict(start=11,end=13,word=' Depois.')]))
        result=trim_left_context([row],10)
        self.assertEqual((result[0]['start'],result[0]['end'],result[0]['text']),(11,13,'Depois.'))
        self.assertTrue(result[0]['_audio_retry'])
        self.assertIsNone(trim_left_context([row],12))
        self.assertIsNone(trim_left_context([dict(start=8,end=13,text='No alignment')],10))
        self.assertEqual(trim_left_context([row],14),[])
