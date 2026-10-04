"""Local, explicitly started microphone/cable -> persistent Vocoflex AU monitor."""
import math
from pathlib import Path
from queue import Queue, Empty, Full
import signal
import subprocess
import tempfile
import threading
import time

import numpy as np
import sounddevice as sd
import soundfile as sf

from platform_support import is_virtual_output
from voice_studio import pitch_summary

RATE = 48000
BLOCK = 512


def devices():
    apis = sd.query_hostapis()
    rows = [{"id": i, "name": d["name"], "api": apis[d["hostapi"]]["name"],
             "inputs": d["max_input_channels"], "outputs": d["max_output_channels"],
             "virtual": is_virtual_output(d["name"]),
             "defaultInput": i == sd.default.device[0], "defaultOutput": i == sd.default.device[1]}
            for i, d in enumerate(sd.query_devices())]
    return {"devices": rows}


def best_shift(target, measured, current=0):
    if not all(math.isfinite(x) and x > 0 for x in (target, measured)):
        raise ValueError("참고 음성 또는 입력 음높이를 분석할 수 없습니다.")
    requested = current + 12 * math.log2(target / measured)
    return round(max(-12, min(12, requested)) * 2) / 2, abs(requested) > 12


def put_latest(queue, value):
    try:
        queue.put_nowait(value)
        return False
    except Full:
        try:
            queue.get_nowait()
        except Empty:
            pass
        try:
            queue.put_nowait(value)
        except Full:
            pass
        return True


