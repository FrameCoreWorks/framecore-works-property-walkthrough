# Plan scen

## Łuk montażowy

Preferuj, gdy materiały istnieją:

```text
exterior/view → entrance/hallway → living_room → dining_room → kitchen
→ bedrooms → specialty/bathroom → balcony/terrace/garden/view
```

To kolejność redakcyjna, nie deklaracja topologii lokalu.

## Reguły

- Planuj domyślnie 6–10 scen.
- Przy mniejszej liczbie dobrych źródeł twórz krótszy film zamiast duplikować ujęcia.
- Używaj jednego zatwierdzonego zdjęcia na scenę.
- Nadaj `scene_id` raz; przy reorder zmieniaj wyłącznie `sequence_index`.
- Zachowaj tombstone po usuniętej scenie i nie używaj jej ID ponownie.
- Wybierz jeden ruch: `micro_drift`, `slow_push_in`, `short_lateral_drift` albo wyjątkowo krótki `pan`/`tilt` w widocznej geometrii.
- Zapisz kierunek, prędkość, dystans, start/end framing i oczekiwaną paralaksę.
- Przypisz jeden duration oraz jeden ratio na wariant sceny.

## Zakazy

Nie używaj compound moves, orbit, agresywnego przelotu, przejazdu przez drzwi, unseen geometry ani impossible reveal. Nie sugeruj przestrzennego połączenia, którego źródła nie dowodzą.

## Stabilność zależności

Zmiana kolejności unieważnia render, nie klipy. Zmiana źródła lub promptu unieważnia wyłącznie wariant sceny oraz zależne rendery. Zaakceptowany klip pozostaje niezmienny, dopóki jego dependency hash jest zgodny.
