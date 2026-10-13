"""Windows VST3 host with the same file/pipe protocol as the macOS AU host."""
import argparse
import json
import math
import os
from pathlib import Path
import plistlib
import struct
import subprocess
import sys
import tempfile
import threading
import time
import xml.etree.ElementTree as ET

import numpy as np
import soundfile as sf

from standalone_vocoflex import decode, encode

RATE, BLOCK = 48000, 512


def component(raw):
    if raw[:4] != b'VC2!':
        raise ValueError('Unsupported VST3 state container')
    root = ET.fromstring(raw[8:].rstrip(b'\0'))
    item = root.find('IComponent')
    if item is None or not item.text:
        raise ValueError('Missing VST3 component state')
    data = decode(item.text)
    boundary = data.find(b'\0')
    if boundary < 0:
        boundary = len(data)
    return root, item, json.loads(data[:boundary]), data[boundary:]


def replace_component(raw, settings):
    root, item, _, suffix = component(raw)
    item.text = encode(json.dumps(settings, ensure_ascii=False).encode('utf-8') + suffix)
    xml = ET.tostring(root, encoding='utf-8', xml_declaration=True)
    return b'VC2!' + struct.pack('<I', len(xml)) + xml + b'\0'


def restore(plugin, settings):
    plugin.raw_state = replace_component(plugin.raw_state, settings)
    # Vocoflex schedules state restoration on the Windows message thread.
    # Dispatch messages without opening its editor during file/stream conversion.
    import ctypes
    from ctypes import wintypes
    message = wintypes.MSG()
    user32 = ctypes.windll.user32
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        while user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 1):
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))
        actual = component(plugin.raw_state)[2]
        if actual.get('voice', {}).get('sources') == settings.get('voice', {}).get('sources') and abs(float(actual.get('inputPitchShift', 0)) - float(settings.get('inputPitchShift', 0))) <= .001:
            return
        time.sleep(.02)
    actual = component(plugin.raw_state)[2]
    if actual.get('voice', {}).get('sources') != settings.get('voice', {}).get('sources'):
        raise ValueError('Vocoflex voice state did not restore')
    if abs(float(actual.get('inputPitchShift', 0)) - float(settings.get('inputPitchShift', 0))) > .001:
        raise ValueError('Vocoflex pitch state did not restore')


def load_state(file):
    with open(file, 'rb') as source:
        value = plistlib.load(source)
    return json.loads(value['jucePluginState'])


def save_state(plugin, file):
    value = component(plugin.raw_state)[2]
    if not value.get('voice', {}).get('sources'):
        raise ValueError('먼저 Import에서 참고 음색을 등록해 주세요.')
    path = Path(file)
    temporary = path.with_suffix('.tmp')
    temporary.write_bytes(plistlib.dumps({'jucePluginState': json.dumps(value, ensure_ascii=False).encode('utf-8')}))
    temporary.replace(path)


def registration_controls(signal_path, reference):
    """Own Tcl exclusively from this separate process's main thread."""
    import tkinter as tk
    root = tk.Tk()
    root.title('Hinana Voice · 음색 등록')
    root.attributes('-topmost', True)
    tk.Label(root, text='Vocoflex 창의 Import에서 다음 파일을 가져오세요.\n음색 등록이 끝나면 아래 등록 저장을 누르세요.', padx=20, pady=16).pack()
    entry = tk.Entry(root, width=75)
    entry.insert(0, reference or '')
    entry.configure(state='readonly')
    entry.pack(padx=20)

    def finish(action):
        path = Path(signal_path)
        temporary = path.with_suffix('.tmp')
        temporary.write_text(action, encoding='utf-8')
        temporary.replace(path)
        root.destroy()

    tk.Button(root, text='등록 저장', command=lambda: finish('save'), width=20).pack(pady=16)
    root.protocol('WM_DELETE_WINDOW', lambda: finish('cancel'))
    root.mainloop()


def editor(plugin, args):
    close = threading.Event()
    finished = threading.Event()
    with tempfile.TemporaryDirectory(prefix='hinana_register_') as directory:
        signal = Path(directory) / 'action.txt'
        invocation = [sys.executable]
        if not getattr(sys, 'frozen', False): invocation.append(str(Path(__file__).resolve()))
        controls = subprocess.Popen(
            [*invocation, '--registration-controls', str(signal), '--reference', args.reference or ''],
            env={**os.environ, 'PYINSTALLER_RESET_ENVIRONMENT': '1'},
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )

        def watch():
            # This thread owns no Tk objects; only a process and a text signal.
            while not finished.wait(.05):
                if signal.exists() or controls.poll() is not None:
                    close.set()
                    return

        watcher = threading.Thread(target=watch)
        watcher.start()
        try:
            plugin.show_editor(close)
        finally:
            finished.set()
            watcher.join()
            if controls.poll() is None:
                controls.terminate()
            controls.wait(timeout=10)
        if signal.exists() and signal.read_text(encoding='utf-8') == 'save':
            save_state(plugin, args.save_state)


