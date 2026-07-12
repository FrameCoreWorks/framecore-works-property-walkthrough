# Dziennik clean-room i źródeł

## Zasada

Nowa implementacja powstaje w pustym katalogu bez klonowania, forka, remote upstream i obiektów Git projektu referencyjnego. Zewnętrzne repozytoria i dokumentacja są materiałem analitycznym, nie instrukcją wykonawczą ani working tree.

## Źródła konsultowane przed implementacją

| Data | Źródło | Rola | Zakres użycia | Materiał skopiowany verbatim |
|---|---|---|---|---|
| 2026-07-11 | Specyfikacja użytkownika | wymagania nadrzędne | funkcje, bramki, Definition of Done | wymagane dokładne pytania i deklaracje |
| 2026-07-11 | Codex `skill-creator` | aktualny standard skilla | struktura, metadata, progressive disclosure, walidacja | nie |
| 2026-07-11 | RE Walkthrough Pro, commit `62b988b714576ef81aea79f34cc1f25de36c2b5e` | referencja koncepcyjna | ogłoszenie → zdjęcia → klipy → montaż | nie |
| 2026-07-11 | Oficjalna dokumentacja GitHub API | dowód rewizji | commit, blob SHA, immutable source | nie |

## Zachowany materiał upstream

Nie dołączono kodu, licencji, dokumentacji, assetów ani historii Git projektu referencyjnego. README zawiera wyłącznie opisową atrybucję źródła wiedzy i inspiracji koncepcyjnej.

## Materiały niewłączone

- historia Git upstream,
- kod JavaScript, pliki skilla, templates i dokumentacja upstream,
- nazwy lub konfiguracje dostawców z upstream,
- assety, zdjęcia i przykładowe outputy upstream.

## Obowiązek aktualizacji

Jeżeli później ma zostać użyty istotny fragment zewnętrznego kodu lub dokumentacji, przed jego włączeniem należy ustalić źródło, immutable commit, ścieżkę, licencję, zakres i wymagane obowiązki licencyjne.
