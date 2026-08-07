# Heim-WLAN mit automatischem Ride-Hotspot (NetworkManager)

## Zweck und Grenzen

Diese Anleitung richtet sich an Raspberry Pi OS Bookworm mit aktivem NetworkManager. Sie ergaenzt die bestehende Installation: Das bestehende Heim-WLAN-Profil, SSH, Samba, Docker und der Python Logger werden nicht ersetzt oder umkonfiguriert.

Beim Boot versucht der Dienst genau 30 Sekunden, das vorhandene NetworkManager-Heimprofil zu aktivieren. Gelingt das, bleibt `wlan0` vollstaendig bei NetworkManager. Schlaegt es fehl, trennt der Dienst NetworkManager nur fuer `wlan0` temporaer ab, startet `hostapd` und einen eigenen `dnsmasq` mit `192.168.10.1/24` und gibt `wlan0` beim Stop wieder an NetworkManager zurueck.

Der Hotspot bietet kein Internet-Uplink und leitet nichts weiter. Das ist beabsichtigt: Er ist ausschliesslich das lokale Ride-Netz. Alle Dienste, die auf allen lokalen IPv4-Adressen lauschen, bleiben damit erreichbar.

## Vorabpruefung

Diese Schritte zu Hause ausfuehren, waehrend eine zweite SSH-Sitzung offen bleibt. Sie pruefen zuerst die Netzwerkverwaltung und veraendern noch nichts:

```bash
systemctl is-active NetworkManager
nmcli -f DEVICE,TYPE,STATE,CONNECTION device status
nmcli -f NAME,UUID,TYPE connection show
nmcli -g GENERAL.CONNECTION device show wlan0
```

Die erste Ausgabe muss `active` sein. Notiere den exakten Namen der verbundenen WLAN-Verbindung aus der letzten Spalte, beispielsweise `MeinHeimnetz`. Ist NetworkManager nicht aktiv, diese Anleitung nicht anwenden; es waere eine getrennte, auf `dhcpcd` abgestimmte Umsetzung erforderlich.
FRITZ!Box 7590 VZ

Pruefe ausserdem, dass kein bestehender Hotspot aktiv ist:

```bash
systemctl is-active hostapd dnsmasq
```

Beide Dienste muessen `inactive` ausgeben. Andernfalls wird bewusst nicht installiert, damit keine bestehende Netzkonfiguration ueberschrieben wird.

## Installation

Zuerst das Projekt wie gewohnt vom Windows-PC deployen. Der vorhandene Deployment-Ablauf uebertraegt den Ordner `deploy/` bereits nach `/home/pi/mtb_telemetry/deploy/`; der Entwicklungsworkflow bleibt unveraendert.

Auf dem Pi einen neuen WPA2-Schluessel mit mindestens 8 Zeichen festlegen und den echten Profilnamen einsetzen. Das Passwort landet ausschliesslich in root-lesbaren Dateien auf dem Pi, nicht in Git und nicht in der Shell-Historie:

```bash
read -rp 'NetworkManager-Heimprofil: ' HOME_CONNECTION_NAME
read -rsp 'Neues Hotspot-Passwort: ' AP_PASSPHRASE; echo
sudo HOME_CONNECTION_NAME="$HOME_CONNECTION_NAME" AP_PASSPHRASE="$AP_PASSPHRASE" \
	bash /home/pi/mtb_telemetry/deploy/network/install-networkmanager-hotspot.sh
unset AP_PASSPHRASE
```

Der Installer bricht vor jeder Aenderung ab, wenn NetworkManager nicht aktiv ist, das Heimprofil nicht existiert oder bereits ein `hostapd`/`dnsmasq` laeuft. Er installiert nur die Standardpakete `hostapd` und `dnsmasq` und legt diese Dateien an:

| Ziel | Aufgabe |
| --- | --- |
| `/etc/mtb-wifi-mode.conf` | Lokaler Heimprofilname, Interface und 30-Sekunden-Timeout |
| `/etc/hostapd/mtb-telemetry.conf` | SSID `MTB-Telemetry` und WPA2-Passwort, Modus 600 |
| `/etc/dnsmasq.d/mtb-telemetry.conf` | DHCP `192.168.10.100` bis `192.168.10.200` |
| `/usr/local/sbin/mtb-wifi-mode` | Auswahl und sauberes Umschalten |
| `/etc/systemd/system/mtb-*.service` | Auswahl, Access Point und DHCP/DNS |

