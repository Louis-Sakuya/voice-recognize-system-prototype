"""云端回包映射与语音开关条件。不连接真实云。"""

from __future__ import annotations

import gzip
import json
import unittest
from dataclasses import replace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import Settings, describe_voice, get_settings
from app.voice.adapters import volc_auth_headers
from app.main import app
from app.voice.events import TranscriptEvent
from app.voice.protocol import (
    build_volc_client_frame,
    humanize_cloud_error,
    map_aliyun_message,
    map_volc_result,
    parse_volc_frame,
)


def _settings(**overrides: object) -> Settings:
    current = get_settings()
    return replace(current, **overrides)


def _server_frame(body: dict, *, flags: int = 0b0001, sequence: int = 1) -> bytes:
    payload = gzip.compress(json.dumps(body).encode("utf-8"))
    header = bytes(
        [
            0x11,
            (0b1001 << 4) | flags,
            0x11,
            0x00,
        ]
    )
    sequence_bytes = sequence.to_bytes(4, "big", signed=True) if flags & 0b0001 else b""
    return header + sequence_bytes + len(payload).to_bytes(4, "big") + payload


class ProtocolTests(unittest.TestCase):
    def test_aliyun_sentence_end_maps_partial_and_final(self) -> None:
        partial = map_aliyun_message(
            {
                "header": {"event": "result-generated"},
                "payload": {"output": {"sentence": {"text": "帮我查询", "sentence_end": False}}},
            }
        )
        final = map_aliyun_message(
            {
                "header": {"event": "result-generated"},
                "payload": {"output": {"sentence": {"text": "帮我查询上海天气", "sentence_end": True}}},
            }
        )
        self.assertEqual(partial["events"], [TranscriptEvent("partial", "帮我查询")])
        self.assertEqual(final["events"], [TranscriptEvent("final", "帮我查询上海天气")])

    def test_aliyun_skips_heartbeat(self) -> None:
        mapped = map_aliyun_message(
            {
                "header": {"event": "result-generated"},
                "payload": {"output": {"sentence": {"heartbeat": True, "text": "忽略"}}},
            }
        )
        self.assertEqual(mapped["events"], [])

    def test_volc_definite_maps_final_and_open_utterance_maps_partial(self) -> None:
        events = map_volc_result(
            {
                "result": {
                    "text": "累计文本",
                    "utterances": [
                        {"definite": True, "text": "这是字节跳动，"},
                        {"definite": False, "text": "今日"},
                    ],
                }
            },
            is_last=False,
        )
        self.assertEqual(
            events,
            [
                TranscriptEvent("final", "这是字节跳动，"),
                TranscriptEvent("partial", "今日"),
            ],
        )

    def test_volc_without_utterances_uses_last_packet_as_final(self) -> None:
        self.assertEqual(
            map_volc_result({"result": {"text": "你好"}}, is_last=False),
            [TranscriptEvent("partial", "你好")],
        )
        self.assertEqual(
            map_volc_result({"result": {"text": "你好"}}, is_last=True),
            [TranscriptEvent("final", "你好")],
        )

    def test_parse_volc_frame_with_sequence(self) -> None:
        body = {"result": {"utterances": [{"definite": True, "text": "定稿"}]}}
        frame = parse_volc_frame(_server_frame(body, flags=0b0011, sequence=-3))
        self.assertTrue(frame["is_last"])
        self.assertEqual(frame["sequence"], -3)
        self.assertEqual(
            map_volc_result(frame["body"], is_last=frame["is_last"]),
            [TranscriptEvent("final", "定稿")],
        )

    def test_client_frame_is_gzip_without_sequence(self) -> None:
        frame = build_volc_client_frame(0b0001, b'{"model_name":"bigmodel"}', json_payload=True)
        self.assertEqual(frame[0], 0x11)
        self.assertEqual(frame[1] >> 4, 0b0001)
        self.assertEqual(frame[1] & 0x0F, 0)
        size = int.from_bytes(frame[4:8], "big")
        self.assertEqual(gzip.decompress(frame[8 : 8 + size]), b'{"model_name":"bigmodel"}')

    def test_voice_report_requires_provider_and_keys(self) -> None:
        missing = describe_voice(_settings(asr_provider=""))
        self.assertFalse(missing["ready"])
        self.assertIn("ASR_PROVIDER", str(missing["reason"]))

        aliyun = describe_voice(
            _settings(
                asr_provider="aliyun",
                dashscope_api_key="",
                aliyun_workspace_id="",
                aliyun_asr_model="paraformer-realtime-v2",
            )
        )
        self.assertFalse(aliyun["ready"])
        self.assertIn("DASHSCOPE_API_KEY", str(aliyun["reason"]))

        ready = describe_voice(
            _settings(
                asr_provider="volcengine",
                volc_api_key="api-key",
            )
        )
        self.assertTrue(ready["ready"])
        missing_volc = describe_voice(_settings(asr_provider="volcengine", volc_api_key=""))
        self.assertFalse(missing_volc["ready"])
        self.assertIn("VOLC_API_KEY", str(missing_volc["reason"]))
        self.assertEqual(ready["model"], "bigmodel")
        headers = volc_auth_headers(_settings(volc_api_key="new-key", volc_resource_id="volc.seedasr.sauc.duration"), "req-1")
        self.assertEqual(headers["X-Api-Key"], "new-key")
        self.assertNotIn("X-Api-App-Key", headers)
        self.assertNotIn("X-Api-Access-Key", headers)

    def test_proxy_error_is_explicit(self) -> None:
        text = humanize_cloud_error(OSError("Failed to connect to 127.0.0.1 port 7890"))
        self.assertIn("127.0.0.1", text)


