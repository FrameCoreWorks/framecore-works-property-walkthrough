# Plan wydania 1.1.1

## Cel

Opublikować zweryfikowaną poprawkę kontraktu CI dla kompletnego pakietu 1.1.x,
bez zmiany zachowania skilla, instalatorów użytkownika ani historii tagu
`v1.1.0`.

## Zakres

1. Przygotować FFmpeg i ffprobe na runnerach Ubuntu, macOS i Windows przed
   pełnym preflightem.
2. Przygotować te same narzędzia w zadaniach zgodności Python 3.9 i 3.13.
3. Zachować read-only charakter preflightu oraz brak automatycznej instalacji
   narzędzi na komputerze użytkownika.
4. Ujednolicić wersję pluginu, marketplace, README, changelogu i tagu na
   `1.1.1` / `v1.1.1`.

## Bramki wydania

- pełny zestaw testów lokalnych przechodzi bez nieoczekiwanych pominięć,
- oficjalne walidatory skilla i pluginu przechodzą,
- izolowana instalacja marketplace przechodzi najpierw lokalnie, a następnie
  z publicznego tagu,
- wszystkie zadania GitHub Actions dla `main` i `v1.1.1` są zielone,
- `main`, `origin/main`, tag i GitHub Release wskazują ten sam commit,
- tag `v1.1.0` pozostaje nienaruszony.

## Poza zakresem

- instalatory FFmpeg lub innych narzędzi dla użytkowników,
- nowy provider, connector, MCP albo zależność Pythona,
- zmiana publicznego workflow skilla lub schematu projektu,
- force-push, przesuwanie lub usuwanie istniejących tagów.
