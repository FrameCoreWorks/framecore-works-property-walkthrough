# FrameCore Works Property Walkthrough

Polskojęzyczny skill Codexa do tworzenia kompletnych projektów cinematic walkthrough nieruchomości z pojedynczego publicznego linku, wgranych zdjęć, katalogu, ZIP-u albo połączenia linku z własnymi zdjęciami.

Skill porządkuje materiał, przygotowuje plan scen i samodzielne prompty image-to-video, wspiera bezpieczny manual mode, importuje gotowe klipy, prowadzi kontrolę jakości i montuje lokalne filmy przez FFmpeg. Automatyczne wykonanie zewnętrzne jest możliwe dopiero po skonfigurowaniu dokładnie wskazanego dostawcy oraz po aktualnej zgodzie na konkretną partię.

## Zakres

- pojedyncze polskie ogłoszenie lub publiczna strona agencji,
- zdjęcia, katalog, ZIP i tryb hybrydowy,
- provenance, hashe, deduplikacja i contact sheets,
- selekcja przestrzeni i stabilny plan scen,
- angielskie prompty I2V z polskimi metadanymi,
- neutralny provider profile bez sekretów,
- manualny pakiet generacyjny,
- import klipów, ffprobe, próbki do QC i selektywna regeneracja,
- master 16:9 oraz opcjonalny wariant 9:16.

Projekt nie jest wyszukiwarką ofert, masowym scraperem, aplikacją ani systemem 3D.

## Wymagania

- Codex z obsługą skilli,
- Python 3.9 lub nowszy; zalecany Python 3.11,
- FFmpeg i ffprobe dostępne w `PATH`,
- uprawnienia do używania zdjęć oraz danych źródłowych.

Repo nie wymaga zewnętrznych pakietów Pythona.

## Instalacja

Z repozytorium instaluj wyłącznie przetestowaną rewizję. Docelowa lokalizacja:

```text
$CODEX_HOME/skills/create-property-walkthrough
```

Proces instalacyjny używa stagingu na tym samym filesystemie, sprawdza hashe i uruchamia systemowy `quick_validate.py`, zanim opublikuje katalog skilla atomowym rename.

Po poprawnej instalacji Codex zadaje jedno pytanie o dostawcę. Przed tym pytaniem nie skanuje integracji, nie wyświetla nazw i niczego nie rekomenduje. Sam wybór dostawcy nie uruchamia generowania.

## Użycie

Przykładowe wywołanie skilla:

```text
Użyj $create-property-walkthrough, aby zamienić link do ogłoszenia lub wgrane zdjęcia nieruchomości w kompletny projekt filmowego walkthrough.
```

Nowy projekt można utworzyć poleceniem:

```bash
python "$CODEX_HOME/skills/create-property-walkthrough/scripts/init_project.py" --root walkthrough-projects --nazwa "Mieszkanie Łódź Centrum"
```

Każdy skrypt ma polski `--help`. Szczegółowy przepływ znajduje się w `skills/create-property-walkthrough/SKILL.md` i jego references.

## Workflow linku

Codex pobiera pojedynczą publiczną stronę przez zaufaną powierzchnię web/browser i zapisuje bounded snapshot. Lokalny helper nie wykonuje sieci, tylko analizuje snapshot JSON-LD, Open Graph i jawne dane. Brakujące wartości pozostają `null`.

Gdy strona blokuje dostęp, projekt zachowuje częściowe dane i ostrzeżenie, a użytkownik może dograć zdjęcia i wznowić ten sam projekt. Skill nie obchodzi zabezpieczeń.

## Workflow zdjęć i ZIP

Originals są zachowywane. ZIP trafia do kwarantanny i przechodzi limity liczby plików, rozmiaru, ścieżek, linków, typów wpisów oraz kolizji Unicode. Obrazy przechodzą kontrolę magic bytes, wymiarów, SHA-256 i duplikatów. Contact sheets powstają lokalnie przez FFmpeg.

## Tryb hybrydowy

Link dostarcza metadane, a zdjęcia użytkownika są preferowanymi assetami. Każde źródło zachowuje provenance. Duplikaty nie są dodawane drugi raz.

