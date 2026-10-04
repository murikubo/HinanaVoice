from queue import Queue
import unittest
from live_voice import best_shift, put_latest


class LiveVoiceTests(unittest.TestCase):
    def test_hinana_correction_and_measured_feedback(self):
        self.assertEqual(best_shift(470.775, 291.556), (8.5, False))
        self.assertEqual(best_shift(470.775, 450, 8.5), (9.5, False))

    def test_unreachable_target_is_bounded_and_reported(self):
        self.assertEqual(best_shift(470, 90), (12.0, True))
        with self.assertRaises(ValueError):
            best_shift(float('nan'), 200)

    def test_overloaded_audio_queue_discards_oldest_instead_of_adding_latency(self):
        queue = Queue(maxsize=2)
        self.assertFalse(put_latest(queue, 1))
        self.assertFalse(put_latest(queue, 2))
        self.assertTrue(put_latest(queue, 3))
        self.assertEqual([queue.get(), queue.get()], [2, 3])
