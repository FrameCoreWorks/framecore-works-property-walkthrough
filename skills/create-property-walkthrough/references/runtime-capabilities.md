# Możliwości środowiska

## Wykrycie bez zbędnych pytań

Rozpoznaj powierzchnię ChatGPT/Codex z kontekstu hosta. Jeżeli host udostępnia
pliki i lokalne wykonanie, uruchom read-only `scripts/preflight_environment.py`.
Nie instaluj narzędzi, nie zmieniaj PATH i nie odczytuj sekretów.

## Tryby

| Tryb | Minimalne możliwości | Wynik |
|---|---|---|
| `plan_only` | rozmowa i materiały użytkownika | brief, analiza, storyboard i prompty; pełny lokalny pakiet tylko przy dostępnych helperach i multimediach |
| `manual_clips` | lokalne pliki, Python 3.9+, FFmpeg i ffprobe | import klipów, QC i lokalny MP4 |
| `full_production` | powyższe oraz jawnie wybrana integracja generacyjna | generacja po zgodzie, QC i dostępny render |

Instalacja pluginu jest natywna, ale nie oznacza, że każda powierzchnia ChatGPT
udostępnia lokalny Python lub FFmpeg. Jeżeli preflight jest niedostępny albo
nie przechodzi, nie udawaj finalnego renderu. Kontynuuj w `plan_only`, poproś o
gotowe klipy albo wskaż, której możliwości brakuje.

Zielony preflight `plan_only` oznacza, że host może kontynuować pracę
koncepcyjną. Nie oznacza gotowości `ingest_images.py`, miniatur ani contact
sheets. Te lokalne etapy wolno uruchomić dopiero, gdy `tools.ffmpeg.available`
i `tools.ffprobe.available` mają wartość `true`.

## Preflight

`preflight_environment.py` sprawdza tylko:

- Python 3.9+,
- nazwę systemu i architekturę,
- obecność oraz wynik `-version` dla FFmpeg i ffprobe.

Raport ma pola `ready`, `blockers`, `tools`, `network_calls` i
`installation_attempts`. Dwa ostatnie zawsze wynoszą zero.
