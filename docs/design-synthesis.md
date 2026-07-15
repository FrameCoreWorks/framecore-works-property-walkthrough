# Synteza projektu

## Status dokumentu

- Projekt: **FrameCore Works Property Walkthrough**
- Repozytorium: `framecore-works-property-walkthrough`
- Skill: `create-property-walkthrough`
- Rynek i język użytkownika: Polska, język polski
- Status: zaakceptowany do implementacji po Hipson Checkpoint 3
- Data syntezy: 2026-07-11
- Aktualizacja kontraktu dystrybucyjnego: 2026-07-15, wydanie 1.1.1
- Tryb realizacji: niezależna implementacja clean-room, skill-first

## Cel

Zbudować instalowalny plugin ChatGPT/Codex z jednym skillem, który tworzy projekt filmowego walkthrough nieruchomości z jednego publicznego linku, wgranych zdjęć, katalogu, ZIP-u albo trybu hybrydowego. Skill prowadzi od bezpiecznego intake przez selekcję zdjęć i plan scen do promptów image-to-video. Zależnie od możliwości hosta i wyboru użytkownika może zakończyć pracę pakietem planistycznym, przyjąć ręcznie wygenerowane klipy albo przeprowadzić zewnętrzną generację, kontrolę jakości i montaż finalnego MP4.

Rezultat jest cinematic walkthrough z osobnych klipów. Nie jest rekonstrukcją 3D i nie gwarantuje ciągłości przestrzennej pomiędzy pomieszczeniami.

## Zakres

- jeden link do ogłoszenia lub strony agencji,
- zdjęcia wgrane bezpośrednio, katalog zdjęć i ZIP,
- link z metadanymi połączony z preferowanymi zdjęciami użytkownika,
- bezpieczne pozyskanie dostępnych publicznie metadanych,
- walidacja, identyfikacja, deduplikacja i miniatury zdjęć,
- contact sheets i zapis analizy wykonanej przez Codexa,
- deterministyczny plan 6–10 scen, gdy materiały na to pozwalają,
- samodzielny angielski prompt I2V dla każdej sceny oraz polskie metadane,
- manualny pakiet generacyjny bez zewnętrznego wykonania,
- provider-neutral onboarding, a konfiguracja connectora, MCP albo API dopiero dla zewnętrznej generacji,
- batch-scoped zgoda na upload i generowanie oraz osobne potwierdzenie kosztu,
- import, techniczna kontrola klipów, raport ręcznego QC,
- render 16:9 i opcjonalny 9:16,
- wznowienie projektu i selektywne unieważnianie zależności,
- testy wyłącznie na syntetycznych fixture’ach.

## Poza zakresem

- wyszukiwarka i porównywarka ofert,
- masowy scraping, crawl kategorii i obchodzenie zabezpieczeń,
- aplikacja webowa, desktopowa, API lub baza danych,
- automatyczny wybór, skanowanie, porównywanie lub rekomendowanie dostawców,
- testowe generowanie zewnętrzne podczas konfiguracji,
- automatyczne dodawanie muzyki, voice-overu, logo, adresu lub danych kontaktowych bez decyzji użytkownika,
- obietnica Matterport, rekonstrukcji 3D lub zweryfikowanej topologii lokalu.

## Relacja z projektem referencyjnym

FrameCore Works Property Walkthrough to niezależnie opracowany plugin ChatGPT/Codex z jednym skillem, koncepcyjnie i architektonicznie inspirowany projektem RE Walkthrough Pro autorstwa Charlesa J. Dove'a. Projekt nie jest forkiem i nie zachowuje ani nie modyfikuje historii Git oryginalnego repozytorium.

RE Walkthrough Pro autorstwa Charlesa J. Dove'a służył jako referencja koncepcyjna i architektoniczna dla workflow tworzenia walkthrough nieruchomości z osobnych klipów pomieszczeń. FrameCore Works Property Walkthrough został zaimplementowany niezależnie od początku i nie zawiera historii Git oryginalnego repozytorium.

