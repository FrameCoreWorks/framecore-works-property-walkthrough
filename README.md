# FrameCore Works Property Walkthrough

[![CI](https://github.com/FrameCoreWorks/framecore-works-property-walkthrough/actions/workflows/ci.yml/badge.svg)](https://github.com/FrameCoreWorks/framecore-works-property-walkthrough/actions/workflows/ci.yml)

Polskojęzyczny skill Codexa do tworzenia projektów filmowej prezentacji nieruchomości z pojedynczego publicznego linku, wgranych zdjęć, katalogu, ZIP-u albo połączenia linku z własnymi zdjęciami.

Skill jest projektowany do natywnego użycia w Codexie na macOS i Windows.

Skill porządkuje materiał, przygotowuje plan scen i samodzielne prompty image-to-video, tworzy pakiet do ręcznego generowania bez połączenia z dostawcą, importuje gotowe klipy, prowadzi kontrolę jakości i montuje finalne filmy. Automatyczne wykonanie zewnętrzne jest możliwe dopiero po skonfigurowaniu dokładnie wskazanego dostawcy oraz po aktualnej zgodzie na konkretną partię.

## Zakres

- pojedyncze polskie ogłoszenie lub publiczna strona agencji,
- zdjęcia, katalog, ZIP i tryb hybrydowy,
- pochodzenie danych, skróty SHA-256, deduplikacja i arkusze kontaktowe,
- selekcja przestrzeni i stabilny plan scen,
- angielskie prompty I2V z polskimi metadanymi,
- neutralny profil dostawcy bez sekretów,
- pakiet do ręcznego generowania,
- import klipów, próbki do kontroli jakości i selektywna regeneracja,
- master 16:9 oraz opcjonalny wariant 9:16.

Projekt nie jest wyszukiwarką ofert, masowym scraperem, aplikacją ani systemem 3D.

## Instalacja w Codexie

Wklej do Codexa link do repozytorium i poproś o instalację skilla:

```text
Zainstaluj skill z repozytorium:
https://github.com/FrameCoreWorks/framecore-works-property-walkthrough
```

Codex instaluje skill `create-property-walkthrough`. Przy pierwszym użyciu skill pyta o dostawcę bez skanowania, sugerowania ani wybierania integracji.

## Użycie

Po instalacji wywołaj skill w Codexie:

```text
Użyj $create-property-walkthrough, aby zamienić link do ogłoszenia lub wgrane zdjęcia nieruchomości w projekt filmowej prezentacji.
```

Szczegółowy przebieg znajduje się w `skills/create-property-walkthrough/SKILL.md` i jego materiałach referencyjnych.

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

Codex przechowuje profil bez sekretów poza repozytorium. Repozytorium, profile, manifesty i logi przechowują tylko nazwę bezpiecznej referencji do sekretu, nigdy jego wartość.

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

Podziękowania dla Charlesa J. Dove'a za publiczne udostępnienie projektu [RE Walkthrough Pro](https://github.com/charlesdove977/re-walkthrough-pro), który posłużył jako źródło wiedzy i inspiracja dla ogólnej koncepcji workflow.

Nie istnieje partnerstwo, poparcie ani afiliacja z autorem projektu referencyjnego.

## Licencja

Niezależna implementacja FrameCore Works jest dostępna na własnej licencji MIT. Zobacz [`LICENSE`](LICENSE).
