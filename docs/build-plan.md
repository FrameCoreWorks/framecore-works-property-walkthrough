# Plan budowy

## Zasady wykonania

- Każdy etap kończy się testem fazy, testami regresyjnymi zależnych elementów, secret scanem i przeglądem diffu.
- Niepowodzenie testu prowadzi do diagnozy i poprawki, nie do pominięcia kryterium.
- Providerzy pozostają nieskanowani aż do P14A.
- Zewnętrzna generacja, upload i koszt nie są częścią testów implementacyjnych.
- Push obejmuje wyłącznie przetestowany, czysty checkpoint.
- SHA testowanego checkpointu jest wpisywany do kolejnego checkpointu; końcowy SHA trafia do handoveru.
- Status `blocked` nie jest równoważny `complete`.

## Kolejność krytyczna

```text
P1A scaffold
→ P15 autorytatywna licencja upstream
→ P1B walidacja fundamentu
→ pierwszy lokalny commit
→ P16 prywatny GitHub i bezpieczny origin
→ P17 checkpoint loop dla P2–P12
→ P13 instalacja exact-SHA
→ P14A dokładne pytanie i oczekiwanie
→ P14B onboarding tylko wskazanego dostawcy
→ P18 finalny audit
```

## Standard zapisu fazy

Każda faza zapisuje: cel, opis, pliki, zależności, skrypty, testy, polecenia walidacyjne, artefakty, ryzyka, kryterium ukończenia, wpływ downstream i dowody. Jeżeli polecenie nie może zostać wykonane, zapisuje dokładny blocker.

## P1A. Scaffold clean-room

- Cel: utworzyć nowy katalog bez historii upstream i utrwalić zatwierdzony projekt.
- Pliki: `docs/design-synthesis.md`, `docs/build-plan.md`, `docs/clean-room-ledger.md`, szkielet katalogów.
- Zależności: Hipson Checkpoint 3 PASS, preflight `/Volumes/Codex/Codex`.
- Testy: brak istniejącego targetu lokalnego, brak `.git`, brak zdalnych obiektów upstream.
- Walidacja: `find`, `git status` oczekiwane jako non-repo przed `git init`.
- Ryzyko: przypadkowe użycie starego working tree.
- Ukończenie: dokumenty są zapisane w nowym katalogu, a ledger potwierdza clean-room.
- Downstream: P15.

## P15. Autorytatywna licencja upstream

- Cel: przypiąć dokładną rewizję i zachować verbatim tekst MIT.
- Pliki: `licenses/re-walkthrough-pro-MIT.txt`, `THIRD_PARTY_NOTICES.md`, `docs/clean-room-ledger.md`.
- Zależności: dostęp do publicznego upstream.
- Metoda: pobrać przez immutable commit URL, zapisać branch, commit SHA, datę, blob SHA i SHA-256 bajtów.
- Testy: dokładne bajty licencji odpowiadają przypiętemu blobowi; copyright Charles J Dove zachowany.
- Ryzyko: zmienny branch albo niepełna kopia.
- Ukończenie: źródło jest immutable i dowód zapisany.
- Downstream: P1B.

## P1B. Fundament repo i skilla

- Cel: utworzyć foundation files, licencję FrameCore Works i standardowy scaffold skilla.
- Pliki: `README.md`, `AGENTS.md`, `LICENSE`, `.gitignore`, `.env.example`, `THIRD_PARTY_NOTICES.md`, `skills/create-property-walkthrough/**`.
- Skrypty: systemowy `init_skill.py`, następnie dostosowanie przez patch.
- Testy: root MIT, upstream MIT, frontmatter, `agents/openai.yaml`, UTF-8, brak sekretów, brak upstream Git history.
- Walidacja: `quick_validate.py`, testy foundation, secret scan.
- Ryzyko: placeholdery albo niezgodny format skilla.
- Ukończenie: foundation validation przechodzi i powstaje pierwszy polski commit.
- Downstream: P16 i P2.

## P2. SKILL.md i references

