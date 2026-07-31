# AI Handover

## 1) Button- und Shutdown-Logik erweitert

In `scripts/haltech_two_point_mm.py` wurde ein zweiter GPIO-Taster ergänzt. Der bestehende Taster steuert weiterhin Logging AN/AUS, der neue Taster löst einen geordneten Raspberry-Pi-Shutdown aus. Vor dem Shutdown wird eine aktive Session sauber geschlossen und der Sufni-Export noch ausgeführt. Zusätzlich gibt es eine Prüfung, damit Logging-GPIO und Shutdown-GPIO nicht identisch gesetzt werden.

## 2) Service-Startskript erweitert

In `scripts/start_button_logger.sh` wurden die neuen Umgebungsvariablen `SHUTDOWN_GPIO` und `SHUTDOWN_DEBOUNCE_MS` ergänzt. Das Skript reicht diese optional an das Python-Skript durch, egal ob der Logging-Eingang als `switch` oder `button` konfiguriert ist.

## 3) Systemd-Default und Dokumentation ergänzt

In `deploy/systemd/mtb-telemetry-button.service` wurden Default-Werte für den Shutdown-Taster ergänzt, aktuell GPIO22. In `docs/python_commands.md` wurden Verdrahtung, Startbeispiel und die nötige `sudoers`-Regel dokumentiert, damit der Dienst als User `pi` das Herunterfahren ohne Passwort auslösen kann.

## 4) Deploy-Skript korrigiert

In `tools/deploy.ps1` wurde der Deploy-Inhalt korrigiert. Zuerst wurde sichtbar, dass `deploy/systemd` gar nicht auf den Pi übertragen wurde. Danach wurde die Lösung auf den kompletten Top-Level-Ordner `deploy` umgestellt, damit auf dem Pi wirklich der Pfad `/home/pi/mtb_telemetry/deploy/systemd/...` existiert.

## 5) Temporäre Befehlsliste angelegt

In `docs/temporary_commands.md` wurde eine reine Copy-Paste-Datei mit den temporären Betriebsbefehlen angelegt: Deploy, Service-Datei prüfen, Service installieren/starten, `sudoers`-Regel setzen und Logs ansehen.

## 6) Tatsächliche Ursache fuer den Service-Fehler

Der Service ist zuletzt nicht an der Python-Logik, sondern am Shell-Launcher `scripts/start_button_logger.sh` gescheitert. Die Datei war mit Windows-Zeilenenden (`CRLF`) gespeichert. Bash auf dem Raspberry Pi hat das Skript deshalb mit `line: invalid option name` abgebrochen, noch bevor Python gestartet wurde.

Wichtig fuer zukuenftige Aenderungen:
- Shell-Skripte fuer den Pi immer mit LF-Zeilenenden speichern.
- Nach Aenderungen an `.sh`-Dateien einmal pruefen, ob keine `CRLF`-Zeilenenden mehr drin sind.
- Wenn ein systemd-Dienst sofort mit Exit-Code 2 endet, zuerst den Launcher und nicht sofort die Python-Optionen pruefen.

## 7) Service-Start robust gemacht

In `deploy/systemd/mtb-telemetry-button.service` wird das Startskript jetzt explizit ueber `/bin/bash` gestartet. Dadurch ist der Dienst nicht mehr davon abhaengig, ob `scripts/start_button_logger.sh` ein executable-Bit hat oder aus dem Windows-Checkout korrekt als ausfuehrbare Datei ankommt.

Zusatzhinweis fuer Deploys von Windows aus:
- Git kann Shell-Dateien auf dem Pi zwar inhaltlich richtig ausrollen, aber Zeilenenden bleiben trotzdem ein Risiko.
- Wenn ein `.sh`-Skript als Service-Entry-Point dient, ist eine kurze Byte-/Zeilenenden-Pruefung nach dem Edit sinnvoll.
- Nach jedem Deploy den Service mit `daemon-reload` und `restart` neu laden, damit die neue Unit und der neue Launcher wirklich aktiv sind.
