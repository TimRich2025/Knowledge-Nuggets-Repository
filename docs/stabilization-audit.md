# Knowledge Nuggets: Bestandsaufnahme und kontrollierter Ausbau

Stand: 8. Oktober 2026, Basis `main` bei `5c6eb658`. Repository-Code, Railway-Worker und die Make-Szenarien wurden getrennt geprüft. Historische Make-Runs belegen nur die jeweils ausgeführten Module, keinen erfolgreichen Short.

## A. Aktuelle Architektur

1. Make erstellt Inhalt und ruft den Worker über HTTP auf. Die Make-Konfiguration ist nicht im Repository versioniert; die aktiven Szenarien wurden am 8. Oktober im angemeldeten Make-Konto lesend geprüft.
2. Der FastAPI-Dienst (`vps/api.py`) bietet Quellenkandidaten, Storyboard- und Plan-Endpunkte sowie `POST /jobs`; Redis hält Jobs und Source-Pools.
3. Der Worker (`vps/worker.py`) holt Jobs aus Redis. `vps/source_cache.py` erzeugt Edge-TTS samt Wortzeiten, lädt Videoausschnitte herunter und prüft sie mit FFprobe.
4. `vps/local_renderer.py` schneidet die lokalen Clips mit FFmpeg, setzt Layout und Wortanimation, mischt gegebenenfalls Musik und prüft das Headerbild.
5. `vps/pipeline.py` verschiebt das MP4 in den persistenten Ausgabepfad, sendet einen Callback und kann bei aktiviertem Flag automatisch **privat** auf YouTube hochladen. Ein privater Upload ist trotzdem ein Upload und bleibt für dieses Projektstadium gesperrt.
6. GitHub Actions enthält Narration-QC und Source-Hunt. Das Root-README beschreibt noch GitHub Actions als Renderer, während `vps/README.md` den Worker als Produktionsruntime beschreibt. Beide Dokumente sind in diesem Punkt widersprüchlich.

## B. Externe Abhängigkeiten

| Abhängigkeit | Aufgabe | Grenze |
| --- | --- | --- |
| Make | Orchestrierung, LLM-/Vision-Schritte und Callback | Szenariodaten fehlen im Repository; aktive Module und Historie separat geprüft |
| GitHub Actions | Unit-Tests, Audio-QC, Quellensuche | Grüne Runs sagen nichts über Videogüte oder zehn End-to-End-Runs |
| Redis und Host (VPS/Railway) | Queue, Token, Cache, Worker, persistente MP4s | Deployment- und Umgebungszustand hier nicht verifiziert |
| Microsoft Edge-TTS | gesprochener Text und Zeitmarken | Externes Netzwerk; Rate und Stimmenqualität separat prüfen |
| NASA-Katalog und Medienserver | Suche, Storyboards, Download | Katalogtitel belegt keine Bildhandlung im gewählten Ausschnitt |
| Vision/LLM über Make | Beschreibung von Frames und Skript | Modellaufrufe und deren Prompt/Version außerhalb des Repos |
| FFmpeg, FFprobe, libass, Pillow und Noto-Fonts | Clipverarbeitung, Render, Bild-QC | Lokal reproduzierbar, sofern Versionen und Fonts vorhanden |
| Musikdateien | optionales Soundbett | Keine Audiodatei im Repo; heutiger Renderer akzeptiert Stille |
| Google/YouTube API | optionaler Upload und Trenddaten | Muss explizit ausgeschaltet bleiben |

Railway-Lesezugriff zeigt im Projekt „Knowledge Nuggets Production“ einen Worker auf Branch `main` mit Dockerfile, Startbefehl `python -m vps.entrypoint` und persistentem `/data`-Volume. Ein älterer API-Dienst schläft, `kn-render-api-v2` ist fehlgeschlagen; Redis/Queue und Worker melden erfolgreiche Deployments vom September. Die Docker-Compose-Datei nennt zusätzlich einen VPS mit getrennten Diensten; `vps/service.py` enthält den kombinierten Prozess. Aus dem Repository allein folgt nicht, welcher HTTP-Endpunkt Make aktuell verwendet.

