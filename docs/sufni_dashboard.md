# Sufni Dashboard — Anforderungen & Inbetriebnahme für eigene Hardware

## 1. Kurzfazit

Für das Sufni Dashboard **mit eigenem Hardware-Setup** (Raspberry Pi 4 + Linearpotis)
wird ausschließlich der **CSV-Import-Weg** genutzt. Die Sufni-DAQ-Hardware (Pico W)
wird **nicht** benötigt.

---

## 2. Hardware-Anforderungen

### 2.1 Was Sufni wirklich braucht

| Komponente | Anforderung | Dein Setup |
|---|---|---|
| **Federweg-Sensor Hinterbau** | Lineares Signal, kalibrierbar auf mm | Haltech HT-011202 (100 mm) ✅ |
| **Federweg-Sensor Gabel** | Lineares Signal, kalibrierbar auf mm | Noch nicht vorhanden — Spalte mit 0 füllen |
| **ADC** | Min. 12 Bit, ausreichend schnell für ≥ 200 Hz | ADS1256 (24 Bit, bis 30 kSPS) ✅ |
| **Zeitstempel** | Absoluter UTC-Zeitstempel beim Session-Start | DS3231 RTC empfohlen (s. u.) |
| **GPS** | Optional — für GPX-Track-Overlay im Dashboard | GPS NEO-6M ✅ optional |

### 2.2 Was Sufni **nicht** benötigt

- MPU6050 (IMU) — Sufni wertet keine Beschleunigung/Gyro aus
- Hall-Sensor (Radgeschwindigkeit) — nicht verwendet
- Raspberry Pi 4 selbst — ist nur deine Aufzeichnungsplattform

### 2.3 RTC: DS3231 oder Pi-Systemzeit?

| Szenario | Ausreichend |
|---|---|
| Nur Federweg-Analyse, kein GPS | Pi-Systemzeit reicht (Startzeitpunkt manuell im Import-Dialog korrigieren) |
| GPX-Track-Overlay aktivieren | **DS3231 erforderlich** — die GPS-Synchronisation basiert auf dem absoluten Zeitstempel |

> **Empfehlung:** Da der DS3231 bereits bestellt ist, immer verwenden.
> Der Pi verliert seine Zeit ohne Netzwerk beim Boot.

---

## 3. Sufni Dashboard in Betrieb nehmen

### 3.1 Backend starten (Docker)

```bash
sudo apt install docker-compose
cd /opt/sst   # oder dein Verzeichnis mit docker-compose.yml
sudo docker-compose up -d
```

Initialpasswort aus den Logs lesen:

```bash
sudo docker logs sst_dashboard_1
# Suche nach: GENERATED INITIAL ACCOUNT
```

Dashboard erreichbar unter: `https://<IP-deines-Servers>`

> Das Dashboard läuft als Docker-Stack bestehend aus:
> - `dashboard` — Python/Flask Webserver (Port 5000 intern)
> - `gosst-http` — Go-Backend für Datenverarbeitung
> - `gosst-tcp` — TCP-Server für DAQ-Upload (Port 557, für dich nicht relevant)
> - `caddy` — TLS-Proxy (HTTPS)

### 3.2 Bike-Setup im Dashboard anlegen

Nach dem Login auf das **Zahnrad-Icon** klicken und folgendes eintragen:

**Linkage (Kinematik deines Bikes):**

CSV-Datei mit Semikolon-Trenner — entweder:

```csv
Wheel_T;Leverage_R
0;3.18
1;3.15
...
170;2.37
```

oder:

```csv
Shock_T;Wheel_T
0;0
0.5;1
...
100;170
```

