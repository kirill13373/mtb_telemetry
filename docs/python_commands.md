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

## Hinweis

Wenn du in einer neuen Shell arbeitest, zuerst immer in den Projektordner wechseln und die Befehle mit dem Python aus dem venv ausfuehren.
