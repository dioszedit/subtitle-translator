"""SRT beolvasás/írás — a projekt EGYETLEN kanonikus parsere.

A refaktor előtt 5+ parse-változat élt a scriptekben, három különböző
kimeneti alakkal. Itt egy közös tokenizáló van (split_blocks), és fölötte
vékony "nézetek" — a hívó a nézetet választja, nem külön parsert:

  - parse_sections():   [{num, timestamp, text}]   (translate / verify)
  - parse_entries():    [nyers blokk-string]        (review)
  - parse_by_index():   {sorszám: (időbélyeg, szöveg)}  (forrás-párosítás)
  - parse_blocks_with_index(): (blokk-lista, {sorszám: index})  (apply_review)

Viselkedési döntés (szándékos): a 2 soros blokk (sorszám + időbélyeg,
üres szöveg) ÉRVÉNYES szekció üres text-tel — a megengedőbb (verify/gemini)
változat a kanonikus; a codex-parser korábban ezeket csendben eldobta.
"""

import re

# Minden olvasás utf-8-sig: a Windows-os szerkesztők BOM-ját lenyeli.
ENCODING_READ = "utf-8-sig"
ENCODING_WRITE = "utf-8"


def read_text(filepath: str) -> str:
    with open(filepath, "r", encoding=ENCODING_READ) as f:
        return f.read()


def split_blocks(content: str) -> list[str]:
    """A kanonikus tokenizáló: üres sor(ok) mentén blokkokra vág,
    a blokkokat strip-eli, az üreseket eldobja."""
    return [b.strip() for b in re.split(r"\n\s*\n", content.strip()) if b.strip()]


def parse_sections(filepath: str) -> list[dict]:
    """SRT szekciók kinyerése: {num, timestamp, text}.

    A num/timestamp string marad (a pipeline 1:1 másolja őket, nem értelmezi);
    a 2 soros blokk üres text-tel kerül be."""
    sections = []
    for block in split_blocks(read_text(filepath)):
        lines = block.split("\n")
        if len(lines) >= 3:
            sections.append({
                "num": lines[0].strip(),
                "timestamp": lines[1].strip(),
                "text": "\n".join(lines[2:]),
            })
        elif len(lines) == 2:
            sections.append({"num": lines[0].strip(),
                             "timestamp": lines[1].strip(), "text": ""})
    return sections


def parse_entries(filepath: str) -> list[str]:
    """SRT blokkok nyers szövegként (csak a legalább 3 sorosak) —
    a review-k chunkolása ezen az alakon dolgozik."""
    return [b for b in split_blocks(read_text(filepath))
            if len(b.split("\n")) >= 3]


def parse_by_index(filepath: str) -> dict:
    """SRT beolvasása: {sorszám: (időbélyeg, szöveg egyben)}.

    A forrásnyelvi SRT-hez kell — az időbélyeg az igazítás-ellenőrzéshez,
    a szöveg (sorok ' | '-lel összefűzve) a review kontextushoz."""
    entries = {}
    for block in split_blocks(read_text(filepath)):
        lines = block.split("\n")
        if len(lines) >= 3:
            try:
                idx = int(lines[0].strip())
            except ValueError:
                continue
            entries[idx] = (lines[1].strip(),
                            " | ".join(l.strip() for l in lines[2:] if l.strip()))
    return entries


def parse_blocks_with_index(filepath: str):
    """SRT beolvasása: (blokk-lista, {sorszám: blokk-index}) — a blokkok
    sorrendje és a nem szabványos blokkok is megőrződnek (apply_review)."""
    blocks = split_blocks(read_text(filepath))
    index = {}
    for i, block in enumerate(blocks):
        lines = block.split("\n")
        if len(lines) >= 2 and "-->" in lines[1]:
            try:
                index[int(lines[0].strip())] = i
            except ValueError:
                continue
    return blocks, index


def write_srt(filepath: str, sections: list[dict]):
    """SRT írása — szekciók közt üres sor, fájl végén egy újsor."""
    out = [f"{s['num']}\n{s['timestamp']}\n{s['text']}" for s in sections]
    with open(filepath, "w", encoding=ENCODING_WRITE) as f:
        f.write("\n\n".join(out) + "\n")


def count_sections(filepath: str) -> int:
    """Strukturális számlálás: csak az a csupa-számjegy sor számít szekciónak,
    amit időbélyeg-sor követ. Így a csak számot tartalmazó felirat-SZÖVEG
    (pl. visszaszámlálás: "3") nem torzítja az ellenőrzést."""
    try:
        lines = read_text(filepath).split("\n")
        return sum(1 for i, line in enumerate(lines)
                   if re.match(r"^\d+$", line.strip())
                   and i + 1 < len(lines) and "-->" in lines[i + 1])
    except Exception:
        return 0
