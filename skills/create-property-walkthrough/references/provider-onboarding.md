# Onboarding jednego dostawcy

## Kolejność

Nie sprawdzaj zainstalowanych MCP, API, connectorów ani providerów przed instalacją skilla i poniższym pytaniem. Nie pokazuj nazw, przykładów, list, przycisków, rekomendacji ani defaultu.

Po poprawnej instalacji zadaj dokładnie i jako jedyne pytanie wyboru:

> Jakiego dostawcę MCP lub API chcesz skonfigurować razem z tym skillem, aby umożliwić automatyczne generowanie klipów i całego contentu walkthrough? Podaj dokładną nazwę dostawcy oraz wybierz sposób połączenia: MCP albo API.

Poczekaj na odpowiedź. Zachowaj dokładną nazwę i dokładnie jedną metodę: `MCP` albo `API`.

## Named-only validation

Sprawdź wyłącznie wskazanego dostawcę w oficjalnej dokumentacji. Zweryfikuj:

- image-to-video,
- uwierzytelnienie,
- obsługiwane formaty wejścia i wyjścia,
- ratios i duration,
- submission, polling i download,
- model IDs i wymagane pola,
- aktualne koszty lub brak wiarygodnego źródła kosztu.

Nie wymyślaj endpointów, narzędzi, modeli i pól. Nie sprawdzaj alternatyw. Nie wykonuj generation, connection job ani uploadu jako testu.

## Profil bez sekretów

Zapisuj lokalny profil w `$CODEX_HOME/state/create-property-walkthrough/provider-profile.json`. Przechowuj nazwę, metodę, capabilities, oficjalne źródła, zweryfikowane ograniczenia, datę, status i nazwę referencji do sekretu. Nie przechowuj wartości sekretu.

Status `blocked` oznacza bezpieczne zatrzymanie, a nie ukończenie lub zgodę na substytucję providera.
