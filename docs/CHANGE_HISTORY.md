# Änderungsverlauf

Unter **Verwaltung → Protokolle** stehen drei Ansichten im bestehenden App-Stil bereit:

- **Änderungsverlauf:** neueste 50 Einträge, heute oder ein gewähltes Datum; weitere Einträge seitenweise. Details sind aufklappbar.
- **Technische Protokolle:** vorhandener Viewer mit Quellenauswahl, Zeilenanzahl, Warnungs-/Fehlerfilter und Kopierfunktion.
- **Downloads:** einzelne oder kombinierte ZIP-Archive; vollständige technische Protokolle enthalten auch rotierte Dateien.

`logs/changes.jsonl` enthält einen JSON-Datensatz je Änderungsanfrage mit Zeitstempel einschließlich Zeitzonenoffset, Aktion, Parametern, Ergebnis, Zugriffsrolle, Client-IP und direkter Verbindungs-IP. Erfasst werden schreibende HTTP-Anfragen sowie die bestehenden GET-Zuweisungsendpunkte. Reine Aufgabenvorschauen und Anmeldungen werden ausgelassen. Fehlgeschlagene und weitergeleitete Anfragen sind entsprechend gekennzeichnet. Der automatische Tageswechsel erhält einen separaten Systemeintrag; fehlende Planaktivierung wird als teilweise ausgeführt angezeigt.

Zeilenänderungen, Mitarbeiterpläne und Abwesenheiten enthalten zusätzlich die gespeicherten Mitarbeiterzeilen vorher und nachher. Eine Abwesenheit über mehrere Modalitäten wird als vollständiger Plan gespeichert; bei Speicherfehlern werden die Änderungen im Arbeitsspeicher zurückgenommen. Dateiimporte enthalten Dateinamen und Ergebnis, keine Kopie des hochgeladenen Inhalts. Passwörter, Secrets, Tokens, Cookies und Authorization-Felder werden rekursiv ausgeblendet. Rohdaten in aufgeklappten Details werden nicht durch die Oberflächenübersetzung verändert.

Die Anwendung verwendet gemeinsame Passwörter. Die Zugriffsrolle bezeichnet deshalb keine verifizierte Person; bei manuellen Lastkorrekturen bleibt der angegebene Adminname in den Änderungsdetails erhalten. Protokollansicht und Downloads verwenden den bestehenden Admin-Zugangsschutz.

Der Verlauf beginnt mit Aktivierung dieser Version. Frühere Änderungen sowie direkte Dateiänderungen außerhalb der Anwendung werden nicht rückwirkend rekonstruiert. Das Datum filtert den Zeitpunkt der Änderung, nicht das bearbeitete Planungsdatum. Alte Einträge werden nicht automatisch gelöscht. Dateisperren schützen parallele Schreibzugriffe. Schreibfehler erscheinen im Anwendungslog und als HTTP-Header `X-Change-History-Status: write-failed`; eine bereits ausgeführte Änderung wird dadurch nicht als fehlgeschlagen ausgegeben.

## Reverse Proxy

Standardmäßig werden `X-Forwarded-For`-Header nur bei direkter Verbindung von `127.0.0.1` oder `::1` ausgewertet. Weitere vertrauenswürdige Proxy-Netze können vor dem Start mit `RADIMO_AUDIT_TRUSTED_PROXIES` als kommagetrennte CIDR-Liste konfiguriert werden. Von rechts nach links wird die erste nicht vertrauenswürdige Adresse als Client verwendet. Bei direktem Zugriff zählt ausschließlich die Verbindungs-IP. Der Proxy muss die tatsächliche Client-IP an die Headerkette anhängen.

## Prüfung

`tests/test_change_audit.py` prüft Erfassung, gespeicherte Vorher-/Nachher-Werte, Ausnahmen, Fehlerstatus, Geheimnisfilterung, Proxy-Vertrauen, Datum/Paginierung, paralleles Schreiben, Schreibfehler, Adminschutz und Darstellung. Die Test-Fixture in `tests/conftest.py` leitet synthetische Audit-Einträge in temporäre Dateien um.
