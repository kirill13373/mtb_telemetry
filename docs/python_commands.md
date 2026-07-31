# Python Kommandos (MTB Telemetry)

Diese Befehle sind auf dein aktuelles Setup zugeschnitten (Raspberry Pi, venv, ADS1256, Haltech-Sensor).

## 1) In das Projekt wechseln

```bash
cd /home/pi/mtb_telemetry
```

## 2) Tests ausfuehren

Alle ADS1256-Tests:

```bash
/home/pi/mtb_telemetry/venv/bin/python -m pytest tests/test_ads1256.py -q
```

## 3) ADS1256 Basis-Check (Status und Chip-ID-Nibble)

```bash
/home/pi/mtb_telemetry/venv/bin/python scripts/ads1256_quick_check.py
```

## 4) Live-Spannung von AD0 lesen

```bash
/home/pi/mtb_telemetry/venv/bin/python scripts/haltech_live_read.py
```

## 5) Range-Diagnose (Min/Max/Span + Clip-Hinweis)

```bash
/home/pi/mtb_telemetry/venv/bin/python scripts/haltech_range_check.py
```

## 6) 2-Punkt-Kalibrierung und Live-Ausgabe in mm

Start mit gespeicherter Kalibrierung (falls vorhanden):

```bash
/home/pi/mtb_telemetry/venv/bin/python scripts/haltech_two_point_mm.py
```

Kalibrierung erzwingen (0 mm / 100 mm neu aufnehmen):

```bash
/home/pi/mtb_telemetry/venv/bin/python scripts/haltech_two_point_mm.py --recalibrate
```

Mit CSV-Logging starten:

```bash
/home/pi/mtb_telemetry/venv/bin/python scripts/haltech_two_point_mm.py --log
```

Die Messwerte werden dann in `data/haltech_travel.csv` gespeichert.

Ohne laufende Terminal-Ausgabe (fuer spaeteren Headless-Betrieb):

```bash
/home/pi/mtb_telemetry/venv/bin/python scripts/haltech_two_point_mm.py --log --quiet
```

Debug-Ausgabe reduzieren (z. B. nur jede 10. Probe):

```bash
/home/pi/mtb_telemetry/venv/bin/python scripts/haltech_two_point_mm.py --log --print-every 10
```

Zielrate explizit setzen (z. B. 80 Hz):

```bash
/home/pi/mtb_telemetry/venv/bin/python scripts/haltech_two_point_mm.py --log --quiet --target-hz 80
```

Maximale Geschwindigkeit ohne zusaetzliches Pacing:

```bash
/home/pi/mtb_telemetry/venv/bin/python scripts/haltech_two_point_mm.py --log --quiet --target-hz 0
```

Mit Kippschalter (z. B. Mitte an GPIO17, eine Seite an GND):

```bash
/home/pi/mtb_telemetry/venv/bin/python scripts/haltech_two_point_mm.py --switch-gpio 17
```

Schalter nach GND: Logging AN. Andere Stellung: Logging AUS.

Wenn der Schalter in einer Stellung flattert, Debounce erhoehen (z. B. 400 ms):

```bash
/home/pi/mtb_telemetry/venv/bin/python scripts/haltech_two_point_mm.py --switch-gpio 17 --switch-debounce-ms 400
```

Mit Taster (momentary button) zum Toggle von Logging AN/AUS:

Verdrahtung (default in Skript):
- eine Taste-Seite an BCM GPIO (z. B. GPIO27)
- andere Taste-Seite an GND
- kein externer Widerstand noetig (interner Pull-up wird verwendet)

Zweiter Taster fuer Raspberry Pi Shutdown:
- eine Taste-Seite an BCM GPIO (Vorschlag: GPIO22)
- andere Taste-Seite an denselben GND wie der Logging-Taster
- ebenfalls kein externer Widerstand noetig (interner Pull-up wird verwendet)
- wichtig: Shutdown-Taster muss an einem anderen GPIO als der Logging-Taster haengen

Status-LED fuer "Messung laeuft":
- Vorschlag GPIO: BCM GPIO23 (physischer Pin 16)
- LED-Anode (langes Bein) -> ueber 220 Ohm bis 470 Ohm Vorwiderstand an GPIO23
- LED-Kathode (kurzes Bein) -> GND
- Verhalten: LED AN waehrend Logging aktiv, LED AUS waehrend Logging pausiert
- nur bei LED-Modulen mit invertierter Logik: `--status-led-active-low` setzen

Startbeispiel:

```bash
/home/pi/mtb_telemetry/venv/bin/python scripts/haltech_two_point_mm.py --button-gpio 27 --shutdown-button-gpio 22 --status-led-gpio 23 --quiet --target-hz 80
```

