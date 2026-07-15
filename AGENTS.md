# Instrukcje projektu

## Cel i język

- Rozwijaj jeden plugin ChatGPT/Codex z jednym skillem `create-property-walkthrough`.
- Pisz dokumentację, komunikaty CLI, błędy, docstringi i komentarze po polsku.
- Zachowuj angielskie prompty image-to-video i wymagane techniczne identyfikatory.
- Używaj UTF-8 i testuj polskie znaki.

## Architektura

- Utrzymuj architekturę skill-first, bez aplikacji webowej, desktopowej, API i bazy danych.
- Używaj Python 3.9+ oraz biblioteki standardowej. Nie dodawaj zależności bez jawnej decyzji.
- Zachowuj przenośność lokalnych helperów na macOS, Windows i Linux; nie wprowadzaj mechanizmów zależnych wyłącznie od jednego systemu.
- Traktuj FFmpeg i ffprobe jako wymagania lokalnych etapów multimedialnych, nie samej instalacji pluginu ani trybu `plan_only`.
- Utrzymuj małe deterministyczne skrypty. Decyzje wizualne pozostawiaj Codexowi lub użytkownikowi.
- Helpery repozytorium nie mogą wykonywać bezpośrednich połączeń sieciowych.

## Bezpieczeństwo

- Nie wymagaj dostawcy przy pierwszym użyciu. Najpierw ustal cel i tryb pracy. Integrację sprawdzaj dopiero dla zewnętrznej generacji; konkretne usługi rekomenduj wyłącznie na jawną prośbę użytkownika i po ustaleniu jego priorytetu.
- Nie uruchamiaj zewnętrznej generacji ani uploadu bez aktualnej zgody na dokładny batch.
- Wymagaj osobnego potwierdzenia kosztu dla operacji płatnych lub potencjalnie płatnych.
- Nie zapisuj sekretów, kluczy, cookies, podpisanych URL-i ani pełnych odpowiedzi providera.
- Nie commituj `walkthrough-projects/`, prawdziwych listingów, zdjęć klientów, klipów ani danych osobowych.
- Nie obchodź CAPTCHA, logowania, paywalla, anti-bot ani private-network protection.
- Rozpakowuj ZIP wyłącznie do kwarantanny i publikuj wynik dopiero po pełnej walidacji.

## Clean-room i licencje

- Nie dodawaj remote upstream ani jego historii Git.
- Zachowuj wyłącznie rootowy `LICENSE` niezależnej implementacji FrameCore Works.
- Projekt referencyjny opisuj w README jako źródło wiedzy i inspirację koncepcyjną.
- Nie kopiuj kodu, licencji ani innych materiałów projektu referencyjnego. Każde planowane późniejsze zapożyczenie wymaga osobnej analizy licencyjnej przed włączeniem.

## Testy i checkpointy

- Używaj wyłącznie syntetycznych fixture’ów tworzonych lokalnie.
- Uruchamiaj testy przez `python3 -m unittest discover -s tests -v`.
- Waliduj skill przez narzędzie `quick_validate.py` dostarczane z Codexem.
- Przed commitem uruchom testy, scan sekretów, scan AppleDouble i przegląd diffu.
- Pushuj wyłącznie przetestowane checkpointy. Nie używaj force-push ani rewrite history.
