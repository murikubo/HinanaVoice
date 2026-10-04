"""Generate Vocoflex candidates with input pitch matched to a local reference.

This matches a robust F0 centre, not the speaker identity or the full intonation.
The AU preset must already contain the intended target voice.
"""
import argparse
import json
import math
from pathlib import Path
import subprocess

import numpy as np
import parselmouth
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "artifacts/vocoflex-lab/Hinana Vocoflex Lab.app/Contents/MacOS/vocoflex-host"


def pitch_summary(path):
    sound = parselmouth.Sound(str(path)).convert_to_mono()
    pitch = sound.to_pitch_ac(time_step=0.01, pitch_floor=70, pitch_ceiling=800, very_accurate=True)
    selected = pitch.selected_array
    valid = (selected["frequency"] > 0) & (selected["strength"] >= 0.6)
    frequencies = selected["frequency"][valid]
    if frequencies.size < 50:
        raise ValueError(f"Not enough confident voiced frames: {path}")
    midi = 69 + 12 * np.log2(frequencies / 440)
    return {
        "median_hz": float(np.median(frequencies)),
        "midi_quantiles_10_25_50_75_90": np.percentile(midi, [10, 25, 50, 75, 90]).tolist(),
        "confident_voiced_frames": int(frequencies.size),
        "duration_seconds": sound.duration,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--offsets", default="-2,0,2", help="Offsets around the estimated shift, in semitones")
    args = parser.parse_args()
    for path in (args.reference, args.input, args.state, HOST):
        if not path.is_file():
            parser.error(f"File not found: {path}")
    offsets = list(dict.fromkeys(float(part) for part in args.offsets.split(",")))
    if any(not math.isfinite(value) or abs(value) > 12 for value in offsets):
        parser.error("Offsets must be finite numbers between -12 and 12")
    reference = pitch_summary(args.reference)
    original = pitch_summary(args.input)
    requested = 12 * math.log2(reference["median_hz"] / original["median_hz"])
    centre = round(float(np.clip(requested, -12, 12)) * 2) / 2
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "reference": str(args.reference.resolve()),
        "input": str(args.input.resolve()),
        "state": str(args.state.resolve()),
        "reference_pitch": reference,
        "input_pitch": original,
        "estimated_shift_semitones": requested,
        "applied_centre_semitones": centre,
        "clamped": abs(requested) > 12,
        "candidates": [],
        "limitations": [
            "Pitch statistics use confident voiced frames; pitch tracking can have octave errors.",
            "Each candidate uses one constant shift. Reference intonation and speaker identity are not matched.",
            "The target voice must already be imported into the supplied Vocoflex preset.",
            "Pitch is set through the exported state format tested with Vocoflex 1.0.3.",
        ],
    }
    print(f"Reference median {reference['median_hz']:.1f} Hz; input {original['median_hz']:.1f} Hz; shift {centre:+.1f} semitones", flush=True)
    shifts = set()
    for offset in offsets:
        shift = float(np.clip(centre + offset, -12, 12))
        if shift in shifts:
            continue
        shifts.add(shift)
        label = "matched" if offset == 0 else f"matched_{'higher' if offset > 0 else 'lower'}"
        if offsets.count(offset) > 1 or sum((item > 0) == (offset > 0) for item in offsets if item != 0) > 1:
            label += f"_{abs(offset):g}"
        output = args.output_dir / f"{label}.wav"
        preset = args.output_dir / f"{label}.aupreset"
        if output.resolve() in (args.reference.resolve(), args.input.resolve()) or preset.resolve() == args.state.resolve():
            raise ValueError("Output must not overwrite an input or reference")
        subprocess.run([
            str(HOST), "--state", str(args.state.resolve()),
            "--pitch-semitones", str(shift), "--input", str(args.input.resolve()),
            "--output", str(output.resolve()), "--save-state", str(preset.resolve()),
            "--output-gain-db", "-6", "--fast",
        ], check=True)
        measured = pitch_summary(output)
        audio, rate = sf.read(output, always_2d=True)
        assert rate == 48000 and np.isfinite(audio).all()
        assert len(audio) / rate > original["duration_seconds"] - 0.01
        peak = float(np.max(np.abs(audio)))
        assert peak < 0.999, f"Clipping: {output}"
        effective = 12 * math.log2(measured["median_hz"] / original["median_hz"])
        # Detect silently ignored state settings or a pitch tracker failure.
        if abs(effective - shift) > 1.5:
            raise ValueError(f"Output pitch does not follow requested shift: {shift:+.1f} requested, {effective:+.1f} measured")
        report["candidates"].append({
            "audio": str(output.resolve()), "preset": str(preset.resolve()),
            "shift_semitones": shift, "output_pitch": measured, "peak": peak,
            "output_gain_db": -6,
            "effective_shift_semitones": effective,
            "target_median_error_semitones": 12 * math.log2(measured["median_hz"] / reference["median_hz"]),
        })
    (args.output_dir / "pitch-match.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Saved pitch candidates and measured results: {args.output_dir}")


if __name__ == "__main__":
    main()
