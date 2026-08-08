from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from typing import Any, Iterable, Iterator

import sounddevice as sd
import soundfile as sf
from openai import OpenAI

from platform_support import (
    audio_api_priority,
    default_voicepeak_path,
    matching_virtual_hint,
    resolve_voicepeak_path,
    virtual_device_hints,
)

DEFAULT_VOICEPEAK = default_voicepeak_path()
DEFAULT_NARRATOR = "Koharu Rikka"
DEFAULT_CABLE_NAME = virtual_device_hints()[0]
DEFAULT_MODEL = "gpt-5.6-sol"
# CLI의 명시적 최대치는 140자지만, 경계 길이의 연속 합성이 간헐적으로
# WAV를 만들지 않는 환경이 있어 안전 여유를 둡니다.
VOICEPEAK_CHARACTER_LIMIT = 120

SYSTEM_PROMPT = """
あなたは市川雛菜のように、のんびりして明るく、幸せを大切にする
アイドルとして会話してください。

ユーザーのことは「プロデューサー」と呼んでください。
「あは～」「やは～」「へえ～？」などを自然に使ってください。
敬語を使いますが、柔らかくマイペースに話してください。

音声会話用なので、回答は日本語だけにしてください。
読点「、」と句点「。」を自然に使い、文の区切りを明確にしてください。
Markdown、箇条書き、装飾用の記号は使わないでください。
""".strip()


def configure_console() -> None:
    # 리디렉션된 Windows 콘솔에서도 한글/일본어가 깨지지 않게 합니다.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="OpenAI → VOICEPEAK → VB-CABLE 음성 대화"
    )
    parser.add_argument(
        "--voicepeak",
        type=Path,
        default=Path(os.getenv("VOICEPEAK_PATH", DEFAULT_VOICEPEAK)),
        help="VOICEPEAK CLI 경로 (환경변수: VOICEPEAK_PATH)",
    )
    parser.add_argument(
        "--narrator",
        default=os.getenv("VOICEPEAK_NARRATOR", DEFAULT_NARRATOR),
        help="VOICEPEAK 화자 이름 (환경변수: VOICEPEAK_NARRATOR)",
    )
    parser.add_argument(
        "--device",
        default=os.getenv("VB_CABLE_NAME", DEFAULT_CABLE_NAME),
        help="출력 장치 이름 일부 또는 장치 번호 (환경변수: VB_CABLE_NAME)",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("OPENAI_MODEL", DEFAULT_MODEL),
        help="OpenAI 모델 (환경변수: OPENAI_MODEL)",
    )
    parser.add_argument("--speed", type=int, default=95, choices=range(50, 201))
    parser.add_argument("--pitch", type=int, default=0, choices=range(-300, 301))
    parser.add_argument(
        "--list-devices", action="store_true", help="오디오 출력 장치 목록만 표시"
    )
    parser.add_argument(
        "--list-narrators", action="store_true", help="VOICEPEAK 화자 목록만 표시"
    )
    parser.add_argument(
        "--check", action="store_true", help="API 호출 없이 설정 상태만 점검"
    )
    return parser


def run_voicepeak(voicepeak: Path, arguments: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(voicepeak), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def list_narrators(voicepeak: Path) -> list[str]:
    if not voicepeak.is_file():
        raise FileNotFoundError(f"VOICEPEAK를 찾을 수 없습니다: {voicepeak}")

    result = run_voicepeak(voicepeak, ["--list-narrator"])
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"VOICEPEAK 화자 조회 실패: {detail}")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def output_devices() -> list[tuple[int, dict[str, Any]]]:
    return [
        (index, device)
        for index, device in enumerate(sd.query_devices())
        if int(device["max_output_channels"]) > 0
    ]


def print_output_devices() -> None:
    host_apis = sd.query_hostapis()
    for index, device in output_devices():
        api_name = host_apis[int(device["hostapi"])]["name"]
        print(
            f"{index:>2}: {device['name']} "
            f"(출력 {device['max_output_channels']}ch, {api_name})"
        )


