from __future__ import annotations

import json
import os
from pathlib import Path
from queue import Queue
import sys
import tempfile
from threading import Event, Lock, Thread
from typing import Any

import sounddevice as sd
from openai import OpenAI
import voice_studio
import live_voice
import standalone_vocoflex

from hinana_voice import (
    DEFAULT_MODEL,
    DEFAULT_NARRATOR,
    StreamingSentenceBuffer,
    list_narrators,
    make_voicepeak_wav,
    output_devices,
    playback_candidates,
    play_to_device,
    punctuate_for_speech,
    stream_llm_text,
    translate_to_korean,
)
from platform_support import (
    audio_api_priority,
    is_virtual_output,
    platform_key,
    platform_name,
    resolve_voicepeak_path,
    route_instructions,
    virtual_device_hints,
)


EMIT_LOCK = Lock()


def sanitize_json_value(value: Any) -> Any:
    """surrogateescape로 남은 UTF-8 바이트를 복원하고 나머지는 안전하게 치환합니다."""
    if isinstance(value, str):
        try:
            return value.encode("utf-8", errors="surrogateescape").decode(
                "utf-8", errors="replace"
            )
        except UnicodeEncodeError:
            return "".join(
                "�" if 0xD800 <= ord(character) <= 0xDFFF else character
                for character in value
            )
    if isinstance(value, dict):
        return {
            sanitize_json_value(key): sanitize_json_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [sanitize_json_value(item) for item in value]
    return value


def emit(event: str, **payload: Any) -> None:
    message = sanitize_json_value({"event": event, **payload})
    with EMIT_LOCK:
        print(json.dumps(message, ensure_ascii=False), flush=True)


def probe(command: dict[str, Any]) -> None:
    voicepeak = resolve_voicepeak_path(command.get("voicepeak"))
    narrators: list[str] = []
    voicepeak_error = ""
    if voicepeak.is_file():
        try:
            narrators = list_narrators(voicepeak)
        except Exception as exc:
            voicepeak_error = str(exc)
    else:
        voicepeak_error = f"VOICEPEAK CLI를 찾을 수 없습니다: {voicepeak}"
    host_apis = sd.query_hostapis()
    devices = []
    for index, device in output_devices():
        api = str(host_apis[int(device["hostapi"])]["name"])
        devices.append(
            {
                "id": index,
                "name": str(device["name"]),
                "api": api,
                "channels": int(device["max_output_channels"]),
                "virtual": is_virtual_output(str(device["name"])),
                "default": index == sd.default.device[1],
                "priority": audio_api_priority(api),
            }
        )
    devices.sort(key=lambda item: (not item["virtual"], item["priority"], item["name"]))
    emit(
        "probe",
        platform=platform_key(),
        platformName=platform_name(),
        voicepeak=str(voicepeak),
        voicepeakFound=voicepeak.is_file(),
        voicepeakError=voicepeak_error,
        narrators=narrators,
        devices=devices,
        virtualDeviceHints=list(virtual_device_hints()),
        route=route_instructions(),
    )


def resolve_device(command: dict[str, Any]) -> int:
    requested_name = str(command.get("deviceName") or "").casefold()
    requested_api = str(command.get("deviceApi") or "").casefold()
    requested_id = command.get("device")
    host_apis = sd.query_hostapis()
    devices = output_devices()
    if command.get("voiceProfile"):
        devices = [(index, device) for index, device in devices
                   if not is_virtual_output(str(device["name"]))]
        if not devices:
            raise RuntimeError("실제 오디오 출력 장치를 찾지 못했습니다. 헤드폰이나 스피커를 연결해 주세요.")

    if requested_name:
        matches = [
            (index, device)
            for index, device in devices
            if str(device["name"]).casefold() == requested_name
            and (
                not requested_api
                or str(host_apis[int(device["hostapi"])]["name"]).casefold()
                == requested_api
            )
        ]
        if matches:
            return matches[0][0]

    if requested_id is not None:
        numeric_id = int(requested_id)
        if any(index == numeric_id for index, _ in devices):
            return numeric_id

    if command.get("voiceProfile"):
        default_output = sd.default.device[1]
        return next((index for index, _ in devices if index == default_output), devices[0][0])

    virtual = [
        (index, device)
        for index, device in devices
        if is_virtual_output(str(device["name"]))
    ]
    if virtual:
        virtual.sort(
            key=lambda item: audio_api_priority(
                str(host_apis[int(item[1]["hostapi"])]["name"])
            )
        )
        return virtual[0][0]
    raise RuntimeError(
        "가상 오디오 출력 장치를 찾지 못했습니다. "
        f"권장 이름: {', '.join(virtual_device_hints())}"
    )


def chat(command: dict[str, Any]) -> None:
    api_key = str(command.get("apiKey") or os.getenv("OPENAI_API_KEY", "")).strip()
    if not api_key:
        raise RuntimeError("OpenAI API 키를 설정 화면에 입력하세요.")

    text = str(command.get("text", "")).strip()
    if not text:
        raise RuntimeError("메시지를 입력하세요.")

    voicepeak = resolve_voicepeak_path(command.get("voicepeak"))
    if not voicepeak.is_file():
        raise RuntimeError(f"VOICEPEAK CLI를 찾을 수 없습니다: {voicepeak}")
    narrator = str(command.get("narrator") or DEFAULT_NARRATOR)
    installed_narrators = list_narrators(voicepeak)
    if narrator not in installed_narrators:
        rikka_aliases = ("Koharu Rikka", "小春六花")
        narrator = next(
            (name for name in installed_narrators if name in rikka_aliases),
            installed_narrators[0] if installed_narrators else narrator,
        )
    device = resolve_device(command)
    voice_profile = command.get("voiceProfile")
    if voice_profile:
        device_info = sd.query_devices(device)
        if is_virtual_output(str(device_info["name"])):
            raise RuntimeError("음성 프리셋은 변환을 마친 음성을 재생합니다. 설정에서 실제 헤드폰이나 스피커를 선택해 주세요.")
    speed = int(command.get("speed", 95))
    pitch = int(command.get("pitch", 0))

    synthesis_queue: Queue[tuple[int, str] | None] = Queue()
    playback_queue: Queue[tuple[int, Path] | None] = Queue()
    worker_errors: Queue[BaseException] = Queue()
    stop_event = Event()
    candidates = playback_candidates(device)

    with tempfile.TemporaryDirectory(prefix="hinana_electron_") as temp_dir:
        output_dir = Path(temp_dir)

        def synthesize_worker() -> None:
            try:
                while True:
                    item = synthesis_queue.get()
                    if item is None:
                        break
                    index, sentence = item
                    if stop_event.is_set():
                        break
                    emit("status", message=f"VOICEPEAK 문장 {index} 합성 중…")
                    wav_path = output_dir / f"answer_{index:03d}.wav"
                    make_voicepeak_wav(
                        voicepeak, narrator, sentence, wav_path, speed, pitch
                    )
                    if voice_profile:
                        emit("status", message=f"Vocoflex 문장 {index} 변환 중…")
                        converted = output_dir / f"converted_{index:03d}.wav"
                        voice_studio.convert(wav_path, converted, voice_profile)
                        wav_path = converted
                    playback_queue.put((index, wav_path))
            except BaseException as exc:
                worker_errors.put(exc)
                stop_event.set()
            finally:
                playback_queue.put(None)

        def playback_worker() -> None:
            try:
                while True:
                    item = playback_queue.get()
                    if item is None:
                        break
                    index, wav_path = item
                    message = (
                        "첫 문장이 준비되어 바로 재생 중…"
                        if index == 1
                        else f"문장 {index} 재생 중…"
                    )
                    emit("status", message=message)
                    play_to_device(wav_path, device, candidates)
            except BaseException as exc:
                worker_errors.put(exc)
                stop_event.set()

        synth_thread = Thread(target=synthesize_worker, name="voicepeak-synth")
        play_thread = Thread(target=playback_worker, name="voicepeak-playback")
        translation_thread: Thread | None = None
        synth_thread.start()
        play_thread.start()

        emit("status", message="히나나가 생각하는 중이에요…")
        buffer = StreamingSentenceBuffer()
        raw_answer_parts: list[str] = []
        sentence_index = 0
        stream_error: BaseException | None = None
        try:
            for delta in stream_llm_text(OpenAI(api_key=api_key), DEFAULT_MODEL, text):
                if stop_event.is_set():
                    break
                raw_answer_parts.append(delta)
                emit("answer_delta", delta=delta)
                for sentence in buffer.feed(delta):
                    sentence_index += 1
                    synthesis_queue.put((sentence_index, sentence))

            for sentence in buffer.flush():
                sentence_index += 1
                synthesis_queue.put((sentence_index, sentence))

            answer = punctuate_for_speech("".join(raw_answer_parts))
            if not answer:
                raise RuntimeError("모델이 빈 답변을 반환했습니다.")
            emit("answer_done", text=answer)

            def translation_worker() -> None:
                try:
                    translation = translate_to_korean(
                        OpenAI(api_key=api_key), DEFAULT_MODEL, answer
                    )
                    emit("translation", text=translation)
                except BaseException as exc:
                    emit("translation_error", message=str(exc))

            translation_thread = Thread(
                target=translation_worker,
                name="korean-translation",
            )
            translation_thread.start()
        except BaseException as exc:
            stream_error = exc
            stop_event.set()
        finally:
            synthesis_queue.put(None)

        synth_thread.join()
        play_thread.join()
        if translation_thread is not None:
            translation_thread.join()

        if stream_error is not None:
            raise stream_error
        if not worker_errors.empty():
            raise worker_errors.get()
    emit("done", message="음성 재생을 마쳤어요")


def main() -> int:
    # Electron은 stdin으로 UTF-8 JSON을 전달합니다. PyInstaller의 Windows 콘솔
    # 기본 인코딩에 맡기면 한글 바이트가 surrogateescape 문자로 남을 수 있습니다.
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    try:
        command = sanitize_json_value(json.loads(sys.stdin.readline()))
        action = command.get("action")
        if action == "probe":
            probe(command)
        elif action == "live_devices":
            emit("live_devices", **live_voice.devices())
        elif action == "live_start":
            live_voice.run(command, emit)
        elif action == "standalone_apply":
            emit("standalone_applied", **standalone_vocoflex.apply(command))
        elif action == "voice_analyze":
            emit("voice_analysis", **voice_studio.analyze(command))
        elif action == "voice_target":
            emit("voice_target", reference=voice_studio.pitch_summary(Path(command['referencePath'])))
        elif action == "voice_preview":
            emit("voice_preview", **voice_studio.preview(command))
        elif action == "chat":
            chat(command)
        else:
            raise RuntimeError(f"지원하지 않는 명령입니다: {action}")
        return 0
    except Exception as exc:
        emit("error", message=str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
