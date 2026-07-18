# FrameCore Works Property Walkthrough

[![CI](https://github.com/FrameCoreWorks/framecore-works-property-walkthrough/actions/workflows/ci.yml/badge.svg)](https://github.com/FrameCoreWorks/framecore-works-property-walkthrough/actions/workflows/ci.yml)

Polskojęzyczny plugin ChatGPT/Codex do przygotowania filmowej prezentacji
nieruchomości na podstawie linku do ogłoszenia albo zdjęć. Prowadzi użytkownika
od zebrania materiałów, przez plan filmu i generowanie klipów, aż do kontroli
jakości oraz finalnego MP4, jeżeli środowisko udostępnia potrzebne narzędzia.

Repozytorium zawiera jeden plugin i jeden skill:
`$create-property-walkthrough`.

## Czym jest ten skill

To kierownik procesu produkcji, a nie osobny model wideo. Porządkuje pracę,
pilnuje kolejności etapów i przygotowuje wszystkie artefakty potrzebne do
stworzenia filmu:

```text
ogłoszenie lub zdjęcia → brief → wybór ujęć → storyboard i prompty
→ generacja albo import klipów → kontrola jakości → finalny MP4
```

Skill może:

- przyjąć link do pojedynczego ogłoszenia, zdjęcia JPEG/PNG, katalog, ZIP albo
  połączenie linku z własnymi zdjęciami,
- rozpoznać pomieszczenia i wybrać materiały nadające się do filmu,
- przygotować zwykle 6–10 scen, storyboard oraz samodzielne prompty
  image-to-video,
- utworzyć pakiet ręczny, który można wykorzystać w dowolnym zgodnym
  generatorze,
- użyć wskazanego przez użytkownika connectora, MCP albo API, jeżeli taka
  integracja jest już dostępna w środowisku,
- przyjąć gotowe klipy, wykonać ich techniczną i wizualną kontrolę jakości,
- zmontować zaakceptowane klipy do filmu 16:9 lub 9:16,
- wznowić istniejący projekt bez powtarzania poprawnie ukończonych etapów.

Skill nie jest scraperem portali, aplikacją SaaS ani dostawcą generowania. Nie
instaluje modeli, FFmpeg, kluczy API ani dodatkowych programów na urządzeniu
użytkownika. Nie obchodzi logowania, CAPTCHA, paywalla ani zabezpieczeń
anti-bot.

## Dla kogo

Skill jest przeznaczony dla osób, które mają zdjęcia lub ogłoszenie
nieruchomości i chcą przygotować uporządkowaną prezentację wideo, między innymi
dla pośredników, agentów nieruchomości, fotografów, deweloperów i zespołów
marketingowych.

Użytkownik dostarcza materiały, wybiera kierunek filmu i zatwierdza płatne
operacje. Skill prowadzi analizę, planowanie, przygotowanie promptów, kontrolę
stanu, QC oraz dostępny montaż.

## Jak wygląda praca ze skillem

1. Użytkownik podaje link, wgrywa zdjęcia albo przekazuje gotowe klipy.
2. Skill ustala cel filmu, format, odbiorcę, styl i wezwanie do działania.
3. Analizuje materiały i proponuje scenariusz, kolejność ujęć oraz storyboard.
4. Pokazuje prompty i listę używanych materiałów do akceptacji.
5. Użytkownik wybiera pracę bez generowania, montaż własnych klipów albo pełną
   produkcję przez swoją integrację.
6. Przed każdą płatną operacją skill pokazuje przewidywany koszt i prosi o
   jednoznaczną zgodę.
7. Po wygenerowaniu lub wgraniu klipów skill wykonuje QC i przygotowuje finalny
   film, jeżeli środowisko pozwala na lokalny montaż.

Scenariusz, storyboard, prompty i materiały są zatwierdzanymi etapami
pośrednimi. Głównym rezultatem pełnej produkcji jest zmontowany plik MP4.

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

Do samej instalacji pluginu nie są potrzebne FFmpeg, klucz API ani konto u
dostawcy wideo. Są one sprawdzane dopiero wtedy, gdy użytkownik wybiera etap,
który rzeczywiście ich wymaga.

Codex oraz ChatGPT w trybie Work obsługują skille. W tym repozytorium skill
`create-property-walkthrough` jest dystrybuowany wewnątrz pluginu, dzięki czemu
host instaluje jego instrukcje i wszystkie pliki pomocnicze jako jeden
wersjonowany pakiet.

Plugin można zainstalować na cztery sposoby. Codex Desktop i Codex CLI używają
tego samego wersjonowanego pakietu, ale oferują inny interfejs instalacji.
„Terminal” poniżej oznacza wariant bez interaktywnego katalogu pluginów.

### Codex Desktop na macOS lub Windows

To zalecana ścieżka dla osób pracujących w aplikacji desktopowej.

1. Sklonuj albo pobierz repozytorium do wybranego folderu na komputerze.
2. Otwórz jego katalog główny w aplikacji ChatGPT i wybierz powierzchnię
   **Codex** albo tryb **Work**.
3. Uruchom aplikację ponownie. Codex wykryje repozytoryjny katalog
   `.agents/plugins/marketplace.json`.
4. Otwórz **Plugins**, wybierz źródło **FrameCore Works**, otwórz
   **FrameCore Works Property Walkthrough** i wybierz przycisk instalacji.
5. Po instalacji rozpocznij nowe zadanie, aby załadować skill.

Gotowe polecenie do wklejenia w nowym zadaniu Codex Desktop:

```text
Zainstaluj w tym Codexie plugin z publicznego repozytorium:
https://github.com/FrameCoreWorks/framecore-works-property-walkthrough

Użyj oficjalnego wydania v1.1.1 i repozytoryjnego marketplace. Jeżeli repo jest
już sklonowane, nie twórz drugiej kopii. Nie kopiuj skilla ręcznie, nie instaluj
FFmpeg, modeli ani integracji API/MCP. Na końcu sprawdź, czy plugin jest
zainstalowany i aktywny, oraz poinformuj mnie, czy trzeba ponownie uruchomić
aplikację.
```

### Codex CLI z interaktywnym katalogiem pluginów

Ta ścieżka używa tekstowego katalogu pluginów dostępnego bezpośrednio w sesji
Codex CLI.

1. Dodaj marketplace przypięty do zweryfikowanego wydania i uruchom Codex:

   ```bash
   codex plugin marketplace add FrameCoreWorks/framecore-works-property-walkthrough --ref v1.1.1
   codex
   ```

2. W uruchomionej sesji wpisz:

   ```text
   /plugins
   ```

3. Wybierz marketplace **FrameCore Works**, otwórz plugin
   **FrameCore Works Property Walkthrough** i zainstaluj go.
4. Zakończ sesję i rozpocznij nową, aby załadować skill.

### Terminal bez interaktywnego katalogu

Ta ścieżka wykonuje całą instalację bezpośrednimi poleceniami i działa w
terminalu na macOS, Linuxie oraz Windowsie, jeżeli polecenie `codex` jest
dostępne w `PATH`.

```bash
codex plugin marketplace add FrameCoreWorks/framecore-works-property-walkthrough --ref v1.1.1
codex plugin add framecore-works-property-walkthrough@framecore-works
codex plugin list --marketplace framecore-works
```

Ostatnie polecenie powinno pokazać plugin jako zainstalowany i włączony. Po
instalacji uruchom nową sesję Codex.

### ChatGPT w przeglądarce

W ChatGPT web skille i pluginy są dostępne w trybie **Work**. Instalacja nie
jest dostępna w zwykłym trybie **Chat**, aplikacji mobilnej ani rozszerzeniu
IDE.

1. Otwórz [ChatGPT](https://chatgpt.com), przełącz się na tryb **Work** i otwórz
   [Plugins](https://chatgpt.com/plugins).
2. Wybierz źródło osobiste albo udostępnione przez workspace i znajdź
   **FrameCore Works Property Walkthrough**.
3. Otwórz szczegóły pluginu i wybierz przycisk instalacji.
4. Rozpocznij nowy czat. Wpisz `@` i wybierz plugin lub jego skill.

Gotowe polecenie do wklejenia w ChatGPT web w trybie Work:

```text
Chcę zainstalować plugin z publicznego repozytorium:
https://github.com/FrameCoreWorks/framecore-works-property-walkthrough

Sprawdź, czy FrameCore Works Property Walkthrough jest dostępny w katalogu
Plugins mojego trybu Work lub workspace. Jeżeli jest dostępny, przeprowadź mnie
przez instalację i poproś o rozpoczęcie nowego czatu. Jeżeli ta powierzchnia nie
pozwala na trwałą instalację z tego publicznego repozytorium, nie udawaj, że
plugin został zainstalowany. Wyjaśnij, że marketplace musi zostać najpierw
udostępniony w moim katalogu Plugins.
```

Samo wklejenie URL GitHuba do ChatGPT web nie jest
gwarantowaną ścieżką instalacji. Publiczny katalog Plugins użytkownika,
workspace albo udostępniony marketplace musi już zawierać ten plugin. Do
testowania bez publikacji w katalogu najpewniejsze są Codex Desktop i Codex CLI z
repozytoryjnym marketplace.

Instalacja kopiuje wersjonowany plugin do zarządzanego środowiska hosta. Nie
kopiuje skilla ręcznie do przypadkowych folderów i nie uruchamia instalatora
systemowego. Nie gwarantuje również dostępności lokalnego Pythona ani FFmpeg.
Skill sprawdza te możliwości dopiero przed etapem multimedialnym i pozostaje w
trybie planu lub pakietu ręcznego, gdy ich brakuje.

Więcej informacji zawiera oficjalna dokumentacja
[pluginów ChatGPT i Codexa](https://learn.chatgpt.com/docs/plugins) oraz
[budowania marketplace](https://learn.chatgpt.com/docs/build-plugins#build-your-own-curated-plugin-list).

## Pierwsze uruchomienie

Najprostsze polecenie startowe:

```text
Użyj $create-property-walkthrough. Chcę przygotować filmową prezentację
nieruchomości. Najpierw ustal ze mną cel, format i tryb pracy. Nie uruchamiaj
płatnej generacji bez pokazania kosztu i mojej jednoznacznej zgody.
```

Skill powinien zacząć od celu i dostępnych materiałów. Nie powinien na początku
wymagać wyboru dostawcy. Jeżeli użytkownik nie ma jeszcze integracji, nadal może
ukończyć analizę, storyboard, prompty i pakiet ręczny.

### Start z linku

```text
Użyj $create-property-walkthrough i przygotuj projekt prezentacji tej nieruchomości:
<link do ogłoszenia>
```

### Start ze zdjęć

```text
Użyj $create-property-walkthrough na wgranych zdjęciach. Przygotuj brief,
storyboard, prompty i pakiet ręczny. Nie uruchamiaj płatnej generacji.
```

### Start z gotowych klipów

```text
Użyj $create-property-walkthrough, wznów projekt, zaimportuj klipy,
wykonaj QC i przygotuj finalny MP4.
```

Przed generacją skill pokazuje zwięzłe podsumowanie celu, scenariusza,
storyboardu, promptów i materiałów. Akceptacja kreatywna jest osobna od zgody
na upload i koszt.

## Podłączenie generowania przez MCP lub API

Połączenie z generatorem jest potrzebne tylko w trybie `full_production`.
Plugin nie narzuca dostawcy i nie zawiera uniwersalnego klienta do wszystkich
usług. Użytkownik może wykorzystać istniejące MCP, connector albo zgodne
narzędzie API dostępne w swoim środowisku.

Samo ustawienie klucza API nie dodaje nowego narzędzia do Codexa. Musi istnieć
również klient, komenda, plugin albo MCP, które potrafią użyć tego klucza i
wywołać konkretną usługę.

### Wariant 1: MCP w Codexie

Najpierw sprawdź w oficjalnej dokumentacji wybranej usługi jej URL MCP, komendę
serwera i sposób uwierzytelnienia. Następnie dodaj dokładnie tę integrację.

Dla zdalnego serwera Streamable HTTP:

```bash
codex mcp add NAZWA_INTEGRACJI --url URL_MCP
```

Jeżeli serwer używa tokenu z prywatnej zmiennej środowiskowej:

```bash
codex mcp add NAZWA_INTEGRACJI --url URL_MCP --bearer-token-env-var NAZWA_ZMIENNEJ
```

Dla lokalnego serwera STDIO udostępnionego przez dostawcę:

```bash
codex mcp add NAZWA_INTEGRACJI -- POLECENIE_SERWERA ARGUMENTY
```

Jeżeli integracja używa OAuth, po jej dodaniu uruchom:

```bash
codex mcp login NAZWA_INTEGRACJI
```

Sprawdź konfigurację poleceniem:

```bash
codex mcp list
```

Po zmianie konfiguracji uruchom nowe zadanie Codex. W aplikacji desktopowej
może być potrzebne ponowne uruchomienie. W aktywnym zadaniu można użyć `/mcp`,
aby zobaczyć dostępne serwery i narzędzia. Konfigurację MCP współdzielą
aplikacja ChatGPT desktop, Codex CLI i rozszerzenie IDE. ChatGPT w przeglądarce
korzysta natomiast z pluginów i narzędzi udostępnionych w danym workspace, a
nie z lokalnego pliku konfiguracyjnego Codexa.

Szczegóły konfiguracji opisuje oficjalna dokumentacja
[MCP w Codexie](https://learn.chatgpt.com/docs/extend/mcp).

### Wariant 2: API dostawcy

Nazwa klucza, endpointy, modele i format żądań zależą od konkretnego dostawcy.
Użyj wyłącznie jego aktualnej oficjalnej dokumentacji. Klucz umieść w prywatnym
mechanizmie sekretów albo w zmiennej środowiskowej bieżącej sesji terminala,
nigdy w README, repozytorium, pliku projektu ani oknie rozmowy.

Przykład dla macOS lub Linux, gdzie `PROVIDER_API_KEY` jest tylko nazwą
zastępczą:

```bash
export PROVIDER_API_KEY="..."
```

Przykład dla Windows PowerShell:

```powershell
$env:PROVIDER_API_KEY="..."
```

Ustaw zmienną w tej samej sesji terminala przed uruchomieniem zadania Codex.
Już otwarta aplikacja może wymagać ponownego uruchomienia, aby odziedziczyć
zmienione środowisko. Następnie skonfiguruj zgodny klient lub narzędzie tak, aby
odczytywało tę zmienną. Skillowi podaj wyłącznie nazwę dostawcy, metodę `API` i
nazwę referencji do sekretu. Nie podawaj wartości klucza.

### Polecenie po przygotowaniu integracji

```text
Użyj $create-property-walkthrough w trybie full_production. Mam już integrację
NAZWA_INTEGRACJI przez MCP/API. Najpierw sprawdź jej aktualne możliwości,
przygotuj batch, pokaż przewidywany koszt i poproś mnie o zgodę. Nie wysyłaj
plików przed moim potwierdzeniem.
```

Po wskazaniu integracji skill sprawdza jej aktualną oficjalną dokumentację,
obsługę image-to-video, formaty, czas klipów, sposób uwierzytelnienia i koszt.
Nie wykonuje płatnego zadania jako testu połączenia.

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
klipów. Jeżeli dodatkowo zainstalowano Remotion lub HyperFrames, workflow może
użyć ich na polecenie użytkownika do bardziej rozbudowanych napisów, warstw i
motion designu.

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
a plan wydania 1.1.1 w
[`docs/release-plan-v1.1.1.md`](docs/release-plan-v1.1.1.md).

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
