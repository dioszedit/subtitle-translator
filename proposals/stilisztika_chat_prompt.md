# Feliratfájl Korrekciós Prompt

---

## Teljes prompt (másold be egészben)

```
Elemezd az alábbi .srt feliratfájlt, és azonosítsd az összes hibás szekciót.

### Ellenőrzési szempontok

**1. Olvasási sebesség**
- Maximum 20 karakter/másodperc (szóköz nélkül számolva)
- Ha egy szekció meghaladja ezt, a szöveget tömöríteni kell
- Rövidebb szinonimák, tömörebb mondatszerkezetek használatával
- Az időkódon NE változtass

**2. Stílus és magyarosság**
- Természetes, gördülékeny magyar mondatszerkezetek
- Kerüld a szó szerinti fordítás tükörszerkezeteit
- Kerüld a redundanciát (pl. "búsulhatok bánatban")
- Kerüld az idegenszerű összetételeket (pl. "démonikus", "játszadozásunk")

**3. Helyesírás és grammatika**
- Elírások javítása (pl. "hilvest" → "hitvest", "nemezni" → "nemzeni")
- Névelők: "a udvarban" → "az udvarban"
- Nagybetűk: "ő Felsége" → "Ő Felsége"
- Igekötők és toldalékok helyes illeszkedése

**4. Mondattördelés**
- Ne maradjon félmondat tördelési hiba miatt értelmetlennek
- A két sorra tördelt szöveg mindkét sorában legyen értelmes egység
- Kerüld az egyszavas második sort, ha elkerülhető

### Kimeneti formátum

Csak a hibás szekciókat sorold fel:

**#[szám]** – *(hiba leírása)*
\```
Javított szöveg
\```

### Megjegyzések a javításhoz
- Ha egy szekció csak kicsit lépi túl a 20 c/s határt (pl. 20.5), és a szöveg nem tömöríthető értelmesen, jelöld meg de hagyd
- A dallövegeket (♪...♪) is javítsd ha szükséges, de őrizd meg a ritmust
- Inzert kártyák ([Helyszín neve], [Évszám]) nem számítanak bele a sebességbe
- Ha egymást fedő szekcióknál van hiba, mindkettőt jelöld
```

## Példa a kimenetre

**#40** – *(41.5 c/s – kritikus)*
```
A Nyugati Udvar követe igen szívélyes volt.
Nem mondhattam nemet a meghívására...
```

**#222** – *(elírás: „hilvest" → „hitvest")*
```
Én hívtam ide Lin hitvest.
```

**#280** – *(redundáns: „bánkódhatok bánatban")*
```
és csak magamban bánkódhatok.
```