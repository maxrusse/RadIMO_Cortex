# Update vom 12.11.2026: Kompakt-Auswertung und Medianabweichung (r9)

Rollen können mit `exclude_from_compact_stats: true` aus der Kompakt-Auswertung
ausgenommen werden. Hat eine Person am Tag eine solche Rolle, entfällt sie
vollständig aus Kompakt, dessen Summen und Medianvergleich. Matrix, Tagesbild,
Protokoll, gespeicherte Buchungen und Zuweisungslogik bleiben erhalten.
In der Demo-Vorlage ist dies für „SBZ: Privatbefundung“ und „Kinderarzt“ gesetzt.

Die Medianabweichung zeigt weiter Prozent und die bisherige Balkenskalierung.
Zusätzlich steht darunter die absolute Differenz in Gewicht pro Stunde.
Die Gewichtszellen in den Personendetails verwenden keine Hovertexte mehr.

Das r9-Paket enthält auf ausdrücklichen Wunsch die angepasste Live-Konfiguration
`config_live_20261112.yaml` als aktive `app/config.yaml`. Diese ersetzt nach
vollständigem Backup die Serverkonfiguration. Zugangsdaten bleiben ausschließlich
im privaten Paket; die öffentliche Demo-Vorlage behält ihre drei radimo-Passwörter.
Es werden keine Betriebssystem- oder Abhängigkeitspakete aktualisiert.

# Update vom 12.11.2026: Buchungsgewichte in Personendetails (r8)

Unter Auslastung zeigt die aufgeklappte Tabelle „Anzahl / gebuchtes Gewicht“
statt Anzahl und nachträglich berechnetem Normalgewicht. Neue Buchungen speichern
den tatsächlichen Gewichtszuwachs einschließlich Strict und persönlicher Faktoren.
Ältere Verlaufseinträge verwenden ihr gespeichertes Anfragegewicht; die Legende
erklärt diesen Unterschied. Bei unvollständigem Verlauf steht Anzahl / –.
Korrekturen bleiben separat und ändern keine Zuweisungszahlen.

Numerische Spaltenüberschriften und Werte in der kompakten Auslastungstabelle
sind einheitlich rechtsbündig. Die große Matrixansicht „Gewicht“ bleibt eine
aus Anzahl und aktuellem Normalgewicht abgeleitete Ansicht.

Das r8-Paket enthält keine aktive `config.yaml`. Serverkonfiguration und
Laufzeitdaten bleiben erhalten; es werden keine Abhängigkeiten installiert.

# Update vom 12.11.2026: Zeitlinie im Zeitplan (r7)

Die rote Zeitlinie im Zeitplan aktualisiert sich jede Sekunde. Ihre Position
berücksichtigt die tatsächliche Breite der Namensspalte, auch nach einer
Änderung der Fenstergröße. Die Anwesenheitsprüfung bleibt im Minutentakt.

Das r7-Updatepaket enthält keine aktive `config.yaml`; die vorhandene
Serverkonfiguration bleibt erhalten. Es installiert keine Abhängigkeiten.

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

## Zwischenablage: bewährten Kopierweg wiederhergestellt

Der früher lokal genutzte Textfeld-/`execCommand('copy')`-Weg ergänzt wieder die
moderne Clipboard-API. Damit funktioniert das Kopieren auch auf internen
HTTP-Seiten, wo die moderne API fehlt, sowie bei abgewiesenem modernem Zugriff.
Beide Live-Ansichten, Verlauf und Protokollvorschau verwenden denselben Helfer.

Ein fehlgeschlagener Kopierversuch wird nicht als Erfolg gemeldet. Der aktuelle
Ergebnisbereich bietet dann einen erneuten Kopierversuch, ohne eine weitere
Person zuzuweisen. Temporäre Textfelder werden entfernt und vorheriger Fokus
sowie Textauswahl wiederhergestellt.

Historischer Abgleich: Der alte lokale RadIMO-Code verwendet den Ersatzweg
bereits im CTSBZ8-Archiv (Dateistand 18.11.2024). Cortex behielt ihn bis zum
Stand 9b53c5a; Commit 376bdaa vom 31.07.2026 entfernte ihn. Das Designupdate
vom 15.10.2026 übernahm die API-only-Funktion in den Live-Verlauf. Die alte und
die wiederhergestellte Funktion wurden auf HTTP mit echtem Einfügen verglichen.

## r6: Paket ohne aktive Konfiguration

Die r6-ZIP enthält keine `config.yaml`. Das Deployment erhält die vorhandene
Serverdatei und schützt sie auch vor Löschung beim Codesynchronisieren.
`config.demo.yaml` bleibt als öffentliche Vorlage enthalten; Zugang-, Admin-
und Sysadmin-Passwort lauten dort wie gewünscht jeweils `radimo`. Diese Vorlage
ersetzt niemals automatisch eine bestehende aktive Serverkonfiguration.
