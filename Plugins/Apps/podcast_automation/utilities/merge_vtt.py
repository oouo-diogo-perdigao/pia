# Este script une dois arquivos VTT (Web Video Text Tracks) sequencialmente, ajustando os timestamps do segundo arquivo para que comecem imediatamente após o último timestamp do primeiro arquivo. O resultado é salvo em um novo arquivo VTT.
# uso: python merge_vtt.py primeiro.vtt segundo.vtt -o resultado.vtt

import argparse
import re
from pathlib import Path

TIMESTAMP = re.compile(r"(?<!\d)(?:(\d{2,}):)?(\d{2}):(\d{2})\.(\d{3})(?!\d)")
TIMING_LINE = re.compile(r"^\s*(\S+)\s+-->\s+(\S+)(.*)$")


def to_ms(timestamp):
    match = TIMESTAMP.fullmatch(timestamp)
    if not match:
        raise ValueError(f"Timestamp inválido: {timestamp}")

    hours, minutes, seconds, millis = match.groups()
    return (int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds)) * 1000 + int(
        millis
    )


def from_ms(milliseconds):
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


def read_vtt(path):
    content = Path(path).read_text(encoding="utf-8-sig")
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    lines = content.split("\n")

    if not lines[0].startswith("WEBVTT"):
        raise ValueError(f"Arquivo VTT inválido: {path}")

    return lines


def get_last_timestamp(lines):
    last_end = None

    for line in lines:
        match = TIMING_LINE.match(line)
        if match:
            end = to_ms(match.group(2))
            last_end = max(last_end or 0, end)

    if last_end is None:
        raise ValueError("Nenhuma legenda encontrada no primeiro arquivo.")

    return last_end


def shift_timestamps(lines, offset):
    result = []

    for line in lines:
        match = TIMING_LINE.match(line)

        if match:
            start, end, settings = match.groups()
            new_start = from_ms(to_ms(start) + offset)
            new_end = from_ms(to_ms(end) + offset)
            result.append(f"{new_start} --> {new_end}{settings}")
        else:
            result.append(line)

    return result


def merge_vtt(first_file, second_file, output_file):
    first = read_vtt(first_file)
    second = read_vtt(second_file)

    offset = get_last_timestamp(first)

    # Remove o cabeçalho e os metadados iniciais do segundo VTT.
    index = 1
    while index < len(second) and second[index].strip():
        index += 1

    while index < len(second) and not second[index].strip():
        index += 1

    second = shift_timestamps(second[index:], offset)

    # Garante separação entre os dois conjuntos de legendas.
    merged = "\n".join(first).rstrip()
    merged += "\n\n" + "\n".join(second).strip() + "\n"

    Path(output_file).write_text(merged, encoding="utf-8")

    print(f"Arquivo criado: {output_file}")
    print(f"Deslocamento aplicado: {from_ms(offset)}")


def main():
    parser = argparse.ArgumentParser(
        description="Une dois arquivos VTT sequencialmente."
    )
    parser.add_argument("primeiro", help="Primeiro arquivo VTT")
    parser.add_argument("segundo", help="Segundo arquivo VTT")
    parser.add_argument("-o", "--output", default="merged.vtt", help="Arquivo de saída")

    args = parser.parse_args()
    merge_vtt(args.primeiro, args.segundo, args.output)


if __name__ == "__main__":
    main()
