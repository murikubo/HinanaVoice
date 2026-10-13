from queue import Queue
import unittest
from unittest.mock import patch
import sounddevice as sd
from live_voice import best_shift, put_latest, audio_settings


class LiveVoiceTests(unittest.TestCase):
    def test_wasapi_uses_shared_format_conversion(self):
        info = {'name': 'Controller', 'max_output_channels': 4, 'hostapi': 1}
        with patch('live_voice.sd.query_devices', return_value=info), \
             patch('live_voice.sd.query_hostapis', return_value={'name': 'Windows WASAPI'}), \
             patch('live_voice.sd.WasapiSettings', return_value='converted') as factory, \
             patch('live_voice.sd.check_output_settings') as check:
            result = audio_settings(2, 'output')
            factory.assert_called_once_with(auto_convert=True)
            self.assertEqual(result['extra_settings'], 'converted')
            self.assertEqual(result['channels'], 2)
            check.assert_called_once_with(**result)

    def test_input_falls_back_to_mono_when_stereo_is_rejected(self):
        info = {'name': 'Mic', 'max_input_channels': 2, 'hostapi': 1}
        with patch('live_voice.sd.query_devices', return_value=info), \
             patch('live_voice.sd.query_hostapis', return_value={'name': 'Core Audio'}), \
             patch('live_voice.sd.check_input_settings', side_effect=[sd.PortAudioError('Invalid channels'), None]):
            self.assertEqual(audio_settings(2, 'input')['channels'], 1)

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
