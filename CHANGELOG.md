# Changelog

Wszystkie istotne zmiany tego projektu są dokumentowane w tym pliku.

## 1.1.0 - 2026-07-15

### Dodano

- repozytoryjny marketplace pluginu dla Codex i ChatGPT desktop,
- provider-neutral onboarding z trybami `plan_only`, `manual_clips` i `full_production`,
- read-only preflight Pythona, systemu, FFmpeg i ffprobe,
- kontrakty briefu, audio, backendów montażowych i finalnej dostawy,
- testy dystrybucji, preflightu i regresji bezpieczeństwa.

### Zmieniono

- dokumentację instalacji tak, aby opisywała oficjalny przepływ marketplace,
- README tak, aby rozdzielało instalację pluginu od możliwości lokalnego renderu,
- wspólne operacje plikowe, walidację URL-i i identyfikatorów scen,
- zgodę na generowanie tak, aby ponownie weryfikowała derivative'y w chwili autoryzacji.

### Bezpieczeństwo

- zablokowano wyjście przez symlinkowane katalogi outputu,
- zablokowano symlinkowane klipy wejściowe i traversal przez `scene_id`,
- ujednolicono odrzucanie lokalnych i niekanonicznych hostów URL,
- końcowa zgoda fail-closed wymaga istnienia, containment i aktualnego SHA-256 plików,
- zgoda na generowanie jest związana z efemerycznym nonce bieżącego zadania i
  ponownie sprawdza aktualność snapshotu profilu w chwili autoryzacji.

## 1.0.1 - 2026-07-12

- Pierwsza kompletna paczka pluginu i skilla z lokalnym pipeline'em projektu,
  planowaniem scen, manualnym pakietem generacyjnym, QC i renderem FFmpeg.