- Cel: opisać kompletny workflow przy progressive disclosure.
- Pliki: `SKILL.md`, `references/workflow.md`, `input-ingestion.md`, `polish-portals.md`, `image-curation.md`, `scene-planning.md`, `video-prompt-contract.md`, `provider-onboarding.md`, `provider-execution.md`, `project-state.md`, `quality-control.md`, `rendering.md`, `security-and-rights.md`.
- Testy: body poniżej 500 linii, imperative style, wszystkie references podlinkowane bez głębokiego zagnieżdżania, pozytywne i negatywne przykłady activation.
- Walidacja: `quick_validate.py`, testy kontraktów tekstowych.
- Ryzyko: duplikacja i context bloat.
- Ukończenie: skill prowadzi od intake do delivery i respektuje wszystkie bramki.
- Downstream: P3–P12.

## P3. Project state, schematy i manifest

- Cel: zapewnić wersjonowany, atomowy i walidowalny stan.
- Pliki: `_common.py`, `_schema.py`, `init_project.py`, `update_manifest.py`, schematy JSON i templates.
- Testy: atomic write, schema subset, rejection unsupported keywords, semantic validation, hashes, tombstones, Unicode.
- Walidacja: `python -m unittest tests.test_state tests.test_schema`.
- Ryzyko: częściowy zapis lub ciche pominięcie reguły.
- Ukończenie: projekt można utworzyć, odczytać i bezpiecznie aktualizować.
- Downstream: wszystkie operacje projektu.

## P4. Listing i image ingestion

- Cel: obsłużyć pięć trybów wejścia bez ukrytej sieci.
- Pliki: `extract_listing.py`, `ingest_images.py`, `_media.py`, fixtures HTML/ZIP/image.
- Testy: HTTP/HTTPS metadata, lokalny snapshot JSON-LD/OG, blocked fallback, zero socket, safe ZIP, MIME/magic, rozmiary, exact i near duplicates, katalog, ZIP, hybrid, Unicode.
- Walidacja: `python -m unittest tests.test_listing tests.test_ingestion`.
- Ryzyko: SSRF, prompt injection, ZIP traversal/bomb, utrata originals.
- Ukończenie: wejścia są zapisane z provenance, a niebezpieczne są odrzucone fail-closed.
- Downstream: P5.

## P5. Contact sheets i analiza

- Cel: utworzyć deterministyczne miniatury/contact sheets i kontrakt analizy Codexa.
- Pliki: `make_contact_sheet.py`, `image-analysis.schema.json`, reference image curation.
- Testy: JPEG/PNG, orientacja, FFmpeg, polskie ścieżki, brak destrukcyjnego usuwania.
- Walidacja: `python -m unittest tests.test_contact_sheets`.
- Ryzyko: brak FFmpeg lub niedekodowalny obraz.
- Ukończenie: raport i contact sheet są gotowe do wizualnej oceny.
- Downstream: P6.

## P6. Scene planning i prompt contract

- Cel: zapisać stabilne sceny i samodzielne prompty I2V.
- Pliki: `prepare_generation_package.py`, scene schema, prompt templates, scene/prompt references.
- Testy: 6–10 lub uzasadniony krótszy plan, stable IDs po reorder, jedna scena/jedno źródło/jeden ruch/jeden ratio, pełne geometry locks, polskie metadane, brak wymyślonych przestrzeni.
- Walidacja: `python -m unittest tests.test_scene_planning tests.test_prompts`.
- Ryzyko: fałszywa ciągłość i unsupported reveals.
- Ukończenie: Markdown, JSON i opcjonalny CSV są spójne.
- Downstream: P7–P9.

## P7. Provider onboarding

- Cel: przechować named-only profil bez sekretów i walidować go bez generowania.
- Pliki: `configure_provider.py`, `validate_provider.py`, provider schema i reference.
- Testy: dokładne pytanie, brak nazw/sugestii/skanu przed pytaniem, MCP/API, masking, secure secret reference, no-generation trap.
- Walidacja: `python -m unittest tests.test_provider_onboarding`.
- Ryzyko: wyciek sekretu lub domyślna rekomendacja.
- Ukończenie: profil przechodzi walidację albo bezpiecznie raportuje `blocked`.
- Downstream: P8.

## P8. Provider execution i manual fallback

- Cel: przygotować bezpieczny pakiet wykonawczy bez adaptera konkretnego providera.
- Pliki: `prepare_upload_derivatives.py`, generation manifest, provider execution reference.
- Testy: metadata stripping, osobne hashe, PII/rights flags, fingerprint zgody, koszt unknown fail-closed, duplicate submission, `submission_pending`, manual mode, zerowy provider call bez zgody.
- Walidacja: `python -m unittest tests.test_generation_safety tests.test_manual_mode`.
- Ryzyko: cichy upload originals albo płatny resubmit.
- Ukończenie: pakiet manualny działa, a automat nie przechodzi bez kompletu bramek.
- Downstream: P9.

