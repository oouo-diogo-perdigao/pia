"""Technical point-duration repair must not shift the source timeline or call STT."""
import unittest
from src.transcription import timed_result,render_subtitles

class PointTimestampTests(unittest.TestCase):
    def response(self,segments,duration=10):
        return dict(text=' '.join(s['text'] for s in segments),duration=duration,segments=segments)

    def test_minimal_extension_bounded_by_next_real_start_and_idempotent(self):
        raw=self.response([dict(start=2,end=2,text='Uma.'),dict(start=2.01,end=4,text='Duas.')])
        result=timed_result(raw)
        self.assertEqual(result['segments'][0]['start'],2)
        self.assertEqual(result['segments'][0]['end'],2.01)
        self.assertEqual(result['segments'][1]['end'],4)
        self.assertEqual(result['timestamp_adjustments'][0]['original_end'],2)
        self.assertEqual(timed_result(result),result)
        self.assertEqual(raw['segments'][0]['end'],2)
        self.assertIn('00:00:02,000 --> 00:00:02,010',render_subtitles(result['segments'],'srt'))

    def test_shared_point_times_and_terminal_point_preserve_all_text(self):
        result=timed_result(self.response([dict(start=5,end=5,text='Uma.'),dict(start=5,end=5,text='Duas.'),dict(start=10,end=10,text='Fim.')]))
        self.assertEqual([s['text'] for s in result['segments']],['Uma.','Duas.','Fim.'])
        self.assertTrue(all(s['end']>s['start'] for s in result['segments']))
        self.assertEqual(result['duration'],10)
        self.assertAlmostEqual(result['segments'][-1]['end'],10.02)
        self.assertEqual(len(result['timestamp_adjustments']),3)

    def test_positive_intervals_unchanged_and_bad_timestamps_rejected(self):
        good=self.response([dict(id=0,start=3,end=4,text='Fala')])
        self.assertEqual(timed_result(good),good)
        for start,end in ((-1,0),(4,3),(11,11),(True,True)):
            with self.subTest(start=start,end=end),self.assertRaises(ValueError):
                timed_result(self.response([dict(start=start,end=end,text='Inválido')]))
