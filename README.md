# 🎮 Arena Studio Connector

Verbinde **Arena AI mit deinem Roblox Studio**: Eine kleine Windows-App (EXE)
zeigt deine Roblox-Places an, startet eine lokale Bridge + Cloudflare-Tunnel
und kopiert per Button einen fertigen Prompt. Den schickst du an Arena AI –
Arena kann dann in deiner geöffneten Studio-Place arbeiten (Scripts lesen/
schreiben, Objekte erstellen, Eigenschaften ändern, Luau ausführen) und über
deine lokale Bridge sogar Creator-Dashboard-Aktionen anstoßen (GamePässe,
Developer-Produkte, Badges, DataStores …), **ohne dass dein Roblox-API-Key
deinen PC je verlässt.**

> Früher war das als `.bat` geplant (Prompt in die Zwischenablage kopieren).
> Die EXE ersetzt die `.bat` komplett: Places-Liste + „Prompt kopieren"-Button
> direkt daneben – so weiß Arena immer exakt, welche Place gemeint ist.

---

## 🚀 Schnellstart

### 1. EXE herunterladen (kein Python nötig)
GitHub → **Actions** → letzter Lauf von „Build Windows EXE" → Artifact
**ArenaStudioConnector-exe** herunterladen (enthält `ArenaStudioConnector.exe`).
Oder bei einem Release direkt die EXE laden.

> Selbst bauen stattdessen: Python 3.11+ installieren, dann `build_exe.bat`
> doppelklicken → EXE liegt in `dist\`.

### 2. (Optional, nur für Dashboard-Aktionen) Roblox API-Key eintragen
Für reines Arbeiten **in Studio** brauchst du **keinen** Key.
Nur wenn Arena z. B. GamePässe/Developer-Produkte erstellen soll:

1. `.env.example` als **`.env`** kopieren (liegt neben der EXE).
2. Das ausführliche Tutorial **in der `.env.example`** befolgen
   (Key auf <https://create.roblox.com/dashboard/credentials> erstellen,
   dort steht auch exakt, **welche Berechtigungen wofür** nötig sind).
3. Key in die `.env` eintragen. Die App liest ihn auch direkt aus dem
   Key-Feld in der GUI. Alternativ `config.example.json` → `config.json`
   für Username/Port.

⚠️ **Der Key ist wie ein Passwort.** Niemals an Arena schicken, niemals
öffentlich posten. `.env` und `config.json` stehen in `.gitignore`.

### 3. App benutzen
1. `ArenaStudioConnector.exe` starten.
2. Roblox-Username eintragen → **„Places laden"**.
3. **„Bridge + Tunnel starten"** → kurz warten, bis die Tunnel-URL erscheint
   (die App lädt `cloudflared` bei Bedarf selbst von GitHub herunter).
4. **„Studio-Plugin installieren"** → Roblox Studio neu starten, die
   gewünschte Place öffnen, im Plugin-Toolbar-Button **„ArenaBridge"**
   klicken und beim ersten Mal den Zugriff auf `127.0.0.1` erlauben.
5. In der App beim gewünschten Spiel auf **„📋 Prompt kopieren"** klicken.
6. Prompt bei **Arena AI einfügen**, danach einfach sagen, was Arena in
   Studio machen soll (z. B. „Baue ein Spawn-Gebäude" oder „Erstelle einen
   GamePass für 100 Robux").

Token & Tunnel-URL gelten nur, solange die App läuft. Zum Trennen einfach
die App schließen / „Stoppen" klicken.

---

## 🔁 So funktioniert es

```
Arena AI ──HTTPS──► Cloudflare Tunnel ──► Bridge (dein PC, 127.0.0.1:8765)
                                              │  ▲
                          Open Cloud (lokal,  │  │ pollt lokal
                          Key bleibt hier)    ▼  │
                                     Roblox Studio Plugin ──► deine Place
```

- **Bridge** (`arena_studio_connector.py`): token-geschützte HTTP-API.
- **Studio-Plugin** (`plugin/ArenaBridgePlugin.lua`): fragt die Bridge lokal
  nach Kommandos und führt sie in Studio aus. Spricht nie direkt mit dem
  Internet – nur mit `127.0.0.1`.
- **Prompt**: enthält Tunnel-URL, Bridge-Token, **PlaceId + UniverseId** und
  eine komplette Anleitung für Arena (Verbindungsprüfung, alle Kommandos mit
  Curl-Beispielen, Open-Cloud-Proxy, Sicherheitsregeln). Beispiel:
  `prompt_beispiel.txt`.

### Was Arena über die Bridge kann
| Endpunkt | Zweck |
|---|---|
| `GET /api/status` | Verbindung + geöffnete Place prüfen |
| `POST /api/command` | `place_info`, `list_children`, `get_tree`, `get_script`, `set_script`, `create_instance`, `set_property`, `delete_instance`, `execute_luau` |
| `POST /api/execute` | Beliebiges Luau im Studio ausführen |
| `POST /api/roblox/open-cloud` | Beliebiger Roblox-Open-Cloud-Call – Bridge hängt deinen Key **lokal** an |
| `POST /api/roblox/game-pass` / `/developer-product` | GamePass / Dev-Produkt anlegen (UniverseId, Name, Preis …) |
| `GET /api/docs` | Komplette API-Doku für Arena |

Alle Anfragen brauchen `Authorization: Bearer <Token>` aus dem Prompt.

### Ehrliche Einschränkung
Nicht jede Dashboard-Aktion gibt Roblox per API-Key frei. GamePässe und
Developer-Produkte funktionieren per Open Cloud nur, wenn der Key die
passenden Rechte hat (siehe Tutorial in `.env.example`). Sonst antwortet
Roblox mit 401/403 – die Bridge reicht die Meldung unverändert an Arena
weiter, damit Arena dir exakt sagen kann, welche Berechtigung fehlt, statt
so zu tun, als hätte es geklappt.

---

## 🗂️ Dateien

| Datei | Zweck |
|---|---|
| `arena_studio_connector.py` | Komplette App (GUI + Bridge + Tunnel + Prompt-Generator) |
| `plugin/ArenaBridgePlugin.lua` | Roblox-Studio-Plugin (wird von der App installiert) |
| `.env.example` | **Tutorial + Rechte-Liste für den Roblox API-Key** – als `.env` kopieren |
| `config.example.json` | Vorlage für `config.json` (Username, Port) |
| `prompt_beispiel.txt` | So sieht der kopierte Prompt aus |
| `build_exe.bat` + `ArenaStudioConnector.spec` | EXE lokal bauen |
| `.github/workflows/build-exe.yml` | EXE automatisch auf GitHub bauen (Actions/Release) |
| `tests/test_bridge.py` | Tests: Auth, Kommando-Roundtrip, Prompt-Inhalt |

## 🧪 Entwickeln / Testen
```powershell
python arena_studio_connector.py            # GUI starten
python arena_studio_connector.py --headless # nur Bridge+Tunnel (Konsole)
python -m unittest discover -s tests -v     # Tests
```
