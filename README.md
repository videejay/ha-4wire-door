# 4-Wire Door – Home-Assistant-Integration (GBF MR263C4 / ControlCam)

Lokale Home-Assistant-Integration für die GBF-MR263C4-Türstation („ControlCam"):
Gerät über die HA-Oberfläche hinzufügen, Tür über einen **Unlock-Button mit
PIN-Abfrage** öffnen und den **RTSP-Livestream** direkt einbinden.

Reiner LAN-Weg (TCP:18600), keine Cloud. Die bestehende Bedienung über App und
Innenstationstaste bleibt unberührt.

## Was die Integration bietet

- **Config-Flow (UI):** Gerät hinzufügen mit **IP-Adresse, Benutzername, Passwort**
  (optional Name/Port). Die Zugangsdaten werden beim Anlegen per Login-Probe geprüft
  (nur Login, **keine** Türöffnung).
- **Lock-Entität mit PIN:** Beim Öffnen fragt HA die **Unlock-PIN** ab. Nur wenn sie
  stimmt, wird geöffnet. Die PIN wird lokal geprüft (lockout-sicher, wie die
  Original-App) und als `lockPwd` an das Gerät gesendet, das sie zusätzlich validiert.
  Der Türstatus wird bewusst **nicht** vorgetäuscht – die Entität bleibt „verriegelt"
  (es gibt keinen echten Statuskanal); das Öffnen ist eine momentane Aktion.
- **Kamera-Entität:** Bindet den RTSP-Livestream ein
  (`rtsp://<host>/tcp/av1_0`, über Optionen anpassbar).

## Funktionsweise der Türöffnung

Eine Auslösung öffnet eine eigene, kurzlebige Verbindung und macht:
1. **Login** (TLV 40+41, `streamMode=SUB`/`dataType=MIXED` – exakt der App-Pfad).
2. **Auf aktiven Video-Kanal warten** (mehrere echte I-Frames + kurze Setzzeit) –
   die Firmware triggert den Türöffner nur bei real laufendem Video (Doorbell-Logik).
3. **Lock senden** (TLV 425, `action=1`, `lockPwd` = eingegebene PIN), Antwort prüfen.
4. **Sauberer Teardown** (App-Paket `TalkRequest action=2`) + geordnetes Schließen –
   damit auch Folgeauslösungen zuverlässig funktionieren.

## Installation

### Variante A: HACS (als benutzerdefiniertes Repository)
1. HACS → Integrationen → ⋮ → „Benutzerdefiniertes Repository" → URL dieses Repos,
   Kategorie „Integration".
2. „4-Wire Door" installieren, **Home Assistant neu starten**.

### Variante B: manuell
1. Ordner `custom_components/fourwire_door/` in das HA-Config-Verzeichnis kopieren:
   `<config>/custom_components/fourwire_door/…`
2. Home Assistant neu starten.

### Danach: Gerät hinzufügen
Einstellungen → Geräte & Dienste → **Integration hinzufügen** → „4-Wire Door" →
IP-Adresse, Benutzername, Passwort eingeben.

Die Entitäten erscheinen unter dem neuen Gerät:
- `lock.<name>` – Tür öffnen (mit PIN-Abfrage),
- `camera.<name>_live` – RTSP-Livestream.

## Optionen (Einstellungen → Gerät → Konfigurieren)

| Option | Default | Zweck |
|---|---|---|
| PIN beim Öffnen abfragen | an | Bei „aus" öffnet der Button ohne PIN (nutzt das Passwort). |
| RTSP-Pfad | `/tcp/av1_0` | Stream-Pfad, falls abweichend. |
| Max. Wartezeit auf Videobild | 6 s | Wartezeit auf echte I-Frames vor dem Lock. |
| Nachlaufzeit vor Abbau | 2 s | Sitzung offen halten vor Teardown. |
| Kanal / Aktion / Öffnungsdauer | 1 / 1 / 1 | Nur bei Bedarf ändern (`action` = 1 = öffnen, verifiziert). |

## Netzwerk (Docker)

Der HA-Container muss die Türstation (`<host>:18600` und RTSP `:554`) erreichen.
Feste IP wird verwendet – keine Broadcast-/Multicast-Discovery nötig. Bei
`network_mode: host` meist problemlos; im Bridge-Modus muss das Routing ins
Kamera-Subnetz stehen.

## Sicherheit / Hinweise

- Das Geräte-Passwort entspricht hier der Tür-PIN (das Protokoll verschlüsselt sie
  nicht). HA speichert die Config-Daten in seiner internen Datenbank – Zugriff auf die
  HA-Instanz entsprechend absichern.
- **Keine Automatik:** Die Integration legt bewusst keine automatische Entriegelung an.
  Das Öffnen ist eine bewusste Benutzeraktion (Button + PIN).
- `action` auf `1` belassen (= öffnen, verifiziert). Andere Werte sind unerforscht.

## Alternative ohne Custom-Integration

Unter `shell_command_alternative/` liegt die frühere, einfachere Lösung per
`shell_command` + Skript (ohne UI-Config-Flow, ohne Kamera). Für die meisten
Nutzer ist die Integration oben die bessere Wahl.