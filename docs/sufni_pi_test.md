# Sufni-Test direkt auf dem Raspberry Pi

Diese Anleitung fuehrt einen reversiblen Test des Sufni-Dashboards direkt auf dem Raspberry Pi aus. Der bestehende Telemetrie-Stack bleibt dabei getrennt: Logger, ADS1256, GPS, Samba, SSH, Hotspot und der Windows-Deploy-Workflow werden nicht in die Sufni-Umgebung integriert oder umkonfiguriert.

## Ziel

Der Test beantwortet drei Fragen:

1. Laeuft der Sufni-Docker-Stack auf ARM64 vollstaendig auf dem Raspberry Pi?
2. Bleibt der bestehende Logger unter Last unveraendert stabil?
3. Ist der Zugriff per iPhone ueber das bestehende Ride-Hotspot-Netz praktikabel?

## Neue Hilfsskripte

Die Umsetzung fuegt zwei Windows-Skripte und ein Pi-Skript hinzu:

- [tools/deploy_sufni_test.ps1](../tools/deploy_sufni_test.ps1) kopiert nur den neuen Pi-Helfer nach `/home/pi/mtb_telemetry/deploy/sufni/`.
- [tools/sufni_test.ps1](../tools/sufni_test.ps1) fuehrt den Pi-Helfer per SSH aus.
- [deploy/sufni/sufni_test.sh](../deploy/sufni/sufni_test.sh) kapselt Baseline, Docker-Installation, isoliertes Klonen, ARM64-Pruefung und `docker compose`-Befehle.

Die Hilfsskripte arbeiten absichtlich ausserhalb des Produktivpfads des Loggers.

## 1. Pi-Helfer deployen

Vom Windows-Projektordner aus:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\deploy_sufni_test.ps1
```

Das kopiert nur die Datei `deploy/sufni/sufni_test.sh` auf den Pi und setzt dort Unix-Zeilenenden plus Ausfuehrungsbit.

## 2. Plattform-Baseline erfassen

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\sufni_test.ps1 baseline
```

Der Befehl gibt aus:

- `uname -m`
- `/etc/os-release`
- `free -h`
- `df -h /`
- Docker-Versionen, falls schon vorhanden
- Status wichtiger Dienste wie `ssh`, `smbd`, `mtb-wifi-mode` und `mtb-telemetry-button`

## 3. Docker nur bei Bedarf installieren

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\sufni_test.ps1 install-docker
```

Eigenschaften:

- installiert Docker Engine und das Compose-Plugin ueber das Docker-APT-Repository
- aendert nichts an der Python-Venv des Telemetrieprojekts
- registriert den aktuellen Pi-Benutzer in der `docker`-Gruppe
- kann danach eine neue SSH-Anmeldung erfordern, damit Docker ohne `sudo` nutzbar ist

Danach die Baseline nochmals ausfuehren und pruefen, dass SSH, Samba und Hotspot unveraendert erreichbar sind.

## 4. Sufni isoliert vorbereiten

Standardmaessig wird der aktuelle `main`-Stand verwendet, passend zum Dashboard auf dem Windows-PC. Fuer reproduzierbare Tests kann `SUFNI_REF` auf einen konkreten Commit oder Tag gesetzt werden.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\sufni_test.ps1 prepare
```

Falls eine konkrete Version genutzt werden soll:

```powershell
$env:SUFNI_REF = '9efe33da8733db54468ca2554f6232638ae2818a'
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\sufni_test.ps1 prepare
Remove-Item Env:SUFNI_REF
```

Der Checkout landet standardmaessig in `~/sufni_test/sst`.

## 5. ARM64-Unterstuetzung pruefen

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\sufni_test.ps1 arm64-check
```

Geprueft werden die benoetigten Basisimages:

- `node:22.0-bookworm-slim`
- `python:3.11-slim-bookworm`
- `golang:1.22-alpine`
- `alpine:3.20`
- `caddy:2.7.6`

Die Pruefung validiert, ob die Images `linux/arm64` in ihren Manifests ausweisen.

## 6. Zunaechst nur bauen

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\sufni_test.ps1 build
```

Parallel auf einer zweiten SSH-Sitzung beobachten:

```bash
htop
```

oder:

```bash
top
```

Relevante Beobachtungen:

- RAM-Verbrauch waehrend des Builds
- CPU-Last
- Swap-Nutzung
- eventuelle OOM-Signaturen oder Build-Abbrueche

## 7. Testweise im Vordergrund starten

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\sufni_test.ps1 up
```

Der Prozess bleibt im Vordergrund, damit die Compose-Logs direkt sichtbar sind.

In einer zweiten Sitzung:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\sufni_test.ps1 ps
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\sufni_test.ps1 stats
```

Erwartete Services:

- `dashboard`
- `gosst-http`
- `gosst-tcp`
- `caddy`

## 8. Zugriff pruefen

Die zu erwartenden URLs lassen sich ausgeben mit:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\sufni_test.ps1 urls
```

Typisch:

- Zuhause: `https://<PI-IP>`
- Unterwegs: `https://192.168.10.1`

Hinweis:

- Der Stack nutzt Caddy mit internem TLS.
- Fuer den Ersttest auf dem iPhone ist ein Zertifikatswarnhinweis erwartbar und akzeptabel.
- Der Test bleibt trotzdem komplett offline-faehig.

## 9. Koexistenz mit dem Logger pruefen

Waehrend Sufni weiterlaeuft:

1. Logger normal starten.
2. Kurze Testsession aufzeichnen.
3. Parallel `docker stats` und `htop` beobachten.
4. Nach dem Lauf CSV beziehungsweise Exportdaten auf Timing und Vollstaendigkeit pruefen.

Wichtig:

- Die Telemetrie-Aufzeichnung hat Prioritaet.
- Jede erkennbare Verschlechterung bei Samples, Timing oder Stabilitaet ist ein Ausschlusskriterium.

## 10. Rollback

Stack stoppen:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\sufni_test.ps1 down
```

Danach auf dem Pi bei Bedarf den Testordner entfernen:

```bash
rm -rf ~/sufni_test
```

Docker muss fuer den Rollback nicht deinstalliert werden. Der Produktivpfad des Loggers bleibt unberuehrt.

## Grenzen des aktuellen Helfers

- Er integriert Sufni noch nicht in systemd.
- Er aendert keine Hotspot-, Samba- oder Logger-Konfiguration.
- Er fuehrt keinen automatischen Performance-Report zusammen; die Bewertung erfolgt bewusst manuell anhand von Build-, Laufzeit- und Logger-Beobachtung.