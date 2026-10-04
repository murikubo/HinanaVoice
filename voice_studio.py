"""Local reference-pitch analysis and Vocoflex preview/conversion helpers."""
from __future__ import annotations

import math
from pathlib import Path
import subprocess

import numpy as np
import soundfile as sf

from hinana_voice import make_voicepeak_wavs
from platform_support import resolve_voicepeak_path

TEST_TEXT = "こんにちは。今日はどんな一日でしたか。あなたとお話しできて、うれしいです。少し休んでから、一緒に続きを始めましょう。"


def pitch_summary(path: Path) -> dict:
    import parselmouth

    sound = parselmouth.Sound(str(path)).convert_to_mono()
    if sound.duration > 600:
        raise ValueError("참고 음성은 10분 이하로 선택해 주세요.")
    pitch = sound.to_pitch_ac(time_step=0.01, pitch_floor=70, pitch_ceiling=800, very_accurate=True)
    selected = pitch.selected_array
    f0 = selected["frequency"][(selected["frequency"] > 0) & (selected["strength"] >= 0.6)]
    if len(f0) < 50:
        raise ValueError("분석할 음성이 부족합니다. 배경음 없이 한 사람이 말하는 구간을 선택해 주세요.")
    midi = 69 + 12 * np.log2(f0 / 440)
    return {"medianHz": float(np.median(f0)), "duration": sound.duration,
            "voicedFrames": len(f0), "pitchRange": np.percentile(midi, [10, 50, 90]).tolist()}


def synthesize(command: dict, directory: Path, text: str = TEST_TEXT) -> Path:
    voicepeak = resolve_voicepeak_path(command.get("voicepeak"))
    if not voicepeak.is_file():
        raise ValueError("VOICEPEAK 실행 파일을 확인해 주세요.")
    parts = make_voicepeak_wavs(voicepeak, command.get("narrator") or "Koharu Rikka",
                              text, directory, int(command.get("speed", 95)), int(command.get("pitch", 0)))
    audio = []
    rate = None
    for path in parts:
        samples, sample_rate = sf.read(path, always_2d=True)
        if rate is not None and rate != sample_rate:
            raise ValueError("합성된 음성의 샘플레이트가 다릅니다.")
        rate = sample_rate
        audio.append(samples)
    output = directory / "input.wav"
    sf.write(output, np.concatenate(audio), rate, subtype="PCM_16")
    return output


def analyze(command: dict) -> dict:
    directory = Path(command["outputDir"])
    directory.mkdir(parents=True, exist_ok=True)
    reference = pitch_summary(Path(command["referencePath"]))
    original_path = synthesize(command, directory)
    original = pitch_summary(original_path)
    estimated = 12 * math.log2(reference["medianHz"] / original["medianHz"])
    shift = round(max(-12, min(12, estimated)) * 2) / 2
    return {"reference": reference, "input": original, "shift": shift,
            "clamped": abs(estimated) > 12, "inputPath": str(original_path)}


def convert(input_path: Path, output_path: Path, profile: dict) -> None:
    host = Path(profile["hostPath"])
    state = Path(profile["statePath"])
    shift = float(profile["shift"])
    if not math.isfinite(shift) or abs(shift) > 12:
        raise ValueError("음높이 보정은 -12~12반음 범위로 설정해 주세요.")
    if not host.is_file() or not state.is_file():
        raise ValueError("Vocoflex 변환 도구 또는 등록된 음색을 찾을 수 없습니다.")
    result = subprocess.run([str(host), "--state", str(state), "--pitch-semitones", str(shift),
                             "--input", str(input_path), "--output", str(output_path),
                             "--output-gain-db", "-6", "--fast"],
                            capture_output=True, text=True, timeout=180)
    if result.returncode:
        raise RuntimeError("Vocoflex 변환 실패: " + (result.stderr.strip() or result.stdout[-500:]))
    audio, _ = sf.read(output_path)
    if not np.isfinite(audio).all() or np.max(np.abs(audio)) >= 0.999:
        raise RuntimeError("변환 출력이 과도하게 커졌습니다. 입력 음량 또는 음색 설정을 조절해 주세요.")


def preview(command: dict) -> dict:
    directory = Path(command["outputDir"])
    directory.mkdir(parents=True, exist_ok=True)
    text = str(command.get("text") or TEST_TEXT).strip()
    if len(text) > 400:
        raise ValueError("미리 듣기 문장은 400자 이하로 입력해 주세요.")
    original = synthesize(command, directory, text)
    output = directory / "preview.wav"
    convert(original, output, command)
    return {"path": str(output), "pitch": pitch_summary(output)}
