# Update vom 11.11.2026: Oberfläche und Sysadmin-Zugang

- Verwaltung öffnet vor dem Seiteninhalt.
- Auslastung > Kompakt zeigt jede Person in einer eigenen Tabellenzeile.
- Abdeckungswarnungen berücksichtigen nur sichtbare, konfigurierte Zuweisungsbuttons.
- Heute und Planung verwenden beschriftete Stift-/Papierkorbsymbole. Die
  Aktionsspalte bleibt beim horizontalen Scrollen erreichbar.
- Die Mitarbeitertabellen zeigen alle Zeilen ohne eigenen vertikalen Scrollbereich.

## Sysadmin

Dateien/Backups, System mit Reload, Einstellungen und Protokolle verlangen das
zusätzliche Sysadmin-Passwort. Der Schutz gilt auch für direkte API-Aufrufe.
CSV-Upload/Import und die Tagesplanung bleiben im normalen Admin-Bereich.

Das Passwort wird über `sysadmin_password` in YAML konfiguriert. Der separate
Passworteintrag in den allgemeinen Einstellungen entfällt; der vollständige
YAML-Editor liegt in der geschützten erweiterten Administration. Ein vorhandenes
`log_password` wird übergangsweise akzeptiert, solange kein neues Sysadmin-Passwort
gesetzt ist. Passwortwechsel und Abmelden sperren den Zugang erneut.

## Updatepaket

Das Paket enthält auf ausdrücklichen Wunsch wieder die lokale `config.yaml`.
Sie ersetzt die Serverkonfiguration nach einem vollständigen Backup. In dieser
Datei wurde der bisherige Passwortwert unverändert unter `sysadmin_password`
übernommen. Keine Passwortwerte gehören in öffentliche Quelldateien.

Dienst `radimo-cortex`, System-Python und Port 5035 bleiben erhalten. Es werden
keine Betriebssystem- oder Abhängigkeitspakete installiert oder aktualisiert.
