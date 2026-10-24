"""Validation and subtitle rendering for provider-produced segment timestamps."""
import math


def timed_result(result):
    """Reject missing/invalid timing, including text incorrectly marked as silence."""
    duration = result.get("duration")
    segments = result.get("segments")
    if not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration < 0:
        raise ValueError("Duração real do áudio indisponível.")
    if not isinstance(segments, list) or (result.get("text") and not segments):
        raise ValueError("Provider não retornou timestamps reais para o texto.")
    normalized = []
    previous = 0.0
    for segment in segments:
        if not isinstance(segment, dict):
            raise ValueError("Provider retornou um segmento inválido.")
        start, end = segment.get("start"), segment.get("end")
        if (not isinstance(start, (int, float)) or not isinstance(end, (int, float))
                or not math.isfinite(start) or not math.isfinite(end)
                or start < previous or end < start or end > duration + 0.1):
            raise ValueError("Provider retornou timestamps inválidos.")
        text = str(segment.get("text") or "").strip()
        if text:
            normalized.append({"id": len(normalized), "start": start, "end": end, "text": text})
        previous = start
    if result.get("text") and not normalized:
        raise ValueError("Provider não retornou segmentos com fala.")
    return {**result, "segments": normalized}


def subtitle_timestamp(seconds, separator):
    milliseconds = round(seconds * 1000)
    hours, milliseconds = divmod(milliseconds, 3600000)
    minutes, milliseconds = divmod(milliseconds, 60000)
    seconds, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02}{separator}{milliseconds:03}"


def render_subtitles(segments, response_format):
    separator = "," if response_format == "srt" else "."
    cues = []
    for i, segment in enumerate(segments, 1):
        start = subtitle_timestamp(segment["start"], separator)
        end = subtitle_timestamp(segment["end"], separator)
        # Empty lines delimit cues; preserve text while preventing accidental cue breaks.
        text = " ".join(segment["text"].splitlines()).strip()
        cues.append(f"{i}\n{start} --> {end}\n{text}\n\n")
    return ("WEBVTT\n\n" if response_format == "vtt" else "") + "".join(cues)
