# SSD1306 OLED Anschluss und Statusanzeige

## Hardwareanschluss (Raspberry Pi 4)

Das bestellte SSD1306 OLED (I2C) wird so angeschlossen:

| OLED Pin | Raspberry Pi Pin | BCM | Hinweis |
|---|---|---|---|
| VCC | Physisch 1 (3V3) | - | 3.3V Versorgung |
| GND | Physisch 6 (GND) | - | Masse |
| SDA | Physisch 3 | GPIO2 | I2C SDA1 |
| SCL | Physisch 5 | GPIO3 | I2C SCL1 |

## Warum diese Pins

- Das SST-Firmwareprojekt nutzt fuer SSD1306 standardmaessig I2C mit Adresse `0x3C`.
- In diesem Projekt sind folgende GPIOs bereits belegt und sollten fuer das OLED nicht benutzt werden:
  - ADS1256: GPIO17, GPIO18, GPIO22, GPIO27
  - Logging-/Shutdown-/LED: GPIO5, GPIO6, GPIO24

GPIO2/GPIO3 sind deshalb die konfliktfreie Standardwahl.

## Angezeigte Informationen (3 Zeilen)

Die Anzeige ist absichtlich kompakt und entspricht den Anforderungen:

1. Zeile 1: Uhrzeit + Status (`HH:MM:SS STATUS`)
2. Zeile 2: Dauer + Samples (`D:xxxx.xs S:nnnn`)
3. Zeile 3: Queue + Fehlerzaehler (`Q:a/b E:n`)

### Statuswerte

- `IDLE`: nicht am Aufzeichnen
- `REC`: aktive Session
- `ERR`: Writer-Fehler beim Schliessen
- `QFULL`: Queue-Ueberlauf erkannt, Session gestoppt

## Aktivierung im Service

Die OLED-Parameter sind ueber Umgebungsvariablen konfigurierbar:

- `OLED_ENABLE=1`
- `OLED_I2C_BUS=1`
- `OLED_I2C_ADDRESS=0x3C`
- `OLED_REFRESH_HZ=2.0`

Dateien:

- Service: `deploy/systemd/mtb-telemetry-button.service`
- Launcher: `scripts/start_button_logger.sh`

## Python-Abhaengigkeiten auf dem Pi

Fuer die Anzeige werden zusaetzlich benoetigt:

```bash
/home/pi/mtb_telemetry/venv/bin/pip install luma.oled pillow smbus2
```

Wenn die Abhaengigkeiten fehlen, startet der Logger trotzdem; das OLED wird dann deaktiviert und eine Meldung ausgegeben.

Schritte auf dem Pi, die nun ausgeführt werden müssen:

Display-Pakete installieren
/home/pi/mtb_telemetry/venv/bin/pip install luma.oled pillow smbus2

Deploy und Service neu laden
sudo systemctl daemon-reload
sudo systemctl restart mtb-telemetry-button.service

Logs prüfen
journalctl -u mtb-telemetry-button.service -n 100 --no-pager