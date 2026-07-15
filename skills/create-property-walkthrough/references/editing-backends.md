# Backend montażowy

Dobierz narzędzie do zaakceptowanego efektu, nie do samej dostępności skilla.

## FFmpeg

Domyślny lokalny backend tego repo. Jest właściwy dla deterministycznego
łączenia zaakceptowanych klipów, skalowania, kadrowania, hard cuts i technicznej
walidacji. Używaj `scripts/render_walkthrough.py` tylko po zielonym preflight.

## Remotion

Jeżeli środowisko udostępnia skill Remotion, rozważ go dla rozbudowanych
napisów, warstw, layoutów, animacji komponentowych i montażu sterowanego kodem.
Nie instaluj go automatycznie. Zachowaj te same zaakceptowane klipy, scene_id i
bramki QC.

## HyperFrames

Jeżeli środowisko udostępnia HyperFrames, rozważ go dla motion designu,
plansz, typografii, overlayów i bardziej graficznych sekwencji. Nie używaj go do
ukrywania błędów geometrii klipu.

Backendy można stosować zamiennie lub etapami, jeśli użytkownik tego chce.
Każda zmiana backendu musi zachować kolejność scen, zaakceptowane źródła,
informację o audio i finalny QA. Gdy żaden zewnętrzny backend nie jest dostępny,
pozostań przy FFmpeg albo wydaj pakiet ręczny.
