"""Send one authenticated local STT or TTS smoke request through the Gateway."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from scripts.preflight import ROOT, load_env

MAX_STT_BYTES = 25 * 1024 * 1024 - 1024
MAX_TTS_BYTES = 64 * 1024 * 1024
DEFAULT_TTS_TEXT = "This is a synthetic SpeechPlatform text-to-speech smoke test."


class SmokeError(ValueError):
    """A safe smoke-test input, HTTP or response error."""


def _gateway_origin(values):
    origin = values.get(
        "SPEECH_API_URL", f"http://127.0.0.1:{values.get('SPEECH_PORT', '')}"
    ).rstrip("/")
    parsed = urlparse(origin)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise SmokeError("SPEECH_API_URL must be an HTTP(S) origin")
    token = values.get("SPEECH_API_TOKEN", "")
    if len(token) < 32:
        raise SmokeError("SPEECH_API_TOKEN is missing or too short")
    return origin, token


def _request(url, token, body, content_type, *, timeout, max_bytes=MAX_TTS_BYTES):
    request = Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": content_type,
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read(max_bytes + 1)
    except HTTPError as exc:
        raise SmokeError(f"Gateway request failed with HTTP {exc.code}") from exc
    except (OSError, URLError, TimeoutError) as exc:
        raise SmokeError("Gateway request did not complete") from exc


def _multipart(audio, source_language, output_language):
    if not audio.is_file():
        raise SmokeError("provide an existing local audio file")
    if audio.stat().st_size > MAX_STT_BYTES:
        raise SmokeError("audio file exceeds the Gateway request limit")
    name = audio.name.replace('"', "_").replace("\\", "_")
    media = {
        ".wav": "audio/wav",
        ".flac": "audio/flac",
        ".mp3": "audio/mpeg",
        ".ogg": "audio/ogg",
        ".opus": "audio/ogg",
        ".m4a": "audio/mp4",
        ".mp4": "audio/mp4",
    }.get(
        audio.suffix.lower(),
        mimetypes.guess_type(name)[0] or "application/octet-stream",
    )
    boundary = "----speech-platform-" + uuid.uuid4().hex
    body = bytearray(
        f'--{boundary}\r\nContent-Disposition: form-data; name="audio"; filename="{name}"\r\n'
        f"Content-Type: {media}\r\n\r\n".encode()
    )
    body.extend(audio.read_bytes())
    for field, value in (
        ("source_language", source_language),
        ("output_language", output_language),
    ):
        body.extend(
            f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="{field}"\r\n\r\n{value}'.encode()
        )
    body.extend(f"\r\n--{boundary}--\r\n".encode())
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def run_stt(args, values):
    origin, token = _gateway_origin(values)
    body, content_type = _multipart(
        args.audio, args.source_language, args.output_language
    )
    raw = _request(
        f"{origin}/v1/stt/transcriptions",
        token,
        body,
        content_type,
        timeout=195,
        max_bytes=2 * 1024 * 1024,
    )
    if len(raw) > 2 * 1024 * 1024:
        raise SmokeError("Gateway returned an oversized STT response")
    try:
        result = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SmokeError("Gateway returned an invalid STT response") from exc
    if not isinstance(result, dict) or not isinstance(result.get("text"), str):
        raise SmokeError("Gateway returned an invalid STT response")
    print(
        json.dumps(
            {
                key: result.get(key)
                for key in (
                    "detected_language",
                    "source_language",
                    "output_language",
                    "translated",
                    "language_probability",
                )
                if key in result
            },
            ensure_ascii=False,
        )
    )
    print(result["text"])


def run_tts(args, values):
    origin, token = _gateway_origin(values)
    output = args.output.absolute()
    private = (ROOT / "private").resolve()
    if not output.resolve(strict=False).is_relative_to(private):
        raise SmokeError("TTS output must be under private/")
    if not output.parent.is_dir():
        raise SmokeError("TTS output directory must already exist")
    if output.exists() or output.is_symlink():
        raise SmokeError("TTS output already exists; choose a new private path")
    body = json.dumps(
        {
            "text": args.text,
            "language": "auto",
            "mode": "quality",
            "input_format": "text",
            "audio_processing": "none",
        }
    ).encode()
    audio = _request(
        f"{origin}/v1/tts/speech",
        token,
        body,
        "application/json",
        timeout=600,
    )
    if (
        len(audio) > MAX_TTS_BYTES
        or not audio.startswith(b"RIFF")
        or audio[8:12] != b"WAVE"
    ):
        raise SmokeError("Gateway returned invalid or oversized WAV audio")
    try:
        descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise SmokeError(
            "TTS output already exists; choose a new private path"
        ) from exc
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(audio)
    except OSError:
        output.unlink(missing_ok=True)
        raise
    print(f"PASS: received WAV audio ({len(audio)} bytes); saved under private/")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="service", required=True)
    stt = subparsers.add_parser("stt")
    stt.add_argument("--audio", type=Path, required=True)
    stt.add_argument(
        "--source-language", choices=("auto", "ru", "en", "sv"), default="auto"
    )
    stt.add_argument(
        "--output-language", choices=("auto", "ru", "en", "sv"), default="auto"
    )
    tts = subparsers.add_parser("tts")
    tts.add_argument("--text", default=DEFAULT_TTS_TEXT)
    tts.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        values = load_env()
        if args.service == "stt":
            run_stt(args, values)
        else:
            if not args.text or len(args.text) > 10_000:
                raise SmokeError("TTS text must contain 1 to 10000 characters")
            run_tts(args, values)
    except (OSError, ValueError) as exc:
        print(f"speech-platform smoke failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