## Make-Bestandsaufnahme vom 8. Oktober 2026

Im Team `2019909` sind die Szenarien `KN 02 | Content Intelligence` (9783555), `KN 03 | Visual Intelligence` (9783563), `KN 03B | Shot Manifest and Gate` (9875497), `KN 04 | Production Engine` (9783567) und `KN 04B | Render Callback` (9802445) aktiv. Außerdem existieren drei KN-Diagnoseszenarien. Keine Make-Ausführung wurde bei der Bestandsaufnahme gestartet. Andere Projekte wurden nicht verändert.

- `KN 02`: zahlreiche API-Runs am 27./28. September meldeten Erfolg. Das belegt Skript-/Shot-Brief-Erzeugung, nicht nachfolgende Videoqualität. Ein einzelner Lauf verbrauchte teils über 100 Make-Credits.
- `KN 03`: am 28. September wechselten Success, Error und Warning; sieben unaufgelöste Incomplete Executions waren sichtbar. Im jüngsten Warnlauf `6dbce079...` erledigten Suchplanung und Kandidatensuche ihre Arbeit; `V1 | Look At The Footage` scheiterte an Gemini HTTP 429, Free-Tier-Quota 20 Requests für `gemini-3.8-flash`. Eine zufällige Wiederholung oder ein bezahltes Upgrade löst den Architekturfehler nicht.
- `KN 03B`: der einzige sichtbare Success-Lauf `561b81e5...` führte nur `Verified Shot Manifest Builder` und `Parse Shot Manifest` aus. Die im Advanced Log aufgeführten Module `Visual Coverage Gate`, `Record Gate Decision` und `Launch Production Engine Async` wurden lediglich initialisiert und finalisiert, nicht ausgeführt. **Success ist hier kein Gate-Pass.** Drei weitere Starts am 28. September scheiterten vor der ersten Operation; ein geprüfter Fehlerlauf fehlte an den fünf Pflichtfeldern `content_id`, `topic`, `script`, `scene_brief` und `plan_json`.
- `KN 04`: mehrere API-Success-Runs reichten bis `Queue Persistent Railway Render` und `Return output`. Das beweist nur die Annahme eines asynchronen Renderjobs. Ein Error-Lauf `1cb39267...` scheiterte an HTTP 422: `production_status must be READY`.
- `KN 04B`: der jüngste sichtbare Callback-Run `437701e3...` speicherte das Renderer-Ergebnis, dann sperrte der Filter `Only technically valid Railway previews` den Review-Payload. Der Make-Run war dennoch `Success`. Die Callback-Historie belegt keine finale kreative Abnahme.

Im aktuellen Diagramm von `KN 04` endet die Kette nach HTTP-Jobqueue, Datensatz und Szenario-Output; in `KN 04B` endet sie nach Callback-Datensatz, Review-Payload und Webhook-Antwort. In diesen zwei geprüften Szenarien ist kein YouTube-Modul sichtbar. Andere KN-Szenarien und abweichende Versionen sind damit nicht pauschal ausgeschlossen.

Diese Befunde erklären die Differenz zwischen grünen Teilruns und fehlenden freigegebenen Shorts. Für Stufe 10 sind Run-ID, technischer Endstatus und eigenständiger Quality-Status über alle Szenarien und den Worker hinweg zu korrelieren. Vorher keine der Teilhistorien als End-to-End-Stabilitätsserie zählen.

## C. Nachweislich stabile Komponenten

