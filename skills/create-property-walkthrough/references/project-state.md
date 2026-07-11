# Stan projektu i resume

## Drzewo projektu

```text
walkthrough-projects/<project-id>/
├── project.json
├── SOURCE.md
├── source-images/
├── thumbnails/
├── contact-sheets/
├── rejected/
├── prompts/
├── generation-package/
├── provider/provider-profile.snapshot.json
├── scenes/imported/
├── scenes/approved/
├── scenes/rejected/
├── final/
└── reports/
```

## Zapis

Zapisuj `project.json` w UTF-8 przez tymczasowy plik na tym samym filesystemie, flush, `fsync` i `os.replace`. Waliduj schemat i semantykę przed publikacją. Nie zapisuj sekretów.

## Identyfikatory i rewizje

- `image_id`: stabilny identyfikator oparty na SHA-256.
- `room_instance_id`: identyfikator widocznej przestrzeni.
- `scene_id`: nieprzezroczysty identyfikator nadany raz.
- `sequence_index`: kolejność montażowa.
- usunięty `scene_id`: tombstone, bez ponownego użycia.
- clip revision: nowy `attempt_no`, nowa ścieżka i hash; nigdy overwrite approved.

## Resume

1. Wczytaj i zwaliduj manifest.
2. Zweryfikuj ścieżki, pliki i hashe.
3. Znajdź pierwszy `pending`, `in_progress`, `blocked` lub `invalidated` etap.
4. Zachowaj kompletne etapy i approved revisions.
5. Uzgodnij istniejące job IDs i `submission_pending`.
6. Regeneruj tylko unieważnione warianty po aktualnych zgodach.
7. Re-renderuj wyłącznie po zmianie render dependency hash.

Poprzednia zgoda nie przenosi się do nowego batcha ani nowej rozmowy.