## P9. Import klipów i QC

- Cel: importować zewnętrzne klipy jako rewizje i zbierać dowody QC.
- Pliki: `import_clips.py`, `_media.py`, QC reference i schema.
- Testy: expected filenames, hashes, ffprobe, próbki klatek, statusy QC, append-only approved, selective invalidation.
- Walidacja: `python -m unittest tests.test_clip_import tests.test_quality_control`.
- Ryzyko: zatwierdzenie wadliwego lub nadpisanie approved.
- Ukończenie: każda scena ma audytowalny status i dowody.
- Downstream: P10–P11.

## P10. FFmpeg rendering

- Cel: deterministycznie tworzyć master 16:9 i wariant 9:16.
- Pliki: `render_walkthrough.py`, rendering reference.
- Testy: H.264, yuv420p, stały FPS, SAR 1:1, hard cuts, bez stretch, anchored crop/contain/padded background, brak automatycznego audio i PII overlays.
- Walidacja: `python -m unittest tests.test_rendering` oraz `ffprobe` outputów.
- Ryzyko: crop loss, stale render, platformowe różnice FFmpeg.
- Ukończenie: syntetyczny render przechodzi parametry techniczne.
- Downstream: P11–P12.

## P11. Resume i selective regeneration

- Cel: wznawiać pierwszy niekompletny etap bez duplikowania pracy.
- Pliki: `validate_output.py`, state/resume reference.
- Testy: uszkodzony manifest, hash mismatch, przerwany atomic write, istniejące job IDs, reorder, jedna invalidated scene, zachowane approved hashes, render dependency hash.
- Walidacja: `python -m unittest tests.test_resume`.
- Ryzyko: niejawne ponowne submission.
- Ukończenie: resume jest idempotentne i fail-closed.
- Downstream: P12.

## P12. Synthetic E2E

- Cel: przejść pełną lokalną ścieżkę bez providera.
- Przepływ: synthetic images → init → ingestion → fixture analysis → plan → prompts → synthetic clips → import → QC → FFmpeg → validate.
- Testy: network deny, provider trap count = 0, 16:9 i 9:16, Unicode, secret canary, selective regeneration.
- Walidacja: `python -m unittest discover -s tests -v` i osobny E2E command.
- Ryzyko: test przypadkowo zależny od sieci lub stanu użytkownika.
- Ukończenie: cały suite przechodzi w czystym tempdir.
- Downstream: P13 i checkpoint finalny implementacji.

## P13. Instalacja exact-SHA

- Cel: zainstalować dokładnie przetestowany skill.
- Pliki: lokalny installation attestation i hash manifest; sam skill poza repo po instalacji.
- Metoda: same-filesystem staging, kontrola hashy, `quick_validate.py`, atomic rename.
- Testy: clean `CODEX_HOME`, kolizja, interrupted staging, hash equality, smoke validation.
- Ryzyko: nadpisanie istniejącego skilla albo instalacja innej rewizji.
- Ukończenie: `$CODEX_HOME/skills/create-property-walkthrough` odpowiada testowanemu commitowi.
- Downstream: P14A.

## P14A. Dokładne pytanie o dostawcę

- Cel: po instalacji zadać jedyne pytanie wyboru dostawcy dokładnie według specyfikacji.
- Test: exact string equality i brak listy, przykładów, nazw, rekomendacji oraz pre-scan.
- Ukończenie: pytanie zadane i workflow czeka na odpowiedź.
- Downstream: P14B po nowej wiadomości użytkownika.

## P14B. Named-only onboarding

- Cel: sprawdzić wyłącznie wskazanego dostawcę i wybraną metodę.
- Zależności: dokładna nazwa i `MCP` albo `API` od użytkownika.
- Testy/dowody: oficjalne źródła dla auth, I2V, ratios, duration, submission, polling, download, kosztów; brak generacji i uploadu.
- Ryzyko: dokumentacja niepełna lub niedostępna.
- Ukończenie: profil zwalidowany albo status `blocked` z konkretnym brakiem. `blocked` nie oznacza completion.
- Downstream: P18.

