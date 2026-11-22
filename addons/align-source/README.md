# align-source add-on (forrás igazítása külső fordításhoz)

Akkor kell, ha egy **kész, máshonnan származó magyar fordítást** lektorálsz, és
annak a feliratai nem egyeznek a forrás feliratbeosztásával. A külső fordítók
gyakran összevonják a rövid feliratokat: a magyar fájlban 450 felirat van, az
angolban 750. Ilyenkor a `subtr.py review` sorszám szerinti párosítása rossz
forrássort tenne a magyar mellé.

Az add-on a forrás-SRT-t a magyar fájl sorszámaihoz igazítja, **időzítés
alapján**. Csak Python stdlib, nincs telepítendő függőség.

## Mit csinál

- Minden forrásfelirat ahhoz a magyar felirathoz kerül, amelyik időben a
  nagyobb részét lefedi; egyenlőségnél ahhoz, amelyik pontosabban egybeesik
  vele (így egy hosszú stáblista- vagy táblafelirat nem viszi el a párbeszéd
  forrássorát). Ha egyikkel sem fedi, a legközelebbihez, legfeljebb
  `--max-gap` (1,0) másodperc résig.
- A kimenet sorszáma és időbélyege a magyar fájlé, a szövege a forrásé. Ha egy
  magyar felirathoz több forrásfelirat tartozik, soronként egymás alá kerülnek.
- Ha a fordító egy hosszú forrásmondatot két feliratra bontott, a második
  felirat is megkapja ugyanazt a forrássort (ha az legalább a felét lefedi).
- A forrás nélküli magyar felirat (pl. a fordító saját stáblistája vagy
  táblafelirata) helyére ez kerül:
  `(nincs forrássor — a fordító saját kiírása)`.
- A sehová nem illő forrássorok a kimenet mellé kerülnek:
  `….unmatched.txt`. Ezek **lehetséges kihagyások** a fordításból, érdemes
  átnézni őket (képernyőszöveg, dal, egy elmaradt mondat).

## Használat

```bash
# a magyar fájlhoz tartozó összes forrás (input/…eng.srt, input/…chi.srt …)
python addons/align-source/align_source.py "output/Sorozat - S01E03.hun.srt"

# több rész egyszerre, csak angol és kínai
python addons/align-source/align_source.py "output/Sorozat - S01E*.hun.srt" --lang eng,chi

# kézzel megadott forrás és kimenet (a -o csak egy forrással megy)
python addons/align-source/align_source.py "output/Sorozat - S01E03.hun.srt" \
    --src "input/Sorozat - S01E03.eng.srt" -o "input/aligned/Sorozat - S01E03.eng.srt"
```

Windowson `py addons\align-source\align_source.py "output\Sorozat - S01E03.hun.srt"`.

Alapértelmezett kimenet: `input/aligned/<forrásfájl neve>`. Utána a review:

```bash
python subtr.py review "output/Sorozat - S01E03.hun.srt" --source "input/aligned/Sorozat - S01E03.eng.srt"
```

**Ha a magyar fájlba utólag feliratot szúrsz be** (pl. hiányzó táblafeliratot),
a sorszámok eltolódnak: futtasd újra az igazítást a review előtt.

A párosítás logikája a `subtr/timing.py`-ban van. Ugyanezt használja a
`subtr.py consistency` is.
