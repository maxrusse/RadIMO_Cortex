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

## Korrekturen aus dem vertieften Review

- Normales Abmelden sperrt Sysadmin für alle Sitzungsarten, auch bei deaktiviertem
  Admin-Passwortschutz. Veraltete Sysadmin-Tokens erhalten keine erhöhte Auditrolle.
- Authentifizierte Sysadmin-Aktionen erscheinen im Änderungsverlauf als Sysadmin.
- Die Kopfzeile bleibt nach dem Entsperren auch bei 768 Pixeln vollständig erreichbar.
- Spaltenüberschriften bleiben beim Scrollen der langen Mitarbeitertabellen sichtbar
  und folgen der horizontalen Tabellenposition. Während Bearbeitungs- und
  Pausendialogen bleiben sie verborgen; Sortieren ist dann gesperrt, damit ein
  offener Entwurf weiterhin zur ursprünglichen Person gehört.
- Abdeckungswarnungen verwenden exakt dieselbe Groß-/Kleinschreibung der
  Konfigurationslisten wie die tatsächlichen Zuweisungsbuttons.

- Dialoge berechnen ihre Abdeckung auch nach Seitenscrollen und unmittelbar
  beim Öffnen neu. Tabellenaktionen hinter einem geöffneten Editor bleiben
  dadurch vollständig gesperrt; ein anderer Eintrag kann den Entwurf nicht
  über einen unbedeckten Streifen am oberen Fensterrand ersetzen.