def find_output_device(query: str) -> int:
    devices = output_devices()

    if query.isdecimal():
        requested = int(query)
        if any(index == requested for index, _ in devices):
            return requested
        raise RuntimeError(f"{requested}번 장치는 사용할 수 있는 출력 장치가 아닙니다.")

    matches = [
        (index, device)
        for index, device in devices
        if query.casefold() in str(device["name"]).casefold()
    ]
    if not matches:
        raise RuntimeError(
            f"'{query}'이 포함된 출력 장치를 찾지 못했습니다. "
            "--list-devices로 이름이나 번호를 확인하세요."
        )

    host_apis = sd.query_hostapis()
    matches.sort(
        key=lambda item: audio_api_priority(
            str(host_apis[int(item[1]["hostapi"])]["name"])
        )
    )
    index, device = matches[0]
    print(f"[Audio] {index} - {device['name']}")
    return index


def ask_llm(client: OpenAI, model: str, user_text: str) -> str:
    response = client.responses.create(
        model=model,
        instructions=SYSTEM_PROMPT,
        input=user_text,
        reasoning={"effort": "low"},
        text={"verbosity": "medium"},
    )
    answer = punctuate_for_speech(response.output_text)
    if not answer:
        raise RuntimeError("모델이 빈 답변을 반환했습니다.")
    return answer


def stream_llm_text(client: OpenAI, model: str, user_text: str) -> Iterator[str]:
    """Responses API에서 생성되는 텍스트 조각만 순서대로 반환합니다."""
    stream = client.responses.create(
        model=model,
        instructions=SYSTEM_PROMPT,
        input=user_text,
        reasoning={"effort": "low"},
        text={"verbosity": "medium"},
        stream=True,
    )
    try:
        for event in stream:
            event_type = getattr(event, "type", "")
            if event_type == "response.output_text.delta":
                delta = getattr(event, "delta", "")
                if delta:
                    yield delta
            elif event_type == "error":
                error = getattr(event, "error", event)
                message = getattr(error, "message", None) or str(error)
                raise RuntimeError(f"OpenAI 스트리밍 오류: {message}")
            elif event_type == "response.failed":
                response = getattr(event, "response", None)
                error = getattr(response, "error", None)
                message = getattr(error, "message", None) or "응답 생성에 실패했습니다."
                raise RuntimeError(f"OpenAI 스트리밍 오류: {message}")
    finally:
        close = getattr(stream, "close", None)
        if callable(close):
            close()


def make_voicepeak_wav(
    voicepeak: Path,
    narrator: str,
    text: str,
    filename: Path,
    speed: int,
    pitch: int,
) -> None:
    command = [
        "-s",
        text,
        "-o",
        str(filename),
        "-n",
        narrator,
        "--speed",
        str(speed),
        "--pitch",
        str(pitch),
    ]
    results: list[subprocess.CompletedProcess[str]] = []
    for attempt in range(2):
        if filename.exists():
            filename.unlink()
        result = run_voicepeak(voicepeak, command)
        results.append(result)

        # 일부 환경에서는 프로세스 종료 직후 WAV 파일 반영이 늦습니다.
        for _ in range(20):
            if filename.is_file() and filename.stat().st_size > 44:
                return
            time.sleep(0.1)
        if attempt == 0:
            time.sleep(0.5)

    last_result = results[-1]
    detail = (last_result.stderr or last_result.stdout).strip()
    preview = text[:40].replace("\n", " ")
    raise RuntimeError(
        "VOICEPEAK 합성 실패: 출력 WAV가 없습니다. "
        f"(길이={voicepeak_character_count(text)}, 종료코드={last_result.returncode}, "
        f"문장='{preview}{'…' if len(text) > 40 else ''}')"
        f"{' - ' + detail if detail else ''}"
    )


def voicepeak_character_count(text: str) -> int:
    """VOICEPEAK/Windows가 사용하는 UTF-16 코드 단위 기준 길이입니다."""
    return len(text.encode("utf-16-le")) // 2


def punctuate_for_speech(text: str) -> str:
    """구두점 없는 각 출력 줄 끝에 일본어 마침표를 보완합니다."""
    terminal_marks = "。！？!?、，,；;：:"
    lines: list[str] = []
    for raw_line in text.strip().splitlines():
        line = re.sub(r"[ \t　]+", " ", raw_line).strip()
        if not line:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        if line[-1] not in terminal_marks:
            line += "。"
        lines.append(line)
    return "\n".join(lines).strip()


