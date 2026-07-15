# Opcjonalne połączenie zewnętrzne

## Kiedy otworzyć tę gałąź

Nie pytaj o dostawcę podczas zwykłego startu. Najpierw wykryj możliwości hosta,
ustal cel projektu i wybierz tryb:

- `plan_only`: analiza, storyboard, prompty i pakiet ręczny,
- `manual_clips`: użytkownik dostarcza gotowe klipy, a skill wykonuje import, QC i dostępny lokalnie montaż,
- `full_production`: użytkownik chce również zewnętrznej generacji klipów.

Provider jest potrzebny wyłącznie w trzecim trybie i tylko wtedy, gdy host nie
ma już odpowiedniego, jawnie wybranego narzędzia generacyjnego.

## Wyjaśnij połączenie ogólnie

Powiedz zwięźle, że generowanie może korzystać z connectora, MCP albo API
udostępnionego przez środowisko ChatGPT/Codex. Nie instaluj niczego, nie skanuj
sekretów, nie zmieniaj PATH i nie obiecuj funkcji, których host nie udostępnia.

Jeżeli użytkownik ma już integrację, poproś o dokładną nazwę oraz jedną metodę:
`connector`, `MCP` albo `API`. Dla lokalnego profilu wykonawczego mapuj connector
hosta na kontrolowaną przez host powierzchnię, a w pliku profilu zapisuj tylko
obsługiwane technicznie wartości `MCP` albo `API`.

## Rekomendacje tylko na prośbę

Nie pokazuj listy dostawców z własnej inicjatywy. Jeżeli użytkownik jawnie prosi
o rekomendację:

1. zapytaj o jeden główny priorytet i opcjonalnie drugi, na przykład jakość,
   koszt, szybkość, prostotę połączenia albo konkretny format;
2. sprawdź aktualną oficjalną dokumentację rozważanych usług;
3. przedstaw najwyżej trzy pasujące opcje bez ukrytego defaultu;
4. oznacz ceny i dostępność jako aktualne na dzień weryfikacji, a brak pewnych
   danych jako niezweryfikowany;
5. pozwól użytkownikowi wybrać albo pozostać w trybie ręcznym.

## Walidacja wybranego rozwiązania

Po wyborze sprawdź wyłącznie wskazaną integrację w oficjalnej dokumentacji.
Zweryfikuj:

- image-to-video,
- sposób uwierzytelnienia,
- obsługiwane wejścia i wyjścia,
- ratios i duration,
- submission, polling i download,
- model IDs i wymagane pola,
- aktualny koszt albo uczciwy brak wiarygodnego źródła kosztu.

Nie wymyślaj endpointów, narzędzi, modeli i pól. Nie uruchamiaj generation,
connection job ani uploadu jako testu.

## Profil bez sekretów

Zapisuj lokalny profil w
`$CODEX_HOME/state/create-property-walkthrough/provider-profile.json`.
Przechowuj nazwę, metodę, capabilities, oficjalne źródła, ograniczenia, datę,
status i nazwę referencji do sekretu. Nigdy nie przechowuj wartości sekretu.

Profil `validated` pozostaje ważny najwyżej 7 dni przed płatnym albo zewnętrznym
wykonaniem. Po tym okresie oznacz go jako `stale` i ponownie sprawdź oficjalne
źródła. Status `blocked` oznacza bezpieczne zatrzymanie, nie automatyczny wybór
zamiennika. `scripts/configure_provider.py reset` przywraca profil
`not_configured` bez skanowania integracji i bez usuwania projektów.
