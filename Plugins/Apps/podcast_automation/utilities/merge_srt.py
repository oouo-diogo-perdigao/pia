# Este script une dois arquivos SRT sequencialmente, ajustando os timestamps do segundo arquivo para que comecem após o término do primeiro arquivo. O resultado é salvo em um novo arquivo SRT.
# Uso: python merge_srt.py primeiro.srt segundo.srt -o resultado.srt
import argparse
import re
from pathlib import Path

TIMESTAMP = re.compile(r"^(\d+):(\d{2}):(\d{2}),(\d{3})$")
TIMING_LINE = re.compile(
    r"^(\d+:\d{2}:\d{2},\d{3})\s+-->\s+" r"(\d+:\d{2}:\d{2},\d{3})$"
)


def to_ms(timestamp):
    match = TIMESTAMP.fullmatch(timestamp)
    if not match:
        raise ValueError(f"Timestamp inválido: {timestamp}")

    hours, minutes, seconds, millis = map(int, match.groups())
    return (hours * 3600 + minutes * 60 + seconds) * 1000 + millis


def from_ms(milliseconds):
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def read_srt(path):
    content = Path(path).read_text(encoding="utf-8-sig")
    content = content.replace("\r\n", "\n").replace("\r", "\n")

    subtitles = []

    for block in re.split(r"\n\s*\n", content.strip()):
        lines = block.split("\n")

        if not lines:
            continue

        # Localiza a linha de timestamps.
        timing_index = next(
            (i for i, line in enumerate(lines) if TIMING_LINE.fullmatch(line.strip())),
            None,
        )

        if timing_index is None:
            raise ValueError(f"Bloco SRT inválido em {path}:\n{block}")

        match = TIMING_LINE.fullmatch(lines[timing_index].strip())

        start, end = match.groups()
        text = "\n".join(lines[timing_index + 1 :])

        subtitles.append({"start": to_ms(start), "end": to_ms(end), "text": text})

    return subtitles


def merge_srt(first_file, second_file, output_file):
    first = read_srt(first_file)
    second = read_srt(second_file)

    if not first:
        raise ValueError("O primeiro arquivo não contém legendas.")

    if not second:
        raise ValueError("O segundo arquivo não contém legendas.")

    # Último horário de término do primeiro arquivo.
    offset = max(subtitle["end"] for subtitle in first)

    # Desloca todos os timestamps do segundo arquivo.
    for subtitle in second:
        subtitle["start"] += offset
        subtitle["end"] += offset

    merged = first + second

    # Renumera todas as legendas sequencialmente.
    blocks = []

    for index, subtitle in enumerate(merged, start=1):
        start = from_ms(subtitle["start"])
        end = from_ms(subtitle["end"])

        blocks.append(f"{index}\n{start} --> {end}\n{subtitle['text']}")

    output = "\n\n".join(blocks) + "\n"

    Path(output_file).write_text(output, encoding="utf-8-sig")

    print(f"Arquivo criado: {output_file}")
    print(f"Legendas do primeiro arquivo: {len(first)}")
    print(f"Legendas do segundo arquivo: {len(second)}")
    print(f"Total de legendas: {len(merged)}")
    print(f"Deslocamento aplicado: {from_ms(offset)}")


def main():
    parser = argparse.ArgumentParser(
        description="Une dois arquivos SRT sequencialmente."
    )

    parser.add_argument("primeiro", help="Primeiro arquivo SRT")
    parser.add_argument("segundo", help="Segundo arquivo SRT")

    parser.add_argument("-o", "--output", default="merged.srt", help="Arquivo de saída")

    args = parser.parse_args()

    merge_srt(args.primeiro, args.segundo, args.output)


if __name__ == "__main__":
    main()
