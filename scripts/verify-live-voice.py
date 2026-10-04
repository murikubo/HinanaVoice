"""Feed a known WAV at wall-clock speed through the persistent Vocoflex host."""
import json
from pathlib import Path
import subprocess
import time
import numpy as np
import soundfile as sf
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from voice_studio import pitch_summary

x, rate = sf.read(ROOT / 'artifacts/voice-studio-check/bundled-analysis/input.wav', always_2d=True, dtype='float32')
assert rate == 48000
if x.shape[1] == 1:
    x = np.repeat(x, 2, axis=1)
x = np.concatenate([x, np.zeros((48000, 2), dtype='float32')])
x = np.pad(x, ((0, (-len(x)) % 512), (0, 0)))
process = subprocess.Popen([str(ROOT / 'backend-bin/vocoflex-host'), '--state',
    str(ROOT / 'artifacts/vocoflex-lab/hinana.aupreset'), '--pitch-semitones', '8.5', '--stream'],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
try:
    for raw in process.stderr:
        if raw.startswith(b'LIVE_READY '):
            latency = float(raw.split()[1])
            break
    else:
        raise RuntimeError('Native host did not become ready')
    chunks, timings = [], []
    start = time.monotonic()
    for offset in range(0, len(x), 512):
        before = time.monotonic()
        process.stdin.write(x[offset:offset + 512].astype('<f4').tobytes())
        process.stdin.flush()
        raw = process.stdout.read(4096)
        assert len(raw) == 4096
        chunks.append(raw)
        timings.append(time.monotonic() - before)
        time.sleep(max(0, start + (offset + 512) / rate - time.monotonic()))
    process.stdin.close()
    process.wait(timeout=5)
    assert process.returncode == 0
    y = np.frombuffer(b''.join(chunks), dtype='<f4').reshape(-1, 2)
    assert len(y) == len(x) and np.isfinite(y).all() and 0.001 < np.max(abs(y)) <= .981
    directory = ROOT / 'artifacts/live-voice-check'
    directory.mkdir(exist_ok=True)
    sf.write(directory / 'stream.wav', y, rate)
    summary = pitch_summary(directory / 'stream.wav')
    assert abs(12 * np.log2(summary['medianHz'] / 471)) < 1.5, summary
    report = {'audioSeconds': len(x) / rate, 'outputHz': summary['medianHz'],
              'pluginLatencyMs': latency * 1000, 'blockP95ms': float(np.percentile(timings, 95) * 1000),
              'peak': float(np.max(abs(y)))}
    (directory / 'report.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report))
finally:
    if process.poll() is None:
        process.kill()
        process.wait()
