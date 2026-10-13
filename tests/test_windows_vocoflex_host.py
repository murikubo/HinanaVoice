import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from standalone_vocoflex import encode, decode
from windows_vocoflex_host import component, replace_component


class WindowsStateTests(unittest.TestCase):
    def test_component_rewrite_preserves_private_suffix_and_unicode(self):
        suffix = b'\0\0JUCEPrivateData\x01Bypass'
        old = {'voice': {'sources': []}, 'inputPitchShift': 0}
        root = ET.Element('VST3PluginState')
        ET.SubElement(root, 'IComponent').text = encode(json.dumps(old).encode() + suffix)
        xml = ET.tostring(root)
        raw = b'VC2!' + struct.pack('<I', len(xml)) + xml + b'\0'
        new = {'voice': {'sources': [{'name': '히나나'}]}, 'inputPitchShift': 7.5}
        replaced = replace_component(raw, new)
        _, _, settings, after = component(replaced)
        self.assertEqual(settings, new)
        self.assertEqual(after, suffix)
        self.assertEqual(struct.unpack('<I', replaced[4:8])[0], len(replaced[8:-1]))

    def test_invalid_container_is_rejected(self):
        with self.assertRaises(ValueError): component(b'not a preset')

    @unittest.skipUnless(os.name == 'nt', 'Windows Tcl lifecycle regression')
    def test_native_tk_controls_close_cleanly_on_main_thread(self):
        script = '''
import sys, tkinter as tk
from windows_vocoflex_host import registration_controls
original = tk.Tk
def hidden_root():
    root = original()
    root.withdraw()
    def cancel():
        handler = root.tk.call('wm', 'protocol', root._w, 'WM_DELETE_WINDOW')
        root.tk.call(handler)
    root.after(100, cancel)
    return root
tk.Tk = hidden_root
registration_controls(sys.argv[1], 'reference.wav')
'''
        with tempfile.TemporaryDirectory() as folder:
            signal = Path(folder) / 'action.txt'
            for _ in range(3):
                result = subprocess.run([sys.executable, '-c', script, str(signal)],
                                        capture_output=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
                self.assertEqual(signal.read_text(), 'cancel')
