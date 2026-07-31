# 500 Hz Naechste Schritte (Copy/Paste)

## 1) Auf Windows deployen

PowerShell:

cd C:\Users\muellerk\Documents\Telemetry\mtb-telemetry
.\tools\deploy.ps1

## 2) Service stoppen und GPIOs neu verdrahten

sudo systemctl stop mtb-telemetry-button.service

Danach den Raspberry Pi ausschalten und die GPIOs konfliktfrei verdrahten:

- Logging-Taster: BCM GPIO5 gegen GND
- Shutdown-Taster: BCM GPIO6 gegen GND
- Status-LED: BCM GPIO24 ueber 220 bis 470 Ohm gegen GND
- GPIO17, GPIO18, GPIO22, GPIO23 und GPIO27 sind fuer das Waveshare AD/DA HAT reserviert.

## 3) ADS1256 vor dem Service pruefen

cd /home/pi/mtb_telemetry
/home/pi/mtb_telemetry/venv/bin/python scripts/ads1256_quick_check.py

Erwartet werden `chip_id_nibble: 3 (0x3)` sowie ein AD0-Rohwert und eine Spannung.
Danach den Live-Test starten und das Potentiometer bewegen:

/home/pi/mtb_telemetry/venv/bin/python scripts/haltech_live_read.py

Erst fortfahren, wenn sich Rohwert und Spannung mit dem Potentiometer aendern.

## 4) Auf dem Pi die neue Service-Datei installieren

sudo cp /home/pi/mtb_telemetry/deploy/systemd/mtb-telemetry-button.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart mtb-telemetry-button.service
sudo systemctl status mtb-telemetry-button.service --no-pager

## 5) Laufende Logs ansehen

sudo journalctl -u mtb-telemetry-button.service -f

## 6) 500-Hz-Messung ausloesen

- Bei CONTROL_MODE=button: Logging-Taster einmal druecken (Start), nochmal druecken (Stop)
- Bei CONTROL_MODE=switch: Schalter auf Logging ON stellen

## 7) Metriken auslesen

cat /home/pi/mtb_telemetry/data/last_run_metrics.json

## 8) Optional: Direkter Benchmark ohne Service (im Vordergrund)

cd /home/pi/mtb_telemetry
/home/pi/mtb_telemetry/venv/bin/python scripts/haltech_two_point_mm.py --button-gpio 5 --shutdown-button-gpio 6 --status-led-gpio 24 --target-hz 500 --adc-samples 1 --session-metrics-json data/bench_500hz_metrics.json

Danach:

cat /home/pi/mtb_telemetry/data/bench_500hz_metrics.json

## 9) Was bei 500 Hz wichtig ist

- effective_loop_hz moeglichst nahe 500
- loop_overruns moeglichst niedrig
- max_loop_elapsed_ms stabil
- samples_total passt zur Laufzeit (z. B. ca. 30000 in 60s)

## 10) Wenn die Service-Datei geaendert wurde

sudo cp /home/pi/mtb_telemetry/deploy/systemd/mtb-telemetry-button.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart mtb-telemetry-button.service
