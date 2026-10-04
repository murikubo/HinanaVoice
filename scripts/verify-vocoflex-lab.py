"""Inspect real Vocoflex lab artifacts; these checks do not score speaker identity."""
import json
import plistlib
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1] / "artifacts" / "vocoflex-lab"


def state(name):
    with (ROOT / f"{name}.aupreset").open("rb") as stream:
        return json.loads(plistlib.load(stream)["jucePluginState"])


def audio(name):
    samples, sample_rate = sf.read(ROOT / f"{name}.wav", always_2d=True)
    assert sample_rate == 48000, (name, sample_rate)
    assert np.isfinite(samples).all(), name
    assert np.max(np.abs(samples)) < 0.999, f"Clipping in {name}"
    assert np.sqrt(np.mean(samples ** 2)) > 0.001, f"Silent output: {name}"
    return samples


def envelope_and_spectrum(samples):
    mono = samples.mean(axis=1)
    frames = np.lib.stride_tricks.sliding_window_view(mono, 2048)[::512]
    energy = np.sqrt(np.mean(frames ** 2, axis=1))
    power = np.abs(np.fft.rfft(frames * np.hanning(2048), axis=1)) ** 2
    frequencies = np.fft.rfftfreq(2048, 1 / 48000)
    mel = np.linspace(2595 * np.log10(1 + 80 / 700), 2595 * np.log10(1 + 12000 / 700), 33)
    edges = 700 * (10 ** (mel / 2595) - 1)
    bands = np.stack([
        power[:, (frequencies >= lower) & (frequencies < upper)].mean(axis=1)
        for lower, upper in zip(edges[:-1], edges[1:])
    ], axis=1)
    average = bands[energy > 0.015].mean(axis=0)
    return energy, 10 * np.log10(np.maximum(average / average.sum(), 1e-12))


def compare(first, second):
    assert first.shape == second.shape
    a, x = envelope_and_spectrum(first)
    b, y = envelope_and_spectrum(second)
    return {
        "waveform_rms_difference": float(np.sqrt(np.mean((first - second) ** 2))),
        "energy_envelope_correlation": float(np.corrcoef(a, b)[0, 1]),
        "mean_normalized_band_difference_db": float(np.mean(np.abs(x - y))),
    }


original = audio("voicepeak-input")
original = np.repeat(original, 2, axis=1) if original.shape[1] == 1 else original
converted = audio("hinana-offline")
repeated = audio("hinana-offline-repeat")
reference_state = state("hinana")
restored_state = state("hinana-roundtrip")
assert reference_state["voice"]["sources"], "Reference source is missing"
assert reference_state["voice"]["sources"] == restored_state["voice"]["sources"]
assert len(converted) == len(original), "Latency-compensated output length mismatch"
cursor_checks = {}
for name, expected in [("hinana-candidate-a", (-0.12, -0.08)), ("hinana-candidate-b", (0.12, 0.08))]:
    saved = state(name)["voice"]
    actual = (saved["probeLocationX"], saved["probeLocationY"])
    assert np.allclose(actual, expected, atol=1e-6), (name, actual)
    audio(name)
    cursor_checks[name] = {"requested": expected, "saved": actual}

report = {
    "reference_sources_survive_restore": True,
    "reference_source_count": len(reference_state["voice"]["sources"]),
    "output_frames": len(converted),
    "output_seconds": len(converted) / 48000,
    "finite_non_silent_unclipped_output": True,
    "cursor_state_checks": cursor_checks,
    "original_vs_converted": compare(original, converted),
    "same_state_repeat": compare(converted, repeated),
    "exact_waveform_repeat": bool(np.array_equal(converted, repeated)),
    "roundtrip_cached_transformation_exact": reference_state["voice"]["transformation"] == restored_state["voice"]["transformation"],
    "notes": [
        "Spectral band distance is a diagnostic, not speaker similarity or perceptual quality.",
        "Repeated renders differ. The cause is unverified; sample-exact comparisons cannot rank candidates.",
        "The exported transformation cache changes on restoration; use the immutable reference state as the baseline.",
        "Writing and saving cursor coordinates is verified. Its audible effect is not isolated from repeated-render variation.",
        "These checks cover the original unshifted experiment. F0-centre matching is measured separately in pitch-matched/pitch-match.json.",
        "Speaker identity optimization and perceptual quality validation have not been completed.",
    ],
}
(ROOT / "validation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report, indent=2))
