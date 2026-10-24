from __future__ import annotations

import hashlib
import json
import math
import os
import socket
import struct
import sys
import threading
import time
import unittest
import shutil
import tempfile
import types
from unittest import mock
from http.server import ThreadingHTTPServer
from pathlib import Path

from services.tts.config import load_config
from services.tts.lifecycle import (
    ModelLifecycle,
    PermanentModelError,
    SynthesisContext,
    TTSFailure,
    _file_metadata,
    _file_sha256,
    language_instruction,
    mode_timesteps,
    vox_model_factory,
)
from services.tts.audio import InvalidAudio, compose_wav, pcm16_frames
from services.tts.audio_processing import AudioProcessingError, process_gently
from services.tts.ssml import (
    SSMLValidationError,
    SilenceSegment,
    SpeechSegment,
    parse_ssml,
)
from services.tts.server import handler


ROOT = Path(__file__).resolve().parents[3]


def test_config():
    return load_config(ROOT / "configs/tts.yaml")


def fake_model_factory(_context=None):
    return object()


class ConfigTests(unittest.TestCase):
    def test_strict_config(self):
        source = (ROOT / "configs/tts.yaml").read_text()
        for name, content in {
            "valid": source,
            "unknown": source + "unexpected: true\n",
            "bad_digest": source.replace(
                "04d6e05b69b22568030ac21f494e406ffdf2d06efeeab43cfdb4c21ba8c9bd41",
                "x" * 64,
            ),
            "negative_idle": source.replace(
                "idle_unload_seconds: 60", "idle_unload_seconds: -1"
            ),
            "bad_processing_timeout": source.replace(
                "audio_processing_timeout_seconds: 30",
                "audio_processing_timeout_seconds: 61",
            ),
            "too_many_segments": source.replace(
                "max_ssml_segments: 64", "max_ssml_segments: 0"
            ),
        }.items():
            with self.subTest(name=name):
                import tempfile

                with tempfile.TemporaryDirectory() as temp:
                    config_path = Path(temp) / "tts.yaml"
                    config_path.write_text(content)
                    if name == "valid":
                        self.assertEqual(load_config(config_path)["listen_port"], 8082)
                    else:
                        with self.assertRaises(ValueError):
                            load_config(config_path)


class ModeAndLanguageTests(unittest.TestCase):
    def test_mode_selection(self):
        self.assertEqual(
            [
                mode_timesteps(mode)
                for mode in (
                    "quality",
                    "fast",
                    "auto",
                    "high_quality",
                    "extra_high_quality",
                )
            ],
            [10, 8, 10, 16, 32],
        )
        with self.assertRaises(TTSFailure):
            mode_timesteps("turbo")

    def test_language_is_a_hint_and_auto_preserves_text(self):
        text = "Hello, мир."
        hints = {
            "en": "Speak in English.",
            "ru": "Speak in Russian.",
            "sv": "Speak in Swedish.",
        }
        self.assertEqual(language_instruction(text, "auto", hints), text)
        self.assertEqual(
            language_instruction(text, "ru", hints), "(Speak in Russian.)Hello, мир."
        )


def ssml_config(**overrides):
    config = test_config()
    config.update(overrides)
    return config


class SSMLParserTests(unittest.TestCase):
    def test_ordered_languages_breaks_and_consecutive_breaks(self):
        document = (
            '<speak xmlns="http://www.w3.org/2001/10/synthesis" version="1.1" '
            'xml:lang="en-US">hello <break time="250ms"/>'
            '<break time="0.5s"/><lang xml:lang="sv-SE">hej '
            '<lang xml:lang="ru-RU">мир</lang> igen</lang></speak>'
        )
        self.assertEqual(
            parse_ssml(document, ssml_config()),
            [
                SpeechSegment("hello ", "en"),
                SilenceSegment(250),
                SilenceSegment(500),
                SpeechSegment("hej ", "sv"),
                SpeechSegment("мир", "ru"),
                SpeechSegment(" igen", "sv"),
            ],
        )

    def test_ignores_formatting_whitespace_but_preserves_inline_space(self):
        document = """<speak xmlns="http://www.w3.org/2001/10/synthesis" version="1.1" xml:lang="en">
  hello <lang xml:lang="sv">hej</lang> there
</speak>"""
        self.assertEqual(
            parse_ssml(document, ssml_config()),
            [
                SpeechSegment("hello ", "en"),
                SpeechSegment("hej", "sv"),
                SpeechSegment(" there", "en"),
            ],
        )

    def test_rejects_malformed_unsupported_and_unsafe_markup(self):
        prefix = '<speak xmlns="http://www.w3.org/2001/10/synthesis" version="1.1" xml:lang="en">'
        cases = (
            "<speak",
            prefix + "hello</wrong>",
            '<speak xmlns="urn:wrong" version="1.1" xml:lang="en">hello</speak>',
            '<speak xmlns="http://www.w3.org/2001/10/synthesis" version="1.1">hello</speak>',
            prefix.replace('xml:lang="en"', 'xml:lang="en" extra="x"')
            + "hello</speak>",
            prefix.replace('version="1.1"', 'version="1.0"') + "hello</speak>",
            prefix + '<prosody rate="slow">hello</prosody></speak>',
            prefix + '<break strength="weak"/></speak>',
            prefix + '<lang xml:lang="de">hello</lang></speak>',
            prefix + '<break time="1.0001s"/></speak>',
            '<!DOCTYPE speak [<!ENTITY x "hello">]>' + prefix + "&x;</speak>",
            '<!DOCTYPE speak SYSTEM "file:///etc/passwd">' + prefix + "hello</speak>",
        )
        for document in cases:
            with (
                self.subTest(document=document[:80]),
                self.assertRaises(SSMLValidationError),
            ):
                parse_ssml(document, ssml_config())

    def test_rejects_each_configured_limit_and_no_speech(self):
        def document(body):
            return (
                '<speak xmlns="http://www.w3.org/2001/10/synthesis" version="1.1" xml:lang="en">'
                + body
                + "</speak>"
            )

        checks = (
            (document("hello"), {"max_ssml_bytes": 10}),
            (document("hello"), {"max_text_characters": 4}),
            (
                document('<lang xml:lang="sv">a</lang><lang xml:lang="ru">b</lang>'),
                {"max_ssml_segments": 1},
            ),
            (
                document('<break time="0ms"/><break time="0ms"/>hello'),
                {"max_ssml_elements": 2},
            ),
            (
                document('<lang xml:lang="sv"><lang xml:lang="ru">hello</lang></lang>'),
                {"max_ssml_nesting_depth": 1},
            ),
            (document('<break time="1001ms"/>hello'), {"max_ssml_break_ms": 1000}),
            (
                document('<break time="600ms"/><break time="600ms"/>hello'),
                {"max_ssml_total_silence_ms": 1000},
            ),
            (
                document("hello"),
                {
                    "max_output_audio_bytes": 1024,
                    "ssml_estimated_characters_per_second": 0.01,
                },
            ),
        )
        for source, overrides in checks:
            with (
                self.subTest(overrides=overrides),
                self.assertRaises(SSMLValidationError),
            ):
                parse_ssml(source, ssml_config(**overrides))
        with self.assertRaises(SSMLValidationError):
            parse_ssml(document(" \n  "), ssml_config())


def wav_segment(frames: bytes) -> bytes:
    import io
    import wave

    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(48000)
        wav.writeframes(frames)
    return output.getvalue()


