# Knowledge Nuggets: Bestandsaufnahme und kontrollierter Ausbau

Stand: 7. Oktober 2026, Basis `main` bei `5c6eb658`. Diese Analyse beschreibt den Repository-Code. Sie beweist weder den Zustand eines laufenden Make-Szenarios noch die aktuelle Railway-Konfiguration.

## A. Aktuelle Architektur

1. Make erstellt Inhalt und ruft den Worker über HTTP auf. Die tatsächliche Make-Konfiguration ist nicht im Repository versioniert.
2. Der FastAPI-Dienst (`vps/api.py`) bietet Quellenkandidaten, Storyboard- und Plan-Endpunkte sowie `POST /jobs`; Redis hält Jobs und Source-Pools.
3. Der Worker (`vps/worker.py`) holt Jobs aus Redis. `vps/source_cache.py` erzeugt Edge-TTS samt Wortzeiten, lädt Videoausschnitte herunter und prüft sie mit FFprobe.
4. `vps/local_renderer.py` schneidet die lokalen Clips mit FFmpeg, setzt Layout und Wortanimation, mischt gegebenenfalls Musik und prüft das Headerbild.
5. `vps/pipeline.py` verschiebt das MP4 in den persistenten Ausgabepfad, sendet einen Callback und kann bei aktiviertem Flag automatisch **privat** auf YouTube hochladen. Ein privater Upload ist trotzdem ein Upload und bleibt für dieses Projektstadium gesperrt.
6. GitHub Actions enthält Narration-QC und Source-Hunt. Das Root-README beschreibt noch GitHub Actions als Renderer, während `vps/README.md` den Worker als Produktionsruntime beschreibt. Beide Dokumente sind in diesem Punkt widersprüchlich.

## B. Externe Abhängigkeiten

| Abhängigkeit | Aufgabe | Grenze |
| --- | --- | --- |
| Make | Orchestrierung, LLM-/Vision-Schritte und Callback | Szenariodaten fehlen im Repository; kein Nachweis über aktive Konfiguration |
| GitHub Actions | Unit-Tests, Audio-QC, Quellensuche | Grüne Runs sagen nichts über Videogüte oder zehn End-to-End-Runs |
| Redis und Host (VPS/Railway) | Queue, Token, Cache, Worker, persistente MP4s | Deployment- und Umgebungszustand hier nicht verifiziert |
| Microsoft Edge-TTS | gesprochener Text und Zeitmarken | Externes Netzwerk; Rate und Stimmenqualität separat prüfen |
| NASA-Katalog und Medienserver | Suche, Storyboards, Download | Katalogtitel belegt keine Bildhandlung im gewählten Ausschnitt |
| Vision/LLM über Make | Beschreibung von Frames und Skript | Modellaufrufe und deren Prompt/Version außerhalb des Repos |
| FFmpeg, FFprobe, libass, Pillow und Noto-Fonts | Clipverarbeitung, Render, Bild-QC | Lokal reproduzierbar, sofern Versionen und Fonts vorhanden |
| Musikdateien | optionales Soundbett | Keine Audiodatei im Repo; heutiger Renderer akzeptiert Stille |
| Google/YouTube API | optionaler Upload und Trenddaten | Muss explizit ausgeschaltet bleiben |

Railway-Lesezugriff zeigt im Projekt „Knowledge Nuggets Production“ einen Worker auf Branch `main` mit Dockerfile, Startbefehl `python -m vps.entrypoint` und persistentem `/data`-Volume. Ein älterer API-Dienst schläft, `kn-render-api-v2` ist fehlgeschlagen; Redis/Queue und Worker melden erfolgreiche Deployments vom September. Die Docker-Compose-Datei nennt zusätzlich einen VPS mit getrennten Diensten; `vps/service.py` enthält den kombinierten Prozess. Aus dem Repository allein folgt nicht, welcher HTTP-Endpunkt Make aktuell verwendet.

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
