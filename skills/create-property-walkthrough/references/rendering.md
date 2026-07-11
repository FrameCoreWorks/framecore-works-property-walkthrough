# Rendering FFmpeg

## Profile

- 16:9: 1920×1080, SAR 1:1, H.264, `yuv420p`, stały FPS.
- 9:16: 1080×1920, SAR 1:1, H.264, `yuv420p`, stały FPS.

Normalizuj klipy przed concat. Używaj hard cuts domyślnie. Crossfade stosuj wyłącznie na prośbę i po sprawdzeniu długości.

## Kadrowanie

Nie rozciągaj obrazu. Dla 9:16 zapisz strategię per scena:

- `anchored_crop`,
- `contain`,
- `padded_background`,
- zatwierdzone `content_aware_reframe` tylko po osobnej konfiguracji i zgodzie.

Jeżeli crop usuwa istotną przestrzeń, zmień strategię. Nie ukrywaj utraty kadru.

## Audio i overlay

Nie dodawaj automatycznie muzyki, voice-over, logo, dokładnego adresu, numeru telefonu, emaila ani danych osobowych. Zatwierdzone audio normalizuj osobno i zapisuj prawa/licencję.

## Output

- `final/walkthrough-16x9.mp4`
- `final/walkthrough-9x16.mp4`, gdy wymagany

Po renderze uruchom ffprobe, zapisz hash, profil, listę scene revisions, dependency hash i raport. Nie uznawaj starego renderu po zmianie kolejności, klipu, strategii crop lub profilu.