## Manual mode

Manual mode nie wymaga dostawcy. Tworzy:

- wybrane zdjęcia,
- plan scen i stable scene IDs,
- samodzielne prompty,
- oczekiwane nazwy klipów,
- manifest pakietu generacyjnego.

Po wygenerowaniu klipów poza Codexem można je zaimportować i wznowić workflow od kontroli technicznej.

## Onboarding dostawcy i credentials

Po odpowiedzi użytkownika sprawdzany jest wyłącznie wskazany dostawca i wyłącznie wybrana metoda MCP albo API. Walidacja opiera się na oficjalnej dokumentacji, nie wykonuje testowej generacji i nie wysyła zdjęć.

Profil bez sekretów jest przechowywany poza repo w:

```text
$CODEX_HOME/state/create-property-walkthrough/provider-profile.json
```

Sekret pozostaje w bezpiecznym magazynie, keychain albo zmiennej środowiskowej. Repo, profile, manifesty i logi przechowują tylko nazwę referencji do sekretu.

## Zgoda na generowanie i koszt

Przed każdą partią zewnętrzną Codex pokazuje dostawcę, model, scene IDs, liczbę scen, czas, format, zakres uploadu i koszt lub stan jego weryfikacji. Zgoda dotyczy wyłącznie niezmiennego fingerprintu tej partii.

Zmiana dostawcy, modelu, zdjęć, scen, formatu, czasu, scope albo kosztu wymaga nowej zgody. Nieznany koszt i dodatkowo płatny retry blokują wykonanie do jawnego potwierdzenia.

## Struktura outputu

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

`project.json` jest zapisywany atomowo i przechowuje wersjonowany stan, provenance, hashe, sceny, job IDs, klipy, QC i zależności. Nie przechowuje sekretów.

## Ograniczenia i prawa

- Efekt jest cinematic walkthrough z osobnych klipów, nie prawdziwą rekonstrukcją 3D ani Matterport.
- Kolejność scen jest redakcyjna. Nie stanowi potwierdzenia rzeczywistej ciągłości przestrzennej.
- Skill nie wymyśla niewidocznych pomieszczeń i nie gwarantuje, że zablokowana strona będzie dostępna.
- Walidacja near-duplicate i wizualne QC wspierają decyzję, ale wymagają oceny Codexa lub użytkownika.
- Licencja kodu nie daje praw do zdjęć, opisów, znaków, logo, fontów, muzyki ani danych osobowych.
- Użytkownik odpowiada za prawa do źródeł i upload do wybranego dostawcy.

## Udział Hipsona

Projekt przeszedł trzy obowiązkowe checkpointy Hipsona. Checkpoint 2 i 3 wymagały korekt, po których finalny plan P1–P18 oraz macierz R001–R051 otrzymały `PASS`. Szczegóły decyzji znajdują się w [`docs/design-synthesis.md`](docs/design-synthesis.md) i [`docs/build-plan.md`](docs/build-plan.md).

## Referencja koncepcyjna

FrameCore Works Property Walkthrough to niezależnie opracowany skill Codexa, koncepcyjnie i architektonicznie inspirowany projektem RE Walkthrough Pro autorstwa Charlesa J. Dove'a. Projekt nie jest forkiem i nie zachowuje ani nie modyfikuje historii Git oryginalnego repozytorium.

- [RE Walkthrough Pro](https://github.com/charlesdove977/re-walkthrough-pro)
- [Upstream LICENSE](https://github.com/charlesdove977/re-walkthrough-pro/blob/62b988b714576ef81aea79f34cc1f25de36c2b5e/LICENSE)
- [Zachowana licencja MIT upstream](licenses/re-walkthrough-pro-MIT.txt)
- [Informacje o materiałach zewnętrznych](THIRD_PARTY_NOTICES.md)

Nie istnieje partnerstwo, endorsement ani afiliacja z autorem projektu referencyjnego.

## Licencja

Niezależna implementacja FrameCore Works jest dostępna na licencji MIT. Zobacz [`LICENSE`](LICENSE).
