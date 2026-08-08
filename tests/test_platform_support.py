from pathlib import Path
import unittest

from platform_support import (
    audio_api_priority,
    default_voicepeak_path,
    is_virtual_output,
    platform_key,
    route_instructions,
    virtual_device_hints,
    voicepeak_candidates,
)


class PlatformSupportTests(unittest.TestCase):
    def test_platform_keys(self) -> None:
        self.assertEqual(platform_key("win32"), "win32")
        self.assertEqual(platform_key("darwin"), "darwin")
        self.assertEqual(platform_key("linux"), "linux")

    def test_macos_voicepeak_bundle_path(self) -> None:
        candidates = voicepeak_candidates("darwin", Path("/Users/tester"))
        self.assertIn(
            Path("/Applications/VOICEPEAK.app/Contents/MacOS/voicepeak"),
            candidates,
        )
        self.assertEqual(default_voicepeak_path("darwin"), candidates[0])

    def test_virtual_audio_names(self) -> None:
        self.assertTrue(is_virtual_output("CABLE Input (VB-Audio)", "win32"))
        self.assertTrue(is_virtual_output("VB-Cable", "darwin"))
        self.assertTrue(is_virtual_output("BlackHole 2ch", "darwin"))
        self.assertFalse(is_virtual_output("MacBook Pro Speakers", "darwin"))
        self.assertIn("BlackHole", virtual_device_hints("darwin"))

    def test_host_api_priorities(self) -> None:
        self.assertLess(
            audio_api_priority("Windows DirectSound", "win32"),
            audio_api_priority("Windows WASAPI", "win32"),
        )
        self.assertEqual(audio_api_priority("Core Audio", "darwin"), 0)

    def test_route_copy_is_os_specific(self) -> None:
        self.assertIn("CABLE Output", route_instructions("win32")["receiver"])
        self.assertIn("가상 장치", route_instructions("darwin")["receiver"])


if __name__ == "__main__":
    unittest.main()