## P16. GitHub private create albo safe resume

- Cel: utworzyć lub bezpiecznie kontynuować dokładny target.
- Preflight: `gh auth status`, login `FrameCoreWorks`, target owner/name, visibility private, `isFork=false`, branches/history, remote head.
- Testy: zły login, public/fork target, istniejąca zawartość, remote mismatch, non-fast-forward, secret scan failure.
- Ryzyko: zmiana obcego projektu albo nieprywatny remote.
- Ukończenie: origin wskazuje dokładny private target, initial validated commit jest na remote i remote SHA jest zgodny.
- Downstream: P17.

## P17. Checkpoint commit/push loop

- Cel: po P2–P12 publikować wyłącznie zweryfikowane checkpointy.
- Przed każdym push: phase tests, affected regression, secret scan, asset scan, diff review, clean status, remote-head recheck.
- Polecenia: jawny non-force refspec, remote SHA verify.
- Artefakty: `docs/checkpoint-log.md` z komendami, wynikiem, tree SHA i poprzednim remote SHA.
- Ukończenie: każdy remote commit jest powiązany z dowodem testowym.
- Downstream: P13.

## P18. Finalny audit i handover

- Cel: porównać stan z Definition of Done bez fałszywego PASS.
- Testy: pełny suite, skill validation, license hash, secret/history scan, install hashes, local/remote SHA, private/non-fork, język polski, AppleDouble scan.
- Statusy: `complete` tylko przy spełnieniu wszystkich obowiązkowych kryteriów; `blocked` przy rzeczywistym zewnętrznym blockerze.
- Ukończenie: 35-punktowy handover po polsku i brak wymaganej bezpiecznej poprawki.

## Macierz wymagań R001–R051

