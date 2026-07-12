# Publiczne polskie listingi

## Zasada ogólna

Obsługuj pojedynczą publiczną stronę ogłoszenia lub agencji tylko wtedy, gdy zaufana powierzchnia web/browser może ją legalnie i technicznie odczytać. Nie buduj adaptera obchodzącego zabezpieczenia konkretnego portalu.

## Preferowana kolejność danych

1. JSON-LD typu `Product`, `Offer`, `Residence`, `Apartment`, `House` lub powiązanej struktury.
2. Open Graph i standardowe meta tagi.
3. Jawne elementy strony widoczne bez interakcji i logowania.
4. Dane przekazane przez użytkownika.

Zapisuj tytuł, lokalizację, cenę, walutę, powierzchnię, liczbę pokoi, piętro, typ, opis i zdjęcia tylko wtedy, gdy występują. Nie zgaduj jednostek, waluty ani lokalizacji.

## Zdjęcia z portali takich jak Otodom

Otodom i podobne portale mogą renderować galerię klientowo albo ukrywać pełne zdjęcia poza JSON-LD i Open Graph. Najpierw użyj publicznych URL-i zdjęć znalezionych w `listing.images` albo jawnie widocznych w zaufanej powierzchni web/browser. Jeżeli takie URL-e są dostępne, spróbuj pobrać obrazy przez zaufaną powierzchnię i przyjmij je przez `ingest_images.py`.

Nie buduj adaptera konkretnego portalu, nie używaj cookies, stealth, proxy, prywatnych endpointów ani mechanizmów obchodzących anti-bot. Jeżeli pełne zdjęcia nie są technicznie dostępne bez takiego obejścia, zatrzymaj link mode jako partial i poproś użytkownika o upload zdjęć albo lokalny eksport z przeglądarki.

## Polskie formaty

- Zachowuj oryginalny tekst ceny i osobno normalizuj liczbę, gdy jest jednoznaczna.
- Rozpoznawaj przecinek dziesiętny, `m²`, `m2`, `zł` i `PLN` bez zmiany źródłowej wartości.
- Traktuj `parter`, `poddasze`, `suterena` i numer piętra jako wartości opisowe, jeśli brak bezpiecznej normalizacji.
- Zachowuj polskie znaki i Unicode NFC.

## Blokada i fallback

Przy 401, 403, CAPTCHA, logowaniu, paywallu, anti-bot, timeout albo niedostępnym renderze:

1. Zapisz uzyskane publiczne dane i dokładny kod ostrzeżenia.
2. Nie próbuj stealth, proxy, cookies, headless bypass ani innego endpointu.
3. Poproś o zdjęcia lub lokalny eksport.
4. Wznów ten sam `project_id`.
