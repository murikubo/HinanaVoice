import json
from pathlib import Path
import plistlib
import tempfile
import unittest
import xml.etree.ElementTree as ET
from standalone_vocoflex import apply, encode, decode


class StandaloneTests(unittest.TestCase):
    def test_juce_known_encoding_and_binary_roundtrip(self):
        self.assertEqual(encode(b'\x00'), '1...')
        self.assertEqual(encode(b'\xff'), '1.+C')
        self.assertEqual(decode(encode(bytes(range(256)))), bytes(range(256)))

    def test_apply_preserves_other_settings_and_backs_up_original(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            settings = folder / 'settings.xml'
            root = ET.Element('ApplicationSettings')
            ET.SubElement(root, 'State', savedState=encode(json.dumps({'inputGain': -3, 'custom': True}).encode()))
            ET.SubElement(root, 'General', interfaceLanguage='ja-jp')
            ET.SubElement(root, 'Audio', audioSetup='<DEVICESETUP audioDeviceBufferSize="512"/>')
            ET.ElementTree(root).write(settings)
            original = settings.read_bytes()
            state = folder / 'voice.aupreset'
            state.write_bytes(plistlib.dumps({'jucePluginState': json.dumps({'voice': {'sources': ['reference']}}).encode()}))
            result = apply({'settingsPath': str(settings), 'statePath': str(state), 'shift': 7.5,
                            'name': '히나나', 'inputName': 'Microphone', 'outputName': 'Headphones'})
            updated = ET.parse(settings).getroot()
            voice = json.loads(decode(updated.find('State').get('savedState')))
            self.assertEqual(voice['voice']['sources'], ['reference'])
            self.assertEqual(voice['inputPitchShift'], 7.5)
            self.assertEqual(voice['inputGain'], -3)
            self.assertTrue(voice['useRealtimeLatency'])
            self.assertEqual(updated.find('General').get('interfaceLanguage'), 'ja-jp')
            audio = ET.fromstring(updated.find('Audio').get('audioSetup'))
            self.assertEqual(audio.get('audioInputDeviceName'), 'Microphone')
            self.assertEqual(audio.get('audioDeviceBufferSize'), '512')
            self.assertEqual(Path(result['backupPath']).read_bytes(), original)
            with self.assertRaises(ValueError):
                apply({'settingsPath': str(settings), 'statePath': str(state), 'shift': 50})