def render(plugin, args):
    from pedalboard.io import AudioFile
    with AudioFile(args.input) as file:
        with file.resampled_to(RATE) as resampled:
            audio = resampled.read(resampled.frames)
    if audio.shape[0] == 1: audio = np.repeat(audio, 2, axis=0)
    if audio.shape[0] > 2: audio = audio[:2]
    converted = plugin.process(audio, RATE, buffer_size=BLOCK, reset=True)
    if converted.shape[-1] != audio.shape[-1] or not np.isfinite(converted).all():
        raise ValueError('Incomplete or invalid Vocoflex render')
    sf.write(args.output, converted.T * 10 ** (args.output_gain_db / 20), RATE, subtype='PCM_16')


def stream(plugin, output):
    plugin.process(np.zeros((2, BLOCK), dtype=np.float32), RATE, buffer_size=BLOCK, reset=True)
    print(f'LIVE_READY {plugin.reported_latency_samples / RATE}', file=sys.stderr, flush=True)
    pending = np.zeros((2, 0), dtype=np.float32)
    packet = BLOCK * 2 * 4
    while True:
        raw = sys.stdin.buffer.read(packet)
        if not raw: return
        if len(raw) != packet: raise ValueError('Incomplete audio packet')
        audio = np.frombuffer(raw, dtype='<f4').reshape(BLOCK, 2).T.copy()
        converted = plugin.process(audio, RATE, buffer_size=BLOCK, reset=False)
        pending = np.concatenate((pending, converted), axis=1)
        result = np.zeros((2, BLOCK), dtype=np.float32)
        count = min(BLOCK, pending.shape[1])
        result[:, :count] = pending[:, :count]
        pending = pending[:, count:]
        output.write((result.T * .501187).astype('<f4').tobytes())
        output.flush()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--editor', action='store_true')
    parser.add_argument('--reference')
    parser.add_argument('--finish-on-save', action='store_true')
    parser.add_argument('--save-state')
    parser.add_argument('--state')
    parser.add_argument('--input')
    parser.add_argument('--output')
    parser.add_argument('--pitch-semitones', type=float, default=0)
    parser.add_argument('--output-gain-db', type=float, default=-6)
    parser.add_argument('--fast', action='store_true')
    parser.add_argument('--stream', action='store_true')
    parser.add_argument('--inspect', action='store_true')
    parser.add_argument('--registration-controls')
    args = parser.parse_args()
    if args.registration_controls:
        registration_controls(args.registration_controls, args.reference)
        return
    if not math.isfinite(args.pitch_semitones) or abs(args.pitch_semitones) > 12:
        raise ValueError('Invalid pitch shift')
    # Vocoflex writes native diagnostics to stdout; keep binary pipe output separate.
    output = os.fdopen(os.dup(sys.stdout.fileno()), 'wb', buffering=0)
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    import pedalboard
    plugin_path = Path(os.environ.get('CommonProgramFiles', r'C:\Program Files\Common Files')) / 'VST3/Vocoflex.vst3'
    if not plugin_path.exists(): raise FileNotFoundError('Vocoflex VST3를 설치해 주세요: ' + str(plugin_path))
    plugin = pedalboard.load_plugin(str(plugin_path))
    if args.inspect:
        output.write(json.dumps({'name': plugin.name, 'version': plugin.version}).encode('utf-8'))
        return
    if args.editor:
        if not args.save_state: raise ValueError('Missing save path')
        editor(plugin, args)
        return
    if not args.state: raise ValueError('Missing registered voice state')
    settings = load_state(args.state)
    if not settings.get('voice', {}).get('sources'): raise ValueError('No registered voice sources')
    settings['inputPitchShift'] = args.pitch_semitones
    # Captured/WAV input already has its own recording level. Do not inherit
    # a standalone microphone boost, which can clip synthesized speech.
    settings['inputGain'] = 0
    if args.stream: settings['useRealtimeLatency'] = True
    restore(plugin, settings)
    if args.stream: stream(plugin, output)
    elif args.input and args.output: render(plugin, args)
    else: raise ValueError('Select editor, render or stream mode')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr, flush=True)
        sys.exit(1)
