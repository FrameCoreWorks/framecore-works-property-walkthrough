# Współtworzenie

## Zakres projektu

Repozytorium rozwija jeden wieloplatformowy plugin ChatGPT/Codex z jednym skillem `create-property-walkthrough`. Zmiany nie powinny przekształcać go w osobną aplikację ani usługę.

## Zasady zmian

- Otwórz mały, tematyczny pull request.
- Zachowuj zgodność z Pythonem 3.9+ oraz natywne działanie na macOS i Windows.
- Nie dodawaj zależności ani nie zmieniaj publicznych kontraktów bez wcześniejszego uzgodnienia.
- Używaj wyłącznie syntetycznych fixture’ów. Nie commituj zdjęć, listingów, klipów ani danych klientów.
- Nie zapisuj sekretów, tokenów, cookies, podpisanych URL-i ani wartości zmiennych środowiskowych.
- Projekt RE Walkthrough Pro traktuj wyłącznie jako opisaną w README referencję koncepcyjną. Nie kopiuj jego kodu ani materiałów.

## Weryfikacja

Przed wysłaniem pull requesta uruchom:

```text
python3 -m unittest discover -s tests -v
```

Następnie:

- uruchom `quick_validate.py` dla `skills/create-property-walkthrough`,
- uruchom oficjalny `validate_plugin.py` dla rootu repo,
- sprawdź JSON w `.codex-plugin/plugin.json` i `.agents/plugins/marketplace.json`,
- uruchom `python3 -m unittest tests.test_distribution -v`,
- sprawdź `git diff --check`.

## Pull request

Opis powinien zawierać zakres, wykonane testy oraz istotne ryzyka. CI musi przejść przed scaleniem.