Der Source fuer die installierten Dateien liegt nachvollziehbar unter `deploy/network/` im Projekt. Die einzige bewusst lokale Konfiguration ist `/etc/mtb-wifi-mode.conf` sowie das Passwort in der hostapd-Datei.

## Aktivierung und Tests

Vor dem Reboot kontrollieren:

```bash
sudo systemctl status mtb-wifi-mode.service --no-pager
sudo systemctl cat mtb-wifi-mode.service mtb-hostapd.service mtb-dnsmasq.service
```

### Zuhause

Mit eingeschaltetem Heim-WLAN rebooten:

```bash
sudo reboot
```

Danach pruefen:

```bash
nmcli -g GENERAL.CONNECTION device show wlan0
ip -4 addr show wlan0
systemctl is-active ssh smbd mtb-wifi-mode
systemctl is-active mtb-hostapd mtb-dnsmasq
```

Die erste Ausgabe muss der konfigurierte Heimprofilname sein. `mtb-hostapd` und `mtb-dnsmasq` muessen `inactive` sein. VS Code Remote SSH und Samba bleiben unter der bisherigen Heimnetz-IP erreichbar.

Falls das Sufni Dashboard auf dem Pi betrieben wird, dessen bestehenden Container und Listener separat pruefen:

```bash
sudo docker ps
sudo ss -ltnp '( sport = :443 )'
```

Auf dem aktuell geprueften Pi sind weder Docker noch ein HTTPS-Listener auf Port 443 installiert. Das Dashboard kann deshalb dort zurzeit weder im Heimnetz noch ueber den Hotspot erreichbar sein; die WLAN-Konfiguration veraendert diesen Zustand nicht.

### Unterwegs

Das Heim-WLAN ausser Reichweite bringen und rebooten. Nach maximal 30 Sekunden erscheint `MTB-Telemetry`. Ein Telefon oder Laptop verbindet sich damit und muss eine Adresse zwischen `192.168.10.100` und `192.168.10.200` erhalten. Danach testen:

```bash
ssh pi@192.168.10.1
smbclient -L //192.168.10.1 -U pi
curl -kI https://192.168.10.1
```

Der letzte Test setzt voraus, dass das Dashboard bereits auf Port 443 und auf allen lokalen Adressen lauscht. Bei einem abweichenden Docker-Port diesen entsprechend einsetzen. Auf dem Pi zeigen diese Befehle den Zustand und die Ursache eines Fehlers:

```bash
ip -4 addr show wlan0
systemctl status mtb-wifi-mode mtb-hostapd mtb-dnsmasq --no-pager
journalctl -b -u mtb-wifi-mode -u mtb-hostapd -u mtb-dnsmasq --no-pager
```

## Rollback

Ein Rollback ist zu Hause oder per lokaler Konsole moeglich. Es entfernt nur die Dateien dieser Anleitung, nicht das Heimnetzprofil und keine Anwendungsdienste:

```bash
sudo systemctl disable --now mtb-wifi-mode.service
sudo systemctl stop mtb-hostapd.service mtb-dnsmasq.service
sudo rm -f /etc/systemd/system/mtb-wifi-mode.service
sudo rm -f /etc/systemd/system/mtb-hostapd.service
sudo rm -f /etc/systemd/system/mtb-dnsmasq.service
sudo rm -f /usr/local/sbin/mtb-wifi-mode
sudo rm -f /etc/mtb-wifi-mode.conf
sudo rm -f /etc/hostapd/mtb-telemetry.conf
sudo rm -f /etc/dnsmasq.d/mtb-telemetry.conf
sudo nmcli device set wlan0 managed yes
sudo systemctl daemon-reload
sudo reboot
```

Optional lassen sich danach die ungenutzten Standardpakete entfernen:

```bash
sudo apt purge -y hostapd dnsmasq
sudo apt autoremove -y
```

## Warum das stabil bleibt

NetworkManager bleibt alleiniger Verwalter des Heimnetzprofils. Der Access Point wird nur nach einem fehlgeschlagenen, zeitlich begrenzten Verbindungsversuch aktiviert und nur auf `wlan0` betrieben. Sein DHCP/DNS-Dienst ist an `192.168.10.1` gebunden und verwendet einen eigenen Dienstnamen; damit veraendert er weder Docker-Netze noch Samba, SSH, die Logger oder kabelgebundene Schnittstellen. Beim kontrollierten Stop und beim naechsten Boot wird `wlan0` wieder von NetworkManager verwaltet. Der Installer prueft Konflikte vor der Paketinstallation und schreibt keine bestehende NetworkManager- oder Samba-Konfiguration um.