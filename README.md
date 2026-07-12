# FrameCore Works Property Walkthrough

Polskojęzyczny skill Codexa do tworzenia projektów filmowej prezentacji nieruchomości z pojedynczego publicznego linku, wgranych zdjęć, katalogu, ZIP-u albo połączenia linku z własnymi zdjęciami.

Skill porządkuje materiał, przygotowuje plan scen i samodzielne prompty image-to-video, tworzy pakiet do ręcznego generowania bez połączenia z dostawcą, importuje gotowe klipy, prowadzi kontrolę jakości i montuje lokalne filmy przez FFmpeg. Automatyczne wykonanie zewnętrzne jest możliwe dopiero po skonfigurowaniu dokładnie wskazanego dostawcy oraz po aktualnej zgodzie na konkretną partię.

## Zakres

- pojedyncze polskie ogłoszenie lub publiczna strona agencji,
- zdjęcia, katalog, ZIP i tryb hybrydowy,
- pochodzenie danych, skróty SHA-256, deduplikacja i arkusze kontaktowe,
- selekcja przestrzeni i stabilny plan scen,
- angielskie prompty I2V z polskimi metadanymi,
- neutralny profil dostawcy bez sekretów,
- pakiet do ręcznego generowania,
- import klipów, ffprobe, próbki do kontroli jakości i selektywna regeneracja,
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

Instalacja odbywa się przez katalog tymczasowy w tym samym systemie plików. Przed atomowym opublikowaniem katalogu skilla sprawdzane są skróty plików i uruchamiany jest systemowy `quick_validate.py`.

Po poprawnej instalacji Codex zadaje jedno pytanie o dostawcę. Przed tym pytaniem nie skanuje integracji, nie wyświetla nazw i niczego nie rekomenduje. Sam wybór dostawcy nie uruchamia generowania.

## Użycie

Przykładowe wywołanie skilla:

```text
Użyj $create-property-walkthrough, aby zamienić link do ogłoszenia lub wgrane zdjęcia nieruchomości w projekt filmowej prezentacji.
```

Nowy projekt można utworzyć poleceniem:

```bash
python "$CODEX_HOME/skills/create-property-walkthrough/scripts/init_project.py" --projects-root walkthrough-projects "Mieszkanie Łódź Centrum"
```

Każdy skrypt ma polski `--help`. Szczegółowy przebieg znajduje się w `skills/create-property-walkthrough/SKILL.md` i jego materiałach referencyjnych.

## Praca z linkiem

Codex pobiera jedną publiczną stronę przez zaufane narzędzie przeglądarkowe i zapisuje jej ograniczoną kopię. Lokalny skrypt nie łączy się z siecią; analizuje JSON-LD, Open Graph i jawne dane strony. Brakujące wartości pozostają `null`.

Gdy strona blokuje dostęp, projekt zachowuje częściowe dane i ostrzeżenie, a użytkownik może dograć zdjęcia i wznowić ten sam projekt. Skill nie obchodzi zabezpieczeń.

## Praca ze zdjęciami i ZIP-em

Pliki źródłowe są zachowywane. ZIP trafia do kwarantanny i przechodzi limity liczby plików, rozmiaru, ścieżek, dowiązań, typów wpisów oraz kolizji Unicode. Obrazy przechodzą kontrolę sygnatury pliku, wymiarów, SHA-256 i duplikatów. Arkusze kontaktowe powstają lokalnie przez FFmpeg.

## Tryb hybrydowy

Link dostarcza metadane, a zdjęcia użytkownika są preferowanymi materiałami. Każde źródło zachowuje opis pochodzenia danych. Duplikaty nie są dodawane drugi raz.

## Tryb ręczny

Tryb ręczny nie wymaga dostawcy. Tworzy:

- wybrane zdjęcia,
- plan scen i stabilne `scene_id`,
- samodzielne prompty,
- oczekiwane nazwy klipów,
- manifest pakietu generacyjnego.

Po wygenerowaniu klipów poza Codexem można je zaimportować i wznowić proces od kontroli technicznej.

## Konfiguracja dostawcy i dane dostępowe

Po odpowiedzi użytkownika sprawdzany jest wyłącznie wskazany dostawca i wyłącznie wybrana metoda MCP albo API. Walidacja opiera się na oficjalnej dokumentacji, nie wykonuje testowej generacji i nie wysyła zdjęć.

Profil bez sekretów jest przechowywany poza repo w:

```text
$CODEX_HOME/state/create-property-walkthrough/provider-profile.json
```

Sekret pozostaje w bezpiecznym magazynie, pęku kluczy albo zmiennej środowiskowej. Repozytorium, profile, manifesty i logi przechowują tylko nazwę referencji do sekretu.

## Zgoda na generowanie i koszt

Przed każdą partią zewnętrzną Codex pokazuje dostawcę, model, `scene_id`, liczbę scen, czas, format, zakres przesyłania danych i koszt lub stan jego weryfikacji. Zgoda dotyczy wyłącznie niezmiennego odcisku tej partii.

Zmiana dostawcy, modelu, zdjęć, scen, formatu, czasu, zakresu albo kosztu wymaga nowej zgody. Nieznany koszt i dodatkowo płatna ponowna próba blokują wykonanie do jawnego potwierdzenia.

## Struktura plików wynikowych

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

`project.json` jest zapisywany atomowo i przechowuje wersjonowany stan, pochodzenie danych, skróty SHA-256, sceny, identyfikatory zadań, klipy, kontrolę jakości i zależności. Nie przechowuje sekretów.

## Ograniczenia i prawa

- Efekt jest filmową prezentacją z osobnych klipów, nie prawdziwą rekonstrukcją 3D ani Matterport.
- Kolejność scen jest redakcyjna. Nie stanowi potwierdzenia rzeczywistej ciągłości przestrzennej.
- Skill nie wymyśla niewidocznych pomieszczeń i nie gwarantuje, że zablokowana strona będzie dostępna.
- Wykrywanie bardzo podobnych zdjęć i wizualna kontrola jakości wspierają decyzję, ale wymagają oceny Codexa lub użytkownika.
- Licencja kodu nie daje praw do zdjęć, opisów, znaków, logo, fontów, muzyki ani danych osobowych.
- Użytkownik odpowiada za prawa do źródeł i przesyłanie ich do wybranego dostawcy.

## Dokumentacja projektu

Plan i decyzje projektowe znajdują się w [`docs/design-synthesis.md`](docs/design-synthesis.md) oraz [`docs/build-plan.md`](docs/build-plan.md).

## Referencja koncepcyjna

FrameCore Works Property Walkthrough to niezależnie opracowany skill Codexa, koncepcyjnie i architektonicznie inspirowany projektem RE Walkthrough Pro autorstwa Charlesa J. Dove'a. Projekt nie jest forkiem i nie zachowuje ani nie modyfikuje historii Git oryginalnego repozytorium.

- [RE Walkthrough Pro](https://github.com/charlesdove977/re-walkthrough-pro)
- [Licencja projektu źródłowego](https://github.com/charlesdove977/re-walkthrough-pro/blob/62b988b714576ef81aea79f34cc1f25de36c2b5e/LICENSE)
- [Zachowana licencja MIT projektu źródłowego](licenses/re-walkthrough-pro-MIT.txt)
- [Informacje o materiałach zewnętrznych](THIRD_PARTY_NOTICES.md)

Nie istnieje partnerstwo, poparcie ani afiliacja z autorem projektu referencyjnego.

## Licencja

Niezależna implementacja FrameCore Works jest dostępna na licencji MIT. Zobacz [`LICENSE`](LICENSE).