def run(command, emit):
    source_id, sink_id = int(command["inputDevice"]), int(command["outputDevice"])
    source, sink = sd.query_devices(source_id), sd.query_devices(sink_id)
    if source["max_input_channels"] < 1 or sink["max_output_channels"] < 1:
        raise ValueError("사용할 입력과 출력을 다시 선택해 주세요.")
    if source_id == sink_id or is_virtual_output(sink["name"]):
        raise ValueError("실시간 변환 출력에는 실제 헤드폰이나 스피커를 선택해 주세요.")
    input_channels, output_channels = min(2, source["max_input_channels"]), min(2, sink["max_output_channels"])
    sd.check_input_settings(device=source_id, channels=input_channels, samplerate=RATE, dtype="float32")
    sd.check_output_settings(device=sink_id, channels=output_channels, samplerate=RATE, dtype="float32")
    target = float(command["targetHz"])
    best_shift(target, target)  # Validate before opening input.
    stop = threading.Event()
    host = None
    incoming, outgoing = Queue(maxsize=24), Queue(maxsize=12)
    counters = {"inputDrops": 0, "outputDrops": 0, "underruns": 0}
    level = [0.0]

    def shutdown(*_):
        stop.set()
        if host and host.poll() is None:
            host.terminate()

    old_handlers = {sig: signal.signal(sig, shutdown) for sig in (signal.SIGTERM, signal.SIGINT)}

    def capture(data, frames, timing, status):
        if stop.is_set():
            raise sd.CallbackStop
        level[0] = float(np.max(np.abs(data)))
        counters["inputDrops"] += int(put_latest(incoming, data.copy())) + int(bool(status))

    def playback(data, frames, timing, status):
        data.fill(0)
        if stop.is_set():
            raise sd.CallbackStop
        try:
            chunk = outgoing.get_nowait()
            data[:] = chunk[:, :output_channels]
        except Empty:
            counters["underruns"] += 1

    try:
        with tempfile.TemporaryDirectory(prefix="hinana_live_") as directory:
            recording = Path(directory) / "calibration.wav"
            captured = []
            count = 0
            last_second = -1
            emit("live_status", phase="calibrating", message="8초 동안 평소 목소리로 말하거나 입력 음성을 재생해 주세요.")
            with sd.InputStream(device=source_id, channels=input_channels, samplerate=RATE,
                                blocksize=BLOCK, dtype="float32", callback=capture):
                while count < RATE * 8 and not stop.is_set():
                    try:
                        chunk = incoming.get(timeout=1)
                    except Empty:
                        raise RuntimeError("입력이 들어오지 않습니다. 입력 장치와 마이크 권한을 확인해 주세요.")
                    captured.append(chunk)
                    count += len(chunk)
                    second = int(count / RATE)
                    if second != last_second:
                        emit("live_level", phase="calibrating", seconds=second, level=level[0])
                        last_second = second
            if stop.is_set():
                return
            sf.write(recording, np.concatenate(captured), RATE)
            measured = pitch_summary(recording)
            shift, clamped = best_shift(target, measured["medianHz"])
            emit("live_status", phase="matching", message="히나나 음색으로 시험 변환하고 음높이를 확인하고 있어요.")
            trial = Path(directory) / "trial.wav"
            host = subprocess.Popen([command["hostPath"], "--state", command["statePath"],
                                     "--pitch-semitones", str(shift), "--input", str(recording),
                                     "--output", str(trial), "--output-gain-db", "-6", "--fast"],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            _, trial_error = host.communicate(timeout=180)
            if stop.is_set():
                return
            if host.returncode:
                raise RuntimeError("시험 변환 실패: " + trial_error.decode("utf-8", errors="replace")[-1000:])
            output_pitch = pitch_summary(trial)["medianHz"]
            corrected, correction_clamped = best_shift(target, output_pitch, shift)
            # Reject octave-tracker failures rather than making a large blind correction.
            if abs(corrected - shift) <= 2:
                shift = corrected
            emit("live_match", shift=shift, targetHz=target, inputHz=measured["medianHz"],
                 trialHz=output_pitch, clamped=clamped or correction_clamped)
            if command.get("calibrationOnly"):
                emit("standalone_calibrated", shift=shift, targetHz=target,
                     inputHz=measured["medianHz"], inputName=source["name"], outputName=sink["name"])
                return
            host = subprocess.Popen([command["hostPath"], "--state", command["statePath"],
                                     "--pitch-semitones", str(shift), "--stream"],
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            errors = []
            worker_errors = []
            ready = threading.Event()
            latency = [0.0]

            def diagnostics():
                for raw in host.stderr:
                    line = raw.decode("utf-8", errors="replace").strip()
                    if line.startswith("LIVE_READY "):
                        latency[0] = float(line.split()[1])
                        ready.set()
                    else:
                        errors.append(line)
                        del errors[:-20]

            threading.Thread(target=diagnostics, daemon=True).start()
            deadline = time.monotonic() + 20
            while not ready.wait(.1):
                if stop.is_set():
                    return
                if host.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("Vocoflex 실시간 준비 실패: " + " ".join(errors))
            while not incoming.empty():
                incoming.get_nowait()

            def process():
                try:
                    while not stop.is_set():
                        try:
                            chunk = incoming.get(timeout=.2)
                        except Empty:
                            continue
                        if input_channels == 1:
                            chunk = np.repeat(chunk, 2, axis=1)
                        host.stdin.write(chunk.astype("<f4").tobytes())
                        host.stdin.flush()
                        raw = host.stdout.read(BLOCK * 2 * 4)
                        if len(raw) != BLOCK * 2 * 4:
                            raise RuntimeError("Vocoflex 실시간 변환이 종료되었습니다.")
                        converted = np.frombuffer(raw, dtype="<f4").reshape(BLOCK, 2)
                        counters["outputDrops"] += int(put_latest(outgoing, converted))
                except Exception as exc:
                    if not stop.is_set():
                        worker_errors.append(str(exc))
                        stop.set()

            worker = threading.Thread(target=process, daemon=True)
            worker.start()
            with sd.OutputStream(device=sink_id, channels=output_channels, samplerate=RATE,
                                 blocksize=BLOCK, dtype="float32", callback=playback) as output_stream, \
                 sd.InputStream(device=source_id, channels=input_channels, samplerate=RATE,
                                blocksize=BLOCK, dtype="float32", callback=capture) as input_stream:
                emit("live_status", phase="running", message="실시간 히나나 변환 중", shift=shift,
                     latencyMs=round((latency[0] + input_stream.latency + output_stream.latency) * 1000))
                while not stop.wait(.5):
                    if host.poll() is not None or not input_stream.active or not output_stream.active:
                        raise RuntimeError("오디오 연결이 끊겼습니다. 장치를 확인하고 다시 시작해 주세요.")
                    emit("live_level", phase="running", level=level[0], **counters)
            if worker_errors:
                raise RuntimeError(worker_errors[-1])
    finally:
        shutdown()
        if host:
            try:
                host.wait(timeout=2)
            except subprocess.TimeoutExpired:
                host.kill()
                host.wait()
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)
        emit("live_stopped")