def tone_with_silence_wav() -> tuple[bytes, int, int]:
    import io
    import wave

    rate = 48000
    tone_frames = rate
    silence_frames = rate // 2
    values = bytearray()
    for i in range(tone_frames):
        value = int(0.2 * 32767 * math.sin(2 * math.pi * 440 * i / rate))
        values.extend(struct.pack("<h", value))
    silence_start = len(values) // 2
    values.extend(b"\x00\x00" * silence_frames)
    for i in range(tone_frames):
        value = int(0.2 * 32767 * math.sin(2 * math.pi * 660 * i / rate))
        values.extend(struct.pack("<h", value))
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(bytes(values))
    return output.getvalue(), silence_start, silence_frames


class AudioProcessingTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg is not installed")
    def test_gentle_master_preserves_wav_duration_and_digital_silence(self):
        payload, silence_start, silence_frames = tone_with_silence_wav()
        config = test_config()
        with tempfile.TemporaryDirectory() as temp:
            with mock.patch("services.tts.audio_processing.tempfile.tempdir", temp):
                result = process_gently(payload, config)
            self.assertEqual(list(Path(temp).iterdir()), [])
        frames = pcm16_frames(result)
        self.assertLessEqual(abs(len(frames) - len(pcm16_frames(payload))), 480)
        silence = frames[silence_start * 2 : (silence_start + silence_frames) * 2]
        self.assertEqual(len(silence), silence_frames * 2)
        self.assertFalse(any(silence))
        self.assertGreater(max(abs(v[0]) for v in struct.iter_unpack("<h", frames)), 0)

    def test_silence_and_near_silence_are_not_boosted(self):
        silent = wav_segment(b"\x00\x00" * 480)
        quiet = wav_segment(b"\x01\x00" * 480)
        config = test_config()
        self.assertEqual(process_gently(silent, config), silent)
        self.assertEqual(process_gently(quiet, config), quiet)
        config["max_output_audio_bytes"] = len(silent) - 1
        with self.assertRaises(AudioProcessingError) as caught:
            process_gently(silent, config)
        self.assertEqual(caught.exception.code, "output_too_large")

    def test_processing_errors_are_sanitized_and_timeout_is_bounded(self):
        payload, _start, _length = tone_with_silence_wav()
        config = test_config()
        with tempfile.TemporaryDirectory() as directory:
            failing = Path(directory) / "ffmpeg-fails"
            failing.write_text(
                f"#!{__import__('sys').executable}\n"
                "import sys\nsys.stderr.write('private synthetic detail')\nsys.exit(7)\n"
            )
            failing.chmod(0o700)
            with mock.patch(
                "services.tts.audio_processing.shutil.which", return_value=str(failing)
            ):
                with self.assertRaises(AudioProcessingError) as caught:
                    process_gently(payload, config)
            self.assertEqual(caught.exception.code, "audio_processing_failed")
            self.assertNotIn("private", caught.exception.message)

            slow = Path(directory) / "ffmpeg-sleeps"
            slow.write_text(
                f"#!{__import__('sys').executable}\nimport time\ntime.sleep(3)\n"
            )
            slow.chmod(0o700)
            config["audio_processing_timeout_seconds"] = 1
            started = time.monotonic()
            with mock.patch(
                "services.tts.audio_processing.shutil.which", return_value=str(slow)
            ):
                with self.assertRaises(AudioProcessingError) as caught:
                    process_gently(payload, config)
            self.assertEqual(caught.exception.code, "audio_processing_timeout")
            self.assertLess(time.monotonic() - started, 2.5)


class AudioCompositionTests(unittest.TestCase):
    def test_composes_exact_silence_and_one_mono_pcm16_48khz_wav(self):
        first = b"\x01\x00" * 100
        silence = b"\x00\x00" * (250 * 48)
        second = b"\x02\x00" * 50
        composed = compose_wav([first, silence, second], 100000)
        frames = pcm16_frames(composed)
        self.assertEqual(len(frames), (100 + 250 * 48 + 50) * 2)
        self.assertEqual(frames[: len(first)], first)
        self.assertEqual(frames[len(first) : len(first) + len(silence)], silence)
        self.assertEqual(frames[-len(second) :], second)
        import io
        import wave

        with wave.open(io.BytesIO(composed), "rb") as wav:
            self.assertEqual(
                (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()),
                (1, 2, 48000),
            )
            self.assertEqual(wav.getcomptype(), "NONE")

    def test_rejects_bad_input_format_and_output_limit(self):
        with self.assertRaises(InvalidAudio):
            pcm16_frames(b"not a wav")
        with self.assertRaises(InvalidAudio):
            compose_wav([b"\x00\x00" * 100], 100)


