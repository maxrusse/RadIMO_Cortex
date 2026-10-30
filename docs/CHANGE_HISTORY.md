# Änderungsverlauf

Unter **Verwaltung → Protokolle** stehen drei Ansichten im bestehenden App-Stil bereit:

- **Änderungsverlauf:** neueste 50 Einträge, heute oder ein gewähltes Datum; weitere Einträge seitenweise. Details sind aufklappbar.
- **Technische Protokolle:** vorhandener Viewer mit Quellenauswahl, Zeilenanzahl, Warnungs-/Fehlerfilter und Kopierfunktion.
- **Downloads:** einzelne oder kombinierte ZIP-Archive; vollständige technische Protokolle enthalten auch rotierte Dateien.

`logs/changes.jsonl` enthält einen JSON-Datensatz je Änderungsanfrage mit Zeitstempel einschließlich Zeitzonenoffset, Aktion, Parametern, Ergebnis, Zugriffsrolle. Erfasst werden schreibende HTTP-Anfragen sowie die bestehenden GET-Zuweisungsendpunkte. Reine Aufgabenvorschauen und Anmeldungen werden ausgelassen. Fehlgeschlagene und weitergeleitete Anfragen sind entsprechend gekennzeichnet. Der automatische Tageswechsel erhält einen separaten Systemeintrag; fehlende Planaktivierung wird als teilweise ausgeführt angezeigt.

Zeilenänderungen, Mitarbeiterpläne und Abwesenheiten enthalten zusätzlich die gespeicherten Mitarbeiterzeilen vorher und nachher. Eine Abwesenheit über mehrere Modalitäten wird als vollständiger Plan gespeichert; bei Speicherfehlern werden die Änderungen im Arbeitsspeicher zurückgenommen. Dateiimporte enthalten Dateinamen und Ergebnis, keine Kopie des hochgeladenen Inhalts. Passwörter, Secrets, Tokens, Cookies und Authorization-Felder werden rekursiv ausgeblendet. Rohdaten in aufgeklappten Details werden nicht durch die Oberflächenübersetzung verändert.

Die Anwendung verwendet gemeinsame Passwörter. Die Zugriffsrolle bezeichnet deshalb keine verifizierte Person; bei manuellen Lastkorrekturen bleibt der angegebene Adminname in den Änderungsdetails erhalten. Protokollansicht, Vorschau und Downloads verlangen ein separates `log_password`, auch bei deaktiviertem Admin-Passwortschutz. Das Passwort wird unter **Einstellungen** gesetzt; ohne konfiguriertes Passwort bleibt der Zugriff gesperrt. Ein Log-Login gewährt keine zusätzlichen Adminrechte. Nach einer Passwortänderung müssen sich Log-Nutzer erneut anmelden.

Der Verlauf beginnt mit Aktivierung dieser Version. Frühere Änderungen sowie direkte Dateiänderungen außerhalb der Anwendung werden nicht rückwirkend rekonstruiert. Das Datum filtert den Zeitpunkt der Änderung, nicht das bearbeitete Planungsdatum. `change_history_enabled` schaltet die Erfassung von Änderungen und manuellen Korrekturen ein oder aus (Standard: an); vorhandene Einträge bleiben lesbar. `log_retention_days` bestimmt die Aufbewahrung (Standard: 100 Tage einschließlich heute, mindestens 1 Tag). Beim ersten Request, danach stündlich und nach Änderung der Dauer werden Änderungsverlauf, technische Logs einschließlich Rotation und Nutzungsstatistik bereinigt. Ohne Requests läuft keine Bereinigung; sie wird vor dem nächsten Zugriff nachgeholt. Undatierte technische Zeilen werden dem vorhergehenden datierten Eintrag bzw. dem Dateiänderungsdatum zugeordnet. Dateisperren schützen parallele Schreibzugriffe. Schreibfehler erscheinen im Anwendungslog und als HTTP-Header `X-Change-History-Status: write-failed`; eine bereits ausgeführte Änderung wird dadurch nicht als fehlgeschlagen ausgegeben.

IP-Adressen werden nicht mehr als Metadaten erfasst oder angezeigt. Die Bereinigung entfernt alte IP-Felder aus dem Änderungsverlauf. Alte IP-Felder manueller Korrekturen werden beim Laden und Speichern des Zustands entfernt. Freitext wird dabei nicht als IP-Adresse interpretiert.

Downloads tragen den Hinweis: „Sicher aufbewahren und nach der Auswertung löschen.“

## Prüfung

`tests/test_change_audit.py` prüft Erfassung, gespeicherte Vorher-/Nachher-Werte, Ausnahmen, Fehlerstatus, Geheimnisfilterung, Datum/Paginierung, paralleles Schreiben, Schreibfehler, Log-Passwortschutz und Darstellung. Die Test-Fixture in `tests/conftest.py` leitet synthetische Audit-Einträge in temporäre Dateien um.
