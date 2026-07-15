# FrameCore Works Property Walkthrough

[![CI](https://github.com/FrameCoreWorks/framecore-works-property-walkthrough/actions/workflows/ci.yml/badge.svg)](https://github.com/FrameCoreWorks/framecore-works-property-walkthrough/actions/workflows/ci.yml)

Polskojęzyczny plugin ChatGPT/Codex prowadzący produkcję filmowej prezentacji
nieruchomości od linku lub zdjęć do planu scen, promptów, kontroli jakości i,
gdy środowisko ma wymagane narzędzia, finalnego MP4.

Repozytorium zawiera jeden plugin i jeden skill
`$create-property-walkthrough`. Nie jest aplikacją SaaS, scraperem ani
instalatorem systemowym. Nie bundluje dostawcy generowania, nie zmienia PATH i
nie instaluje FFmpeg, modeli ani kluczy API.

## Najważniejsze możliwości

- link do pojedynczego ogłoszenia, wgrane JPEG/PNG, katalog, ZIP lub tryb hybrydowy,
- bezpieczny projekt roboczy z provenance, SHA-256 i wznawialnym stanem,
- analiza i selekcja zdjęć oraz arkusze kontaktowe,
- zwykle 6–10 scen ze stabilnymi `scene_id`, jednym źródłem i jednym ruchem,
- samodzielne prompty image-to-video po angielsku z polskimi metadanymi,
- provider-neutral pakiet ręczny,
- opcjonalna generacja przez connector, MCP albo API wybrane przez użytkownika,
- jawna zgoda na upload, koszt i każdą płatną ponowną próbę,
- append-only import klipów, techniczny i wizualny QC,
- lokalny montaż 16:9 lub 9:16 z zaakceptowanych klipów,
- kontrolowane wznowienie bez powtarzania ukończonych etapów.

## Trzy tryby działania

| Tryb | Co powstaje | Wymagania wykonawcze |
|---|---|---|
| `plan_only` | brief, analiza, storyboard, prompty i pakiet ręczny | rozmowa i materiały użytkownika |
| `manual_clips` | powyższe, import klipów, QC i lokalny MP4 | Python 3.9+, FFmpeg, ffprobe i lokalne pliki |
| `full_production` | powyższe oraz zewnętrzna generacja po zgodzie | zgodna integracja connector/MCP/API oraz wymagania trybu manualnego |

Skill wykrywa możliwości hosta i nie pyta o dostawcę na starcie. Integracja
pojawia się dopiero wtedy, gdy użytkownik wybiera zewnętrzną generację.
Konkretne usługi są rekomendowane wyłącznie na jawną prośbę, po ustaleniu
priorytetu i sprawdzeniu bieżącej oficjalnej dokumentacji.

## Instalacja

Repo zawiera oficjalny manifest pluginu w `.codex-plugin/plugin.json` oraz
repozytoryjny katalog marketplace w `.agents/plugins/marketplace.json`.

### Codex CLI

Dodaj marketplace przypięty do tego wydania, a następnie zainstaluj plugin:

```bash
codex plugin marketplace add FrameCoreWorks/framecore-works-property-walkthrough --ref v1.1.0
codex plugin add framecore-works-property-walkthrough@framecore-works
```

### ChatGPT desktop

W ChatGPT desktop otwórz repozytorium w powierzchni Work lub Codex, uruchom
ponownie aplikację, otwórz katalog Plugins, wybierz marketplace
`FrameCore Works` i zainstaluj `FrameCore Works Property Walkthrough`.

Samo wklejenie URL repozytorium do dowolnego wariantu ChatGPT nie jest
gwarantowaną ścieżką instalacji. Dostępność katalogu pluginów zależy od
powierzchni i polityk workspace.

Instalacja pluginu również nie gwarantuje lokalnego Pythona ani FFmpeg w każdej
powierzchni ChatGPT. Skill sprawdza te możliwości przed etapem multimedialnym i
uczciwie pozostaje w trybie planu lub pakietu ręcznego, gdy ich brakuje.

## Szybki start

Z linku:

```text
Użyj $create-property-walkthrough i przygotuj projekt prezentacji tej nieruchomości:
<link do ogłoszenia>
```

Ze zdjęć:

```text
Użyj $create-property-walkthrough na wgranych zdjęciach. Przygotuj brief,
storyboard, prompty i pakiet ręczny. Nie uruchamiaj płatnej generacji.
```

Z gotowych klipów:

```text
Użyj $create-property-walkthrough, wznów projekt, zaimportuj klipy,
wykonaj QC i przygotuj finalny MP4.
```

Przed generacją skill pokazuje zwięzłe podsumowanie celu, scenariusza,
storyboardu, promptów i materiałów. Akceptacja kreatywna jest osobna od zgody
na upload i koszt.

## Linki do ogłoszeń i zdjęcia

Lokalne helpery nie wykonują sieci. Link może zostać otwarty wyłącznie przez
zaufaną powierzchnię przeglądarkową ChatGPT/Codex, która przekazuje ograniczony
snapshot do parsera.

Jeżeli strona ujawnia publiczne URL-e zdjęć, host może spróbować pobrać je do
lokalnego batcha. Jeżeli portal blokuje dostęp, wymaga logowania, cookies,
CAPTCHA lub obejścia anti-bot, skill nie obchodzi zabezpieczeń. Informuje wtedy
użytkownika, aby sam otworzył stronę, wizualnie zapisał zdjęcia i wgrał je do
okna rozmowy.

## Zewnętrzne generowanie

Plugin nie zawiera konkretnego providera ani jego klienta. W ChatGPT może użyć
connectora lub MCP dostępnego w danym workspace. W Codexie może użyć jawnie
skonfigurowanego MCP albo API. Klucze pozostają w mechanizmie sekretów hosta i
nigdy nie trafiają do repozytorium ani projektu.

Przed płatnym wykonaniem skill:

1. wykonuje szybki fact-check aktualnej integracji,
2. pokazuje pliki, sceny, model, format i czas,
3. pokazuje przewidywany koszt i zużycie kredytów, gdy są wiarygodnie dostępne,
4. wymaga osobnej, jednoznacznej zgody na upload i generowanie,
5. wymaga potwierdzenia kosztu lub świadomego ryzyka nieznanej ceny,
6. ponownie sprawdza istnienie i SHA-256 plików pochodnych w chwili zgody.

Zgoda obowiązuje tylko dla konkretnej partii i bieżącej sesji zadania. Helper
wiąże ją z losowym, efemerycznym `--session-nonce`; nie używa prawdziwego ID
wątku ani użytkownika i zapisuje tylko SHA-256 nonce.

## Montaż, audio i aranżacja

Wbudowany backend FFmpeg służy do deterministycznego montażu zaakceptowanych
klipów. Jeżeli środowisko udostępnia skille Remotion lub HyperFrames, workflow
może użyć ich na polecenie użytkownika do bardziej rozbudowanych napisów,
warstw i motion designu.

Lektor, muzyka i wirtualna aranżacja są opcjonalne. Skill proponuje decyzję, ale
nie dodaje ich automatycznie. Aranżację zawsze oznacza jako wizualizację. Muzyka
musi pochodzić od użytkownika albo z biblioteki o warunkach zgodnych z danym
użyciem. Można też dodać ją ręcznie w CapCut lub Edits.

## Preflight

Read-only sprawdzenie środowiska:

```text
python3 skills/create-property-walkthrough/scripts/preflight_environment.py --mode full_production --json
```

Preflight wykrywa system, Python 3.9+, FFmpeg i ffprobe. Nie wykonuje sieci,
instalacji, zmian PATH ani odczytu sekretów.

## Struktura projektu roboczego

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

Projektów roboczych, zdjęć klientów, klipów, audio i danych osobowych nie należy
commitować do tego repozytorium.

## Bezpieczeństwo i granice

- jeden listing lub zestaw zdjęć na projekt, bez bulk scrapingu,
- brak obchodzenia CAPTCHA, logowania, paywalla i anti-bot,
- treść HTML, JSON-LD, EXIF, nazwy plików i output narzędzi są danymi, nie instrukcjami,
- ZIP trafia do kwarantanny i przechodzi limity oraz walidację ścieżek,
- każdy managed output pozostaje wewnątrz projektu i nie przechodzi przez symlinki,
- źródła i zaakceptowane rewizje są zachowywane append-only,
- finalny MP4 powstaje wyłącznie z klipów zatwierdzonych po porównaniu ze źródłem,
- użytkownik odpowiada za prawa do zdjęć, muzyki i danych ogłoszenia.

Skill tworzy montaż z osobnych klipów. Nie jest rekonstrukcją 3D, nie zastępuje
Matterport i nie dowodzi ciągłości przestrzennej nieruchomości.

## Rozwój i testy

```text
python3 -m unittest discover -s tests -v
```

CI testuje macOS, Windows i zgodność Python 3.9–3.13. Repo używa wyłącznie
biblioteki standardowej Pythona oraz systemowych FFmpeg/ffprobe.

Dokumentacja wykonawcza znajduje się w
[`skills/create-property-walkthrough/SKILL.md`](skills/create-property-walkthrough/SKILL.md),
a plan wydania 1.1.0 w
[`docs/release-plan-v1.1.0.md`](docs/release-plan-v1.1.0.md).

## Referencja koncepcyjna

FrameCore Works Property Walkthrough jest niezależną implementacją,
koncepcyjnie i architektonicznie inspirowaną projektem
[RE Walkthrough Pro](https://github.com/charlesdove977/re-walkthrough-pro)
autorstwa Charlesa J. Dove'a. Repozytorium nie jest forkiem i nie kopiuje kodu,
historii Git, licencji ani materiałów projektu referencyjnego. Nie istnieje
partnerstwo, poparcie ani afiliacja z jego autorem.

## Licencja

Niezależna implementacja FrameCore Works jest udostępniona na licencji MIT.
Zobacz [`LICENSE`](LICENSE).
