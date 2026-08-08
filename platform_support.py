from __future__ import annotations

from pathlib import Path
import sys
from typing import Iterable


PLATFORM_NAMES = {"win32": "Windows", "darwin": "macOS", "linux": "Linux"}

VIRTUAL_DEVICE_HINTS = {
    "win32": ("CABLE Input", "VB-Cable", "VB-CABLE"),
    "darwin": ("VB-Cable", "VB-CABLE", "CABLE Input", "BlackHole", "Loopback Audio"),
    "linux": ("Pulse", "PipeWire", "JACK", "CABLE Input", "BlackHole"),
}


def platform_key(value: str | None = None) -> str:
    current = value or sys.platform
    if current.startswith("win"):
        return "win32"
    if current == "darwin":
        return "darwin"
    return "linux"


def platform_name(value: str | None = None) -> str:
    return PLATFORM_NAMES[platform_key(value)]


def voicepeak_candidates(
    value: str | None = None, home: Path | None = None
) -> list[Path]:
    key = platform_key(value)
    user_home = home or Path.home()
    if key == "win32":
        return [
            Path(r"C:\Program Files\VOICEPEAK\voicepeak.exe"),
            Path(r"C:\Program Files\Voicepeak\voicepeak.exe"),
            Path(r"C:\Program Files (x86)\VOICEPEAK\voicepeak.exe"),
        ]
    if key == "darwin":
        roots = [Path("/Applications"), user_home / "Applications"]
        bundles = ("VOICEPEAK.app", "Voicepeak.app", "voicepeak.app")
        binaries = ("voicepeak", "VOICEPEAK", "Voicepeak")
        return [
            root / bundle / "Contents" / "MacOS" / binary
            for root in roots
            for bundle in bundles
            for binary in binaries
        ]
    return [
        Path("/usr/bin/voicepeak"),
        Path("/usr/local/bin/voicepeak"),
        Path("/opt/voicepeak/voicepeak"),
        user_home / ".local" / "bin" / "voicepeak",
    ]


def default_voicepeak_path(value: str | None = None) -> Path:
    return voicepeak_candidates(value)[0]


def resolve_voicepeak_path(
    configured: str | Path | None = None, value: str | None = None
) -> Path:
    if configured:
        requested = Path(configured).expanduser()
        if requested.is_file():
            return requested
    for candidate in voicepeak_candidates(value):
        if candidate.is_file():
            return candidate
    return Path(configured).expanduser() if configured else default_voicepeak_path(value)


def virtual_device_hints(value: str | None = None) -> tuple[str, ...]:
    return VIRTUAL_DEVICE_HINTS[platform_key(value)]


def matching_virtual_hint(name: str, value: str | None = None) -> str | None:
    folded = name.casefold()
    return next(
        (hint for hint in virtual_device_hints(value) if hint.casefold() in folded),
        None,
    )


def is_virtual_output(name: str, value: str | None = None) -> bool:
    return matching_virtual_hint(name, value) is not None


def audio_api_priority(api_name: str, value: str | None = None) -> int:
    key = platform_key(value)
    normalized = api_name.upper()
    if key == "win32":
        return {"WINDOWS DIRECTSOUND": 0, "MME": 1, "WINDOWS WASAPI": 2}.get(
            normalized, 9
        )
    if key == "darwin":
        return 0 if "CORE AUDIO" in normalized else 9
    return {"PIPEWIRE": 0, "PULSE AUDIO": 1, "ALSA": 2, "JACK": 3}.get(
        normalized, 9
    )


def route_instructions(value: str | None = None) -> dict[str, str]:
    key = platform_key(value)
    if key == "darwin":
        return {
            "sender": "VB-Cable/BlackHole 출력 장치",
            "receiver": "Vocoflex 입력에서 같은 가상 장치 선택",
            "monitor": "Vocoflex 출력을 실제 헤드폰으로 선택",
        }
    if key == "linux":
        return {
            "sender": "PipeWire/Pulse/JACK 가상 출력",
            "receiver": "변조 앱 입력에서 같은 가상 장치 선택",
            "monitor": "변조 앱 출력을 실제 헤드폰으로 선택",
        }
    return {
        "sender": "CABLE Input 재생 장치",
        "receiver": "Vocoflex 입력에서 CABLE Output 선택",
        "monitor": "Vocoflex 출력을 실제 헤드폰으로 선택",
    }


def first_virtual_name(names: Iterable[str], value: str | None = None) -> str | None:
    return next((name for name in names if is_virtual_output(name, value)), None)
