# Temporaere Kommandos

Diese Liste ist zum schnellen Kopieren gedacht.

## 1) Windows PowerShell: Projekt auf den Pi deployen

```powershell
cd C:\Users\muellerk\Documents\Telemetry\mtb-telemetry
.\tools\deploy.ps1
```

## 2) Auf dem Raspberry Pi: pruefen, ob Service-Datei vorhanden ist

```bash
ls -l /home/pi/mtb_telemetry/deploy/systemd/mtb-telemetry-button.service
```

## 3) Service-Datei installieren und Dienst neu laden

```bash
sudo cp /home/pi/mtb_telemetry/deploy/systemd/mtb-telemetry-button.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart mtb-telemetry-button.service
sudo systemctl status mtb-telemetry-button.service
```

## 4) Dienst dauerhaft aktivieren (falls noch nicht aktiviert)

```bash
sudo systemctl enable --now mtb-telemetry-button.service
```

## 5) Shutdown-Berechtigung fuer User pi setzen (einmalig)

```bash
echo 'pi ALL=(root) NOPASSWD: /usr/sbin/shutdown, /sbin/shutdown' | sudo tee /etc/sudoers.d/mtb-telemetry-shutdown
sudo chmod 440 /etc/sudoers.d/mtb-telemetry-shutdown
sudo visudo -cf /etc/sudoers.d/mtb-telemetry-shutdown
```

## 6) Service-Logs live ansehen

```bash
sudo journalctl -u mtb-telemetry-button.service -f
```

## 7) Optional: auf dem Pi schnell pruefen, welche GPIO-Settings aktiv sind

```bash
sudo systemctl cat mtb-telemetry-button.service
```

## 8) Optional: Service-Datei nach Aenderung neu kopieren und neu starten

```bash
sudo cp /home/pi/mtb_telemetry/deploy/systemd/mtb-telemetry-button.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart mtb-telemetry-button.service
```

## 9) Troubleshooting: Service startet nicht, Exit-Code 2 / "blob data"

Wenn im Journal bei Startskripten Fehler wie `status=2/INVALIDARGUMENT`, `line: invalid option name`
oder `[xxB blob data]` auftauchen, zuerst Zeilenenden im Shell-Skript pruefen und auf LF umstellen:

```bash
sed -n '1,5p' /home/pi/mtb_telemetry/scripts/start_button_logger.sh
sudo sed -i 's/\r$//' /home/pi/mtb_telemetry/scripts/start_button_logger.sh
sudo chmod +x /home/pi/mtb_telemetry/scripts/start_button_logger.sh
sudo systemctl restart mtb-telemetry-button.service
sudo journalctl -u mtb-telemetry-button.service -n 50 --no-pager -o cat
```
