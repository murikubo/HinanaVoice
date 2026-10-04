from types import SimpleNamespace
import unittest
from unittest.mock import patch

import hinana_bridge


class VoiceOutputTests(unittest.TestCase):
    def resolve(self, command, default=3, physical=True):
        devices = [(1, {"name": "VB-Cable", "hostapi": 0})]
        if physical:
            devices += [(2, {"name": "Speakers", "hostapi": 0}),
                        (3, {"name": "Headphones", "hostapi": 0})]
        with (
            patch.object(hinana_bridge, "output_devices", return_value=devices),
            patch.object(hinana_bridge.sd, "query_hostapis", return_value=[{"name": "Core Audio"}]),
            patch.object(hinana_bridge.sd, "default", SimpleNamespace(device=(-1, default))),
        ):
            return hinana_bridge.resolve_device(command)

    def test_existing_virtual_selection_switches_to_default_physical_output(self):
        self.assertEqual(self.resolve({"device": 1, "deviceName": "VB-Cable", "voiceProfile": {"shift": 8.5}}), 3)

    def test_explicit_physical_output_is_preserved(self):
        self.assertEqual(self.resolve({"device": 2, "deviceName": "Speakers", "voiceProfile": {"shift": 8.5}}), 2)

    def test_virtual_system_default_uses_an_available_physical_output(self):
        self.assertEqual(self.resolve({"voiceProfile": {"shift": 8.5}}, default=1), 2)

    def test_missing_physical_output_has_actionable_error(self):
        with self.assertRaisesRegex(RuntimeError, "헤드폰이나 스피커"):
            self.resolve({"voiceProfile": {"shift": 8.5}}, physical=False)

    def test_original_virtual_route_is_preserved_without_a_preset(self):
        self.assertEqual(self.resolve({"device": 1, "deviceName": "VB-Cable"}), 1)