class LifecycleTests(unittest.TestCase):
    def _artifact_fixture(self, root):
        import yaml

        model_path = root / "artifact"
        model_path.mkdir()
        contents = {
            "model.safetensors": b"tiny model fixture",
            "config.json": b"{}\n",
        }
        entries = []
        for name, value in contents.items():
            (model_path / name).write_bytes(value)
            entries.append(
                {
                    "path": name,
                    "size_bytes": len(value),
                    "sha256": hashlib.sha256(value).hexdigest(),
                }
            )
        manifest = {
            "manifest_version": 1,
            "model": {
                "family": "voxcpm2",
                "repository": "openbmb/VoxCPM2",
                "revision": "test-revision",
            },
            "artifact": {
                "format": "voxcpm2",
                "tool": "VoxCPM from_local",
                "tool_version": "test-version",
            },
            "files": entries,
        }
        (root / "manifest.yaml").write_text(yaml.safe_dump(manifest))
        config = test_config()
        config["model_path"] = str(model_path)
        config["model_revision"] = "test-revision"
        config["model_manifest_sha256"] = hashlib.sha256(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return config, model_path, contents

    def _fake_voxcpm_imports(self):
        loaded = object()
        load_calls = []
        torch = types.ModuleType("torch")
        torch.cuda = types.SimpleNamespace(
            is_available=lambda: True,
            mem_get_info=lambda: (16 * 1024**2 * 1024, 16 * 1024**2 * 1024),
            set_per_process_memory_fraction=lambda *_: None,
            empty_cache=lambda: None,
        )
        torch.set_num_threads = lambda *_: None
        voxcpm = types.ModuleType("voxcpm")

        class VoxCPM:
            @staticmethod
            def from_pretrained(*_args, **_kwargs):
                load_calls.append(True)
                return loaded

        voxcpm.VoxCPM = VoxCPM
        return loaded, load_calls, {"torch": torch, "voxcpm": voxcpm}

    def test_model_factory_verifies_valid_artifact_checksums_before_load(self):
        with tempfile.TemporaryDirectory() as temp:
            config, model_path, contents = self._artifact_fixture(Path(temp))
            loaded, load_calls, fake_modules = self._fake_voxcpm_imports()
            with (
                mock.patch.dict(sys.modules, fake_modules),
                mock.patch(
                    "services.tts.lifecycle._file_sha256",
                    wraps=_file_sha256,
                ) as digest,
            ):
                self.assertIs(vox_model_factory(config)(), loaded)
            self.assertEqual(len(digest.call_args_list), len(contents))
            self.assertEqual(len(load_calls), 1)
            self.assertTrue((model_path / "model.safetensors").is_file())

    def test_model_factory_rejects_missing_wrong_size_corrupt_and_bad_manifest(self):
        for case in ("missing", "wrong_size", "same_size_corruption", "bad_manifest"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temp:
                config, model_path, contents = self._artifact_fixture(Path(temp))
                target = model_path / "model.safetensors"
                if case == "missing":
                    target.unlink()
                elif case == "wrong_size":
                    target.write_bytes(b"different size")
                elif case == "same_size_corruption":
                    original = contents["model.safetensors"]
                    target.write_bytes(bytes([original[0] ^ 1]) + original[1:])
                else:
                    config["model_manifest_sha256"] = "0" * 64
                with self.assertRaises(PermanentModelError) as caught:
                    vox_model_factory(config)()
                self.assertEqual(caught.exception.category, "model_artifact_invalid")
                self.assertNotIn(str(model_path), caught.exception.message)

    def test_artifact_hashes_run_lazily_once_per_model_load_not_per_request(self):
        with tempfile.TemporaryDirectory() as temp:
            config, _model_path, contents = self._artifact_fixture(Path(temp))
            loaded, load_calls, fake_modules = self._fake_voxcpm_imports()
            with (
                mock.patch.dict(sys.modules, fake_modules),
                mock.patch(
                    "services.tts.lifecycle._file_sha256",
                    wraps=_file_sha256,
                ) as digest,
            ):
                lifecycle = ModelLifecycle(config, vox_model_factory(config))
                try:
                    self.assertTrue(lifecycle.ready())
                    self.assertEqual(digest.call_count, 0)
                    lifecycle._generate_segment = lambda *_args: (b"wav", "audio/wav")
                    lifecycle.synthesize("one", "en", "quality")
                    lifecycle.synthesize("two", "en", "quality")
                    self.assertEqual(digest.call_count, len(contents))
                    self.assertEqual(len(load_calls), 1)
                    self.assertIsNotNone(lifecycle._model)
                finally:
                    with mock.patch.dict(sys.modules, fake_modules):
                        lifecycle.stop(1)

    def test_worker_restart_performs_fresh_full_verification(self):
        with tempfile.TemporaryDirectory() as temp:
            config, _model_path, contents = self._artifact_fixture(Path(temp))
            _loaded, _load_calls, fake_modules = self._fake_voxcpm_imports()
            calls = []
            with (
                mock.patch.dict(sys.modules, fake_modules),
                mock.patch(
                    "services.tts.lifecycle._file_sha256",
                    side_effect=lambda path, context: (
                        calls.append(path.name) or _file_sha256(path, context)
                    ),
                ),
            ):
                first_worker = ModelLifecycle(config, vox_model_factory(config))
                second_worker = None
                try:
                    first_worker.warmup()
                    self.assertEqual(len(calls), len(contents))
                    self.assertTrue(first_worker.stop(1))

                    second_worker = ModelLifecycle(config, vox_model_factory(config))
                    second_worker.warmup()
                    self.assertEqual(len(calls), 2 * len(contents))
                finally:
                    if second_worker is not None:
                        second_worker.stop(1)

    def test_idle_reload_reuses_hashes_until_manifest_or_file_metadata_changes(self):
        for changed in ("artifact_mtime", "manifest_mtime"):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as temp:
                config, model_path, contents = self._artifact_fixture(Path(temp))
                _loaded, _load_calls, fake_modules = self._fake_voxcpm_imports()
                calls = []
                lifecycle = ModelLifecycle(config, vox_model_factory(config))
                try:
                    with (
                        mock.patch.dict(sys.modules, fake_modules),
                        mock.patch(
                            "services.tts.lifecycle._file_sha256",
                            side_effect=lambda path, context: (
                                calls.append(path.name) or _file_sha256(path, context)
                            ),
                        ),
                    ):
                        lifecycle.warmup()
                        self.assertEqual(len(calls), len(contents))
                        self.assertTrue(lifecycle.unload())
                        lifecycle.warmup()
                        self.assertEqual(len(calls), len(contents))

                        target = (
                            model_path / "model.safetensors"
                            if changed == "artifact_mtime"
                            else Path(config["model_path"]).parent / "manifest.yaml"
                        )
                        stat = target.stat()
                        os.utime(
                            target,
                            ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000),
                        )
                        self.assertTrue(lifecycle.unload())
                        lifecycle.warmup()
                        self.assertEqual(len(calls), 2 * len(contents))
                finally:
                    with mock.patch.dict(sys.modules, fake_modules):
                        lifecycle.stop(1)

    def test_changed_artifact_size_forces_full_hash_and_is_not_cached(self):
        with tempfile.TemporaryDirectory() as temp:
            config, model_path, contents = self._artifact_fixture(Path(temp))
            _loaded, _load_calls, fake_modules = self._fake_voxcpm_imports()
            calls = []
            lifecycle = ModelLifecycle(config, vox_model_factory(config))
            try:
                with (
                    mock.patch.dict(sys.modules, fake_modules),
                    mock.patch(
                        "services.tts.lifecycle._file_sha256",
                        side_effect=lambda path, context: (
                            calls.append(path.name) or _file_sha256(path, context)
                        ),
                    ),
                ):
                    lifecycle.warmup()
                    self.assertTrue(lifecycle.unload())
                    (model_path / "model.safetensors").write_bytes(
                        contents["model.safetensors"] + b"x"
                    )
                    with self.assertRaises(TTSFailure) as failure:
                        lifecycle.warmup()
                    self.assertEqual(failure.exception.code, "model_artifact_invalid")
                    self.assertEqual(len(calls), 2 * len(contents))

                    (model_path / "model.safetensors").write_bytes(
                        contents["model.safetensors"]
                    )
                    calls.clear()
                    lifecycle.warmup()
                    self.assertEqual(len(calls), len(contents))
                    self.assertTrue(lifecycle.ready())
            finally:
                with mock.patch.dict(sys.modules, fake_modules):
                    lifecycle.stop(1)

    def test_failed_verification_is_not_cached(self):
        with tempfile.TemporaryDirectory() as temp:
            config, _model_path, contents = self._artifact_fixture(Path(temp))
            loaded, load_calls, fake_modules = self._fake_voxcpm_imports()
            calls = []

            def fail_first_hash(path, context):
                calls.append(path.name)
                if len(calls) == 1:
                    raise OSError("synthetic transient read error")
                return _file_sha256(path, context)

            lifecycle = ModelLifecycle(config, vox_model_factory(config))
            try:
                with (
                    mock.patch.dict(sys.modules, fake_modules),
                    mock.patch(
                        "services.tts.lifecycle._file_sha256",
                        side_effect=fail_first_hash,
                    ),
                ):
                    with self.assertRaises(TTSFailure):
                        lifecycle.warmup()
                    self.assertTrue(lifecycle.ready())
                    lifecycle.warmup()
                    self.assertEqual(len(calls), len(contents) + 1)
                    self.assertIs(lifecycle._model, loaded)
                    self.assertEqual(len(load_calls), 1)
            finally:
                with mock.patch.dict(sys.modules, fake_modules):
                    lifecycle.stop(1)

    def test_stat_io_error_is_recoverable_and_not_cached(self):
        with tempfile.TemporaryDirectory() as temp:
            config, _model_path, contents = self._artifact_fixture(Path(temp))
            loaded, load_calls, fake_modules = self._fake_voxcpm_imports()
            calls = []

            def fail_manifest_stat_once(path):
                calls.append(path.name)
                if len(calls) == 1:
                    raise OSError("synthetic transient stat error")
                return _file_metadata(path)

            lifecycle = ModelLifecycle(config, vox_model_factory(config))
            try:
                with (
                    mock.patch.dict(sys.modules, fake_modules),
                    mock.patch(
                        "services.tts.lifecycle._file_metadata",
                        side_effect=fail_manifest_stat_once,
                    ),
                    mock.patch(
                        "services.tts.lifecycle._file_sha256",
                        wraps=_file_sha256,
                    ) as digest,
                ):
                    with self.assertRaises(TTSFailure) as failure:
                        lifecycle.warmup()
                    self.assertEqual(failure.exception.code, "model_load_failed")
                    self.assertTrue(lifecycle.ready())
                    self.assertEqual(digest.call_count, 0)
                    lifecycle.warmup()
                    self.assertEqual(digest.call_count, len(contents))
                    self.assertIs(lifecycle._model, loaded)
                    self.assertEqual(len(load_calls), 1)
            finally:
                with mock.patch.dict(sys.modules, fake_modules):
                    lifecycle.stop(1)

    def test_cancelled_verification_is_not_cached(self):
        with tempfile.TemporaryDirectory() as temp:
            config, _model_path, contents = self._artifact_fixture(Path(temp))
            loaded, load_calls, fake_modules = self._fake_voxcpm_imports()
            entered, release = threading.Event(), threading.Event()
            disconnected, failures, calls = [False], [], []
            context = SynthesisContext(time.monotonic() + 10, lambda: disconnected[0])

            def block_first_hash(path, hash_context):
                calls.append(path.name)
                if len(calls) == 1:
                    entered.set()
                    if not release.wait(2):
                        raise AssertionError("test did not release blocked hash")
                return _file_sha256(path, hash_context)

            lifecycle = ModelLifecycle(config, vox_model_factory(config))
            with (
                mock.patch.dict(sys.modules, fake_modules),
                mock.patch(
                    "services.tts.lifecycle._file_sha256",
                    side_effect=block_first_hash,
                ),
            ):
                request = threading.Thread(
                    target=lambda: self._capture_tts_failure(
                        lambda: lifecycle.synthesize(
                            "hello", "en", "quality", context=context
                        ),
                        failures,
                    )
                )
                try:
                    request.start()
                    self.assertTrue(entered.wait(1))
                    disconnected[0] = True
                finally:
                    release.set()
                    request.join(2)
                self.assertFalse(request.is_alive())
                self.assertEqual(failures[0].code, "request_cancelled")
                disconnected[0] = False
                lifecycle.warmup()
                self.assertEqual(len(calls), len(contents) + 1)
                self.assertIs(lifecycle._model, loaded)
                self.assertEqual(len(load_calls), 1)
                lifecycle.stop(1)

    def test_replaced_inode_forces_full_verification(self):
        with tempfile.TemporaryDirectory() as temp:
            config, model_path, contents = self._artifact_fixture(Path(temp))
            _loaded, _load_calls, fake_modules = self._fake_voxcpm_imports()
            calls = []
            lifecycle = ModelLifecycle(config, vox_model_factory(config))
            with (
                mock.patch.dict(sys.modules, fake_modules),
                mock.patch(
                    "services.tts.lifecycle._file_sha256",
                    side_effect=lambda path, context: (
                        calls.append(path.name) or _file_sha256(path, context)
                    ),
                ),
            ):
                try:
                    lifecycle.warmup()
                    self.assertTrue(lifecycle.unload())
                    target = model_path / "model.safetensors"
                    old_stat = target.stat()
                    replacement = model_path / "replacement.tmp"
                    replacement.write_bytes(contents["model.safetensors"])
                    os.utime(
                        replacement,
                        ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns),
                    )
                    os.replace(replacement, target)
                    self.assertNotEqual(target.stat().st_ino, old_stat.st_ino)
                    self.assertEqual(target.stat().st_mtime_ns, old_stat.st_mtime_ns)
                    lifecycle.warmup()
                    self.assertEqual(len(calls), 2 * len(contents))
                finally:
                    lifecycle.stop(1)

    def test_same_size_modification_with_restored_mtime_uses_ctime(self):
        with tempfile.TemporaryDirectory() as temp:
            config, model_path, contents = self._artifact_fixture(Path(temp))
            _loaded, _load_calls, fake_modules = self._fake_voxcpm_imports()
            calls = []
            lifecycle = ModelLifecycle(config, vox_model_factory(config))
            with (
                mock.patch.dict(sys.modules, fake_modules),
                mock.patch(
                    "services.tts.lifecycle._file_sha256",
                    side_effect=lambda path, context: (
                        calls.append(path.name) or _file_sha256(path, context)
                    ),
                ),
            ):
                try:
                    lifecycle.warmup()
                    self.assertTrue(lifecycle.unload())
                    target = model_path / "model.safetensors"
                    original = contents["model.safetensors"]
                    original_stat = target.stat()
                    changed = bytes([original[0] ^ 1]) + original[1:]
                    target.write_bytes(changed)
                    os.utime(
                        target,
                        ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
                    )
                    changed_stat = target.stat()
                    self.assertEqual(changed_stat.st_size, original_stat.st_size)
                    self.assertEqual(
                        changed_stat.st_mtime_ns, original_stat.st_mtime_ns
                    )
                    self.assertNotEqual(
                        changed_stat.st_ctime_ns, original_stat.st_ctime_ns
                    )
                    with self.assertRaises(TTSFailure) as failure:
                        lifecycle.warmup()
                    self.assertEqual(failure.exception.code, "model_artifact_invalid")
                    self.assertEqual(len(calls), 2 * len(contents))
                finally:
                    lifecycle.stop(1)

    def _capture_tts_failure(self, operation, failures):
        try:
            operation()
        except TTSFailure as error:
            failures.append(error)

    def test_concurrent_waiter_cannot_bypass_incomplete_verification(self):
        with tempfile.TemporaryDirectory() as temp:
            config, _model_path, contents = self._artifact_fixture(Path(temp))
            loaded, load_calls, fake_modules = self._fake_voxcpm_imports()
            entered, release, second_waiting = (
                threading.Event(),
                threading.Event(),
                threading.Event(),
            )
            calls, errors = [], []
            lifecycle = ModelLifecycle(config, vox_model_factory(config))
            original_wait = lifecycle._condition.wait

            def observe_wait(timeout=None):
                second_waiting.set()
                return original_wait(timeout)

            lifecycle._condition.wait = observe_wait

            def block_hash(path, context):
                calls.append(path.name)
                if len(calls) == 1:
                    entered.set()
                    if not release.wait(2):
                        raise AssertionError("test did not release blocked hash")
                return _file_sha256(path, context)

            def warmup():
                try:
                    lifecycle.warmup()
                except Exception as error:  # captured for the test thread
                    errors.append(error)

            with (
                mock.patch.dict(sys.modules, fake_modules),
                mock.patch(
                    "services.tts.lifecycle._file_sha256", side_effect=block_hash
                ),
            ):
                first = threading.Thread(target=warmup)
                second = threading.Thread(target=warmup)
                first.start()
                try:
                    self.assertTrue(entered.wait(1))
                    second.start()
                    self.assertTrue(second_waiting.wait(1))
                    self.assertEqual(len(calls), 1)
                    self.assertEqual(load_calls, [])
                finally:
                    release.set()
                    first.join(2)
                    second.join(2)
                    self.assertIs(lifecycle._model, loaded)
                    lifecycle.stop(1)
            self.assertFalse(first.is_alive())
            self.assertFalse(second.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(len(calls), len(contents))
            self.assertEqual(len(load_calls), 1)
            self.assertIs(lifecycle._model, None)

    def test_artifact_integrity_failure_recovers_after_repair(self):
        with tempfile.TemporaryDirectory() as temp:
            config, model_path, contents = self._artifact_fixture(Path(temp))
            original = contents["model.safetensors"]
            (model_path / "model.safetensors").write_bytes(
                bytes([original[0] ^ 1]) + original[1:]
            )
            loaded, load_calls, fake_modules = self._fake_voxcpm_imports()
            with mock.patch.dict(sys.modules, fake_modules):
                lifecycle = ModelLifecycle(config, vox_model_factory(config))
                try:
                    with self.assertRaises(TTSFailure) as failure:
                        lifecycle.warmup()
                    self.assertEqual(failure.exception.code, "model_artifact_invalid")
                    self.assertFalse(lifecycle.ready())
                    self.assertEqual(
                        lifecycle.readiness()["code"], "model_artifact_invalid"
                    )
                    (model_path / "model.safetensors").write_bytes(original)
                    lifecycle.warmup()
                    self.assertTrue(lifecycle.ready())
                    self.assertIs(lifecycle._model, loaded)
                    self.assertEqual(len(load_calls), 1)
                finally:
                    lifecycle.stop(1)

    def test_hash_io_error_is_transient_and_does_not_latch_readiness(self):
        with tempfile.TemporaryDirectory() as temp:
            config, _model_path, _contents = self._artifact_fixture(Path(temp))
            loaded, load_calls, fake_modules = self._fake_voxcpm_imports()
            with mock.patch.dict(sys.modules, fake_modules):
                lifecycle = ModelLifecycle(config, vox_model_factory(config))
                try:
                    with mock.patch(
                        "services.tts.lifecycle._file_sha256",
                        side_effect=OSError("synthetic transient read error"),
                    ):
                        with self.assertRaises(TTSFailure) as failure:
                            lifecycle.warmup()
                    self.assertEqual(failure.exception.code, "model_load_failed")
                    self.assertTrue(lifecycle.ready())
                    self.assertEqual(lifecycle.readiness(), {"ready": True})
                    lifecycle.warmup()
                    self.assertTrue(lifecycle.ready())
                    self.assertIs(lifecycle._model, loaded)
                    self.assertEqual(len(load_calls), 1)
                finally:
                    lifecycle.stop(1)

    def test_deadline_and_cancellation_during_hash_stop_before_native_load(self):
        for reason in ("deadline", "cancellation"):
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as temp:
                config, _model_path, _contents = self._artifact_fixture(Path(temp))
                loaded, load_calls, fake_modules = self._fake_voxcpm_imports()
                entered, release = threading.Event(), threading.Event()
                now, disconnected, failures = [0], [False], []
                context = SynthesisContext(
                    10, lambda: disconnected[0], clock=lambda: now[0]
                )

                def blocked_hash(path, hash_context):
                    entered.set()
                    if not release.wait(2):
                        raise AssertionError("test did not release blocked hash")
                    return _file_sha256(path, hash_context)

                with (
                    mock.patch.dict(sys.modules, fake_modules),
                    mock.patch(
                        "services.tts.lifecycle._file_sha256",
                        side_effect=blocked_hash,
                    ),
                ):
                    lifecycle = ModelLifecycle(config, vox_model_factory(config))

                    def synthesize():
                        try:
                            lifecycle.synthesize(
                                "hello", "en", "quality", context=context
                            )
                        except TTSFailure as error:
                            failures.append(error)

                    request = threading.Thread(target=synthesize)
                    request.start()
                    try:
                        self.assertTrue(entered.wait(1))
                        self.assertTrue(lifecycle.state()["inference_active"])
                        if reason == "deadline":
                            now[0] = 11
                        else:
                            disconnected[0] = True
                    finally:
                        release.set()
                        request.join(2)
                        lifecycle.stop(1)
                self.assertFalse(request.is_alive())
                self.assertEqual(len(failures), 1)
                self.assertEqual(
                    failures[0].code,
                    "deadline_exceeded"
                    if reason == "deadline"
                    else "request_cancelled",
                )
                self.assertEqual(load_calls, [])

    def test_native_model_load_retains_ownership_after_caller_timeout(self):
        with tempfile.TemporaryDirectory() as temp:
            config, _model_path, _contents = self._artifact_fixture(Path(temp))
            loaded, load_calls, fake_modules = self._fake_voxcpm_imports()
            entered, release = threading.Event(), threading.Event()
            now, failures = [0], []

            def blocked_load(*_args, **_kwargs):
                entered.set()
                if not release.wait(2):
                    raise AssertionError("test did not release native load")
                load_calls.append(True)
                return loaded

            fake_modules["voxcpm"].VoxCPM.from_pretrained = staticmethod(blocked_load)
            lifecycle = ModelLifecycle(config, vox_model_factory(config))
            context = SynthesisContext(10, clock=lambda: now[0])

            def synthesize():
                try:
                    lifecycle.synthesize("hello", "en", "quality", context=context)
                except TTSFailure as error:
                    failures.append(error)

            request = threading.Thread(target=synthesize)
            with mock.patch.dict(sys.modules, fake_modules):
                request.start()
                try:
                    self.assertTrue(entered.wait(2))
                    now[0] = 11
                    self.assertFalse(lifecycle.stop(0.01))
                    self.assertTrue(lifecycle.state()["inference_active"])
                    self.assertFalse(lifecycle.ready())
                    self.assertEqual(load_calls, [])
                finally:
                    release.set()
                    request.join(2)
                self.assertFalse(request.is_alive())
                self.assertEqual(len(failures), 1)
                self.assertEqual(failures[0].code, "deadline_exceeded")
                self.assertIs(lifecycle._model, loaded)
                self.assertFalse(lifecycle.ready())
                self.assertTrue(lifecycle.stop(1))
            self.assertEqual(len(load_calls), 1)

    def test_model_factory_marks_missing_and_invalid_artifacts_permanent(self):
        with tempfile.TemporaryDirectory() as temp:
            missing = test_config()
            missing["model_path"] = str(Path(temp) / "missing-model")
            with self.assertRaises(PermanentModelError) as unavailable:
                vox_model_factory(missing)()
            self.assertEqual(
                unavailable.exception.category, "model_artifact_unavailable"
            )

            model_path = Path(temp) / "model"
            model_path.mkdir()
            (Path(temp) / "manifest.yaml").write_text("model: [invalid\n")
            invalid = test_config()
            invalid["model_path"] = str(model_path)
            with self.assertRaises(PermanentModelError) as malformed:
                vox_model_factory(invalid)()
            self.assertEqual(malformed.exception.category, "model_artifact_invalid")

    def test_unloaded_worker_is_ready_without_loading(self):
        calls = []
        lifecycle = ModelLifecycle(
            {"idle_unload_seconds": 0},
            lambda _context=None: calls.append(True) or object(),
        )
        try:
            self.assertTrue(lifecycle.ready())
            self.assertEqual(lifecycle.readiness(), {"ready": True})
            self.assertEqual(
                lifecycle.state(),
                {"model_state": "unloaded", "inference_active": False},
            )
            self.assertEqual(calls, [])
        finally:
            lifecycle.stop(1)

    def test_permanent_artifact_failure_marks_unready_and_recovers_after_repair(self):
        attempts = []

        def factory(_context=None):
            attempts.append(True)
            if len(attempts) == 1:
                raise PermanentModelError(
                    "model_artifact_invalid",
                    "configured TTS model artifacts are invalid; restore the pinned model files and manifest",
                )
            return object()

        lifecycle = ModelLifecycle({"idle_unload_seconds": 0}, factory)
        try:
            self.assertTrue(lifecycle.ready())
            with self.assertRaises(TTSFailure) as caught:
                lifecycle.warmup()
            self.assertEqual(caught.exception.code, "model_artifact_invalid")
            self.assertFalse(lifecycle.ready())
            self.assertEqual(
                lifecycle.readiness(),
                {
                    "ready": False,
                    "code": "model_artifact_invalid",
                    "message": "configured TTS model artifacts are invalid; restore the pinned model files and manifest",
                },
            )
            self.assertEqual(
                lifecycle.state(),
                {
                    "model_state": "unloaded",
                    "inference_active": False,
                    "failure_category": "model_artifact_invalid",
                },
            )
            # A normal subsequent request retries loading; a corrected artifact
            # clears the latch without restarting the control process.
            lifecycle.warmup()
            self.assertTrue(lifecycle.ready())
            self.assertEqual(lifecycle.state()["model_state"], "loaded")
            self.assertNotIn("failure_category", lifecycle.state())
            self.assertEqual(len(attempts), 2)
        finally:
            lifecycle.stop(1)

    def test_synthesis_selects_steps_for_each_mode(self):
        lifecycle = ModelLifecycle({"idle_unload_seconds": 0}, fake_model_factory)
        observed = []
        lifecycle._generate = lambda _model, _text, _language, steps: (
            observed.append(steps) or b"wav",
            "audio/wav",
        )
        try:
            for mode in (
                "quality",
                "fast",
                "auto",
                "high_quality",
                "extra_high_quality",
            ):
                lifecycle.synthesize("hello", "auto", mode)
            self.assertEqual(observed, [10, 8, 10, 16, 32])
        finally:
            lifecycle.stop(1)

    def test_processing_defaults_to_none_and_gentle_wraps_completed_audio(self):
        lifecycle = ModelLifecycle(
            ssml_config(idle_unload_seconds=0), fake_model_factory
        )
        source = wav_segment(b"\x01\x00" * 480)
        calls = []
        lifecycle._generate = lambda *_args, **_kwargs: (source, "audio/wav")

        def process(audio, config):
            calls.append((audio, config))
            return b"processed-wav"

        try:
            with mock.patch(
                "services.tts.lifecycle.process_gently", side_effect=process
            ):
                self.assertEqual(
                    lifecycle.synthesize("hello", "auto", "quality"),
                    (source, "audio/wav"),
                )
                self.assertEqual(
                    lifecycle.synthesize(
                        "hello", "auto", "quality", audio_processing="gentle"
                    ),
                    (b"processed-wav", "audio/wav"),
                )
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][0], source)
        finally:
            lifecycle.stop(1)

    def test_invalid_processing_does_not_load_model(self):
        calls = []
        lifecycle = ModelLifecycle(
            {"idle_unload_seconds": 0},
            lambda _context=None: calls.append(True) or object(),
        )
        try:
            with self.assertRaises(TTSFailure) as caught:
                lifecycle.synthesize(
                    "hello", "auto", "quality", audio_processing="unknown"
                )
            self.assertEqual(caught.exception.code, "invalid_audio_processing")
            self.assertEqual(calls, [])
        finally:
            lifecycle.stop(1)

    def test_ssml_synthesis_uses_language_context_and_composes_all_segments(self):
        lifecycle = ModelLifecycle(
            ssml_config(idle_unload_seconds=0), fake_model_factory
        )
        observed = []

        def generate(_model, text, language, steps):
            observed.append((text, language, steps))
            marker = {"en": b"\x01\x00", "sv": b"\x02\x00", "ru": b"\x03\x00"}[language]
            return wav_segment(marker * 480), "audio/wav"

        lifecycle._generate = generate
        document = (
            '<speak xmlns="http://www.w3.org/2001/10/synthesis" version="1.1" '
            'xml:lang="en-US">one<break time="10ms"/>'
            '<lang xml:lang="sv-SE">två<lang xml:lang="ru-RU">три</lang></lang>'
            "</speak>"
        )
        try:
            result, content_type = lifecycle.synthesize(
                document, "auto", "high_quality", "ssml"
            )
            self.assertEqual(content_type, "audio/wav")
            self.assertEqual(
                observed,
                [("one", "en", 16), ("två", "sv", 16), ("три", "ru", 16)],
            )
            frames = pcm16_frames(result)
            self.assertEqual(len(frames) // 2, 480 * 3 + 480)
            self.assertEqual(frames[480 * 2 : 480 * 2 + 480 * 2], b"\x00\x00" * 480)
        finally:
            lifecycle.stop(1)

    def test_ssml_segment_failure_never_returns_composed_audio(self):
        lifecycle = ModelLifecycle(
            ssml_config(idle_unload_seconds=0), fake_model_factory
        )
        calls = []

        def generate(_model, text, language, steps):
            calls.append(text)
            if text == "second":
                raise TTSFailure("inference_failed", "synthetic failure", 500)
            return wav_segment(b"\x00\x00" * 480), "audio/wav"

        lifecycle._generate = generate
        document = (
            '<speak xmlns="http://www.w3.org/2001/10/synthesis" version="1.1" '
            'xml:lang="en">first<lang xml:lang="sv">second</lang></speak>'
        )
        try:
            with self.assertRaises(TTSFailure):
                lifecycle.synthesize(document, "auto", "quality", "ssml")
            self.assertEqual(calls, ["first", "second"])
            self.assertEqual(lifecycle.state()["model_state"], "loaded")
        finally:
            lifecycle.stop(1)

    def test_warmup_loads_and_idle_unload_reloads(self):
        calls = []
        lifecycle = ModelLifecycle(
            {"idle_unload_seconds": 0.2},
            lambda _context=None: calls.append(object()) or calls[-1],
        )
        try:
            self.assertEqual(lifecycle.state()["model_state"], "unloaded")
            lifecycle.warmup()
            self.assertEqual(lifecycle.state()["model_state"], "loaded")
            deadline = time.monotonic() + 2
            while (
                lifecycle.state()["model_state"] != "unloaded"
                and time.monotonic() < deadline
            ):
                time.sleep(0.02)
            self.assertEqual(lifecycle.state()["model_state"], "unloaded")
            lifecycle.warmup()
            self.assertEqual(len(calls), 2)
        finally:
            lifecycle.stop(1)

    def test_active_inference_prevents_unload(self):
        entered = threading.Event()
        release = threading.Event()
        lifecycle = ModelLifecycle({"idle_unload_seconds": 0.1}, fake_model_factory)
        worker = threading.Thread(
            target=lambda: lifecycle._with_model(
                lambda _model: (entered.set(), release.wait(2))
            )
        )
        try:
            worker.start()
            self.assertTrue(entered.wait(1))
            self.assertTrue(lifecycle.ready())
            time.sleep(1.2)
            self.assertEqual(
                lifecycle.state(), {"model_state": "loaded", "inference_active": True}
            )
        finally:
            release.set()
            worker.join(1)
            lifecycle.stop(1)

    def test_failed_load_recovers_on_next_request(self):
        attempts = []

        def factory(_context=None):
            attempts.append(True)
            if len(attempts) == 1:
                raise RuntimeError("temporary load failure")
            return object()

        lifecycle = ModelLifecycle({"idle_unload_seconds": 0}, factory)
        try:
            with self.assertRaises(TTSFailure) as caught:
                lifecycle.warmup()
            self.assertEqual(caught.exception.code, "model_load_failed")
            self.assertEqual(lifecycle.state()["model_state"], "unloaded")
            self.assertTrue(lifecycle.ready())
            lifecycle.warmup()
            self.assertEqual(lifecycle.state()["model_state"], "loaded")
            self.assertEqual(len(attempts), 2)
        finally:
            lifecycle.stop(1)

    def test_inference_failure_does_not_latch_worker(self):
        lifecycle = ModelLifecycle({"idle_unload_seconds": 0}, fake_model_factory)
        attempts = []
        original = lifecycle._generate

        def sometimes_fail(*args):
            attempts.append(True)
            if len(attempts) == 1:
                raise TTSFailure("inference_failed", "synthetic failure", 500)
            return b"wav", "audio/wav"

        lifecycle._generate = sometimes_fail
        try:
            with self.assertRaises(TTSFailure):
                lifecycle.synthesize("hello", "auto", "quality")
            self.assertEqual(lifecycle.state()["model_state"], "loaded")
            self.assertEqual(
                lifecycle.synthesize("hello", "auto", "quality"), (b"wav", "audio/wav")
            )
            self.assertEqual(len(attempts), 2)
        finally:
            lifecycle._generate = original
            lifecycle.stop(1)


class WorkerHTTPTests(unittest.TestCase):
    def setUp(self):
        class FakeLifecycle:
            def __init__(self):
                self.started = threading.Event()
                self.release = threading.Event()
                self.finished = threading.Event()
                self.requests = []
                self.warmups = 0

            def ready(self):
                return True

            def readiness(self):
                return {"ready": True}

            def state(self):
                return {"model_state": "unloaded", "inference_active": False}

            def warmup(self):
                self.warmups += 1

            def synthesize(
                self,
                text,
                language,
                mode,
                input_format="text",
                audio_processing="none",
                *,
                context=None,
            ):
                self.requests.append(
                    (text, language, mode, input_format, audio_processing)
                )
                self.started.set()
                self.release.wait(2)
                self.finished.set()
                import io
                import wave

                output = io.BytesIO()
                with wave.open(output, "wb") as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(24000)
                    wav.writeframes(b"\x00\x00" * 8)
                return output.getvalue(), "audio/wav"

        self.lifecycle = FakeLifecycle()
        self.config = test_config()
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0), handler(self.config, self.lifecycle)
        )
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.lifecycle.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(1)

    def _request(self, payload):
        import urllib.error
        import urllib.request

        request = urllib.request.Request(
            self.url + "/internal/v1/speech",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            return urllib.request.urlopen(request, timeout=3)
        except urllib.error.HTTPError as error:
            return error

    def _warmup(self):
        import urllib.error
        import urllib.request

        request = urllib.request.Request(
            self.url + "/internal/v1/warmup", data=b"", method="POST"
        )
        try:
            return urllib.request.urlopen(request, timeout=3)
        except urllib.error.HTTPError as error:
            return error

    def assert_valid_wav(self, audio):
        import io
        import wave

        with wave.open(io.BytesIO(audio), "rb") as wav:
            self.assertEqual(wav.getnchannels(), 1)
            self.assertEqual(wav.getsampwidth(), 2)
            self.assertEqual(wav.getframerate(), 24000)
            self.assertEqual(wav.getnframes(), 8)

    def test_warmup_and_http_synthesis_share_fake_model_lifecycle(self):
        factory_calls = []
        lifecycle = ModelLifecycle(
            {"idle_unload_seconds": 60},
            lambda _context=None: factory_calls.append(object()) or factory_calls[-1],
        )
        generated = []
        lifecycle._generate = lambda *_args, **_kwargs: (
            generated.append(True) or b"synthetic-wav",
            "audio/wav",
        )
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler(self.config, lifecycle))
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_port}"
        try:
            import urllib.request

            # Synthesis works from a cold worker without prior warmup.
            speech = urllib.request.Request(
                url + "/internal/v1/speech",
                data=b'{"text":"synthetic speech"}',
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(speech, timeout=3) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers["Content-Type"], "audio/wav")
                self.assertEqual(response.read(), b"synthetic-wav")
            self.assertEqual(len(factory_calls), 1)

            warmup = urllib.request.Request(
                url + "/internal/v1/warmup", data=b"", method="POST"
            )
            with urllib.request.urlopen(warmup, timeout=3) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(json.loads(response.read())["model_state"], "loaded")

            with urllib.request.urlopen(speech, timeout=3) as response:
                self.assertEqual(response.read(), b"synthetic-wav")
            self.assertEqual(len(factory_calls), 1)
            self.assertEqual(len(generated), 2)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(1)
            lifecycle.stop(1)

    def test_health_and_readiness_remain_responsive_during_artifact_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            config, _model_path, _contents = LifecycleTests()._artifact_fixture(
                Path(temp)
            )
            loaded, load_calls, fake_modules = LifecycleTests()._fake_voxcpm_imports()
            entered, release = threading.Event(), threading.Event()
            lifecycle = ModelLifecycle(config, vox_model_factory(config))
            lifecycle._generate_segment = lambda *_args: (
                wav_segment(b"\x01\x00" * 480),
                "audio/wav",
            )
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler(config, lifecycle))
            server.daemon_threads = True
            serving = threading.Thread(target=server.serve_forever, daemon=True)
            serving.start()
            url = f"http://127.0.0.1:{server.server_port}"

            def blocked_hash(path, context):
                entered.set()
                if not release.wait(2):
                    raise AssertionError("test did not release artifact hash")
                return _file_sha256(path, context)

            results = []

            def synthesize():
                import urllib.error
                import urllib.request

                request = urllib.request.Request(
                    url + "/internal/v1/speech",
                    data=b'{"text":"hello"}',
                    headers={
                        "Content-Type": "application/json",
                        "X-Request-Timeout-Ms": "5000",
                    },
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(request, timeout=3) as response:
                        results.append(response.status)
                except urllib.error.HTTPError as error:
                    results.append(error.code)

            request_thread = threading.Thread(target=synthesize)
            with (
                mock.patch.dict(sys.modules, fake_modules),
                mock.patch(
                    "services.tts.lifecycle._file_sha256", side_effect=blocked_hash
                ),
            ):
                request_thread.start()
                try:
                    self.assertTrue(entered.wait(1))
                    import urllib.request

                    with urllib.request.urlopen(url + "/healthz", timeout=1) as health:
                        self.assertEqual(health.status, 200)
                    with urllib.request.urlopen(url + "/readyz", timeout=1) as ready:
                        self.assertEqual(ready.status, 200)
                    self.assertEqual(lifecycle.state()["model_state"], "loading")
                finally:
                    release.set()
                    request_thread.join(3)
                    server.shutdown()
                    server.server_close()
                    serving.join(1)
                    lifecycle.stop(1)
            self.assertFalse(request_thread.is_alive())
            self.assertEqual(results, [200])
            self.assertEqual(len(load_calls), 1)

    def test_readiness_exposes_sanitized_permanent_failure_and_liveness(self):
        def permanently_invalid(_context=None):
            try:
                raise RuntimeError("/private/model-store/secret diagnostic")
            except RuntimeError as error:
                raise PermanentModelError(
                    "model_artifact_invalid",
                    "configured TTS model artifacts are invalid; restore the pinned model files and manifest",
                ) from error

        lifecycle = ModelLifecycle({"idle_unload_seconds": 60}, permanently_invalid)
        server = ThreadingHTTPServer(
            ("127.0.0.1", 0), handler(test_config(), lifecycle)
        )
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            import urllib.error
            import urllib.request

            warmup = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/internal/v1/warmup",
                data=b"",
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as failure:
                urllib.request.urlopen(warmup, timeout=2)
            self.assertEqual(failure.exception.code, 503)

            with urllib.request.urlopen(
                f"http://127.0.0.1:{server.server_port}/healthz", timeout=2
            ) as response:
                self.assertEqual(response.status, 200)

            with self.assertRaises(urllib.error.HTTPError) as unavailable:
                urllib.request.urlopen(
                    f"http://127.0.0.1:{server.server_port}/readyz", timeout=2
                )
            self.assertEqual(unavailable.exception.code, 503)
            body = unavailable.exception.read().decode()
            self.assertIn("model_artifact_invalid", body)
            self.assertIn("restore the pinned model files and manifest", body)
            self.assertNotIn("/private/model-store", body)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(1)
            lifecycle.stop(1)

    def test_http_warmup_reports_simulated_insufficient_vram_safely(self):
        def insufficient_resources(_context=None):
            raise RuntimeError("CUDA out of memory in synthetic test")

        lifecycle = ModelLifecycle({"idle_unload_seconds": 60}, insufficient_resources)
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler(self.config, lifecycle))
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            import urllib.error
            import urllib.request

            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/internal/v1/warmup",
                data=b"",
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(request, timeout=3)
            self.assertEqual(caught.exception.code, 503)
            self.assertEqual(
                json.loads(caught.exception.read()),
                {
                    "code": "resource_exhausted",
                    "message": "GPU resources are temporarily unavailable",
                },
            )
            self.assertEqual(lifecycle.state()["model_state"], "unloaded")
            self.assertTrue(lifecycle.ready())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(1)
            lifecycle.stop(1)

    def test_request_defaults_and_validation(self):
        self.lifecycle.release.set()
        response = self._request(b'{"text":"hello"}')
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers["Content-Type"], "audio/wav")
        audio = response.read()
        self.assert_valid_wav(audio)
        self.assertEqual(
            self.lifecycle.requests[-1],
            ("hello", "auto", "quality", "text", "none"),
        )
        for payload, status, code in (
            (b'{"text":"hi","language":"zh"}', 400, "invalid_language"),
            (b'{"text":"hi","extra":1}', 400, "invalid_request"),
            (b'{"text":"hi","mode":"turbo"}', 400, "invalid_mode"),
            (
                b'{"text":"hi","audio_processing":"loud"}',
                400,
                "invalid_audio_processing",
            ),
            (b'{"text":"hi","input_format":"guess"}', 400, "invalid_input_format"),
            (
                b'{"text":"hi","input_format":"ssml","language":"en"}',
                400,
                "invalid_language",
            ),
            (b'{"text":3}', 400, "invalid_text"),
        ):
            response = self._request(payload)
            self.assertEqual(response.code, status)
            self.assertEqual(json.loads(response.read())["code"], code)

    def test_supported_modes_return_wav_with_audio_metadata(self):
        self.lifecycle.release.set()
        for mode in (
            "quality",
            "fast",
            "auto",
            "high_quality",
            "extra_high_quality",
        ):
            with self.subTest(mode=mode):
                response = self._request(
                    json.dumps({"text": "hello", "mode": mode}).encode()
                )
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers["Content-Type"], "audio/wav")
                audio = response.read()
                self.assert_valid_wav(audio)
                self.assertEqual(self.lifecycle.requests[-1][2], mode)

    def test_audio_processing_defaults_and_forwards_gentle(self):
        self.lifecycle.release.set()
        response = self._request(b'{"text":"hello"}')
        self.assertEqual(response.status, 200)
        self.assertEqual(self.lifecycle.requests[-1][-1], "none")
        response = self._request(b'{"text":"hello","audio_processing":"gentle"}')
        self.assertEqual(response.status, 200)
        self.assertEqual(self.lifecycle.requests[-1][-1], "gentle")

    def test_explicit_ssml_input_format_is_forwarded(self):
        self.lifecycle.release.set()
        response = self._request(
            json.dumps(
                {
                    "text": '<speak xmlns="http://www.w3.org/2001/10/synthesis" version="1.1" xml:lang="en">hello</speak>',
                    "input_format": "ssml",
                }
            ).encode()
        )
        self.assertEqual(response.status, 200)
        self.assertEqual(self.lifecycle.requests[-1][3], "ssml")

    def test_explicit_text_input_format_preserves_plain_text_path(self):
        self.lifecycle.release.set()
        response = self._request(b'{"text":"hello","input_format":"text"}')
        self.assertEqual(response.status, 200)
        self.assertEqual(
            self.lifecycle.requests[-1],
            ("hello", "auto", "quality", "text", "none"),
        )

    def test_worker_admission_is_single_slot(self):
        payload = b'{"text":"first"}'
        body = (
            f"POST /internal/v1/speech HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\nContent-Length: {len(payload)}\r\nConnection: close\r\n\r\n".encode()
            + payload
        )
        client = socket.create_connection(
            ("127.0.0.1", self.server.server_port), timeout=2
        )
        client.sendall(body)
        self.assertTrue(self.lifecycle.started.wait(1))
        import urllib.request

        with urllib.request.urlopen(self.url + "/readyz", timeout=2) as readiness:
            self.assertEqual(readiness.status, 200)
        rejected = self._request(b'{"text":"second"}')
        self.assertEqual(rejected.code, 429)
        warmup_rejected = self._warmup()
        self.assertEqual(warmup_rejected.code, 429)
        self.assertEqual(self.lifecycle.warmups, 0)
        self.lifecycle.release.set()
        client.close()
        self.assertTrue(self.lifecycle.finished.wait(1))
        self.assertEqual(len(self.lifecycle.requests), 1)

    def test_cancelled_client_does_not_interrupt_native_call(self):
        payload = json.dumps(
            {
                "text": '<speak xmlns="http://www.w3.org/2001/10/synthesis" version="1.1" xml:lang="sv">hello</speak>',
                "input_format": "ssml",
            }
        ).encode()
        body = (
            f"POST /internal/v1/speech HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\nContent-Length: {len(payload)}\r\nConnection: close\r\n\r\n".encode()
            + payload
        )
        client = socket.create_connection(
            ("127.0.0.1", self.server.server_port), timeout=2
        )
        client.sendall(body)
        self.assertTrue(self.lifecycle.started.wait(1))
        client.close()
        self.lifecycle.release.set()
        self.assertTrue(self.lifecycle.finished.wait(1))
        self.assertEqual(self.lifecycle.requests[-1][2:], ("quality", "ssml", "none"))


if __name__ == "__main__":
    unittest.main()
