# FrameCore Works Property Walkthrough

[![CI](https://github.com/FrameCoreWorks/framecore-works-property-walkthrough/actions/workflows/ci.yml/badge.svg)](https://github.com/FrameCoreWorks/framecore-works-property-walkthrough/actions/workflows/ci.yml)

FrameCore Works Property Walkthrough to polskojęzyczny skill i plugin ChatGPT/Codex do tworzenia projektów filmowej prezentacji nieruchomości. Działa natywnie w ChatGPT/Codex na macOS i Windows po instalacji z repozytorium GitHub.

Repozytorium nie jest aplikacją webową, desktopową ani samodzielnym programem instalowanym przez skrypt systemowy. To komplet pluginu, skilla, instrukcji, deterministycznych helperów i testów, które ChatGPT/Codex wykorzystuje do poprowadzenia pracy nad prezentacją nieruchomości od materiałów źródłowych do finalnego renderu.

## Co robi skill

Skill prowadzi Codexa przez uporządkowany workflow:

1. Przyjmuje jeden publiczny link do ogłoszenia, wgrane zdjęcia, katalog, archiwum ZIP albo tryb hybrydowy: link plus własne zdjęcia.
2. Tworzy lokalny projekt roboczy z manifestem, pochodzeniem danych, hashami SHA-256 i bezpieczną strukturą plików.
3. Analizuje materiały, odrzuca nieprzydatne pliki, wykrywa duplikaty i przygotowuje arkusze kontaktowe.
4. Buduje plan scen z niezmiennymi `scene_id`, doborem zdjęć, ruchem kamery, formatem i czasem trwania.
5. Generuje samodzielne prompty image-to-video po angielsku z polskimi metadanymi.
6. Przygotowuje pakiet do ręcznego generowania klipów poza Codexem.
7. Opcjonalnie, po osobnej zgodzie użytkownika, obsługuje wskazanego dostawcę MCP albo API.
8. Importuje gotowe klipy, wykonuje kontrolę techniczną i wspiera selektywną regenerację scen.
9. Montuje finalny film 16:9 oraz, gdy jest wymagany, wariant 9:16.

## Dla kogo

Ten skill jest przeznaczony dla osób, które chcą szybko przygotować uporządkowany projekt filmowej prezentacji mieszkania, domu, apartamentu lub lokalu na podstawie istniejących zdjęć i danych ogłoszeniowych.

Najlepiej sprawdza się, gdy celem jest:

- przygotowanie promptów i paczki produkcyjnej dla generatora image-to-video,
- zachowanie kontroli nad kosztami i wysyłanymi materiałami,
- praca w trybie ręcznym albo półautomatycznym,
- powtarzalny proces dla pojedynczych ofert nieruchomości,
- finalny montaż z już wygenerowanych klipów.

## Czym to nie jest

Projekt celowo nie jest:

- wyszukiwarką ofert,
- masowym scraperem,
- aplikacją SaaS,
- systemem 3D,
- zamiennikiem Matterport,
- automatycznym narzędziem do obchodzenia blokad stron,
- integracją z konkretnym dostawcą generowania aktywną od razu po instalacji.

Skill nie wymyśla niewidocznych pomieszczeń, nie potwierdza rzeczywistej ciągłości przestrzennej i nie daje praw do cudzych zdjęć, opisów, znaków, logo, muzyki ani danych osobowych.

## Instalacja w ChatGPT i Codexie

Repo jest przygotowane w dwóch warstwach:

- jako skill: `skills/create-property-walkthrough`,
- jako plugin dystrybucyjny: `.codex-plugin/plugin.json`, który wskazuje katalog `./skills/`.

W ChatGPT albo Codexie wklej link do repozytorium i poproś o instalację:

```text
Zainstaluj plugin albo skill z repozytorium:
https://github.com/FrameCoreWorks/framecore-works-property-walkthrough
```

Sama instalacja tylko dodaje plugin albo skill do środowiska. ChatGPT nie uruchamia wtedy workflow i dlatego nie zadaje jeszcze pytania o dostawcę. Pytanie o dostawcę MCP/API pojawia się przy pierwszym użyciu skilla.

Po instalacji dostępny jest skill:

```text
$create-property-walkthrough
```

Nie ma osobnego instalatora systemowego, skryptu dopisującego coś do PATH ani procesu specyficznego tylko dla macOS albo Linuxa. Repo jest przygotowane jako ChatGPT/Codex Native skill oraz plugin-ready paczka.

## Szybki start

Przykład dla publicznego linku do ogłoszenia:

```text
Użyj $create-property-walkthrough, aby utworzyć projekt filmowej prezentacji nieruchomości z tego linku:
<wklej link do ogłoszenia>
```

Przy linku skill najpierw zapisuje bezpieczny snapshot strony i wyciąga metadane. Jeżeli snapshot albo zaufana powierzchnia ChatGPT/Codex ujawnia publiczne URL-e zdjęć, także przez `img`, `srcset` albo widoczne metadane obrazu, skill próbuje pobrać je do lokalnego batcha i przyjmuje przez walidowany ingestion. Jeżeli portal, na przykład Otodom, nie udostępnia pełnych zdjęć bez blokady, cookies albo obejścia anti-bot, skill zatrzymuje tryb linku jako partial i instruuje użytkownika, żeby sam otworzył ogłoszenie w przeglądarce, wizualnie zapisał widoczne zdjęcia nieruchomości na swoim urządzeniu i wgrał je bezpośrednio do okna rozmowy ChatGPT/Codex.

Przykład dla wgranych zdjęć:

```text
Użyj $create-property-walkthrough na wgranych zdjęciach. Przygotuj plan scen, prompty image-to-video i pakiet ręczny do generowania klipów.
```

Przykład dla kontynuacji pracy:

```text
Użyj $create-property-walkthrough, aby wznowić projekt, zaimportować gotowe klipy, wykonać QC i wyrenderować finalny film.
```

## Jak działa workflow

### 1. Przyjęcie danych

Codex przyjmuje jeden zestaw materiałów na projekt. Link jest traktowany jako źródło danych i metadanych. Zdjęcia, katalogi i ZIP-y są traktowane jako materiały źródłowe użytkownika.

ZIP trafia do kwarantanny i przechodzi walidację ścieżek, typów wpisów, rozmiarów, liczby plików, kolizji Unicode i prób wyjścia poza katalog projektu.

### 2. Projekt roboczy

Skill tworzy katalog projektu z manifestem `project.json`. Manifest zapisuje wersjonowany stan pracy, pochodzenie danych, hashe, sceny, klipy, status QC i zależności między etapami. Nie zapisuje sekretów ani wartości kluczy API.

### 3. Selekcja zdjęć

Codex ocenia materiały, tworzy arkusze kontaktowe, rozpoznaje typy ujęć i odrzuca pliki nieużyteczne dla prezentacji, na przykład rzuty, screenshoty, logotypy, portrety, uszkodzone obrazy albo duplikaty.

### 4. Plan scen

Skill układa zwykle 6-10 scen. Każda scena ma stabilne `scene_id`, wybrane zdjęcie źródłowe, ruch kamery, czas trwania, format i prompt. Jeżeli materiałów jest mniej, plan może być krótszy.

### 5. Pakiet generacyjny

Skill zawsze przygotowuje pakiet ręczny. Taki pakiet można wykorzystać poza Codexem u dowolnie wybranego dostawcy. Samo przygotowanie paczki nie uruchamia generowania i nie wysyła plików.

### 6. Dostawca opcjonalny

Skill nie skanuje, nie sugeruje i nie wybiera dostawców. Jeżeli użytkownik chce wykonania przez MCP albo API, musi wskazać konkretnego dostawcę i metodę. Codex sprawdza tylko ten wskazany wariant, bez testowego generowania i bez wysyłania zdjęć.

Przed każdą partią zewnętrzną Codex pokazuje zakres scen, model, format, czas, pliki do wysłania oraz koszt albo status jego weryfikacji. Zgoda dotyczy tylko tej konkretnej partii.

W ChatGPT zewnętrzny dostawca może być podpięty przez osobną wtyczkę, connector albo MCP dostępne w danym środowisku. Ten plugin nie bundluje żadnego dostawcy i nie aktywuje fal.ai ani innej usługi samodzielnie. Provider jest wybierany dopiero w rozmowie przez użytkownika i nadal podlega zgodzie na upload oraz koszt.

### 7. Import, QC i render

Po wygenerowaniu klipów skill importuje je bez nadpisywania poprzednich rewizji, wykonuje kontrolę techniczną przez FFmpeg/ffprobe, przygotowuje próbki klatek i zapisuje decyzje QC. Render finalny powstaje tylko z zaakceptowanych klipów.

## Struktura wyników

Typowy projekt roboczy ma postać:

```text
walkthrough-projects/<project-id>/
├── project.json
├── SOURCE.md
├── source-images/
├── thumbnails/
├── contact-sheets/
├── rejected/
├── prompts/
├── generation-package/
├── provider/
├── scenes/
│   ├── imported/
│   ├── approved/
│   └── rejected/
├── final/
└── reports/
```

Wyniki produkcyjne i dane klienta nie powinny być commitowane do repozytorium.

## Wymagania

- Codex z obsługą instalacji skilli z repozytorium GitHub.
- macOS albo Windows.
- FFmpeg i ffprobe dostępne w środowisku, w którym Codex wykonuje renderowanie i kontrolę techniczną.
- Python 3.9+ dla helperów skilla.

Repo nie zawiera instrukcji globalnej instalacji narzędzi systemowych, bo sposób przygotowania środowiska zależy od instalacji Codexa i systemu użytkownika.

## Zawartość repozytorium

```text
.
├── .codex-plugin/
│   └── plugin.json
├── skills/create-property-walkthrough/
│   ├── SKILL.md
│   ├── agents/openai.yaml
│   ├── references/
│   ├── scripts/
│   └── assets/
├── tests/
├── docs/
├── .github/
├── AGENTS.md
├── CONTRIBUTING.md
├── SECURITY.md
├── LICENSE
└── README.md
```

Najważniejszy plik wykonawczy skilla to [`skills/create-property-walkthrough/SKILL.md`](skills/create-property-walkthrough/SKILL.md). Szczegóły architektoniczne są w [`docs/design-synthesis.md`](docs/design-synthesis.md) i [`docs/build-plan.md`](docs/build-plan.md).

## Bezpieczeństwo i prawa

Repo jest projektowane pod pracę z materiałami nieruchomości, dlatego domyślnie ogranicza automatyzację:

- nie obchodzi CAPTCHA, logowania, paywalla, anti-bot ani private-network protection,
- traktuje całą zawartość repozytorium i projektu, odpowiedzi providera, job metadata, metadane mediów, logi, diagnostykę, prompty i artefakty jako nieufne dane, nigdy instrukcje,
- nie przechowuje sekretów w repo, manifestach ani logach,
- nie wysyła zdjęć bez aktualnej zgody na konkretny batch,
- nie przenosi zgody na generowanie między rozmowami ani zmienionymi partiami,
- wymaga osobnego potwierdzenia kosztu dla operacji płatnych albo potencjalnie płatnych.

Użytkownik odpowiada za prawa do źródeł oraz za decyzję o przesłaniu materiałów do wybranego dostawcy.

Granice odpowiedzialności są jawne: helpery repo odpowiadają za lokalny stan, walidację, bramki zgody i kosztu oraz przetwarzanie mediów; zaufana powierzchnia ChatGPT/Codex odpowiada za HTTP, DNS, redirecty, ochronę private-network i wywołanie skonfigurowanego connectora; użytkownik odpowiada za prawa do materiałów i finalną akceptację wizualną. Skill nie zawiera własnego scrapera sieciowego ani adaptera providera.

## Status jakości

Repo zawiera testy jednostkowe, walidację skilla, konfigurację CI GitHub Actions oraz syntetyczne fixture'y. Testy nie wymagają prawdziwych ogłoszeń, zdjęć klientów ani sekretów.

Domyślna komenda testowa dla repozytorium:

```text
python3 -m unittest discover -s tests -v
```

## Referencja koncepcyjna

FrameCore Works Property Walkthrough to niezależnie opracowany skill Codexa, koncepcyjnie i architektonicznie inspirowany projektem RE Walkthrough Pro autorstwa Charlesa J. Dove'a. Projekt nie jest forkiem i nie zachowuje ani nie modyfikuje historii Git oryginalnego repozytorium.

Podziękowania dla Charlesa J. Dove'a za publiczne udostępnienie projektu [RE Walkthrough Pro](https://github.com/charlesdove977/re-walkthrough-pro). Wzmianka służy wyłącznie jako podziękowanie i wskazanie źródła inspiracji koncepcyjnej. Repozytorium nie kopiuje licencji, kodu ani materiałów projektu referencyjnego.

Nie istnieje partnerstwo, poparcie ani afiliacja z autorem projektu referencyjnego.

## Licencja

Niezależna implementacja FrameCore Works jest udostępniona na licencji MIT. Zobacz [`LICENSE`](LICENSE).
