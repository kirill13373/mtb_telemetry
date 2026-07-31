# 500 Hz Naechste Schritte (Copy/Paste)

## 1) Auf Windows deployen

PowerShell:

cd C:\Users\muellerk\Documents\Telemetry\mtb-telemetry
.\tools\deploy.ps1

## 2) Auf dem Pi die neue Service-Datei installieren

sudo cp /home/pi/mtb_telemetry/deploy/systemd/mtb-telemetry-button.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart mtb-telemetry-button.service
sudo systemctl status mtb-telemetry-button.service --no-pager

## 3) Laufende Logs ansehen

sudo journalctl -u mtb-telemetry-button.service -f

## 4) 500-Hz-Messung ausloesen

- Bei CONTROL_MODE=button: Logging-Taster einmal druecken (Start), nochmal druecken (Stop)
- Bei CONTROL_MODE=switch: Schalter auf Logging ON stellen

## 5) Metriken auslesen

cat /home/pi/mtb_telemetry/data/last_run_metrics.json

## 6) Optional: Direkter Benchmark ohne Service (im Vordergrund)

cd /home/pi/mtb_telemetry
/home/pi/mtb_telemetry/venv/bin/python scripts/haltech_two_point_mm.py --button-gpio 27 --shutdown-button-gpio 22 --status-led-gpio 23 --target-hz 500 --adc-samples 1 --session-metrics-json data/bench_500hz_metrics.json

Danach:

cat /home/pi/mtb_telemetry/data/bench_500hz_metrics.json

## 7) Was bei 500 Hz wichtig ist

- effective_loop_hz moeglichst nahe 500
- loop_overruns moeglichst niedrig
- max_loop_elapsed_ms stabil
- samples_total passt zur Laufzeit (z. B. ca. 30000 in 60s)

## 8) Wenn die Service-Datei geaendert wurde

sudo cp /home/pi/mtb_telemetry/deploy/systemd/mtb-telemetry-button.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart mtb-telemetry-button.service
