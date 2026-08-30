"""A Claude Read tool sorszám-prefixének felismerése és eltávolítása.

Valós hiba: az agent a Read megjelenítési formáját (`sorszám<TAB>tartalom`)
másolta a kiírt SRT-be, így a szekciószámláló 0-t adott, és a kész fordítás
törlésre került.
"""

from subtr.providers.claude_cli import strip_read_line_numbers
from subtr.srt import count_sections_text

# Ahogy a hibás kimenet tényleg kinézett (Pull Strings S01E06, 001-es blokk)
BROKEN = (
    "1\t1\n"
    "2\t00:00:12,530 --> 00:00:20,580\n"
    "3\t♪Az őskáoszból a csillagos égig♪\n"
    "4\n"
    "5\t2\n"
    "6\t00:00:20,580 --> 00:00:28,340\n"
    "7\t♪Az egész világban\n"
    "mi tartjuk fenn az egyensúlyt♪\n"
    "8\n"
    "9\t3\n"
    "10\t00:00:44,920 --> 00:00:46,940\n"
    "11\t[Az óvatos halhatatlan]\n"
    "[Pull Strings]\n"
)

CLEAN = (
    "1\n"
    "00:00:12,530 --> 00:00:20,580\n"
    "♪Az őskáoszból a csillagos égig♪\n"
    "\n"
    "2\n"
    "00:00:20,580 --> 00:00:28,340\n"
    "♪Az egész világban\n"
    "mi tartjuk fenn az egyensúlyt♪\n"
    "\n"
    "3\n"
    "00:00:44,920 --> 00:00:46,940\n"
    "[Az óvatos halhatatlan]\n"
    "[Pull Strings]\n"
)


def test_broken_output_counts_as_zero_sections():
    """Ez a tünet, amit a felhasználó lát: Input 150, Output 0."""
    assert count_sections_text(BROKEN) == 0


def test_repair_restores_the_original_srt():
    assert strip_read_line_numbers(BROKEN) == CLEAN
    assert count_sections_text(CLEAN) == 3


def test_multiline_cue_continuation_is_kept_verbatim():
    """A többsoros felirat folytatássora nem kap sorszámot — nem szabad
    hozzányúlni, és nem szabad elcsúsztatnia a számlálót."""
    out = strip_read_line_numbers(BROKEN)
    assert "♪Az egész világban\nmi tartjuk fenn az egyensúlyt♪" in out
    assert "[Az óvatos halhatatlan]\n[Pull Strings]" in out


def test_healthy_srt_is_left_alone():
    """Ép SRT-t nem szabad megbolygatni: az első sor '1', ami önmagában
    ugyanúgy néz ki, mint egy prefix-maradvány."""
    assert strip_read_line_numbers(CLEAN) is None


def test_plain_text_without_prefixes_returns_none():
    assert strip_read_line_numbers("csak sima szöveg\nmásodik sor\n") is None


def test_empty_input():
    assert strip_read_line_numbers("") is None


def test_trailing_newline_is_preserved():
    assert strip_read_line_numbers("1\ta\n2\tb\n").endswith("b\n")
    assert strip_read_line_numbers("1\ta\n2\tb") == "a\nb"


def test_crlf_prefixed_output_is_repaired():
    broken = "1\t1\r\n2\t00:00:01,000 --> 00:00:02,000\r\n3\tSzia!\r\n4\r\n5\t2\r\n6\t00:00:03,000 --> 00:00:04,000\r\n7\tHé!\r\n"
    assert strip_read_line_numbers(broken) == (
        "1\r\n00:00:01,000 --> 00:00:02,000\r\nSzia!\r\n\r\n2\r\n00:00:03,000 --> 00:00:04,000\r\nHé!\r\n")


def test_cat_n_style_aligned_prefix_is_repaired():
    broken = "     1\t1\n     2\t00:00:01,000 --> 00:00:02,000\n     3\tSzia!\n     4\n"
    assert strip_read_line_numbers(broken) == "1\n00:00:01,000 --> 00:00:02,000\nSzia!\n\n"
