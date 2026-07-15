# Plan wydania 1.1.0

> Status historyczny: tag `v1.1.0` pozostaje niezmieniony, ale jego CI wykazało
> brak przygotowania FFmpeg/ffprobe na czystych runnerach macOS i Ubuntu.
> GitHub Release dla tej wersji nie został opublikowany. Poprawkę wydaje
> `v1.1.1`, bez przesuwania tagu ani przepisywania historii.

## Cel

Przygotować repozytorium do kontrolowanych testów użytkowników i dystrybucji jako jeden plugin zawierający jeden skill, bez duplikowania źródeł i bez instalatorów systemowych.

## Zasady wykonania

- Zachować kompatybilność istniejących projektów ze `schema_version: 1.0`.
- Nie dodawać zależności Pythona ani lokalnego klienta sieciowego.
- Utrzymać działanie na macOS i Windows z Pythonem 3.9+.
- Nie bundlować providera, MCP, connectora, klucza ani automatycznej konfiguracji usługi.
- Nie deklarować obsługi ChatGPT szerzej, niż potwierdza oficjalny mechanizm marketplace i test instalacji.
- Nie przepisywać historii Git i nie usuwać zdalnych gałęzi w ramach tego wydania.

## Faza 1: integralność lokalnego projektu

Zakres:

1. Współdzielony resolver zarządzanych ścieżek wyjściowych sprawdzający containment i wszystkie istniejące komponenty symlinkowe.
2. Walidacja `scene_id` i semantyki projektu przed operacjami ścieżkowymi.
3. Odrzucenie symlinków wejściowych klipów przed dereferencją.
4. Ochrona katalogów ingestion, promptów, generation package, provider, scen, raportów i final renderu.
5. Jedna publiczna polityka URL używana przez inicjalizację projektu i ekstrakcję listingu.
6. Ponowna kontrola aktualnego pliku derivative przy finalnej autoryzacji generowania.

Kryteria akceptacji:

- Każdy potwierdzony przypadek wyjścia zapisu poza katalog projektu kończy się błędem przed utworzeniem pliku.
- Zmieniony lub brakujący derivative unieważnia autoryzację.
- Poprawne projekty i dotychczasowe scenariusze pozostają kompatybilne.

## Faza 2: dystrybucja i onboarding

Zakres:

1. Repozytoryjny `.agents/plugins/marketplace.json` wskazujący plugin w root repo przez Git URL i tag wydania.
2. Zgodność nazw oraz wersji marketplace, pluginu i tagu.
3. Onboarding zaczynający od celu i trybu `plan_only`, `manual_clips` albo `full_production`.
4. Rozpoznanie ChatGPT/Codex z dostępnego kontekstu; pytanie wyłącznie przy niejednoznaczności.
5. Neutralne objaśnienie connector/MCP/API dopiero w gałęzi zewnętrznej generacji.
6. Rekomendacje providerów tylko na wyraźną prośbę użytkownika.
7. Lokalny, tylko-odczytowy preflight Python, FFmpeg i ffprobe bez prób instalacji.

Kryteria akceptacji:

- Repo daje się dodać jako marketplace i zainstalować w pustym profilu Codex.
- Planowanie i praca z własnymi klipami nie wymagają providera.
- Brak FFmpeg/ffprobe daje jednoznaczną diagnozę, nie błąd sugerujący uszkodzone zdjęcie.

## Faza 3: kontrakt produkcyjny

Zakres:

1. Zwięzły production brief i zatwierdzenie storyboardu, promptów, materiałów, CTA oraz decyzji audio przed płatnym wykonaniem.
2. Opcjonalny voice-over i muzyka jako jawnie dostarczone lub wygenerowane zewnętrznie pliki z zapisanym pochodzeniem i statusem praw.
3. FFmpeg jako jedyny lokalnie wykonywany backend montażu.
4. Remotion i HyperFrames jako opcjonalne zewnętrzne backendy, których wynik wraca do tego samego importu i QA.
5. Finalny MP4, technical QA, visual QA i zwięzłe podsumowanie dostawy jako wynik pełnej produkcji.
6. Wirtualna aranżacja wyłącznie na decyzję użytkownika, z obowiązkowym oznaczeniem zmienionych scen.

Kryteria akceptacji:

- Skill wyraźnie rozdziela funkcje wykonywane lokalnie od działań zewnętrznych.
- Każdy płatny batch pokazuje przewidywany koszt lub status nieweryfikowalny i wymaga wyraźnej zgody dla jednej sesji zadania.
- Dokumentacja nie obiecuje uniwersalnego adaptera providerów ani automatycznego pobierania zdjęć z portali blokujących dostęp.

## Faza 4: jakość i wydanie

Zakres:

1. Testy regresji wszystkich nowych granic i test dystrybucji.
2. CI walidujące JSON, pełne testy wielosystemowe i osobny media E2E bez niespodziewanych skipów.
3. `CHANGELOG.md`, aktualny checkpoint, release checklist i precyzyjne informacje o licencji/provenance.
4. Wersja pluginu `1.1.0`, tag `v1.1.0` i GitHub Release wskazujące ten sam zweryfikowany commit.

Kryteria akceptacji:

- Pełne testy, oficjalny walidator skilla i pluginu przechodzą.
- Izolowana instalacja marketplace i test zainstalowanej kopii przechodzą.
- `git diff --check`, scan sekretów, AppleDouble i `git fsck --full` przechodzą.
- `main`, `origin/main`, tag i release wskazują zweryfikowany commit bez force-push.

## Poza zakresem tego wydania

- Implementacja klienta konkretnego providera.
- Automatyczne instalowanie FFmpeg, TTS, Remotion lub HyperFrames.
- Obchodzenie CAPTCHA, anti-bot, logowania, paywalla albo private-network protection.
- Publikacja w publicznym katalogu pluginów bez osobnego procesu akceptacji OpenAI.
- Automatyczne usuwanie istniejących zdalnych gałęzi.