Repozytorium upstream nie jest używane jako working tree. Do nowego repo nie zostaną przeniesione jego obiekty Git, historia, kod, dokumentacja ani plik licencji. README zachowuje opisową atrybucję źródła wiedzy i inspiracji koncepcyjnej. Każde ewentualne późniejsze zapożyczenie wymaga osobnej analizy licencyjnej przed włączeniem.

## Architektura skill-first

Repozytorium zawiera jeden główny skill i małe deterministyczne narzędzia. `SKILL.md` przechowuje rdzeń workflow i routing do references. Szczegóły domenowe są ładowane progresywnie. Skrypty nie podejmują decyzji kreatywnych i nie uruchamiają dostawców bez jawnych danych oraz bramek.

Implementacja zachowuje jeden kontrakt pluginu dla ChatGPT i Codexa. Lokalne helpery pozostają przenośne między macOS, Windows i Linux, ale są uruchamiane wyłącznie wtedy, gdy host udostępnia Python 3.9+, FFmpeg, ffprobe i lokalne pliki. Instalacja pluginu sama nie instaluje tych narzędzi.

Planowana struktura:

```text
framecore-works-property-walkthrough/
├── README.md
├── AGENTS.md
├── LICENSE
├── .gitignore
├── .env.example
├── docs/
│   ├── design-synthesis.md
│   ├── build-plan.md
│   ├── clean-room-ledger.md
│   └── checkpoint-log.md
├── skills/create-property-walkthrough/
│   ├── SKILL.md
│   ├── agents/openai.yaml
│   ├── references/
│   ├── scripts/
│   └── assets/
└── tests/
    ├── fixtures/
    └── synthetic-project/
```

Nie powstaje `requirements.txt`, ponieważ implementacja używa wyłącznie biblioteki standardowej Pythona. Szczegóły wykonawcze helperów pozostają częścią działania skilla w kompatybilnym hoście, a nie osobną ścieżką instalacji użytkownika.

## Model stanu projektu

Każdy projekt żyje w `walkthrough-projects/<project-id>/`. `project.json` jest wersjonowanym źródłem prawdy i jest zapisywany atomowo przez plik tymczasowy na tym samym filesystemie, `fsync` oraz `os.replace`.

Główne własności:

- identyfikatory zdjęć wynikają z SHA-256 zawartości,
- `scene_id` jest nieprzezroczysty, stabilny i nigdy nie jest używany ponownie,
- kolejność zmienia wyłącznie `sequence_index`,
- usunięte sceny pozostawiają tombstone,
- zaakceptowane rewizje klipów są append-only i chronione hashem,
- zmiany zapisują hashe zależności i unieważniają tylko zależny etap,
- istniejące job IDs są uzgadniane przed ewentualnym ponownym submission,
- stan nie przechowuje sekretów ani pełnych odpowiedzi providera.

## Schematy i walidacja

Skrypty używają lokalnego walidatora ograniczonego podzbioru JSON Schema:

- `type`, `properties`, `required`, `additionalProperties`,
- `items`, `minItems`, `maxItems`,
- `enum`, `const`,
- `minLength`, `maxLength`, `pattern`,
- numeryczne `minimum` i `maximum`.

Nieobsługiwane słowa kluczowe są błędem, a nie cichym pominięciem. Reguły zależne od domeny, plików i hashy są sprawdzane osobną walidacją semantyczną.

## Ingestion linku

Codex używa wyłącznie zaufanej powierzchni web/browser do pobierania publicznej strony. Skrypt `extract_listing.py` nie wykonuje połączeń sieciowych. Przyjmuje zapisany lokalnie snapshot HTML i opcjonalny kanoniczny URL, waliduje rozmiar, kodowanie oraz pochodzenie, a następnie parsuje wyłącznie JSON-LD, Open Graph i jawne elementy publiczne.

Taki podział zapewnia:

- brak ukrytego bezpośredniego HTTP w helperach,
- kontrolę redirectów i private-network na powierzchni zaufanej,
- traktowanie treści strony jako danych nieufnych,
- zachowanie częściowych metadanych i fallback do uploadu,
- brak wykonywania instrukcji z HTML, JSON-LD, EXIF i nazw plików.