Die letzten 15 erfassten `KN Narration QC`-Runs auf wechselnden Commits waren erfolgreich (27.–28. September). Das belegt die jeweiligen Testschritte auf GitHub. FFmpeg-Schnitt, Edge-TTS, Download, Make-Übergabe und ästhetische Qualität sind dadurch **nicht** als komplette Produktionskette nachgewiesen. Einzelne vorherige Runs waren fehlgeschlagen. Der alte `vps/stress_test.py` entsprach dem aktuellen Rendervertrag nicht und war daher kein gültiger Zehnernachweis.

## D. Instabile oder unbewiesene Komponenten

- End-to-End: keine zehn aufeinanderfolgenden vollständigen, autonomen Runs im vorliegenden Nachweis.
- Footage: `scene_match.py` verwendet Textbegriffe aus Frame-Beschreibungen. Die Funktion `_serve_from_what_is_left` kann ausdrücklich Video vom falschen Motiv zuweisen. Der niedrig gesetzte `MATCH_FLOOR = 0.40` und ein vom Client geliefertes `semantic_score >= 94` beweisen keine konkrete Bildaussage.
- Schnitttreue: die benachbarten Framebeschreibungen und sparse Storyboards belegen nicht lückenlos, was über den gesamten ausgewählten Ausschnitt sichtbar ist.
- Untertitel: Wortzeiten werden erzeugt und in ASS platziert, aber es gibt keinen wiederholten objektiven Vergleich von hörbarem Wortbeginn und sichtbarem Einblenden am finalen MP4.
- Musik: sie wird bei vorhandener Datei geduckt; fehlt sie, gilt der Render trotzdem als erfolgreich. Das erfüllt den künftigen Quality Gate nicht.
- Qualitätsstatus: `RENDER_READY` und Redis `COMPLETED` bezeichnen technische Fertigstellung; ein eigenständiges `QUALITY_PASS` existiert nicht.
- Publikation: Der auf `main` laufende Worker hatte den Code-Default `KN_YOUTUBE_UPLOAD_ENABLED=true`; die Variable war zunächst **nicht** gesetzt. Ein fertig gerenderter Job hätte den privaten Uploadpfad versuchen können, falls ein OAuth-Token im geschützten Redis-Store liegt. Am 7. Oktober wurde `KN_YOUTUBE_UPLOAD_ENABLED=false` für den laufenden Railway-Worker gesetzt. Das neue Deployment meldet `SUCCESS`, der Worker verbindet sich mit Redis und `/health` liefert 200. Railway zeigt Variablenwerte bei erneutem Lesen geschwärzt an; der Setzvorgang bestätigte den Wert. Unabhängige Uploadpfade in Make sind ohne Einsicht in das Szenario nicht auszuschließen.

## E. Unnötige Komplexität und F. kritische Qualität

Parallel gepflegte Renderwege (`render.py`, `render_core.py`, `renderer.py`, `vps/local_renderer.py`), historische Workflow-Proben sowie zwei Deployment-Modelle erhöhen die Verwechslungsgefahr. Vor Entfernung muss geprüft werden, wer sie noch aufruft. Zu bewahren sind konkrete visuelle Aussage pro Beat, verifizierte Zeitfenster, Vielfalt der echten Videoquellen, Wortzeiten, Layout und Stimme, Musik, Frame- und Audio-QC. Diese Funktionen sind Produktionsanforderungen und dürfen durch einen technischen Fixture-Test nicht ersetzt werden.

## G. Kleinster stabiler Kern: Stufe 1

`vps.stress_test` verwendet den **bestehenden** `render_job` mit fünf lokalen FFmpeg-Testclips, einem festen Ton und vollständigen Szenen- und Wortzeitdaten. Die Testmedien sind nur technische Fixtures. Der Test prüft zehn komplette Renderer-Durchläufe hintereinander, ohne API, Make, Redis, Netzwerk, TTS oder YouTube. Er beendet die Serie bei einem Fehler und schreibt eine Run-ID, Hashes der Assets, Laufzeiten, Einzelfehler und `TECHNICAL_PASS` bzw. `TECHNICAL_FAIL` in ein Manifest. `quality_status=NOT_EVALUATED` ist Absicht. Die neue Action läuft nur auf dem isolierten Entwicklungsbranch oder per Hand. Vor einer Freigabe der nächsten Stufe sind zehn echte Erfolge aus einem Lauf nachzuweisen.

