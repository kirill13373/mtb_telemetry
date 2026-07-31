# 500 Hz Messbericht (2026-07-31)

## Kontext
- Messung wurde im laufenden Service-Setup auf dem Pi durchgefuehrt.
- Ziel: 500 Hz Schleifenrate fuer die Telemetrie.
- Ausgewertete Datei: haltech_travel_20260731T091026Z.csv

## Ergebnisse
- samples_total: 3433
- duration_s: 7.101703
- effective_loop_hz: 483.264
- dt_ms_avg: 2.0693
- dt_ms_min: 1.9171
- dt_ms_p50: 2.0690
- dt_ms_p95: 2.0895
- dt_ms_p99: 2.1122
- dt_ms_max: 2.4359

## Bewertung gegen 500 Hz
- Sollwert: 500 Hz
- Istwert: 483.264 Hz
- Zielerreichung: ca. 96.7%
- Einordnung: Timing ist stabil (enge p95/p99 Streuung), aber die mittlere Rate liegt leicht unter dem Zielwert.

## Auffaelligkeiten
- Die Datei /home/pi/mtb_telemetry/data/last_run_metrics.json war nach der Messung nicht vorhanden.
- Dadurch fehlen die Standard-Kennzahlen loop_overruns und max_loop_elapsed_ms in einer separaten JSON-Ausgabe.

## Empfehlung fuer den naechsten Vergleichslauf
- Optionalen Vordergrund-Benchmark gemaess 500hz_next_steps.md ausfuehren, inklusive:
  - --session-metrics-json data/bench_500hz_metrics.json
- Danach diese Kennzahlen vergleichen:
  - effective_loop_hz
  - loop_overruns
  - max_loop_elapsed_ms
  - samples_total

## Kurzfazit
Die aktuelle Messung ist nahe am 500-Hz-Ziel, aber noch darunter. Fuer eine belastbare Performance-Bewertung sollte ein Lauf mit expliziter Metrics-JSON gespeichert werden.

## Update: Zweite Messung (Metrics-JSON aktiv)

Die zweite Messung wurde mit aktivem SESSION_METRICS_JSON erfasst. Die Datei
/home/pi/mtb_telemetry/data/last_run_metrics.json ist jetzt vorhanden und wurde ausgewertet.

### Service-Metriken (last_run_metrics.json)
- run_started_utc: 2026-07-31T09:15:13.027316Z
- run_ended_utc: 2026-07-31T09:15:53.304946Z
- report_reason: session_finalized
- target_hz: 500.0
- adc_samples: 1
- samples_total: 19471
- samples_logged: 4339
- duration_s: 40.277664
- effective_loop_hz: 483.419297
- loop_overruns: 1
- max_overrun_s: 0.000799
- max_loop_elapsed_s: 0.002799
- mean_loop_interval_s: 0.002069
- min_loop_interval_s: 0.002012
- max_loop_interval_s: 0.002804

### CSV-Plausibilisierung der aufgezeichneten Session
- Datei: haltech_travel_20260731T091544Z.csv
- rows: 4339
- duration_s: 8.976456
- effective_hz: 483.264
- dt_ms_avg: 2.0693
- dt_ms_min: 1.9610
- dt_ms_p95: 2.0871
- dt_ms_p99: 2.1106
- dt_ms_max: 2.5659

### Bewertung der zweiten Messung
- Zielerreichung bleibt bei ca. 96.7% bis 96.8% des 500-Hz-Sollwerts.
- Die Timing-Streuung ist weiterhin eng und damit stabil.
- Overruns sind praktisch nicht vorhanden (1 Ereignis im gesamten Lauf).

### Aktualisiertes Fazit
Metrics-JSON ist jetzt funktionsfaehig im Service-Betrieb. Die 500-Hz-Schleife laeuft stabil, aber weiterhin leicht unter Soll (typisch ~483 Hz).