class GatewayTests(unittest.TestCase):
    def test_legacy_routes_are_not_mounted_and_missing_keys_disable_button_state(self) -> None:
        settings = _settings(asr_provider="aliyun", dashscope_api_key="", aliyun_workspace_id="")
        with patch("app.routers.voice.get_settings", return_value=settings):
            client = TestClient(app)
            health = client.get("/api/v1/voice/health")
            self.assertEqual(health.status_code, 200)
            body = health.json()
            self.assertFalse(body["ready"])
            self.assertIn("DASHSCOPE_API_KEY", body["reason"])
            self.assertEqual(client.get("/api/v1/asr/health").status_code, 404)
            self.assertEqual(client.get("/api/v1/tts/health").status_code, 404)

    def test_stream_relays_partial_and_final_without_cloud(self) -> None:
        settings = _settings(
            asr_provider="aliyun",
            dashscope_api_key="test-key",
            aliyun_workspace_id="workspace",
            aliyun_asr_model="paraformer-realtime-v2",
        )

        class FakeAdapter:
            def __init__(self) -> None:
                self.audio: list[bytes] = []
                self.finished = False
                self.closed = False

            async def connect(self) -> None:
                return None

            async def send_audio(self, pcm: bytes) -> None:
                self.audio.append(pcm)

            async def finish(self) -> None:
                self.finished = True

            async def close(self) -> None:
                self.closed = True

            async def interrupt(self) -> None:
                return None

            async def receive_text(self):
                yield TranscriptEvent("partial", "帮我")
                yield TranscriptEvent("final", "帮我查询")

        fake = FakeAdapter()
        with (
            patch("app.routers.voice.get_settings", return_value=settings),
            patch("app.routers.voice.create_adapter", return_value=fake),
        ):
            client = TestClient(app)
            with client.websocket_connect("/api/v1/voice/stream") as ws:
                ws.send_text(json.dumps({"type": "start"}))
                self.assertEqual(ws.receive_json()["type"], "ready")
                self.assertEqual(ws.receive_json(), {"type": "partial", "text": "帮我"})
                self.assertEqual(ws.receive_json(), {"type": "final", "text": "帮我查询"})
                ws.send_bytes(b"\x01\x02")
                ws.send_text(json.dumps({"type": "stop"}))
        self.assertEqual(fake.audio, [b"\x01\x02"])
        self.assertTrue(fake.finished)
        self.assertTrue(fake.closed)


if __name__ == "__main__":
    unittest.main()