> Daten aus Hersteller-Leverage-Graphen digitalisierbar mit [graphreader.com](http://graphreader.com)

**Setup-Parameter:**

| Feld | Bedeutung | Beispiel |
|---|---|---|
| Head angle | Lenkwinkel in Grad | 64.5 |
| Front stroke | Gabelfederweg in mm | 170 |
| Rear stroke | Dämpferfederweg in mm | 65 |
| DAQ unit | Pico-ID — **nicht setzen** bei eigenem Setup | leer lassen |

---

## 4. Eigene Hardware: Was implementiert sein muss

### 4.1 Aufzeichnung

| Anforderung | Detail |
|---|---|
| **Samplerate** | Min. 200 Hz für sinnvolle Velocity-Analyse; Sufni-Original nutzt 1000 Hz |
| **Synchroner Zeitstempel** | Alle Samples relativ zu einem gemeinsamen t=0 |
| **Einheitlicher Zeitstempel pro Session** | Absoluter UTC-Startzeitpunkt für GPS-Overlay |
| **Kalibrierung** | ADC-Wert bei voll ausgefahren (Baseline) muss bekannt sein |

### 4.2 Kalibrierungsablauf für Linearpoti

Beim Start / vor jeder Session:

1. Federung **vollständig ausfahren** (Bike hochheben)
2. ADC-Wert lesen → `adc_baseline`
3. Optional: Federung **vollständig einfedern** (auf Bike setzen)
4. ADC-Wert lesen → `adc_max`

> Diese beiden Werte werden für die Normalisierung benötigt.

### 4.3 Normalisierungsformel

```python
normalized = (adc_value - adc_baseline) / (adc_max - adc_baseline)
# Ergebnis: 0.0 = voll ausgefahren, 1.0 = voll eingetaucht
```

---

## 5. CSV-Export für den Import-Dialog

### Format

```csv
Time;Fork;Shock
0.000;0.0;0.000
0.002;0.0;0.012
0.004;0.0;0.031
...
```

| Spalte | Pflicht | Inhalt |
|---|---|---|
| `Time` | Optional | Sekunden seit Session-Start — Sufni berechnet Samplerate automatisch |
| `Fork` | Pflicht | Normalisierter Gabelfederweg (0–1) — solange kein Sensor: immer 0.0 |
| `Shock` | Pflicht | Normalisierter Hinterbau-Federweg (0–1) |

> Werte > 1 werden automatisch als **Prozentwerte (0–100%)** interpretiert.
> Weitere Spalten werden ignoriert.

### Metadaten im Import-Dialog

| Feld | Pflicht | Hinweis |
|---|---|---|
| Name | ✅ | Beliebiger Session-Name |
| Start time | ✅ | UTC — aus DS3231 oder manuell |
| Sample rate | ✅ | Automatisch wenn `Time`-Spalte vorhanden |
| Description | ❌ | Optional |
| Linkage | ✅ | Vorher unter Bike-Setup anlegen |

---

## 6. Minimaler Python-Export-Code

```python
import pandas as pd

# Rohwerte aus deiner Aufzeichnung
adc_baseline_shock = 1024   # ADC-Wert bei voll ausgefahren
adc_max_shock      = 3800   # ADC-Wert bei voll eingetaucht

df = pd.read_csv("session_raw.csv")  # Spalten: time, shock_adc

df["Time"]  = df["time"] - df["time"].iloc[0]
df["Fork"]  = 0.0
df["Shock"] = (df["shock_adc"] - adc_baseline_shock) / (adc_max_shock - adc_baseline_shock)
df["Shock"] = df["Shock"].clip(0.0, 1.0)

df[["Time", "Fork", "Shock"]].to_csv("session_sufni.csv", sep=";", index=False)
```

### 6.1 Projekt-Workflow (MTB Telemetry, mit RTC-Zeit)

Fuer dieses Repository kann der Export direkt aus `data/haltech_travel.csv` erstellt werden:

```bash
cd /home/pi/mtb_telemetry
/home/pi/mtb_telemetry/venv/bin/python scripts/export_sufni_csv.py \
	--input data/haltech_travel.csv \
	--output data/session_sufni.csv \
	--metadata data/session_sufni_meta.json
```

Das Skript erzeugt:
- `data/session_sufni.csv` mit Spalten `Time;Fork;Shock`
- `data/session_sufni_meta.json` mit `session_start_utc`

Im Sufni-Importdialog wird als **Start time** genau `session_start_utc` verwendet.
Dieser Wert kommt aus dem ersten UTC-Timestamp deiner Aufzeichnung und damit aus der
Pi-Systemzeit, die durch den DS3231 RTC stabil gehalten wird.

---

## 7. GPS-Track-Overlay (optional)

1. GPX-Datei mit GPS NEO-6M aufzeichnen (separater Track-Logger oder eigenes Python-Script)
2. Im Dashboard die Session öffnen → GPX-Upload-Button → Datei hochladen
3. Dashboard synchronisiert Track mit Travel-Kurve über den absoluten Zeitstempel

> **Voraussetzung:** Session-Startzeitpunkt (UTC) und GPX-Timestamps müssen übereinstimmen → DS3231 oder GPS-Zeit als Zeitquelle nutzen.
