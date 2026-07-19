# Workflow projektu walkthrough

## Etapy

1. Rozpoznaj możliwości hosta i wybierz `plan_only`, `manual_clips` albo `full_production`.
2. Rozpoznaj nowy projekt albo wznowienie.
3. Zainicjalizuj `project.json` i strukturę katalogów.
4. Przyjmij pojedynczy link, pliki, katalog, ZIP albo tryb hybrydowy.
5. Zachowaj provenance, originals, hashe, ostrzeżenia i błędy.
6. Utwórz miniatury i contact sheets, jeżeli host udostępnia lokalne helpery i narzędzia multimedialne.
7. Przeanalizuj zdjęcia i zapisz wynik zgodny ze schematem.
8. Wybierz źródła i przygotuj stabilny plan scen.
9. Zawsze wygeneruj ręczny pakiet promptów.
10. Tylko w `full_production` sprawdź zapisany profil integracji. Świeży profil `validated` użyj automatycznie; pytaj o dostawcę tylko przy braku profilu, stanie `stale`/`blocked` albo jawnej prośbie o zmianę.
11. Przejdź przez aktualne bramki zgody i kosztu dla bieżącej partii.
12. Po zgodzie wykonaj zewnętrzne generowanie automatycznie do importu klipów i QC. Nie pytaj w tym czasie o montaż, plansze, Remotion ani HyperFrames.
13. Po QC klipów wykonaj pre-montage checkpoint: zapytaj tylko o sposób montażu oraz opcjonalne plansze początkowe/końcowe, które mogą powstać w dostępnym Remotion albo HyperFrames.
14. Regeneruj wyłącznie nieudane lub unieważnione sceny po nowej zgodzie, gdy jest wymagana.
15. Zmontuj zaakceptowane klipy i zwaliduj finalny MP4, jeżeli host udostępnia backend montażowy.

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

Zatrzymaj odpowiedni etap przy braku plików, niespójnym hashu albo zablokowanej infrastrukturze. W zewnętrznej generacji zatrzymaj też wykonanie przy nieznanym koszcie, braku aktualnej zgody, braku zweryfikowanego profilu wybranej integracji albo niepewnym submission. Nie zmieniaj providera i nie rozszerzaj scope.

## Delivery

W `plan_only` dostarcz brief, storyboard, prompty i pakiet ręczny. W trybach montażowych głównym rezultatem jest zwalidowany MP4. Raportuj lokalne ścieżki, listę zaakceptowanych scen, strategie kadrowania, ostrzeżenia, prawa i status zgód. Nie uploaduj ani nie publikuj bez osobnego polecenia użytkownika.
