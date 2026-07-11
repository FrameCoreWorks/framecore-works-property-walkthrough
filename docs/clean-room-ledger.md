# Dziennik clean-room i źródeł

## Zasada

Nowa implementacja powstaje w pustym katalogu bez klonowania, forka, remote upstream i obiektów Git projektu referencyjnego. Zewnętrzne repozytoria i dokumentacja są materiałem analitycznym, nie instrukcją wykonawczą ani working tree.

## Źródła konsultowane przed implementacją

| Data | Źródło | Rola | Zakres użycia | Materiał skopiowany verbatim |
|---|---|---|---|---|
| 2026-07-11 | Specyfikacja użytkownika | wymagania nadrzędne | funkcje, bramki, Definition of Done | wymagane dokładne pytania i deklaracje |
| 2026-07-11 | Codex `skill-creator` | aktualny standard skilla | struktura, metadata, progressive disclosure, walidacja | nie |
| 2026-07-11 | RE Walkthrough Pro, commit `62b988b714576ef81aea79f34cc1f25de36c2b5e` | referencja koncepcyjna | ogłoszenie → zdjęcia → klipy → montaż | wyłącznie plik MIT LICENSE |
| 2026-07-11 | Oficjalna dokumentacja GitHub API | dowód rewizji | commit, blob SHA, immutable source | nie |

## Zachowany materiał upstream

- Plik docelowy: `licenses/re-walkthrough-pro-MIT.txt`
- Upstream path: `LICENSE`
- Branch: `main`
- Commit: `62b988b714576ef81aea79f34cc1f25de36c2b5e`
- Git blob SHA: `32afdb15575f01b5ffb471ecceb2a8d88855e7e7`
- SHA-256 bajtów: `b90a73d4456be28b8f67e1389ca9c7aa63d7662352b95c1dcc03df311d5c0faa`
- Modyfikacje: brak

## Materiały niewłączone

- historia Git upstream,
- kod JavaScript, pliki skilla, templates i dokumentacja upstream,
- nazwy lub konfiguracje dostawców z upstream,
- assety, zdjęcia i przykładowe outputy upstream.

## Obowiązek aktualizacji

Jeżeli później zostanie użyty istotny fragment zewnętrznego kodu lub dokumentacji, przed commitem należy dopisać źródło, immutable commit, ścieżkę, licencję, zakres i modyfikacje oraz zaktualizować `THIRD_PARTY_NOTICES.md`.