Jeżeli zaufana powierzchnia nie może zapisać snapshotu, Codex zachowuje uzyskane dane w projekcie i prosi o zdjęcia, zamiast obchodzić blokadę.

## Ingestion zdjęć i ZIP

Wszystkie wejścia trafiają najpierw do kwarantanny. ZIP jest odrzucany przy path traversal, ścieżce absolutnej, linku, specjalnym pliku, zagnieżdżonym archiwum, szyfrowaniu, kolizji nazw po normalizacji Unicode/case, przekroczeniu liczby wpisów, limitu pojedynczego pliku lub sumy rozpakowanych bajtów.

Zdjęcia są sprawdzane przez rozszerzenie, magic bytes i bezpieczny odczyt wymiarów. Obsługiwane są JPEG i PNG. Skrypty nie modyfikują originals. Metadane obejmują SHA-256, rozmiar, wymiary, orientację, provenance i status kwarantanny. Exact duplicates są pewne; near-duplicates są kandydatami do ręcznego potwierdzenia na podstawie deterministycznego dHash miniaturek.

Contact sheets są generowane przez FFmpeg, aby nie wprowadzać biblioteki obrazowej. Nazwy i raporty obsługują UTF-8 oraz polskie znaki.

## Selekcja i taksonomia

Rozdzielone są trzy pojęcia:

- `asset_kind`: fotografia, plan, mapa, screenshot, portret, logo lub inne,
- `room_type`: typ pomieszczenia,
- `curation_status`: wybrane, rezerwa lub odrzucone.

Każda przestrzeń może mieć stabilne `room_instance_id`. Jedno zdjęcie jest domyślnie wybierane na przestrzeń. Dodatkowy kąt jest dopuszczalny tylko, gdy wnosi inną wartość. Ranking uwzględnia jakość techniczną, użyteczność animacyjną, ryzyko deformacji i pokrycie walkthrough.

## Plan scen i kontrakt promptu

Plan jest redakcyjny, a nie topologiczny. Domyślnie ma 6–10 scen, ale krótszy wynik jest poprawny, gdy brakuje materiału. Nie duplikuje się scen jako wypełniaczy.

Każda scena ma:

- jedno zaakceptowane zdjęcie źródłowe,
- jeden format i czas trwania,
- dokładnie jeden kontrolowany ruch kamery,
- stabilny `scene_id`,
- jawne ryzyko deformacji,
- samodzielny prompt po angielsku,
- wymagane polskie metadane statusowe.

Prompty zachowują geometrię i zawartość kadru, blokują nowe otwory, pokoje, obiekty, disappearance, duplication, morphing, bending, geometry drift i impossible reveals. Nie zawierają osobnego generycznego negative promptu.

## Onboarding środowiska i dostawcy

Przy pierwszym użyciu skill ustala cel, materiały i tryb `plan_only`, `manual_clips` albo `full_production`. Nie wymaga dostawcy do planowania ani pracy z ręcznie dostarczonymi klipami. Jeżeli host pozwala uruchomić lokalny preflight, skill sprawdza system, Python, FFmpeg i ffprobe bez sieci, instalacji, zmian `PATH` ani odczytu sekretów.

Dopiero po wyborze zewnętrznej generacji skill pyta o posiadane połączenie przez connector, MCP albo API. Nie skanuje i nie sugeruje konkretnych usług bez jawnej prośby. Gdy użytkownik prosi o rekomendację, najpierw ustala jego priorytet, a potem sprawdza bieżącą oficjalną dokumentację maksymalnie trzech pasujących opcji. Walidacja nie wykonuje generacji ani testowego uploadu.

Profil użytkownika bez sekretów jest przechowywany lokalnie poza repo:

`$CODEX_HOME/state/create-property-walkthrough/provider-profile.json`

Snapshot użyty przez projekt trafia do:

`provider/provider-profile.snapshot.json`

Profil przechowuje wyłącznie identyfikatory, capabilities, zweryfikowane ograniczenia, referencję do sekretu i datę weryfikacji. Sekret pozostaje w bezpiecznym magazynie, keychain albo zmiennej środowiskowej i nigdy nie trafia do argv, logów, Git ani manifestów.

