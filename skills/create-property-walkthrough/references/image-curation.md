# Selekcja zdjęć

## Model analizy

Zapisuj oddzielnie:

- `asset_kind`: `photo`, `floorplan`, `map`, `screenshot`, `portrait`, `logo`, `other`,
- `room_type`: `exterior`, `entrance`, `hallway`, `living_room`, `kitchen`, `dining_room`, `bedroom`, `child_room`, `office`, `bathroom`, `toilet`, `wardrobe`, `utility_room`, `garage`, `balcony`, `terrace`, `garden`, `view`, `other`,
- `curation_status`: `selected`, `reserve`, `rejected`.

Nie używaj `reject`, `floorplan` ani `map` jako typu pomieszczenia.

## Pola zdjęcia

Zapisz `image_id`, `room_instance_id`, confidence, jakość techniczną, użyteczność animacyjną, ryzyko deformacji, kody ryzyka, duplicate status, decyzję i powód.

## Priorytety

1. Odrzuć uszkodzone i nieprzydatne assety.
2. Grupuj tę samą widoczną przestrzeń przez `room_instance_id`.
3. Wybierz jedno mocne zdjęcie na przestrzeń.
4. Dodaj drugi kąt tylko, gdy wnosi nową informację i nie jest near-duplicate.
5. Sortuj według użyteczności animacyjnej, ryzyka, jakości, pokrycia i stabilnego `image_id` jako tie-breaker.

## Ryzyka

Obniżaj ruch przy szerokim kącie, lustrze, szkle, cienkich liniach, powtarzalnym wzorze, geometrii na krawędzi, okluzji, niskiej rozdzielczości, watermarku i potencjalnym unsupported reveal.

Nie wymyślaj niewidocznych przestrzeni. Jeżeli materiał jest słaby, przygotuj krótszy film i ostrzeżenie.