Nachweis: Die endgültige Stufe-1-Fassung prüft zusätzlich Video- und Audiostream sowie die vollständige Fehlerfreiheit beim Dekodieren des MP4. Lokal wurden zehn aufeinanderfolgende vollständige Durchläufe mit Ersatzfonts erfolgreich ausgeführt. Auf GitHub wurden zehn aufeinanderfolgende Durchläufe mit den Produktionsfonts im [Workflow-Run 37581790965](https://github.com/TimRich2025/Knowledge-Nuggets-Repository/actions/runs/37581790965) erfolgreich ausgeführt; das technische Manifest liegt im Run-Artefakt. Dies bestätigt den isolierten Renderer-Kern, nicht TTS, Quellen, Make oder kreative Qualität.

## H. Kontrollierter Ausbau

| Stufe | Eine neue Fehlerquelle | Technischer Nachweis | Zusätzlicher Qualitätsnachweis |
| --- | --- | --- | --- |
| 1 | Bestehender Renderer mit festen lokalen Fixtures | zehn vollständige Render hintereinander | keine Produktionsfreigabe; Testmuster zählen nicht |
| 2 | Dynamische Edge-TTS mit Wortmarken | zehn Audio-/Render-Läufe; Timingdaten vollständig | Stimme, Prosodie und Wortbeginn am MP4 prüfen |
| 3 | Dynamische Beats/Skript | zehn vollständige Durchläufe | Hooks, Fakten, Einfachheit und Storyflow bei mehreren Themen |
| 4 | Quellenkatalog und Cache | zehn Downloads/FFprobe-/Render-Läufe | echte Videoquellen, Rechte, zentrale Motive, keine eingebetteten Texte |
| 5 | Vision-Matching | zehn Pläne ohne stille Fallbacks | jedes Must-show im gewählten Clip tatsächlich sichtbar |
| 6 | Verifizierte Ausschnitte | zehn Intervall-/Schnittläufe | gesamter Ausschnitt passend, keine falschen Nachbarframes |
| 7 | Untertitel im finalen MP4 | zehn vollständige Läufe | Wort gegen hörbaren Beginn, Randabstand, Lesbarkeit |
| 8 | Lizenzierte Musik und Mix | zehn vollständige Läufe | kein fehlendes Bett, sauberes Ducking, guter Sound |
| 9 | Automatisches, fail-closed Quality Gate | zehn vollständige Läufe | mehrere Themen; gezielte Korrektur statt falschem Pass |
| 10 | Make/Worker/Redis-Orchestrierung | zehn autonome Gesamtläufe | mehrere qualitätsgeprüfte Shorts; Upload weiterhin aus |

Für jede Stufe: einen Fehler lokalisieren, genau die betroffene Komponente ändern, ihre Serie neu starten. Produktionsfreigabe erst nach getrennten technischen und kreativen Erfolgen. Veröffentlichungen und Uploads sind nicht Teil dieses Ausbauplans.

## Stufe 2: technischer Nachweis

`vps.stage2_tts_test` spricht in zehn Durchgängen zehn unterschiedliche technische Testtexte mit der vorhandenen Edge-TTS-Stimme, übernimmt native Wortmarken und rendert jeweils ein vollständiges MP4 mit den festen Stufe-1-Clips. Der erste Versuch stoppte beim Renderer: 10,75 Sekunden Narration unterschritten den bestehenden 15-Sekunden-Grenzwert. Nur die Testtexte wurden verlängert; die zweite Serie bestand **10/10 aufeinanderfolgende vollständige TTS-/Render-Durchläufe** im [Action-Run 37817835088](https://github.com/TimRich2025/Knowledge-Nuggets-Repository/actions/runs/37817835088). Das technische Manifest liegt als Artefakt vor. Die Testtexte variierten, die Videoclips blieben feste Fixtures. Das ist `TECHNICAL_PASS`, `quality_status=NOT_EVALUATED`. Stimmklang und hörbar-sichtbare Wort-/Audio-Synchronität sind an echten Themen separat zu beurteilen; Stufe 2 ist kreativ noch nicht abgeschlossen.

## Qualitätsabsicherung der bestehenden Quellenplanung (8. Oktober)

Die bestehende `plan_from_observations`-Übergabe weist nun jede vom Matcher mit `served_by` markierte Zuweisung zurück, ebenso ausdrücklich unbesetzte Beats. Solche Einträge stammen aus dem Nachbar- oder Restclip-Fallback und belegen den geforderten Bildinhalt nicht. Statt eines Renderplans erhält die vorhandene Suchrunde die betroffenen Beat-Nummern und gezielte Suchbegriffe über `UnmatchedBeats`. Der Renderer und die Make-Szenarien wurden hierfür nicht neu gebaut oder umgestellt.

Der bestehende KN Narration QC Workflow wurde auf dem Entwicklungsbranch ausgeführt: [Run 37820801380](https://github.com/TimRich2025/Knowledge-Nuggets-Repository/actions/runs/37820801380) ist erfolgreich. Die Tests umfassen den Fall eines Beats ohne passendes Videomaterial. Dies belegt die technische Sperre, nicht die kreative Freigabe echter Szenen oder zehn autonome Gesamtläufe. Uploads bleiben ausgeschaltet.

## Make-Vertiefung: KN 03B Eingabe und Schein-Erfolg (8. Oktober)

Die erneute Prüfung des letzten API-Runs `561b81e5bd684fe18c0e75ad153f3c76` zeigt die unmittelbare Ursache des übersprungenen Gates: Der Manifest-Builder erhielt `Shot brief JSON: []` und `Matched beat plan: {}`. Er antwortete mit `[]`; `A2 | Parse Shot Manifest` meldete ausdrücklich `No bundles were generated by this operation`. Damit erreichte kein Bundle das Modul `B1 | Visual Coverage Gate`. Make meldete dennoch `Success` und belastete 6,5 Credits. Dieser Lauf beweist weder einen erfolgreichen noch einen gescheiterten Gate-Entscheid für echte Produktionsdaten: Es waren leere Eingaben.

Die Szenario-Eingaben `scene_brief` und `plan_json` sind als erforderliche Textfelder definiert. Ein nichtleerer Text `[]` bzw. `{}` erfüllt diese Pflicht, ohne Shots zu enthalten. Der Filter nach dem Gate lässt nur `B2.status = VISUALS_READY` zur Produktion durch; er erklärt nicht das Ausbleiben von B1 in diesem Run. Nächster gezielter Eingriff: die vorhandene KN-03/03B-Übergabe muss vor dem kostenpflichtigen Builder die tatsächliche Anzahl und Struktur von Brief und Beat-Plan prüfen und bei leerem oder unvollständigem Plan einen ausdrücklichen `QUALITY_FAIL` mit betroffenen Beats zurückgeben. Ein stiller Null-Bundle-Erfolg darf nicht als Qualitätsentscheidung protokolliert werden. Die konkrete Upstream-Abbildung ist vor einer Änderung an aktiven Szenarien zu prüfen.

Eine zweite, eigenständige Qualitätslücke liegt im bestehenden Builder-Prompt: Er schreibt `semantic_match=EXACT`, `semantic_score=96`, `visual_quality_score=90`, `cleanliness_status=PASS` und `crop_status=PASS` als feste Werte vor und lässt `shot_description` aus den gleichen `matched_terms` wie `visual_target` formulieren. Der nachgelagerte Gate-Prompt nennt diese gemeinsame Wortherkunft selbst als Grund, warum die Beschreibungen übereinstimmen sollen. Das ist kein unabhängiger Nachweis sichtbarer Bildinhalte, Qualität oder Passung. Diese Kennzahlen müssen aus beobachteten Kandidaten und Ausschnitten kommen oder `UNVERIFIED` bleiben; der Gate-Status darf sie nicht aus dem eigenen Manifest-Text ableiten. Für den späteren Quality Gate sind mehrere echte Themen und Sichtprüfung der ausgewählten Ausschnitte erforderlich. Bis dahin keine Produktionsfreigabe.

## KN 03 → KN 03B: vorbereiteter Eingangsvertrag

Die letzte `KN 03B`-Ausführung ist ein isolierter API-Aufruf mit `scene_brief=[]` und `plan_json={}`; sie beweist **nicht**, dass der neue Aufruf aus `KN 03` dieselben leeren Werte liefert. Im aktuellen `KN 03`-Diagramm ruft der untere Zweig `/v2/scenarios/9875497/run` über ein JSON-Transform-Modul auf. Der umfangreiche erfolgreiche KN-03-Run `daaa9afe...` vom 27. September enthält Builder, Gate und Produktionsstart noch **innerhalb von KN 03** und ist damit kein End-to-End-Nachweis für die spätere KN-03B-Übergabe.

Eine historische Gate-Ausgabe in diesem alten Lauf war `VISUALS_INCOMPLETE`: Zwei von 18 Shots stammten aus einer Animationsrolle, obwohl das Manifest sie als `VIDEO`, `EXACT` und mit Qualitätswert 90 markiert hatte. Der Gate-Filter verhinderte in drei Bundles den Produktionsstart; ein viertes Bundle erreichte ihn. Das zeigt zugleich die Stärke des Ausschlusses von Animationen und die Schwäche der pauschal vom Builder gesetzten Werte. Ein Modul-Success ist keine unabhängige Prüfung des konkreten Ausschnitts.

**Kleinstes vorgesehenes Änderungsstück im bestehenden KN-03B-Szenario:** Vor A1 die zwei JSON-Textfelder als Daten prüfen. Ein gültiger Aufruf benötigt einen nichtleeren Shot-Brief, einen `MATCHED`-Plan mit nichtleerem `beat_plan`, gleiche Shot-Anzahl und eine eindeutige Zuordnung jeder Beat-Nummer zu einer Szene. Der aktuelle Builder verlangt genau 18 Objekte; solange dieser Vertrag gilt, muss die Vorprüfung ebenfalls 18 verlangen. Leere, ungültige oder unvollständige Eingaben dürfen A1 nicht erreichen. Der Ablehnungspfad muss `content_id`, Run-ID, Grund und einen expliziten technischen/Qualitätsstatus zurückgeben oder persistent festhalten; null Parser-Bundles und ein grüner Szenariostatus reichen nicht. Die bereits vorhandene Produktionsfilterung nach `VISUALS_READY` bleibt erhalten. Ein realer `MATCHED`-Aufruf ist vor jeder Aktivierung des geänderten Pfads als Positivfall zu prüfen.

**Isolierter Testplan nach der einen Änderung:** Einmal den beobachteten Fall `[]`/`{}` reproduzieren und A1=0 Operationen sowie einen ausdrücklichen Fehlerstatus nachweisen; dann fehlendes Feld, kaputtes JSON, 17/18 Beats, doppelte Beat-Nummer und `LOOK_AGAIN` prüfen. Ein gültiges historisches Eingabepaar soll bis zur bestehenden Qualitätsprüfung gelangen, ohne den Renderjob auszulösen; hierfür muss der Produktionsfilter nachweislich geschlossen bleiben. Nach jeder Korrektur der getesteten Komponente beginnt die technische Serie von zehn aufeinanderfolgenden vollständigen Vorprüfungen erneut. Mehrere echte Themen und visuelle Prüfung gehören zum getrennten Quality Gate. Keine dieser Vorprüfungen ist ein Short- oder Produktionspass.
