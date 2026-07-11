# Kontrola jakości klipów

## Kontrola techniczna

Uruchom ffprobe i zapisz:

- dekodowalność i strumienie,
- duration,
- width, height, SAR i ratio,
- FPS i time base,
- codec i pixel format,
- obecność audio bez automatycznego uznania go za zatwierdzone.

Wygeneruj próbki około 0%, 25%, 50%, 75% i 100% czasu.

## Kontrola wizualna

Porównaj próbki z approved source. Sprawdź ściany, proste linie, drzwi, okna, podłogi, sufity, meble, dekoracje, materiały, odbicia, liczbę obiektów, światło, skalę ruchu i paralaksę.

Kody krytyczne obejmują morphing, bent wall, distorted opening, new geometry, object loss, object duplication, lighting drift, scene replacement, excess motion i invalid parallax.

## Status

- `approved`: technicznie poprawny i bez krytycznej zmiany źródła.
- `regenerate`: wymaga nowej rewizji z prostszym ruchem.
- `rejected`: nie może wejść do renderu.
- `needs-manual-review`: dowody nie wystarczają do bezpiecznej decyzji.

Nie akceptuj klipu wyłącznie dlatego, że ffprobe przechodzi. Zapisuj reviewer, czas, failure codes, próbki i dependency hashes.

## Regeneracja

Zachowaj source i poprzednią rewizję. Skróć dystans, uprość ruch lub czas. Nie zmieniaj innych approved scenes. Unieważnij tylko właściwy wariant oraz zależny render. Uzyskaj nową zgodę, jeśli zmienia się fingerprint lub koszt.