## Zgoda, koszt i upload

Każda partia generacyjna ma immutable fingerprint związany z providerem, modelem, hashami assetów, scene IDs, czasem, formatem, liczbą jobów, profilem kosztu i output path.

Przed submission Codex pokazuje zakres oraz pyta dokładnie o zgodę na upload i generowanie. Jeżeli operacja może być płatna, wymaga osobnego potwierdzenia kosztu. Nieznany koszt blokuje automatyczne wykonanie do jawnego potwierdzenia ryzyka. Zmiana fingerprintu lub dodatkowo płatny retry wymaga nowej zgody.

Do uploadu służą tylko osobne derivative files przygotowane przez `prepare_upload_derivatives.py`. Usuwane są metadane, zapisywane są nowe hashe, status praw i PII oraz dokładna lista ujawniana użytkownikowi. Oryginały nie są cicho podstawiane.

## Wykonanie automatyczne i manualne

Rdzeń repo nie zawiera adaptera konkretnego providera. Po wyborze ChatGPT lub Codex korzysta z aktualnie zatwierdzonej powierzchni connector/MCP/API i profilu capabilities. Brak bezpiecznej powierzchni pozostawia projekt w trybie planu albo manualnym.

Manual mode zawsze może wyprodukować curated images, plan scen, prompty, oczekiwane nazwy i manifest generacyjny. Import klipów wznawia ten sam projekt od kontroli technicznej.

Automatyczne joby używają ograniczonej równoległości i idempotency key, jeśli provider ją wspiera. Crash window bez potwierdzonego job ID przechodzi do `submission_pending` i ręcznego reconciliation, nigdy do automatycznego resubmitu.

## Kontrola jakości

`ffprobe` sprawdza dekodowalność, strumienie, czas, wymiary, SAR, FPS i format pikseli. `ffmpeg` tworzy próbki 0/25/50/75/100%. Ocena zgodności obrazu ze źródłem pozostaje kontrolą Codexa lub użytkownika i jest zapisywana w raporcie.

Statusy sceny:

- `approved`,
- `regenerate`,
- `rejected`,
- `needs-manual-review`.

Krytyczne błędy geometrii nie mogą zostać zaakceptowane. Regeneracja tworzy nową rewizję, nie nadpisuje zaakceptowanego klipu i unieważnia tylko scenę oraz zależny render.

## Rendering i resume

Render używa H.264, `yuv420p`, stałego FPS i SAR 1:1. Profil 16:9 to 1920×1080, a 9:16 to 1080×1920. Obraz nie jest rozciągany. Domyślne są hard cuts. Strategia pionowa jest jawna per scena: anchored crop, contain albo padded background; content-aware reframe wymaga osobnej konfiguracji i zgody.

Resume zaczyna od `project.json`, sprawdza schemat, pliki i hashe, zachowuje poprawne etapy oraz zaakceptowane klipy, uzgadnia istniejące joby i wznawia od pierwszego niekompletnego lub unieważnionego etapu. Poprzednia zgoda nigdy nie upoważnia do nowego submission.

## Instalacja

Repozytorium dostarcza manifest pluginu oraz katalog marketplace. W Codex CLI użytkownik dodaje marketplace przypięty do taga wydania i instaluje plugin z tego katalogu. W ChatGPT desktop instalacja odbywa się z katalogu Plugins w obsługiwanej powierzchni Work/Codex. Samo wklejenie URL do dowolnego wariantu ChatGPT nie jest gwarantowaną ścieżką instalacji. Repo nie dostarcza instalatora systemowego i nie modyfikuje hosta.

## GitHub

Lokalne repo ma nową historię Git i wyłącznie origin do `FrameCoreWorks/framecore-works-property-walkthrough`. Publiczny target jest repozytorium dystrybucyjnym skilla, musi być non-fork i należeć do `FrameCoreWorks`. Istniejący target można kontynuować tylko, jeśli jest tym samym clean-room projektem, zachowuje bezpieczne pochodzenie i pozwala na fast-forward bez naruszania zawartości. Każda niepewność lub konflikt zatrzymuje push.