def split_voicepeak_text(
    text: str, limit: int = VOICEPEAK_CHARACTER_LIMIT
) -> list[str]:
    """문장부호를 보존하면서 VOICEPEAK 제한 이하로 텍스트를 나눕니다."""
    normalized = re.sub(r"\s+", " ", punctuate_for_speech(text)).strip()
    if not normalized:
        return []

    def split_long_piece(piece: str) -> list[str]:
        pieces: list[str] = []
        remaining = piece.strip()
        soft_breaks = "、，,；;：: "

        while voicepeak_character_count(remaining) > limit:
            units = 0
            end = 0
            content_limit = limit - 1  # 강제 분할 시 넣을 쉼표 한 글자 확보
            for index, character in enumerate(remaining):
                char_units = voicepeak_character_count(character)
                if units + char_units > content_limit:
                    break
                units += char_units
                end = index + 1

            window = remaining[:end]
            minimum_break = max(1, end // 2)
            break_at = max((window.rfind(mark) + 1 for mark in soft_breaks), default=0)
            if break_at < minimum_break:
                break_at = end

            fragment = remaining[:break_at].strip()
            if fragment and fragment[-1] not in "、，,；;：:。！？!?":
                fragment += "、"
            pieces.append(fragment)
            remaining = remaining[break_at:].strip()

        if remaining:
            pieces.append(remaining)
        return pieces

    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[。！？!?])", normalized)
        if sentence.strip()
    ]
    chunks: list[str] = []
    current = ""

    for sentence in sentences:
        for piece in split_long_piece(sentence):
            combined = f"{current}{piece}" if current else piece
            if voicepeak_character_count(combined) <= limit:
                current = combined
            else:
                if current:
                    chunks.append(current)
                current = piece

    if current:
        chunks.append(current)
    return chunks


