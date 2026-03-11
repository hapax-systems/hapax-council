"""shared/transcript_parser.py — Parse meeting transcripts in VTT, SRT, and speaker-labeled formats.

Stdlib-only. No external dependencies.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TranscriptSegment:
    """A single segment of a transcript."""
    speaker: str
    text: str
    start_time: str = ""
    end_time: str = ""


def parse_transcript(path: Path) -> list[TranscriptSegment]:
    """Auto-detect and parse a transcript file.

    Supports:
    - VTT (WebVTT from Teams/Zoom)
    - SRT (SubRip subtitle format)
    - Speaker-labeled plain text (e.g., "Alice: Hello...")
    """
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    fmt = _detect_format(content)
    if fmt == "vtt":
        return _parse_vtt(content)
    elif fmt == "srt":
        return _parse_srt(content)
    else:
        return _parse_speaker_labeled(content)


def _detect_format(content: str) -> str:
    """Detect transcript format from content."""
    stripped = content.strip()
    if stripped.startswith("WEBVTT"):
        return "vtt"
    # SRT: starts with a number followed by timestamp line
    lines = stripped.split("\n", 5)
    if len(lines) >= 2:
        if re.match(r"^\d+$", lines[0].strip()) and "-->" in lines[1]:
            return "srt"
    return "speaker-labeled"


def _parse_vtt(content: str) -> list[TranscriptSegment]:
    """Parse WebVTT format.

    Handles:
    - Standard VTT with timestamps
    - Speaker tags like <v Alice>text
    """
    segments: list[TranscriptSegment] = []

    # Split into blocks separated by blank lines
    blocks = re.split(r"\n\s*\n", content)

    for block in blocks:
        lines = block.strip().split("\n")
        if not lines:
            continue

        # Skip header
        if lines[0].strip().startswith("WEBVTT"):
            continue

        # Find timestamp line
        timestamp_line = None
        text_lines: list[str] = []
        for line in lines:
            if "-->" in line:
                timestamp_line = line.strip()
            elif timestamp_line is not None:
                text_lines.append(line.strip())

        if not timestamp_line or not text_lines:
            continue

        # Parse timestamps
        ts_match = re.match(r"([\d:.]+)\s*-->\s*([\d:.]+)", timestamp_line)
        start_time = ts_match.group(1) if ts_match else ""
        end_time = ts_match.group(2) if ts_match else ""

        # Join text lines and extract speaker
        full_text = " ".join(text_lines)

        # Check for VTT speaker tags: <v Speaker Name>text
        speaker_match = re.match(r"<v\s+([^>]+)>(.*)", full_text)
        if speaker_match:
            speaker = speaker_match.group(1).strip()
            text = speaker_match.group(2).strip()
        else:
            speaker = ""
            text = full_text

        # Clean up any remaining HTML-like tags
        text = re.sub(r"<[^>]+>", "", text).strip()

        if text:
            segments.append(TranscriptSegment(
                speaker=speaker,
                text=text,
                start_time=start_time,
                end_time=end_time,
            ))

    return segments


def _parse_srt(content: str) -> list[TranscriptSegment]:
    """Parse SRT (SubRip) format."""
    segments: list[TranscriptSegment] = []

    blocks = re.split(r"\n\s*\n", content.strip())

    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 3:
            continue

        # First line: sequence number (skip)
        # Second line: timestamps
        ts_line = lines[1].strip()
        ts_match = re.match(r"([\d:,]+)\s*-->\s*([\d:,]+)", ts_line)
        if not ts_match:
            continue

        start_time = ts_match.group(1).replace(",", ".")
        end_time = ts_match.group(2).replace(",", ".")

        # Remaining lines: text
        text = " ".join(line.strip() for line in lines[2:] if line.strip())

        # Try to extract speaker from "Speaker: text" pattern
        speaker_match = re.match(r"^([A-Z][a-zA-Z\s]+):\s*(.*)", text)
        if speaker_match:
            speaker = speaker_match.group(1).strip()
            text = speaker_match.group(2).strip()
        else:
            speaker = ""

        if text:
            segments.append(TranscriptSegment(
                speaker=speaker,
                text=text,
                start_time=start_time,
                end_time=end_time,
            ))

    return segments


def _parse_speaker_labeled(content: str) -> list[TranscriptSegment]:
    """Parse speaker-labeled plain text format.

    Expects lines like:
    Alice: Hello, how are you?
    Bob: I'm good, thanks.
    """
    segments: list[TranscriptSegment] = []
    current_speaker = ""
    current_lines: list[str] = []

    for line in content.split("\n"):
        line = line.strip()
        if not line:
            continue

        # Check for "Speaker: text" pattern
        speaker_match = re.match(r"^([A-Z][a-zA-Z\s]{0,30}):\s+(.*)", line)
        if speaker_match:
            # Save previous segment
            if current_speaker and current_lines:
                segments.append(TranscriptSegment(
                    speaker=current_speaker,
                    text=" ".join(current_lines),
                ))
            current_speaker = speaker_match.group(1).strip()
            current_lines = [speaker_match.group(2).strip()]
        elif current_speaker:
            # Continuation of current speaker
            current_lines.append(line)

    # Save last segment
    if current_speaker and current_lines:
        segments.append(TranscriptSegment(
            speaker=current_speaker,
            text=" ".join(current_lines),
        ))

    return segments


def format_as_text(segments: list[TranscriptSegment]) -> str:
    """Format transcript segments as readable text."""
    lines: list[str] = []
    for seg in segments:
        if seg.speaker:
            lines.append(f"{seg.speaker}: {seg.text}")
        else:
            lines.append(seg.text)
    return "\n".join(lines)


def map_speakers_to_people(
    segments: list[TranscriptSegment],
    people: list,
) -> dict[str, str]:
    """Fuzzy-match transcript speaker names to PersonState names.

    Returns mapping of transcript_speaker -> person_name.
    Unmatched speakers are kept as-is.
    """
    mapping: dict[str, str] = {}
    speaker_names = {seg.speaker for seg in segments if seg.speaker}

    for speaker in speaker_names:
        speaker_lower = speaker.lower().strip()
        best_match = speaker  # default: keep as-is

        for person in people:
            person_name = getattr(person, "name", str(person))
            # Exact match
            if speaker_lower == person_name.lower():
                best_match = person_name
                break
            # First name match
            if speaker_lower == person_name.lower().split()[0]:
                best_match = person_name
                break
            # Last name match
            parts = person_name.lower().split()
            if len(parts) > 1 and speaker_lower == parts[-1]:
                best_match = person_name
                break

        mapping[speaker] = best_match

    return mapping