Checkpoint jest pushowany dopiero po testach, secret scan, asset scan i czystym diffie. SHA checkpointu jest zapisywany w następnym checkpointcie, a finalny SHA w handoverze, aby uniknąć samoodnoszącego commita.

## Testy

Testy używają `unittest`, tymczasowych katalogów i syntetycznych JPEG/PNG oraz lokalnych klipów FFmpeg. Provider-free E2E uruchamia helpery z blokadą socketów i providerem-pułapką. Licznik zewnętrznych wywołań musi pozostać równy zero.

Zakres obejmuje strukturę pluginu i skilla, marketplace, aktywację, preflight, schematy, ZIP, pliki uszkodzone, Unicode, HTML fixtures, provenance, deduplikację, contact sheets, sceny, prompty, provider-neutral onboarding, profile bez sekretów, zgody, cost gate, trzy tryby pracy, import, FFmpeg, resume, selektywną regenerację, licencje, clean-room i dystrybucję z GitHuba.

## Ryzyka i ograniczenia

- Publiczne strony mogą blokować dostęp. Fallbackiem jest częściowy zapis i upload, nie obchodzenie blokady.
- Bez zewnętrznej biblioteki obrazowej walidacja i miniatury wspierają świadomie ograniczony zestaw JPEG/PNG.
- Near-duplicate i wizualne QC są wsparciem decyzyjnym, nie niezawodnym automatem CV.
- Implicit activation może nie być obserwowalne w lokalnym harnessie. Wtedy status jest `niezweryfikowane`, nigdy cichy PASS.
- Brak wyboru lub bezpiecznej powierzchni providera nie blokuje planowania ani manual mode, ale blokuje zewnętrzną generację.
- `blocked` w onboardingu nie jest ukończeniem projektu i nie uruchamia substytucji dostawcy.

## Rekomendacje przyjęte

- jeden lekki plugin z jednym skillem zamiast aplikacji,
- czysta historia Git i osobny clean-room ledger,
- trusted-web retrieval oraz helpery bez socketów,
- centralna kwarantanna wejść i fail-closed ZIP,
- rozdzielone `asset_kind`, `room_type` i `curation_status`,
- stabilne `scene_id`, tombstones i append-only approved revisions,
- batch fingerprint dla zgody, koszt fail-closed i derivatives-only upload,
- atomic state, dependency hashes i idempotent resume,
- ograniczony jawny podzbiór JSON Schema,
- provider-neutral profile poza repo i manual mode,
- hermetyczny E2E z zerowym ruchem sieciowym,
- dystrybucja pluginu przez przypięty tag i repozytoryjny marketplace.

## Rekomendacje odrzucone lub odłożone

- aplikacja webowa, desktopowa, serwer API i baza danych: poza zakresem,
- aplikacja lub rozbudowany runtime pluginu: brak potrzeby dla jednego skilla,
- zależności Pillow, requests i jsonschema: nie są konieczne dla pierwszej kompletnej wersji,
- bezpośredni scraper HTTP w helperze: zastąpiony zaufaną powierzchnią web/browser,
- committed adapter jednego providera: narusza provider-neutral kontrakt,
- automatyczny wybór providera lub provider fallback: zakazany,
- automatyczna generacja testowa podczas onboardingu: zakazana,
- ukryty cap jako obejście nieznanego kosztu: odrzucony, wymagane jawne potwierdzenie,
- orbit, doorway travel i złożone ruchy: zbyt wysokie ryzyko deformacji.

## Wynik Hipsona

- Checkpoint 1: analiza niezależna ukończona.
- Checkpoint 2: początkowo `REVISE`, po poprawkach `PASS`.
- Checkpoint 3: początkowo `REVISE`, po domknięciu P1–P18 i R001–R051 `PASS`.
- Final gate: `HIPSON_CHECKPOINT_3`, `final_gate: PASSED`.
- Warunek startu: zapis tego dokumentu i planu, preflight workspace/Git oraz brak nowego konfliktu.
