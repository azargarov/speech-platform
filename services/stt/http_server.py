"""Private STT HTTP transport for complete-file multipart transcriptions."""

from __future__ import annotations

import asyncio
import json
import time

from aiohttp import web

from services.stt.domain import FailureCode, OperationContext, SpeechFailure, safe_error
from services.stt.metrics import Metrics

STARTUP_TASK_KEY = web.AppKey("startup_task", asyncio.Task)


def create_http_app(application):
    metrics = Metrics()
    maximum = application.config.admission.max_request_bytes
    http_app = web.Application(
        client_max_size=maximum,
        handler_args={"max_line_size": 8190, "max_field_size": 8190},
    )

    async def health(_request):
        return web.json_response({"status": "alive"})

    async def ready(_request):
        if application.lifecycle.ready():
            return web.json_response({"status": "ready"})
        if application.lifecycle.cleanup_unconfirmed():
            return web.json_response(
                {
                    "code": "cleanup_unconfirmed",
                    "message": "inference process cleanup is unconfirmed",
                },
                status=503,
            )
        return web.json_response(
            {"code": "not_ready", "message": "model provider unavailable"}, status=503
        )

    async def prometheus(_request):
        response = web.Response(
            text=metrics.render(application.lifecycle.ready()),
            content_type="text/plain",
        )
        response.headers["Content-Type"] = "text/plain; version=0.0.4; charset=utf-8"
        return response

    async def transcriptions(request):
        context = None
        worker_task = None
        with metrics.request() as set_outcome:
            try:
                context = _operation_context(
                    request, application.config.admission.request_timeout_seconds
                )
                if (
                    request.content_length is not None
                    and request.content_length > maximum
                ):
                    raise SpeechFailure(FailureCode.INPUT_LIMIT)
                if request.content_type != "multipart/form-data":
                    raise SpeechFailure(FailureCode.UNSUPPORTED_MEDIA_TYPE)
                with application.acquire_upload() as lease:
                    reader = await request.multipart()
                    fields = {}
                    seen = set()
                    audio_type = None
                    audio_seen = False
                    while part := await _next_part(reader, context, request):
                        name = part.name
                        if (
                            name
                            not in {
                                "audio",
                                "language",
                                "source_language",
                                "output_language",
                                "model",
                                "timestamps",
                                "stream",
                            }
                            or name in seen
                        ):
                            raise SpeechFailure(
                                FailureCode.INVALID_INPUT,
                                "multipart fields are invalid",
                            )
                        seen.add(name)
                        if name == "audio":
                            audio_seen = True
                            audio_type = (
                                part.headers.get("Content-Type", "")
                                .split(";", 1)[0]
                                .strip()
                                .lower()
                            )
                            if audio_type not in {
                                "audio/wav",
                                "audio/flac",
                                "audio/mpeg",
                                "audio/ogg",
                                "audio/mp4",
                            }:
                                raise SpeechFailure(FailureCode.UNSUPPORTED_MEDIA_TYPE)
                            while True:
                                chunk = await _read_chunk(part, context, request)
                                if not chunk:
                                    break
                                lease.write(chunk)
                        else:
                            value = await _read_text_part(part, context, request)
                            fields[name] = value
                    if not audio_seen:
                        raise SpeechFailure(
                            FailureCode.INVALID_INPUT, "audio is required"
                        )
                    if (
                        "language" in fields
                        and "source_language" in fields
                        and fields["language"].lower()
                        != fields["source_language"].lower()
                    ):
                        raise SpeechFailure(
                            FailureCode.INVALID_INPUT,
                            "language and source_language conflict",
                        )
                    language = fields.get(
                        "source_language", fields.get("language", "auto")
                    )
                    output_language = fields.get("output_language", "auto")
                    model = fields.get("model")
                    timestamps = _boolean(fields.get("timestamps", "false"))
                    if _boolean(fields.get("stream", "false")):
                        raise SpeechFailure(FailureCode.UNSUPPORTED_OPTION)
                    worker_task = asyncio.create_task(
                        asyncio.to_thread(
                            application.transcribe_uploaded,
                            lease,
                            audio_type,
                            model,
                            language,
                            timestamps,
                            context,
                            output_language,
                        )
                    )
                    result = await _wait_for_result(worker_task, context, request)
                set_outcome("success")
                payload = {
                    "text": result.text,
                    "language": result.language,
                    "transcription": result.transcription
                    if result.transcription is not None
                    else result.text,
                    "detected_language": result.language,
                    "source_language": result.language,
                    "output_language": result.output_language or result.language,
                    "translated": result.translated,
                }
                if result.language_probability is not None:
                    payload["language_probability"] = result.language_probability
                if result.segments is not None:
                    payload["segments"] = [
                        {
                            "start": item.start_seconds,
                            "end": item.end_seconds,
                            "text": item.text,
                        }
                        for item in result.segments
                    ]
                return web.json_response(payload)
            except SpeechFailure as exc:
                set_outcome(_metric_outcome(exc.code))
                status, error = safe_error(exc)
                return web.json_response(
                    {"code": error.code, "message": error.message}, status=status
                )

            except (ConnectionResetError, asyncio.CancelledError):
                if context is not None:
                    context.cancel()
                if worker_task is not None:
                    try:
                        await asyncio.shield(worker_task)
                    except Exception:
                        pass
                if request.transport is not None and request.transport.is_closing():
                    set_outcome("timeout")
                    raise ConnectionResetError
                raise
            except web.HTTPRequestEntityTooLarge:
                set_outcome("input_limit")
                return web.json_response(
                    {
                        "code": FailureCode.INPUT_LIMIT.value,
                        "message": "request exceeds the configured limit",
                    },
                    status=413,
                )
            except (ValueError, web.HTTPException):
                set_outcome("invalid_input")
                return web.json_response(
                    {"code": "invalid_input", "message": "request is invalid"},
                    status=400,
                )
            except Exception:
                context.cancel()
                if worker_task is not None:
                    try:
                        await asyncio.shield(worker_task)
                    except Exception:
                        pass
                set_outcome("backend_error")
                return web.json_response(
                    {"code": "backend_failed", "message": "inference failed"},
                    status=500,
                )

    async def warmup(request):
        context = None
        worker_task = None
        try:
            context = _operation_context(
                request, application.config.admission.request_timeout_seconds
            )
            await _validate_empty_warmup_body(request, context, maximum)
            worker_task = asyncio.create_task(
                asyncio.to_thread(application.warmup, context)
            )
            while not worker_task.done():
                if _disconnected(request):
                    raise ConnectionResetError
                remaining = _remaining(context)
                if remaining <= 0:
                    worker_task.add_done_callback(_consume_task_result)
                    status, error = safe_error(
                        SpeechFailure(FailureCode.DEADLINE_EXCEEDED)
                    )
                    return web.json_response(
                        {"code": error.code, "message": error.message}, status=status
                    )
                await asyncio.wait({worker_task}, timeout=min(remaining, 0.05))
            return web.json_response(await worker_task)
        except SpeechFailure as exc:
            status, error = safe_error(exc)
            return web.json_response(
                {"code": error.code, "message": error.message}, status=status
            )
        except (ConnectionResetError, asyncio.CancelledError):
            if context is not None:
                context.cancel()
            if worker_task is not None:
                worker_task.add_done_callback(_consume_task_result)
            raise
        except web.HTTPException:
            status, error = safe_error(SpeechFailure(FailureCode.INVALID_INPUT))
            return web.json_response(
                {"code": error.code, "message": error.message}, status=status
            )

    async def on_startup(_app):
        _app[STARTUP_TASK_KEY] = asyncio.create_task(
            asyncio.to_thread(application.start)
        )

    async def on_cleanup(_app):
        startup_task = _app.get(STARTUP_TASK_KEY)
        if startup_task is not None:
            try:
                await asyncio.shield(startup_task)
            except Exception:
                pass
        await asyncio.to_thread(application.close)

    http_app.on_startup.append(on_startup)
    http_app.on_cleanup.append(on_cleanup)
    http_app.router.add_get("/healthz", health)
    http_app.router.add_get("/readyz", ready)
    http_app.router.add_get("/metrics", prometheus)
    http_app.router.add_post("/internal/v1/transcriptions", transcriptions)
    http_app.router.add_post("/internal/v1/warmup", warmup)
    return http_app


