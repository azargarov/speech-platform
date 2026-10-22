"""Parser for the intentionally small, bounded M04 SSML subset."""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


SSML_NAMESPACE = "http://www.w3.org/2001/10/synthesis"
XML_LANGUAGE = "{http://www.w3.org/XML/1998/namespace}lang"
_TIME = re.compile(r"^(?:(\d+)ms|(\d+(?:\.\d{1,3})?)s)$")
_LANGUAGE = re.compile(r"^(en|ru|sv)(?:-([A-Za-z]{2}))?$", re.IGNORECASE)
_FORMATTING_PREFIX = re.compile(r"^[ \t]*[\r\n]+[ \t]*")
_FORMATTING_SUFFIX = re.compile(r"[ \t]*[\r\n]+[ \t]*$")
_FORMATTING_NEWLINE = re.compile(r"[ \t]*[\r\n]+[ \t]*")


class SSMLValidationError(ValueError):
    """Safe, user-correctable error in the supported SSML subset."""


@dataclass(frozen=True)
class SpeechSegment:
    text: str
    language: str


@dataclass(frozen=True)
class SilenceSegment:
    duration_ms: int


Segment = SpeechSegment | SilenceSegment


def parse_ssml(document: str, config: dict) -> list[Segment]:
    try:
        encoded = document.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise SSMLValidationError("SSML must be valid Unicode text") from error
    if len(encoded) > config["max_ssml_bytes"]:
        raise SSMLValidationError("SSML document size limit exceeded")
    upper = encoded.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise SSMLValidationError("DTD and entity declarations are not supported")
    try:
        root = ET.fromstring(document)
    except (ET.ParseError, ValueError) as error:
        raise SSMLValidationError("SSML document is not well-formed XML") from error

    if root.tag != f"{{{SSML_NAMESPACE}}}speak":
        raise SSMLValidationError("SSML root must be speak in the SSML namespace")
    if (
        set(root.attrib) != {"version", XML_LANGUAGE}
        or root.attrib.get("version") != "1.1"
    ):
        raise SSMLValidationError(
            'speak requires only version="1.1" and xml:lang attributes'
        )
    root_language = _language(root.attrib[XML_LANGUAGE])
    segments: list[Segment] = []
    total_characters = 0
    total_silence_ms = 0
    element_count = 1

    def append_text(value: str | None, language: str) -> None:
        nonlocal total_characters
        if value and ("\n" in value or "\r" in value):
            value = _FORMATTING_PREFIX.sub("", value, count=1)
            value = _FORMATTING_SUFFIX.sub("", value, count=1)
            value = _FORMATTING_NEWLINE.sub(" ", value)
        if not value or not value.strip():
            return
        total_characters += len(value)
        if total_characters > config["max_text_characters"]:
            raise SSMLValidationError("SSML speech character limit exceeded")
        if (
            segments
            and isinstance(segments[-1], SpeechSegment)
            and segments[-1].language == language
        ):
            previous = segments[-1]
            segments[-1] = SpeechSegment(previous.text + value, language)
        else:
            segments.append(SpeechSegment(value, language))
            if (
                sum(isinstance(item, SpeechSegment) for item in segments)
                > config["max_ssml_segments"]
            ):
                raise SSMLValidationError("SSML speech segment limit exceeded")

    def visit(element: ET.Element, language: str, depth: int) -> None:
        nonlocal total_silence_ms, element_count
        append_text(element.text, language)
        for child in element:
            element_count += 1
            if element_count > config["max_ssml_elements"]:
                raise SSMLValidationError("SSML element count limit exceeded")
            if child.tag == f"{{{SSML_NAMESPACE}}}lang":
                if depth + 1 > config["max_ssml_nesting_depth"]:
                    raise SSMLValidationError("SSML language nesting limit exceeded")
                if set(child.attrib) != {XML_LANGUAGE}:
                    raise SSMLValidationError(
                        "lang requires only the xml:lang attribute"
                    )
                child_language = _language(child.attrib[XML_LANGUAGE])
                visit(child, child_language, depth + 1)
            elif child.tag == f"{{{SSML_NAMESPACE}}}break":
                if (
                    set(child.attrib) != {"time"}
                    or len(child)
                    or (child.text and child.text.strip())
                ):
                    raise SSMLValidationError(
                        "break requires only a time attribute and must be empty"
                    )
                duration_ms = _duration_ms(child.attrib["time"])
                if duration_ms > config["max_ssml_break_ms"]:
                    raise SSMLValidationError("SSML break duration limit exceeded")
                total_silence_ms += duration_ms
                if total_silence_ms > config["max_ssml_total_silence_ms"]:
                    raise SSMLValidationError("SSML total silence limit exceeded")
                segments.append(SilenceSegment(duration_ms))
            else:
                raise SSMLValidationError("unsupported SSML element")
            append_text(child.tail, language)

    visit(root, root_language, 0)
    if not any(isinstance(segment, SpeechSegment) for segment in segments):
        raise SSMLValidationError("SSML must contain at least one speech segment")
    _check_estimated_output(segments, total_characters, total_silence_ms, config)
    return segments


def _language(tag: str) -> str:
    match = _LANGUAGE.fullmatch(tag)
    if not match:
        raise SSMLValidationError(
            "xml:lang must be en, ru, sv, or a two-letter region thereof"
        )
    return match.group(1).lower()


def _duration_ms(value: str) -> int:
    match = _TIME.fullmatch(value)
    if not match:
        raise SSMLValidationError(
            "break time must use integer ms or seconds to millisecond precision"
        )
    try:
        duration = (
            int(match.group(1))
            if match.group(1)
            else int(Decimal(match.group(2)) * 1000)
        )
    except (InvalidOperation, ValueError, OverflowError) as error:
        raise SSMLValidationError("break time is invalid") from error
    if duration < 0:
        raise SSMLValidationError("break time must not be negative")
    return duration


def _check_estimated_output(
    segments: list[Segment], text_characters: int, silence_ms: int, config: dict
) -> None:
    speech_segments = sum(isinstance(segment, SpeechSegment) for segment in segments)
    estimated_seconds = (
        text_characters / config["ssml_estimated_characters_per_second"]
        + speech_segments * config["ssml_segment_overhead_seconds"]
        + silence_ms / 1000
    )
    estimated_bytes = math.ceil(estimated_seconds * 48000 * 2) + 44
    if estimated_bytes > config["max_output_audio_bytes"]:
        raise SSMLValidationError(
            "estimated SSML output exceeds the configured size limit"
        )