class StreamingSentenceBuffer:
    """모델 스트림을 VOICEPEAK에 바로 넘길 수 있는 문장으로 모읍니다."""

    def __init__(self, limit: int = VOICEPEAK_CHARACTER_LIMIT) -> None:
        self.limit = limit
        self._buffer = ""

    def feed(self, delta: str) -> list[str]:
        self._buffer += delta
        ready: list[str] = []

        while self._buffer:
            terminal = re.search(r"[。！？!?]+", self._buffer)
            if terminal:
                end = terminal.end()
                piece = self._buffer[:end]
                self._buffer = self._buffer[end:]
                ready.extend(split_voicepeak_text(piece, self.limit))
                continue

            if voicepeak_character_count(self._buffer) < self.limit:
                break

            piece, self._buffer = self._take_safe_prefix(self._buffer)
            ready.extend(split_voicepeak_text(piece, self.limit))

        return [piece for piece in ready if any(char.isalnum() for char in piece)]

    def flush(self) -> list[str]:
        remaining = self._buffer
        self._buffer = ""
        return [
            piece
            for piece in split_voicepeak_text(remaining, self.limit)
            if any(char.isalnum() for char in piece)
        ]

    def _take_safe_prefix(self, text: str) -> tuple[str, str]:
        units = 0
        end = 0
        content_limit = self.limit - 1
        for index, character in enumerate(text):
            char_units = voicepeak_character_count(character)
            if units + char_units > content_limit:
                break
            units += char_units
            end = index + 1

        window = text[:end]
        minimum_break = max(1, end // 2)
        break_at = max(
            (window.rfind(mark) + 1 for mark in "、，,；;：: \n"),
            default=0,
        )
        if break_at < minimum_break:
            break_at = end

        piece = text[:break_at].strip()
        if piece and piece[-1] not in "、，,；;：:。！？!?":
            piece += "、"
        return piece, text[break_at:].lstrip()


def make_voicepeak_wavs(
    voicepeak: Path,
    narrator: str,
    text: str,
    output_dir: Path,
    speed: int,
    pitch: int,
) -> list[Path]:
    chunks = split_voicepeak_text(text)
    if not chunks:
        raise RuntimeError("합성할 문장이 없습니다.")

    wav_paths: list[Path] = []
    for index, chunk in enumerate(chunks, start=1):
        if not any(character.isalnum() for character in chunk):
            continue
        wav_path = output_dir / f"answer_{index:03d}.wav"
        try:
            make_voicepeak_wav(
                voicepeak, narrator, chunk, wav_path, speed, pitch
            )
        except RuntimeError as exc:
            raise RuntimeError(
                f"음성 조각 {index}/{len(chunks)} 처리 중 오류: {exc}"
            ) from exc
        wav_paths.append(wav_path)
    if not wav_paths:
        raise RuntimeError("발음할 수 있는 문장이 없습니다.")
    return wav_paths


def playback_candidates(device: int) -> list[int]:
    """선택한 가상 케이블의 다른 호스트 API 장치를 반환합니다."""
    selected = sd.query_devices(device)
    selected_name = str(selected["name"])
    candidates = [device]
    family = matching_virtual_hint(selected_name)
    if not family:
        return candidates

    host_apis = sd.query_hostapis()
    alternatives = [
        (index, item)
        for index, item in output_devices()
        if family.casefold() in str(item["name"]).casefold()
        and index != device
    ]
    alternatives.sort(
        key=lambda item: audio_api_priority(
            str(host_apis[int(item[1]["hostapi"])]["name"])
        )
    )
    candidates.extend(index for index, _ in alternatives)
    return candidates


def play_to_device(
    filename: Path, device: int, fallback_devices: Iterable[int] = ()
) -> int:
    audio, sample_rate = sf.read(filename, dtype="float32", always_2d=False)
    candidates = list(dict.fromkeys([device, *fallback_devices]))
    failures: list[str] = []

    for candidate in candidates:
        try:
            sd.play(audio, sample_rate, device=candidate)
            sd.wait()
            return candidate
        except sd.PortAudioError as exc:
            sd.stop()
            device_name = sd.query_devices(candidate)["name"]
            failures.append(f"{candidate} ({device_name}): {exc}")

    detail = "\n".join(failures)
    raise RuntimeError(f"사용 가능한 VB-CABLE 재생 장치가 없습니다.\n{detail}")


def check_configuration(args: argparse.Namespace) -> bool:
    ok = True
    voicepeak = resolve_voicepeak_path(args.voicepeak)
    print(f"VOICEPEAK: {voicepeak}")
    if not voicepeak.is_file():
        print("  [실패] 실행 파일을 찾지 못했습니다.")
        ok = False
    else:
        narrators = list_narrators(voicepeak)
        print(f"  화자: {', '.join(narrators)}")
        if args.narrator not in narrators:
            print(f"  [실패] 선택한 화자 '{args.narrator}'가 설치되어 있지 않습니다.")
            ok = False
        else:
            print(f"  [정상] 선택 화자: {args.narrator}")

    try:
        device = find_output_device(str(args.device))
        print(f"  [정상] 출력 장치 번호: {device}")
    except RuntimeError as exc:
        print(f"  [실패] {exc}")
        ok = False

    if os.getenv("OPENAI_API_KEY"):
        print("OpenAI API 키: [정상] 환경변수에 설정됨")
    else:
        print("OpenAI API 키: [실패] OPENAI_API_KEY가 설정되지 않음")
        ok = False

    print(f"OpenAI 모델: {args.model}")
    return ok


def run_chat(args: argparse.Namespace) -> None:
    voicepeak = resolve_voicepeak_path(args.voicepeak)
    if not voicepeak.is_file():
        raise FileNotFoundError(f"VOICEPEAK를 찾을 수 없습니다: {voicepeak}")

    narrators = list_narrators(voicepeak)
    if args.narrator not in narrators:
        raise RuntimeError(
            f"화자 '{args.narrator}'가 없습니다. 사용 가능: {', '.join(narrators)}"
        )
    cable = find_output_device(str(args.device))

    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY 환경변수를 먼저 설정하세요.")
    client = OpenAI()

    print("=== LLM → VOICEPEAK → Vocoflex ===")
    print(f"모델: {args.model} | 화자: {args.narrator}")
    print("끝내려면 /quit")

    while True:
        try:
            user_text = input("\n프로듀서> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n종료합니다.")
            break

        if not user_text:
            continue
        if user_text.casefold() == "/quit":
            break

        try:
            print("히나나 생각중...")
            answer = ask_llm(client, args.model, user_text)
            print(f"히나나> {answer}")

            with tempfile.TemporaryDirectory(prefix="hinana_voice_") as temp_dir:
                wav_paths = make_voicepeak_wavs(
                    voicepeak,
                    args.narrator,
                    answer,
                    Path(temp_dir),
                    args.speed,
                    args.pitch,
                )
                for wav_path in wav_paths:
                    play_to_device(wav_path, cable, playback_candidates(cable))
        except Exception as exc:
            print(f"[오류] {exc}", file=sys.stderr)


def main() -> int:
    configure_console()
    args = build_parser().parse_args()

    if args.list_devices:
        print_output_devices()
        return 0
    if args.list_narrators:
        for narrator in list_narrators(args.voicepeak):
            print(narrator)
        return 0
    if args.check:
        return 0 if check_configuration(args) else 1

    run_chat(args)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[오류] {exc}", file=sys.stderr)
        raise SystemExit(1)
