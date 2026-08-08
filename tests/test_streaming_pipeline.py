from types import SimpleNamespace
from io import BytesIO, TextIOWrapper
import json
from pathlib import Path
import tempfile
from threading import Event
import unittest
from unittest.mock import patch

from hinana_voice import (
    StreamingSentenceBuffer,
    stream_llm_text,
    translate_to_korean,
    voicepeak_character_count,
)


class FakeResponses:
    def __init__(self, events):
        self.events = events
        self.arguments = None

    def create(self, **kwargs):
        self.arguments = kwargs
        return iter(self.events)


class FakeClient:
    def __init__(self, events):
        self.responses = FakeResponses(events)


class StreamingPipelineTests(unittest.TestCase):
    def test_emit_replaces_unpaired_surrogates_before_utf8_output(self):
        import hinana_bridge

        raw = BytesIO()
        output = TextIOWrapper(raw, encoding="utf-8", errors="strict")
        with patch.object(hinana_bridge.sys, "stdout", output):
            hinana_bridge.emit("probe", name="장치\udced이름")
            output.flush()

        decoded = raw.getvalue().decode("utf-8")
        payload = json.loads(decoded)
        self.assertEqual(payload["event"], "probe")
        self.assertNotIn("\udced", payload["name"])

    def test_sanitizer_recovers_utf8_bytes_read_with_surrogateescape(self):
        import hinana_bridge

        original = "KAL801편 사고에 대해 알려줄래?"
        surrogate_text = original.encode("utf-8").decode(
            "ascii", errors="surrogateescape"
        )

        self.assertEqual(hinana_bridge.sanitize_json_value(surrogate_text), original)

    def test_stream_llm_text_yields_only_output_text_deltas(self):
        client = FakeClient(
            [
                SimpleNamespace(type="response.created"),
                SimpleNamespace(type="response.output_text.delta", delta="あは～、"),
                SimpleNamespace(type="response.output_text.delta", delta="こんにちは。"),
                SimpleNamespace(type="response.completed"),
            ]
        )

        self.assertEqual(
            list(stream_llm_text(client, "gpt-5.6-sol", "안녕")),
            ["あは～、", "こんにちは。"],
        )
        self.assertIs(client.responses.arguments["stream"], True)
        self.assertEqual(client.responses.arguments["model"], "gpt-5.6-sol")

    def test_translate_to_korean_uses_same_model_and_returns_text(self):
        client = FakeClient([])
        client.responses.create = lambda **kwargs: SimpleNamespace(
            output_text="야하~ 프로듀서, 반가워요!"
        )

        self.assertEqual(
            translate_to_korean(client, "gpt-5.6-sol", "やは～、プロデューサー。"),
            "야하~ 프로듀서, 반가워요!",
        )

    def test_sentence_buffer_releases_complete_sentences_immediately(self):
        buffer = StreamingSentenceBuffer()

        self.assertEqual(buffer.feed("あは～、こんにちは"), [])
        self.assertEqual(buffer.feed("。次の文です"), ["あは～、こんにちは。"])
        self.assertEqual(buffer.feed("！"), ["次の文です！"])
        self.assertEqual(buffer.flush(), [])

    def test_sentence_buffer_forces_safe_chunks_without_punctuation(self):
        buffer = StreamingSentenceBuffer(limit=20)
        chunks = buffer.feed("これは句読点がない長い文章です" * 4)
        chunks.extend(buffer.flush())

        self.assertGreater(len(chunks), 1)
        self.assertTrue(
            all(voicepeak_character_count(chunk) <= 20 for chunk in chunks)
        )
        self.assertTrue(all(chunk[-1] in "、。！？!?" for chunk in chunks))

    def test_sentence_buffer_flush_adds_terminal_punctuation(self):
        buffer = StreamingSentenceBuffer()
        buffer.feed("最後の短い文")

        self.assertEqual(buffer.flush(), ["最後の短い文。"])

    def test_bridge_overlaps_next_synthesis_with_current_playback(self):
        import hinana_bridge

        timeline = []
        first_playback_started = Event()
        emitted = []

        def fake_make_wav(_voicepeak, _narrator, sentence, filename, _speed, _pitch):
            index = int(filename.stem.rsplit("_", 1)[-1])
            timeline.append(f"synth-{index}-start")
            if index == 2:
                self.assertTrue(first_playback_started.wait(1.0))
            timeline.append(f"synth-{index}-done")

        def fake_play(filename, _device, _candidates):
            index = int(filename.stem.rsplit("_", 1)[-1])
            timeline.append(f"play-{index}-start")
            if index == 1:
                first_playback_started.set()
            timeline.append(f"play-{index}-done")
            return 1

        with tempfile.TemporaryDirectory() as temp_dir:
            voicepeak = Path(temp_dir) / "voicepeak"
            voicepeak.touch()
            with (
                patch.object(hinana_bridge, "resolve_voicepeak_path", return_value=voicepeak),
                patch.object(hinana_bridge, "list_narrators", return_value=["Koharu Rikka"]),
                patch.object(hinana_bridge, "resolve_device", return_value=1),
                patch.object(hinana_bridge, "playback_candidates", return_value=[1]),
                patch.object(hinana_bridge, "OpenAI", return_value=object()),
                patch.object(
                    hinana_bridge,
                    "stream_llm_text",
                    return_value=iter(["一番目です。", "二番目です。"]),
                ),
                patch.object(
                    hinana_bridge,
                    "translate_to_korean",
                    return_value="첫 번째예요. 두 번째예요.",
                ),
                patch.object(hinana_bridge, "make_voicepeak_wav", side_effect=fake_make_wav),
                patch.object(hinana_bridge, "play_to_device", side_effect=fake_play),
                patch.object(
                    hinana_bridge,
                    "emit",
                    side_effect=lambda event, **payload: emitted.append((event, payload)),
                ),
            ):
                hinana_bridge.chat(
                    {
                        "apiKey": "test",
                        "text": "테스트",
                        "voicepeak": str(voicepeak),
                        "narrator": "Koharu Rikka",
                        "device": 1,
                    }
                )

        self.assertLess(
            timeline.index("play-1-start"), timeline.index("synth-2-done")
        )
        self.assertEqual(
            [payload["delta"] for event, payload in emitted if event == "answer_delta"],
            ["一番目です。", "二番目です。"],
        )
        self.assertEqual(emitted[-1][0], "done")
        self.assertEqual(
            [payload["text"] for event, payload in emitted if event == "translation"],
            ["첫 번째예요. 두 번째예요."],
        )


if __name__ == "__main__":
    unittest.main()