| ID | Wymaganie | Faza | Artefakt | Test lub dowód | Kryterium ukończenia |
|---|---|---|---|---|---|
| R001 | Projekt od początku, bez forka | P1A/P16 | clean-room ledger, Git | brak upstream remote/objects, `isFork=false` | nowa historia |
| R002 | Jeden instalowalny skill | P1B/P13 | `skills/create-property-walkthrough` | quick validate, install hash | skill działa |
| R003 | Brak aplikacji/API/DB | P1B/P18 | struktura repo | tree audit | brak komponentów poza zakresem |
| R004 | Pięć trybów wejścia | P4 | ingestion scripts | unit + E2E | każdy tryb zapisuje projekt |
| R005 | Polska i publiczne listingi | P2/P4 | references, HTML fixtures | JSON-LD/OG/Unicode | dane z provenance/null |
| R006 | Brak wyszukiwarki i bulk scrape | P2/P4 | workflow contract | zero-network helper test | pojedynczy snapshot |
| R007 | Cinematic, nie 3D | P2/P6/README | wording i prompts | text contract test | brak obietnic 3D |
| R008 | Neutralność providera | P7/P8 | profile schema | no-provider-name scan | brak adaptera domyślnego |
| R009 | Dokładne pytanie po instalacji | P13/P14A | onboarding reference | exact string | pytanie identyczne |
| R010 | Brak pre-scan/sugestii | P7/P14A | tests | forbidden-name/suggestion scan | zero pre-scan |
| R011 | Tylko named provider | P14B | provider profile | source ledger named-only | brak alternatyw |
| R012 | Credentials bezpieczne | P7/P18 | secret refs | canary/secret scan | brak sekretów w artefaktach |
| R013 | Zgoda przed generowaniem | P8 | consent fingerprint | ambiguous/stale/changed tests | brak submit bez zgody |
| R014 | Potwierdzenie kosztu | P8/P14B | cost record | unknown/retry tests | fail-closed |
| R015 | Manual mode | P6/P8 | generation package | provider trap = 0 | komplet ręczny |
| R016 | Resume | P3/P11 | project state | interruption/hash tests | idempotent resume |
| R017 | Approved clips zachowane | P9/P11 | revisions/hashes | overwrite regression | immutable approved |
| R018 | Selective regeneration | P9/P11 | dependency hashes | single-scene invalidation | tylko właściwa scena |
| R019 | Synthetic fixtures | P4/P12 | `tests/fixtures` | asset audit | brak realnych listingów |
| R020 | Oddzielne licencje MIT | P15/P1B | LICENSE + licenses | byte/hash tests | oba copyrighty poprawne |
| R021 | Konceptualna relacja upstream | P15/P1B | notices/README | exact wording test | brak endorsementu |
| R022 | Repo i treści po polsku | wszystkie/P18 | wszystkie user docs | language/UTF-8 audit | wymagane treści PL |
| R023 | Prompty EN + metadata PL | P6 | prompt package | schema/text tests | spójny prompt i metadata |
| R024 | Unicode w ścieżkach/outputach | P3–P12 | fixtures | `łazienka_żółta` E2E | pełny PASS |
| R025 | Skill metadata/implicit invocation | P1B/P2/P18 | SKILL/openai.yaml | quick validate + observable harness | PASS lub jawne unverifiable |
| R026 | Project tree | P3 | init template | tree equality | komplet katalogów |
| R027 | Atomic project writes/checkpoints | P3/P11 | `_common.py` | crash simulation | brak partial state |
| R028 | Safe listing ingestion | P4 | snapshot parser | malicious HTML test | dane nie są instrukcją |
| R029 | Blocked listing fallback | P4 | state/warning | blocked fixture | ten sam project resumable |
| R030 | Safe ZIP i image validation | P4 | ingestion | traversal/bomb/magic tests | fail-closed quarantine |
| R031 | Deduplikacja/contact sheets | P4/P5 | hashes/dHash/sheets | duplicates + FFmpeg | deterministyczny output |
| R032 | Curation taxonomy | P5/P6 | analysis schema | fixture analysis | oddzielone trzy pola |
| R033 | Brak wymyślonych pomieszczeń | P5/P6 | scene plan | sparse-source test | tylko widoczne spaces |
| R034 | Plan 6–10 i stable IDs | P6 | scene plan | reorder/sparse/overflow | poprawny łuk i IDs |
| R035 | Jeden kontrolowany ruch | P6 | prompt contract | multi-move rejection | dokładnie jeden ruch |
| R036 | Geometry/source locks | P6 | prompts | required clauses test | komplet blokad |
| R037 | Profile bez sekretów | P7 | profile files | schema + secret canary | tylko secret reference |
| R038 | Validation bez generation | P7/P14B | provider trap | zero submits/uploads | bezpieczny onboarding |
| R039 | Derivatives-only upload | P8 | upload derivatives | EXIF/hash/no-substitution | oryginały nie wysłane |
| R040 | Job persistence/idempotency | P8/P11 | jobs state | crash window/duplicate tests | brak auto-resubmit |
| R041 | Clip import i ffprobe | P9 | imported clips/QC | media fixtures | techniczny status każdej sceny |
| R042 | Wizualny QC i statusy | P9 | QC report | sample frames + contract | krytyczne błędy nieapproved |
| R043 | Render 16:9 | P10/P12 | final MP4 | ffprobe | 1920×1080, SAR 1:1 |
| R044 | Render 9:16 bez stretch | P10/P12 | final MP4 | ffprobe/crop strategy | 1080×1920, SAR 1:1 |
| R045 | Brak automatycznych dodatków/PII | P10 | render config | config/text tests | brak audio/overlay default |
| R046 | Pełny provider-free E2E | P12 | synthetic project | socket deny/provider trap | zero external calls |
| R047 | Exact-SHA bezpieczna instalacja | P13 | install attestation | staging/collision/hash | zainstalowany tested tree |
| R048 | GitHub FrameCoreWorks/private | P16 | remote metadata | gh owner/visibility/fork | dokładny private target |
| R049 | Tylko tested checkpoint push | P17 | checkpoint log | commands/tree SHA/remote SHA | każdy push attested |
| R050 | Secret/user-asset/history scan | P17/P18 | scan logs | canary, path, git object scan | brak zakazanych danych |
| R051 | Goal Completion Loop i handover | wszystkie/P18 | plan, log, raport | DoD audit | complete albo prawdziwy blocker |

## Zatwierdzenie Hipsona

```yaml
checkpoint: HIPSON_CHECKPOINT_3
final_gate: PASSED
plan_status: approved_for_execution_after_external_write_gate
implementation_performed: false
```

Warunek external write gate został spełniony 2026-07-11. Implementacja może zacząć się od P1A po zapisaniu tego planu i ponownym sprawdzeniu braku konfliktu.
