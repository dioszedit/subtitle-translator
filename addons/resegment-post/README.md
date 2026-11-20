# resegment-post add-on (merge utáni utómunka)

A `subtr.py resegment merge` kimenetét (`.merge.srt`) javítja **helyben**, a
`.reflow.srt` alapján. Csak Python stdlib, nincs telepítendő függőség.

## Mit csinál

1. **Kártya-visszabontás.** A merge két rövid cue-t akkor is egybe von, ha az
   egyik szögletes zárójeles képernyőfelirat. A címkártya (`[Magyar cím]` /
   `[Eredeti cím]`) így a `[N. rész]` kártyával kerül egy cue-ba, és a
   sortörés a zárójelpárok közepére esik (`[Her` / `Willing Subject] [1. rész]`),
   ami sérti a TRANSLATION.md *Címkártya* szabályát. Egy névtábla is a következő
   mondattal kerülhet egybe. Az ilyen összevonásokat az eredeti cue-kra és
   időzítésekre bontja vissza; a többi összevonás marad. Kártya az a darab,
   amely egészében szögletes zárójeles (a `{\an8}`, `<i>` tag nem számít) —
   a mondatba ékelt hangjelzés (`[nevet]`) nem. A kártya melletti mondatdarabok
   összevonva maradnak (egy sor, ha belefér, különben két sor). Ha a kártyás cue szövege vagy kezdő időzítése eltér a `.reflow.srt`
   darabjaitól (kézi javítás után), figyelmeztet, és változatlanul hagyja.
2. **Egysorosítás.** A kétsoros cue-t egy sorba vonja, ha együtt legfeljebb
   `--max-chars` (42) karakter, és
   - nem dalszöveg (`♪` / `♫`),
   - nem két mondat (nincs a cue belsejében `. ! ? …` utáni folytatás),
   - nem párbeszéd (`- A` / `– A`, dőlt `<i>- A` is), és egyik sora sem egész `[kártya]`.

A szabály kézi lektorálásból származik (egy sorozat 5 részének 1277 cue-ján
ugyanazt a döntést hozza). Az időzítést nem változtatja. Ha a visszabontás új
átfedő időzítést hozna, nem ír semmit, és hibával áll meg; a forrásból örökölt
átfedés (két beszélő egyszerre) nem akadály.

## Használat

```bash
# a .reflow.srt és a .merge.srt közös eleje
python addons/resegment-post/postmerge.py "output/Sorozat - S01E01.hun"
python addons/resegment-post/postmerge.py "output/Sorozat - S01E01.hun" --no-unbreak  # csak visszabontás
python addons/resegment-post/postmerge.py "output/Sorozat - S01E01.hun" --max-chars 37
python addons/resegment-post/postmerge.py "output/Sorozat - S01E01.hun.merge.srt"  # a fájlnév is jó
```

Windowson `py addons\resegment-post\postmerge.py "output\Sorozat - S01E01.hun"`.

A merge újraszámoz, ezért a review-riportok és a decisions fájlok sorszámai a
`.merge.srt`-re már nem érvényesek: triage és apply a `.hun.srt`-n, ez után.
