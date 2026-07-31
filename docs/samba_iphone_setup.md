# Samba auf Raspberry Pi fuer iPhone (Schritt-fuer-Schritt)

## Ziel

Du willst Dateien vom Raspberry Pi auf dein iPhone kopieren.
Das geht am einfachsten ueber SMB (Samba) und die iPhone Dateien-App.

## Voraussetzungen

- Raspberry Pi und iPhone sind im selben WLAN.
- Du hast SSH-Zugriff auf den Pi.
- Auf dem Pi laeuft Raspberry Pi OS.

## 1) Pi aktualisieren und Samba installieren

Auf dem Pi ausfuehren:

```bash
sudo apt update
sudo apt install -y samba
```

Pruefen:

```bash
smbd --version
```

## 2) Freigabe-Ordner anlegen

Beispielordner fuer iPhone-Downloads:

```bash
mkdir -p /home/pi/iphone_share
```

Optional vorhandene Telemetrie-Dateien dort bereitstellen:

```bash
cp -r /home/pi/mtb_telemetry/data/* /home/pi/iphone_share/
```

## 3) Rechte setzen

```bash
sudo chown -R pi:pi /home/pi/iphone_share
chmod -R 755 /home/pi/iphone_share
```

## 4) Samba konfigurieren

Backup der Konfiguration:

```bash
sudo cp /etc/samba/smb.conf /etc/samba/smb.conf.bak
```

Datei bearbeiten:

```bash
sudo nano /etc/samba/smb.conf
```

Am Ende einfuegen:

```ini
[iPhoneShare]
   path = /home/pi/iphone_share
   browseable = yes
   read only = yes
   guest ok = no
   valid users = pi
   force user = pi
```

Hinweis:
- read only = yes bedeutet: iPhone kann nur lesen/kopieren.
- Wenn du auch vom iPhone auf den Pi schreiben willst, setze read only = no.

## 5) Samba-Benutzer/Passwort setzen

```bash
sudo smbpasswd -a pi
```

Du vergibst hier ein Samba-Passwort fuer den User pi.

## 6) Konfiguration pruefen und Dienste neu starten

```bash
testparm
sudo systemctl restart smbd
sudo systemctl enable smbd
sudo systemctl status smbd --no-pager
```

## 7) IP-Adresse des Pi herausfinden

```bash
hostname -I
```

Beispiel: 192.168.178.42

## 8) Mit dem iPhone verbinden

Auf dem iPhone:

1. Dateien-App oeffnen.
2. Oben rechts auf die drei Punkte tippen.
3. Mit Server verbinden waehlen.
4. Server eingeben: smb://192.168.178.42
5. Registrierter Benutzer waehlen.
6. Benutzername: pi
7. Passwort: das Samba-Passwort aus Schritt 5.

Danach erscheint die Freigabe iPhoneShare und du kannst Dateien auf das iPhone kopieren.

## 9) Optional: Verbindung ueber Hostname

Wenn Namensaufloesung funktioniert, kannst du statt IP nutzen:

smb://mtb-pi.local

Wenn das nicht klappt, nimm immer die IP-Adresse.

## 10) Fehlerbehebung

Keine Verbindung vom iPhone:

```bash
sudo systemctl status smbd --no-pager
sudo journalctl -u smbd -n 50 --no-pager
```

Login fehlgeschlagen:

- smbpasswd fuer pi erneut setzen:

```bash
sudo smbpasswd -a pi
```

Freigabe nicht sichtbar:

- smb.conf auf Tippfehler pruefen:

```bash
testparm
```

## 11) Sicherheit (empfohlen)

- Nur im Heimnetz verwenden.
- guest ok = no belassen.
- Starkes Samba-Passwort setzen.
- Wenn moeglich, nur benoetigte Ordner freigeben.

## 12) Dateiendungen fuer Telemetrie

Typisch zu kopieren:

- CSV aus /home/pi/mtb_telemetry/data
- Export-Dateien aus /home/pi/mtb_telemetry/data/sufni

Du kannst diese Dateien vor dem Kopieren in /home/pi/iphone_share sammeln oder direkt einen dieser Ordner freigeben.