Jeder Tastendruck toggelt Logging zwischen AN und AUS.
Jeder Tastendruck auf den Shutdown-Taster schliesst die aktive Session sauber ab und faehrt den Raspberry Pi herunter.

## 10) Ohne Terminal-Start: Autostart als systemd-Service

Wenn du willst, dass der Button ohne manuelles Starten des Python-Skripts funktioniert,
muss das Skript als Hintergrunddienst beim Boot laufen.

Einmalig einrichten:

```bash
cd /home/pi/mtb_telemetry
chmod +x scripts/start_button_logger.sh
sudo cp deploy/systemd/mtb-telemetry-button.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mtb-telemetry-button.service
```

Status pruefen:

```bash
sudo systemctl status mtb-telemetry-button.service
```

Live-Logs ansehen:

```bash
sudo journalctl -u mtb-telemetry-button.service -f
```

GPIO oder Zielrate anpassen:
- Datei: `deploy/systemd/mtb-telemetry-button.service`
- Fuer rastenden Schalter (Verriegelung):
	- `Environment=CONTROL_MODE=switch`
	- `Environment=CONTROL_GPIO=27`
- Fuer momentary Taster:
	- `Environment=CONTROL_MODE=button`
	- `Environment=CONTROL_GPIO=27`
- Fuer den Shutdown-Taster z. B.:
	- `Environment=SHUTDOWN_GPIO=22`
	- `Environment=SHUTDOWN_DEBOUNCE_MS=800`
- Fuer die Status-LED z. B.:
	- `Environment=STATUS_LED_GPIO=23`
	- `Environment=STATUS_LED_ACTIVE_LOW=0`
- z. B. auch `Environment=TARGET_HZ=80`
- danach neu laden/neustarten:

```bash
sudo systemctl daemon-reload
sudo systemctl restart mtb-telemetry-button.service
```

Damit der systemd-Service als User `pi` das Herunterfahren ohne Passwort ausloesen darf, einmalig sudoers-Regel anlegen:

```bash
echo 'pi ALL=(root) NOPASSWD: /usr/sbin/shutdown, /sbin/shutdown' | sudo tee /etc/sudoers.d/mtb-telemetry-shutdown
sudo chmod 440 /etc/sudoers.d/mtb-telemetry-shutdown
sudo visudo -cf /etc/sudoers.d/mtb-telemetry-shutdown
```

Hinweis zum eBay-Schalter 127910320644:
- Titel/Specs deuten auf "Verriegelung" (rastend, Ein/Aus) und 12 mm Metallschalter hin.
- Dafuer ist `CONTROL_MODE=switch` die richtige Wahl.
- Nur den Schaltkontakt an GPIO+GND verwenden.
- Falls eine LED im Schalter vorhanden ist: LED nicht direkt an GPIO 3.3V betreiben, sondern separat passend versorgen.

## 7) Hauptprogramm starten

```bash
/home/pi/mtb_telemetry/venv/bin/python src/main.py
```

## 8) Syntax-Check fuer ein einzelnes Skript

```bash
/home/pi/mtb_telemetry/venv/bin/python -m py_compile scripts/haltech_two_point_mm.py
```

## 9) Hilfreiche Kurzchecks

Pruefen, ob SPI-Devices vorhanden sind:

```bash
ls /dev/spidev*
```

Pruefen, ob Kalibrierdatei existiert:

```bash
ls calibration/haltech_ads1256_ad0.json
```

## 11) Sufni-CSV Export (mit RTC-Zeit)

Automatisch (Service/Logger):
- Bei Logging ON -> OFF wird der Sufni-Export automatisch gestartet.
- Pro Session-Datei `data/haltech_travel_*.csv` entstehen in `data/sufni/`:
	- `data/sufni/haltech_travel_*_sufni.csv`
	- `data/sufni/haltech_travel_*_sufni_meta.json`

Nach einer Session mit `--log` in das Sufni-Format exportieren:

```bash
/home/pi/mtb_telemetry/venv/bin/python scripts/export_sufni_csv.py \
	--input data/haltech_travel.csv \
	--output data/session_sufni.csv \
	--metadata data/session_sufni_meta.json
```

Ergebnis:
- `data/session_sufni.csv` im Sufni-Format `Time;Fork;Shock`
- `data/session_sufni_meta.json` mit `session_start_utc` aus dem ersten Log-Timestamp (UTC, RTC-basiert)

Fuer den Sufni-Import:
- CSV-Datei: `data/session_sufni.csv`
- Start time: Wert `session_start_utc` aus `data/session_sufni_meta.json`

## Hinweis

Wenn du in einer neuen Shell arbeitest, zuerst immer in den Projektordner wechseln und die Befehle mit dem Python aus dem venv ausfuehren.
