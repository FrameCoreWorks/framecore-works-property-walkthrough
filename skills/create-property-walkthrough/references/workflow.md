# Workflow projektu walkthrough

## Etapy

1. Rozpoznaj nowy projekt albo wznowienie.
2. Zainicjalizuj `project.json` i strukturę katalogów.
3. Przyjmij pojedynczy link, pliki, katalog, ZIP albo tryb hybrydowy.
4. Zachowaj provenance, originals, hashe, ostrzeżenia i błędy.
5. Utwórz miniatury i contact sheets.
6. Przeanalizuj zdjęcia i zapisz wynik zgodny ze schematem.
7. Wybierz źródła i przygotuj stabilny plan scen.
8. Wygeneruj manualny pakiet promptów.
9. Jeżeli użytkownik wcześniej skonfigurował named provider, przejdź przez aktualne bramki zgody i kosztu. W przeciwnym razie pozostań w manual mode.
10. Zaimportuj klipy, wykonaj techniczne i wizualne QC.
11. Regeneruj wyłącznie nieudane lub unieważnione sceny po nowej zgodzie, gdy jest wymagana.
12. Zmontuj zaakceptowane klipy i zwaliduj output.

## Statusy etapów

Używaj `pending`, `in_progress`, `complete`, `blocked` i `invalidated`. Status `blocked` nie jest ukończeniem. Zapisuj kod powodu, czas, zależności i najbliższą bezpieczną akcję.

## Checkpointy

Zapisuj atomowy checkpoint po:

- utrwaleniu snapshotu lub wyniku ingestion,
- każdej operacji sieciowej wykonanej przez zaufaną powierzchnię,
- provider submission i zmianie job status,
- imporcie klipu,
- decyzji QC,
- renderze.

## Stop conditions

Zatrzymaj automatyzację przy braku plików, niespójnym hashu, nieznanym koszcie, braku aktualnej zgody, braku bezpiecznego named profile, niepewnym submission albo zablokowanej infrastrukturze. Nie zmieniaj providera i nie rozszerzaj scope.

## Delivery

Raportuj lokalne ścieżki, listę zaakceptowanych scen, strategie kadrowania, ostrzeżenia, prawa i status zgód. Nie uploaduj ani nie publikuj bez osobnego polecenia użytkownika.