def _operation_context(request, maximum_seconds):
    raw = request.headers.get("X-Request-Timeout-Ms")
    if raw is None or len(raw) > 10 or not raw.isascii() or not raw.isdecimal():
        raise SpeechFailure(FailureCode.INVALID_INPUT, "request timeout is invalid")
    try:
        milliseconds = int(raw)
    except ValueError as exc:
        raise SpeechFailure(FailureCode.INVALID_INPUT) from exc
    if milliseconds < 1:
        raise SpeechFailure(FailureCode.INVALID_INPUT, "request timeout is invalid")
    timeout = min(milliseconds / 1000, maximum_seconds)
    return OperationContext(time.monotonic() + timeout)


async def _validate_empty_warmup_body(request, context, maximum):
    if request.content_length is not None and request.content_length > maximum:
        raise SpeechFailure(FailureCode.INPUT_LIMIT)
    if request.content_length not in (None, 0):
        raise SpeechFailure(FailureCode.INVALID_INPUT, "request body must be empty")
    if request.headers.get("Transfer-Encoding"):
        raise SpeechFailure(FailureCode.INVALID_INPUT, "request body must be empty")
    if request.can_read_body:
        remaining = _remaining(context)
        if remaining <= 0:
            raise SpeechFailure(FailureCode.DEADLINE_EXCEEDED)
        try:
            body_byte = await asyncio.wait_for(request.content.read(1), remaining)
        except asyncio.TimeoutError as exc:
            raise SpeechFailure(FailureCode.DEADLINE_EXCEEDED) from exc
        if body_byte:
            raise SpeechFailure(FailureCode.INVALID_INPUT, "request body must be empty")


