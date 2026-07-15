# Lektor i muzyka

Audio jest opcjonalne. Najpierw zapytaj, czy użytkownik chce lektora, muzykę,
oba elementy czy film bez audio. Nie instaluj silnika i nie uruchamiaj płatnej
usługi bez polecenia.

## Lektor

- Przyjmij nagranie użytkownika albo jawnie wybrane narzędzie.
- Po prośbie o konkretne opcje możesz omówić usługę API, na przykład
  ElevenLabs, albo lokalny silnik, na przykład OmniVoiceTTS lub VoxCPM2.
- Przed użyciem sprawdź bieżącą dokumentację, licencję, obsługę polskiego,
  wymagania sprzętowe i koszt.
- Lokalna opcja może nie pobierać opłaty za wywołanie, ale nie nazywaj jej
  bezwarunkowo darmową. Modele, sprzęt i licencje mają własne warunki.
- Klucze i tokeny pozostają w mechanizmie sekretów hosta, nigdy w projekcie.

## Muzyka

- Używaj wyłącznie utworu dostarczonego przez użytkownika albo materiału z
  bibliotek, których aktualne warunki pozwalają na planowane użycie.
- Przed pobraniem sprawdź licencję konkretnego utworu, wymagane oznaczenie,
  zakres komercyjny i ograniczenia platformy. Sama etykieta „free” nie wystarcza.
- Skill może też przygotować film bez muzyki i zasugerować dodanie jej ręcznie
  w CapCut lub Edits, jeżeli użytkownik woli kontrolować publikację samodzielnie.

Przykładowe biblioteki zweryfikowane w oficjalnych źródłach 15 lipca 2026:

- [YouTube Audio Library](https://support.google.com/youtube/answer/3376882):
  biblioteka muzyki i efektów w YouTube Studio; część utworów wymaga atrybucji,
  a warunki użycia poza YouTube trzeba ocenić dla konkretnego materiału;
- [Pixabay Content License](https://pixabay.com/service/license-summary/):
  pozwala bezpłatnie używać i adaptować content z zastrzeżeniami, między innymi
  zakazem dystrybucji standalone i obowiązkiem sprawdzenia dodatkowych praw;
- [Free Music Archive License Guide](https://freemusicarchive.org/License_Guide):
  każdy utwór ma własną licencję, często Creative Commons; `ND` nie pozwala na
  synchronizację z wideo, a `NC` nie pasuje do komercyjnej promocji oferty.

To są punkty startowe, nie automatycznie zatwierdzona pula. Przed użyciem
sprawdź stronę i licencję konkretnego utworu ponownie.

Zapisz źródło i warunki użycia wybranego audio w podsumowaniu dostawy. Nie
commituj cudzych plików audio do repozytorium skilla.
