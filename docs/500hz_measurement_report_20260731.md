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

## Update: Benchmark nach ADS-Aenderung

Durchgefuehrter Vergleichslauf (Service kurz gestoppt, 20s Benchmark im Vordergrund, danach Service wieder gestartet):
- Kommando-Basis: scripts/haltech_two_point_mm.py mit --log, --target-hz 500, --adc-samples 1, --quiet
- Metrics-Datei: /home/pi/mtb_telemetry/data/bench_500hz_metrics_after_ads.json

### Ergebnisse aus bench_500hz_metrics_after_ads.json
- run_started_utc: 2026-07-31T09:22:48.331057Z
- run_ended_utc: 2026-07-31T09:23:08.060679Z
- report_reason: run_ended
- samples_total: 9528
- samples_logged: 9528
- duration_s: 19.729646
- effective_loop_hz: 482.928065
- loop_overruns: 0
- max_overrun_s: 0.0
- max_loop_elapsed_s: 0.000778
- mean_loop_interval_s: 0.002071
- min_loop_interval_s: 0.002012
- max_loop_interval_s: 0.002117
- logging_mode: always_on

### Bewertung
- Effektive Rate bleibt in der gleichen Groessenordnung wie vorher (~483 Hz).
- In diesem Lauf wurden keine Overruns gemessen.
- Maximal gemessene Loop-Zeit ist niedrig und stabil (0.778 ms), damit bleibt das Timing robust.

### Kurzvergleich vorher vs. nach ADS-Aenderung
- Vorher (zweite Messung): effective_loop_hz 483.419297, loop_overruns 1
- Nach ADS-Aenderung (Benchmark): effective_loop_hz 482.928065, loop_overruns 0
- Einordnung: Kein Hinweis auf Regression bei der Schleifenstabilitaet; mittlere Frequenz bleibt praktisch unveraendert unterhalb des 500-Hz-Ziels.

## Phase B/F Fix: ADS1256-Treiber entlastet (2026-07-31)

### Ursache des 17-Hz-Defizits
Das feste `time.sleep(0.0012)` in `read_adc_raw` hat 1.2 ms pro Sample erzwungen.
Zusammen mit SPI-Overhead und Python-Laufzeit ergab das ~2.069 ms statt 2.000 ms.

### Umgesetzte Aenderungen in `src/mtb_telemetry/sensors/ads1256.py`
- `sleep(0.0012)` aus `read_adc_raw` entfernt. Timing uebernimmt ab sofort der aeussere Loop (`target_period_s`).
- ADC-Datenrate von 1000 SPS auf 2000 SPS erhoeht (neues Konstante `DRATE_2000_SPS = 0xB0`). Bei 2000 SPS liegt eine frische Wandlung alle 0.5 ms bereit, 4x schneller als die 2-ms-Leserate.

### Erwartetes Ergebnis nach Vergleichslauf
- effective_loop_hz soll nahe 500 liegen (Ziel: >= 497)
- mean_loop_interval_ms soll nahe 2.000 ms liegen
- loop_overruns sollen stabil niedrig bleiben (Referenz: 1 in 40s)

### Naechster Schritt
Deploy ausfuehren und einen neuen Benchmark-Lauf gemaess `500hz_next_steps.md` starten.
Vergleich: `effective_loop_hz` neu gegen den Referenzwert 483 Hz aus dieser Messung.

## Update: Analyse Benchmark nach ADS-Aenderung + neue Implementierung

### Diagnose: Warum der ADS-Fix keine Wirkung hatte
Die Messung zeigt: rate vorher 483.4 Hz, nachher 482.9 Hz. Kein Unterschied.

Das `sleep(0.0012)` in `read_adc_raw` war nicht der Engpass, weil es mit dem
aeusseren `time.sleep(remaining)` zusammen zu einem Gesamtsleep von ~1.22 ms fuehrte.
Die 0.071 ms Abweichung kommt vom Linux-Scheduler selbst:
- `max_loop_elapsed_s = 0.000778` → eigentliche Arbeit = 0.78 ms
- `target_period_s = 0.002000`
- `remaining = 0.002000 - 0.000778 = 0.001222` → sleep(1.222 ms)
- OS-Overshoot auf Pi: ~0.071 ms pro sleep() = 5.8% Verlust

### Implementierte Loesung: Deadline-Loop mit Hybrid-Sleep + Spinwait
Jeder `time.sleep()` ueberschiesst auf Linux leicht.
Die Loesung: schlafen fuer `(remaining - 0.8 ms)`, dann Spinwait fuer die letzten 0.8 ms.

Aenderungen in `scripts/haltech_two_point_mm.py`:
- Deadline-basierter Loop: `next_deadline += target_period_s` statt `sleep(remaining)`.
- Hybrid-Pacing: `sleep(deadline - now - 0.8 ms)` dann `while monotonic() < deadline: pass`.
- Per-Sample UTC-ISO-Stringerzeugung entfernt (Phase B): statt `datetime.now().isoformat()`
  wird `loop_started - acquisition_start_monotonic` als Offset in Sekunden gespeichert.
  Das spart ~15-30 µs pro Sample aus dem Hot Path.

Aenderungen in `scripts/export_sufni_csv.py`:
- Liest jetzt beide Zeitstempel-Formate: ISO-UTC (Legacy) und Dezimal-Offset (neu).
- Neues Argument `--session-start-utc` fuer UTC-Rekonstruktion aus `last_run_metrics.json`.
- Interner Export-Aufruf gibt `acquisition_start_utc` automatisch mit.

### Erwartetes Ergebnis nach naechstem Benchmark
- effective_loop_hz deutlich naeher 500 (Ziel: >= 497)
- mean_loop_interval_ms nahe 2.000 ms
- loop_overruns stabil niedrig

## Retest: Aktueller Stand nach neuer Aenderung (2026-07-31)

### Testaufbau
- Neuer Code deployt.
- Service kurz gestoppt.
- 20s Benchmark im Vordergrund ausgefuehrt:
  - `--log --target-hz 500 --adc-samples 1 --csv-flush-every 200 --quiet`
  - `--session-metrics-json /home/pi/mtb_telemetry/data/bench_500hz_metrics_after_ads_v2.json`
- Service danach wieder gestartet (Status: `active`).

### Ergebnis aus bench_500hz_metrics_after_ads_v2.json
- samples_total: 9859
- samples_logged: 9859
- duration_s: 19.717
- effective_loop_hz: 500.04
- loop_overruns: 0
- max_overrun_ms: 0.000
- max_loop_elapsed_ms: 0.712
- mean_loop_interval_ms: 2.000
- min_loop_interval_ms: 1.961
- max_loop_interval_ms: 2.039

### Bewertung
- Die neue Revision trifft das 500-Hz-Ziel im Benchmark praktisch exakt.
- Keine Overruns im Lauf.
- Loop-Zeiten sind eng und stabil.

### Neuer Befund (nicht blockierend fuer Rate, aber Fehler)
- Sufni-Export ist im Benchmark fehlgeschlagen mit:
  - `NameError: name '_clamp01' is not defined`
  - Quelle laut Traceback: `scripts/export_sufni_csv.py`
- Die Messung selbst und Metrics-JSON wurden trotzdem korrekt geschrieben.