async def _next_part(reader, context, request):
    context.check()
    if _disconnected(request):
        raise ConnectionResetError
    timeout = _remaining(context)
    if timeout <= 0:
        raise SpeechFailure(FailureCode.DEADLINE_EXCEEDED)
    try:
        return await asyncio.wait_for(reader.next(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        raise SpeechFailure(FailureCode.DEADLINE_EXCEEDED) from exc


async def _read_chunk(part, context, request):
    context.check()
    if _disconnected(request):
        raise ConnectionResetError
    timeout = _remaining(context)
    if timeout <= 0:
        raise SpeechFailure(FailureCode.DEADLINE_EXCEEDED)
    try:
        return await asyncio.wait_for(part.read_chunk(size=64 * 1024), timeout=timeout)
    except asyncio.TimeoutError as exc:
        raise SpeechFailure(FailureCode.DEADLINE_EXCEEDED) from exc


async def _read_text_part(part, context, request):
    chunks = []
    size = 0
    while chunk := await _read_chunk(part, context, request):
        size += len(chunk)
        if size > 256:
            raise SpeechFailure(FailureCode.INPUT_LIMIT)
        chunks.append(chunk)
    try:
        return b"".join(chunks).decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise SpeechFailure(FailureCode.INVALID_INPUT) from exc


async def _wait_for_result(task, context, request):
    while not task.done():
        if _disconnected(request):
            context.cancel()
            task.add_done_callback(_consume_task_result)
            raise ConnectionResetError
        if context.cancelled():
            context.cancel()
            task.add_done_callback(_consume_task_result)
            context.check()
        await asyncio.wait(
            {task},
            timeout=min(_remaining(context), 0.05) if _remaining(context) > 0 else 0.05,
        )
    if _disconnected(request):
        context.cancel()
        task.add_done_callback(_consume_task_result)
        raise ConnectionResetError
    if context.cancelled():
        task.add_done_callback(_consume_task_result)
        context.check()
    result = await task
    context.check()
    return result


def _remaining(context):
    if context.deadline is None:
        return float("inf")
    return max(0.0, context.deadline - time.monotonic())


def _consume_task_result(task):
    try:
        task.result()
    except (Exception, asyncio.CancelledError):
        pass


def _disconnected(request):
    transport = request.transport
    return transport is None or transport.is_closing()


def _boolean(value):
    if value not in {"true", "false"}:
        raise ValueError("boolean field must be true or false")
    return value == "true"


def _metric_outcome(code):
    if code in {
        FailureCode.INVALID_INPUT,
        FailureCode.UNSUPPORTED_OPTION,
        FailureCode.UNSUPPORTED_MEDIA_TYPE,
        FailureCode.UNSUPPORTED_DETECTED_LANGUAGE,
        FailureCode.UNSUPPORTED_TRANSLATION,
    }:
        return "invalid_input"
    if code == FailureCode.OVERLOADED:
        return "overloaded"
    if code in {
        FailureCode.NOT_READY,
        FailureCode.DEVICE_UNAVAILABLE,
        FailureCode.MODEL_LOAD_FAILED,
    }:
        return "not_ready"
    if code in {FailureCode.DEADLINE_EXCEEDED, FailureCode.CANCELLED}:
        return "timeout"
    if code == FailureCode.DECODE_FAILED:
        return "decode_error"
    return "backend_error"


async def serve(application, listen_host, listen_port, socket_timeout_seconds):
    http_app = create_http_app(application)
    runner = web.AppRunner(
        http_app, access_log=None, shutdown_timeout=socket_timeout_seconds
    )
    await runner.setup()
    site = web.TCPSite(runner, listen_host, listen_port)
    await site.start()
    print(json.dumps({"event": "worker_starting", "kind": "stt"}), flush=True)
    loop = asyncio.get_running_loop()
    stopping = asyncio.Event()
    for name in ("SIGINT", "SIGTERM"):
        import signal

        loop.add_signal_handler(getattr(signal, name), stopping.set)
    try:
        await stopping.wait()
    finally:
        await runner.cleanup()
