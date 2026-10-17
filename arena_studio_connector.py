#!/usr/bin/env python3
"""
Arena Studio Connector
======================
Lokale Windows-App (als .bat + ZIP verteilt - kein Build, keine EXE noetig),
  1. eine lokale Bridge (HTTP) startet,
  2. diese per Cloudflare-Tunnel (trycloudflare.com) öffentlich erreichbar macht,
  3. deine Roblox-Places auflistet und pro Place einen fertigen Prompt kopiert,
     den du an Arena AI schickst. Arena nutzt dann Tunnel-URL + Token, um über
     die Bridge mit dem Roblox-Studio-Plugin zu sprechen.

Der Roblox Open-Cloud API-Key bleibt IMMER nur lokal (.env / config.json)
und wird NIE in den Prompt kopiert. Arena kann ihn nur indirekt über
/api/roblox/open-cloud benutzen.

Start (unter Windows einfach ArenaStudioConnector.bat doppelklicken):
  python arena_studio_connector.py                # GUI
  python arena_studio_connector.py --headless     # nur Bridge + Tunnel
  python arena_studio_connector.py --check        # Systemcheck / Diagnose
  python arena_studio_connector.py --version
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

APP_NAME = "Arena Studio Connector"
APP_VERSION = "1.2.0"
DEFAULT_PORT = 8765
MIN_PYTHON = (3, 9)
GUI_FLAG = "gui_gestartet.tmp"      # Signal an den .bat-Starter: Fenster ist offen
START_LOG = "start_log.txt"         # Log des Starters (wird von der .bat geschrieben)
ERROR_LOG = "last_error.log"        # Log bei Abstürzen
TUNNEL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com", re.I)

# --------------------------------------------------------------------------- #
# Pfade / Konfiguration
# --------------------------------------------------------------------------- #

def app_dir() -> Path:
    """Ordner der App: neben dem Skript bzw. neben einer evtl. gebauten EXE.

    Dort liegen .env, config.json, cloudflared, last_error.log und der Ordner
    plugin/ - also immer dort, wo auch ArenaStudioConnector.bat liegt.
    Fuer Sonderfaelle (oder Tests) laesst sich der Ordner per Umgebungs-
    variable ARENA_APP_DIR umbiegen.
    """
    override = os.environ.get("ARENA_APP_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def is_writable(path: Path) -> bool:
    """Kann die App in diesem Ordner Dateien anlegen (config.json, .env, ...)?"""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".schreibtest"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except Exception:
        return False


def port_in_use(port: int) -> bool:
    """Ist der lokale Port schon belegt (z. B. von einer zweiten Kopie)?"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.8)
        if s.connect_ex(("127.0.0.1", port)) == 0:
            return True
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return True
    return False


def load_dotenv(path: Path) -> dict:
    values = {}
    if path.exists():
        for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def load_config() -> dict:
    base = app_dir()
    cfg = {}
    cfg_file = base / "config.json"
    if cfg_file.exists():
        try:
            cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
    env = load_dotenv(base / ".env")
    # Umgebungsvariablen haben Vorrang, dann .env, dann config.json
    cfg.setdefault("port", DEFAULT_PORT)
    cfg["roblox_api_key"] = (
        os.environ.get("ROBLOX_API_KEY")
        or env.get("ROBLOX_API_KEY")
        or cfg.get("roblox_api_key", "")
    )
    cfg["roblox_username"] = (
        os.environ.get("ROBLOX_USERNAME")
        or env.get("ROBLOX_USERNAME")
        or cfg.get("roblox_username", "")
    )
    return cfg


def save_config(cfg: dict) -> None:
    """Speichert die lokale config.json (ohne den Roblox API-Key!)."""
    safe = {k: v for k, v in cfg.items() if k != "roblox_api_key"}
    (app_dir() / "config.json").write_text(
        json.dumps(safe, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def ensure_bridge_token(cfg: dict) -> str:
    """Liefert den Bridge-Token und merkt ihn lokal.

    Warum nicht bei jedem Start neu? Weil das Studio-Plugin den Token fest
    eingebaut bekommt. Ein stabiler Token heisst: das Plugin wird EINMAL
    installiert und funktioniert danach bei jedem App-Start, ohne dass man
    wieder klicken muss. Der Token liegt nur in config.json (steht in
    .gitignore) und geht ausschliesslich an dein eigenes Studio-Plugin.
    Mit --new-token (bzw. ArenaStudioConnector.bat /newtoken) wird er ersetzt.
    """
    token = (cfg.get("bridge_token") or os.environ.get("BRIDGE_TOKEN") or "").strip()
    if not token:
        # Absicherung: falls hier ein unvollstaendiges cfg ankommt, trotzdem den
        # bereits gespeicherten Token nehmen - sonst wuerde das installierte
        # Studio-Plugin ploetzlich einen veralteten Token haben.
        token = (load_config().get("bridge_token") or "").strip()
    if token:
        cfg["bridge_token"] = token
        return token
    token = secrets.token_urlsafe(32)
    cfg["bridge_token"] = token
    try:
        save_config(cfg)
    except OSError as exc:
        print(f"[!] Token konnte nicht in config.json gespeichert werden ({exc})",
              file=sys.stderr)
    return token


# --------------------------------------------------------------------------- #
# Roblox Web / Open Cloud (Key bleibt lokal!)
# --------------------------------------------------------------------------- #

def http_json(method: str, url: str, body=None, headers=None, timeout=30):
    data = None
    hdrs = {"Content-Type": "application/json", "User-Agent": APP_NAME}
    if headers:
        hdrs.update(headers)
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            return resp.status, (json.loads(text) if text.strip() else {})
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(text) if text.strip() else {}
        except Exception:
            parsed = {"raw": text}
        return e.code, parsed
    except Exception as e:  # Netzwerkfehler etc.
        return 0, {"error": str(e)}


def resolve_user_id(username: str):
    status, data = http_json(
        "POST",
        "https://users.roblox.com/v1/usernames/users",
        {"usernames": [username], "excludeBannedUsers": False},
    )
    items = data.get("data") or []
    return items[0]["id"] if items else None


def fetch_user_places(user_id: int):
    """Öffentliche Liste der Experiences/Root-Places eines Users (kein Key nötig)."""
    places, cursor = [], ""
    while True:
        q = urllib.parse.urlencode(
            {"accessFilter": "All", "limit": 50, "sortOrder": "Asc",
             **({"cursor": cursor} if cursor else {})}
        )
        status, data = http_json("GET", f"https://games.roblox.com/v2/users/{user_id}/games?{q}")
        if status != 200:
            raise RuntimeError(f"Roblox Games-API: HTTP {status}: {data}")
        for g in data.get("data", []):
            root = g.get("rootPlace") or {}
            places.append({
                "name": g.get("name", "Unbenannt"),
                "description": g.get("description", ""),
                "universeId": g.get("id"),
                "placeId": root.get("id"),
                "placeName": root.get("name", ""),
                "playing": g.get("playing", 0),
                "visits": g.get("visits", 0),
            })
        cursor = data.get("nextPageCursor") or ""
        if not cursor:
            return places


def roblox_open_cloud(api_key: str, method: str, path: str, body=None):
    """Beliebigen Open-Cloud-Call ausführen – Key wird nur hier, lokal, angehängt."""
    if not api_key:
        return 400, {"error": "Kein ROBLOX_API_KEY lokal gesetzt (.env / config.json). Siehe .env.example"}
    if not path.startswith("/"):
        path = "/" + path
    if ".." in path or "://" in path:
        return 400, {"error": "Nur relative Open-Cloud-Pfade erlaubt, z. B. /cloud/v2/universes/123"}
    return http_json(method.upper(), f"https://apis.roblox.com{path}", body,
                     {"x-api-key": api_key})


# --------------------------------------------------------------------------- #
# Bridge-Server (Arena <-> Tunnel <-> Bridge <-> Studio-Plugin)
# --------------------------------------------------------------------------- #

class Bridge:
    def __init__(self, config: dict, token: str | None = None):
        self.config = config
        self.token = token or secrets.token_urlsafe(32)
        self.server: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None
        self.heartbeat: dict = {}
        self.pending: dict[str, dict] = {}
        self.queue: list[dict] = []
        self.lock = threading.Lock()

    # -- Kommando ans Plugin schicken und auf Antwort warten ---------------- #
    def send_command(self, cmd_type: str, args: dict, timeout: float = 60):
        cid = uuid.uuid4().hex
        event = threading.Event()
        with self.lock:
            self.pending[cid] = {"event": event, "result": None}
            self.queue.append({"id": cid, "type": cmd_type, "args": args or {}})
        if not event.wait(timeout):
            with self.lock:
                self.pending.pop(cid, None)
            return {"ok": False, "error": "Timeout: Studio-Plugin hat nicht geantwortet. "
                                          "Ist die Place in Studio geöffnet und das Plugin aktiv?"}
        with self.lock:
            item = self.pending.pop(cid, {})
        return item.get("result") or {"ok": False, "error": "Leere Antwort vom Plugin"}

    # -- HTTP-Handler -------------------------------------------------------- #
    def handler_class(self):
        bridge = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):  # ruhig stellen
                pass

            def _send(self, code, obj):
                raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _auth_ok(self):
                given = self.headers.get("Authorization", "")
                token = given[7:] if given.lower().startswith("bearer ") else \
                    self.headers.get("X-Bridge-Token", "")
                return secrets.compare_digest(token, bridge.token)

            def _body(self):
                length = int(self.headers.get("Content-Length") or 0)
                if not length:
                    return {}
                try:
                    return json.loads(self.rfile.read(length).decode("utf-8"))
                except Exception:
                    return {}

            def do_GET(self):
                path = urllib.parse.urlparse(self.path).path
                if path == "/":
                    return self._send(200, {"name": APP_NAME, "ok": True,
                                            "docs": "/api/docs"})
                if not self._auth_ok():
                    return self._send(401, {"ok": False, "error": "Ungültiger oder fehlender Token. "
                                            "Header: Authorization: Bearer <TOKEN>"})
                if path == "/api/status":
                    alive = bool(bridge.heartbeat) and \
                        time.time() - bridge.heartbeat.get("_ts", 0) < 15
                    return self._send(200, {"ok": True, "bridge": "online",
                                            "studio_connected": alive,
                                            "studio": bridge.heartbeat})
                if path == "/api/docs":
                    return self._send(200, {"ok": True, "endpoints": DOCS})
                if path == "/plugin/poll":
                    with bridge.lock:
                        cmd = bridge.queue.pop(0) if bridge.queue else None
                    return self._send(200, {"command": cmd})
                if path.startswith("/api/roblox/universe/"):
                    uid = path.rsplit("/", 1)[-1]
                    code, data = roblox_open_cloud(
                        bridge.config.get("roblox_api_key", ""), "GET",
                        f"/cloud/v2/universes/{uid}")
                    return self._send(code or 502, {"ok": 200 <= code < 300, "roblox": data})
                return self._send(404, {"ok": False, "error": "Nicht gefunden", "docs": "/api/docs"})

            def do_POST(self):
                path = urllib.parse.urlparse(self.path).path
                body = self._body()
                if not self._auth_ok():
                    return self._send(401, {"ok": False, "error": "Ungültiger oder fehlender Token."})
                if path == "/plugin/heartbeat":
                    bridge.heartbeat = {**body, "_ts": time.time()}
                    return self._send(200, {"ok": True})
                if path == "/plugin/result":
                    with bridge.lock:
                        item = bridge.pending.get(body.get("id", ""))
                        if item:
                            item["result"] = body
                            item["event"].set()
                    return self._send(200, {"ok": True})
                if path == "/api/command":
                    result = bridge.send_command(body.get("type", ""), body.get("args") or {},
                                                 float(body.get("timeout", 60)))
                    return self._send(200 if result.get("ok") else 502, result)
                if path == "/api/execute":
                    result = bridge.send_command("execute_luau",
                                                 {"code": body.get("code", "")},
                                                 float(body.get("timeout", 60)))
                    return self._send(200 if result.get("ok") else 502, result)
                if path == "/api/roblox/open-cloud":
                    code, data = roblox_open_cloud(
                        bridge.config.get("roblox_api_key", ""),
                        body.get("method", "GET"), body.get("path", ""), body.get("body"))
                    return self._send(code or 502, {"ok": 200 <= code < 300, "roblox": data})
                if path in ("/api/roblox/game-pass", "/api/roblox/developer-product"):
                    return self._roblox_create(body, path)
                return self._send(404, {"ok": False, "error": "Nicht gefunden", "docs": "/api/docs"})

            def _roblox_create(self, body, path):
                """GamePass / Dev-Product anlegen (Key bleibt lokal).

                Roblox ändert diese Creator-Endpunkte gelegentlich; die Antwort
                von Roblox wird unverändert durchgereicht, damit Arena sieht,
                ob es geklappt hat oder welche Rechte fehlen.
                """
                key = bridge.config.get("roblox_api_key", "")
                if not key:
                    return self._send(400, {"ok": False, "error":
                        "Kein ROBLOX_API_KEY lokal gesetzt. Trage ihn in .env ein (siehe .env.example)."})
                universe = body.get("universeId")
                if not universe:
                    return self._send(400, {"ok": False, "error": "universeId fehlt"})
                if "game-pass" in path:
                    url = f"https://apis.roblox.com/game-passes/v1/universes/{universe}/game-passes"
                else:
                    url = f"https://apis.roblox.com/developer-products/v1/universes/{universe}/developer-products"
                payload = {k: body[k] for k in
                           ("name", "description", "price") if k in body}
                code, data = http_json("POST", url, payload, {"x-api-key": key})
                return self._send(code or 502, {"ok": 200 <= code < 300, "roblox": data,
                                                "hinweis": "Falls Roblox 401/403 meldet: API-Key braucht "
                                                           "die passende Berechtigung (siehe .env.example) "
                                                           "oder Roblox erlaubt diese Aktion nur im Creator Dashboard."})

        return H

    def start(self, port: int):
        self.server = ThreadingHTTPServer(("127.0.0.1", port), self.handler_class())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None


DOCS = {
    "auth": "Jede Anfrage: Header 'Authorization: Bearer <TOKEN>'",
    "GET /api/status": "Prüft, ob Bridge + Studio-Plugin verbunden sind (studio_connected, Place-Infos).",
    "POST /api/command": {"body": {"type": "<Kommando>", "args": {}},
                          "typen": ["place_info", "list_children", "get_tree", "get_script",
                                    "set_script", "create_instance", "set_property",
                                    "delete_instance", "execute_luau"]},
    "POST /api/execute": {"body": {"code": "Luau-Code, läuft im Studio-Plugin-Kontext"}},
    "POST /api/roblox/open-cloud": "Führt einen Roblox-Open-Cloud-Call LOKAL aus (API-Key wird "
                                   "nie an Arena geschickt). body: {method, path, body} – "
                                   "damit z. B. GamePässe/Dev-Produkte/Badges/DataStores verwalten.",
    "POST /api/roblox/game-pass": "body: {universeId, name, description, price}",
    "POST /api/roblox/developer-product": "body: {universeId, name, description, price}",
    "GET /api/roblox/universe/<id>": "Universe-Infos über Open Cloud lesen.",
}


# --------------------------------------------------------------------------- #
# Prompt bauen
# --------------------------------------------------------------------------- #

def build_prompt(tunnel_url: str, token: str, place: dict | None = None,
                 local_url: str | None = None) -> str:
    """Baut den Text, der bei Arena AI eingefügt wird.

    Enthält Verbindungsdaten (Tunnel-URL + Token), die komplette Anleitung und
    am Ende einen klar markierten Platz für die eigentliche Aufgabe.
    """
    place = place or {}
    name = place.get("name") or place.get("placeName")
    pid, uid = place.get("placeId"), place.get("universeId")
    local_url = local_url or "http://127.0.0.1:8765"

    if pid:
        place_block = (f"- Place / Experience: {name}\n"
                       f"- PlaceId: {pid}\n"
                       f"- UniverseId (Experience-Id): {uid}")
        place_rule = f"- Arbeite ausschließlich an PlaceId {pid} / UniverseId {uid}."
        place_check = (f'   Erwartet: "studio_connected": true und studio.placeId == {pid}.\n'
                       f'   Wenn studio_connected false ist oder die PlaceId nicht übereinstimmt: STOPPE,\n'
                       f'   sag mir kurz Bescheid und ändere NICHTS.')
    else:
        place_block = ("- Welche Place offen ist, liest du aus /api/status (Feld studio.placeId /\n"
                       "  studio.name). Arbeite nur an dieser Place.")
        place_rule = "- Arbeite ausschließlich an der Place, die laut /api/status offen ist."
        place_check = ('   Erwartet: "studio_connected": true.\n'
                       '   Wenn studio_connected false ist: STOPPE, sag mir kurz Bescheid (ich muss\n'
                       '   die Place in Roblox Studio öffnen und im Plugin "Verbinden" klicken)\n'
                       '   und ändere NICHTS.')

    uid_text = uid if uid else "<UniverseId aus /api/status>"

    return f"""Verbinde dich mit meinem Roblox Studio über meine lokale Bridge und arbeite dort.

DIE PLACE:
{place_block}

VERBINDUNGSDATEN (streng vertraulich, nirgends posten oder loggen):
- Bridge-URL (Cloudflare Tunnel): {tunnel_url}
- Token: {token}
- (Lokal im Studio-Plugin eingetragen: {local_url} – das brauchst du nicht.)

MEINE AUFGABE – das sollst du in Studio machen:
- <HIER EINTRAGEN, was gemacht werden soll>
  Beispiele: "Baue ein Spawn-Gebäude mit 3 Etagen und Lichtern."
            "Erstelle einen GamePass 'VIP' für 100 Robux."
            "Lies das Script game.ServerScriptService.Main und erkläre es mir."
  Bis hier etwas steht: Frage mich zuerst, was ich machen möchte, und ändere nichts.

SO NUTZT DU DIE VERBINDUNG:
1. Prüfe zuerst die Verbindung:
   curl -s "{tunnel_url}/api/status" -H "Authorization: Bearer {token}"
{place_check}
2. Jede Anfrage braucht den Header: Authorization: Bearer {token}
3. In Studio etwas tun – Kommandos an das Studio-Plugin:
   curl -s -X POST "{tunnel_url}/api/command" \\
     -H "Authorization: Bearer {token}" -H "Content-Type: application/json" \\
     -d '{{"type":"list_children","args":{{"path":"game.Workspace"}}}}'
   Kommando-Typen: place_info, list_children {{path}}, get_tree {{path, depth}},
   get_script {{path}}, set_script {{path, source}}, create_instance
   {{className, parent, name, properties}}, set_property {{path, property, value}},
   delete_instance {{path}}, execute_luau {{code}}.
   Alternativ Luau direkt: POST {tunnel_url}/api/execute mit {{"code":"..."}}.
4. Creator-Dashboard-Aktionen (GamePässe, Developer-Produkte, Badges, DataStores,
   Universe-/Place-Einstellungen): Mein Roblox Open-Cloud API-Key liegt NUR lokal
   auf meinem PC – du bekommst ihn NIE. Rufe stattdessen auf:
   curl -s -X POST "{tunnel_url}/api/roblox/open-cloud" \\
     -H "Authorization: Bearer {token}" -H "Content-Type: application/json" \\
     -d '{{"method":"GET","path":"/cloud/v2/universes/{uid_text}","body":null}}'
   Die Bridge hängt meinen Key lokal an apis.roblox.com an. Komfort-Endpunkte:
   POST {tunnel_url}/api/roblox/game-pass        {{"universeId":{uid_text},"name":"...","description":"...","price":100}}
   POST {tunnel_url}/api/roblox/developer-product {{"universeId":{uid_text},"name":"...","description":"...","price":100}}
   Wenn Roblox 401/403 antwortet, sag mir exakt, welche Berechtigung fehlt –
   erfinde keine Daten und wiederhole die Aktion nicht endlos.
5. Volle Endpunkt-Doku: GET {tunnel_url}/api/docs (mit Token-Header).

REGELN:
{place_rule}
- Mache nur das, worum ich dich bitte; frage bei destruktiven Aktionen
  (Löschen, Überschreiben von Scripts) vorher kurz nach.
- Fasse am Ende kurz zusammen, was du geändert hast, inkl. der Plugin-Antworten.
- Der Token gilt nur, solange meine .bat läuft. Bei 401 ist die Verbindung
  abgelaufen – dann brauche ich einen neuen Prompt aus der .bat."""


# --------------------------------------------------------------------------- #
# Cloudflare-Tunnel
# --------------------------------------------------------------------------- #

class Tunnel:
    def __init__(self):
        self.proc: subprocess.Popen | None = None
        self.url: str | None = None

    @staticmethod
    def cloudflared_path() -> str | None:
        local = app_dir() / ("cloudflared.exe" if os.name == "nt" else "cloudflared")
        if local.exists():
            return str(local)
        return shutil.which("cloudflared")

    @staticmethod
    def download_cloudflared(dest: Path) -> Path:
        url = ("https://github.com/cloudflare/cloudflared/releases/latest/download/"
               + ("cloudflared-windows-amd64.exe" if os.name == "nt"
                  else "cloudflared-linux-amd64"))
        urllib.request.urlretrieve(url, dest)
        return dest

    def start(self, port: int, on_url, on_error=None):
        """Startet den Tunnel. on_url(url) bei Erfolg, on_error(text) bei Problemen."""
        def fail(msg: str) -> None:
            if on_error:
                on_error(msg)
            else:
                print(f"[!] Tunnel: {msg}", flush=True)

        try:
            exe = self.cloudflared_path()
            if not exe:
                fail("cloudflared fehlt - lade es einmalig von GitHub herunter ...")
                dest = app_dir() / ("cloudflared.exe" if os.name == "nt" else "cloudflared")
                exe = str(self.download_cloudflared(dest))
        except Exception as exc:
            fail(f"cloudflared konnte nicht geladen werden ({exc}). "
                 f"Ohne Tunnel ist die Bridge nur lokal erreichbar.")
            return

        try:
            self.proc = subprocess.Popen(
                [exe, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                bufsize=1, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception as exc:
            fail(f"cloudflared konnte nicht gestartet werden ({exc}).")
            return

        def reader():
            assert self.proc and self.proc.stdout
            for line in self.proc.stdout:
                m = TUNNEL_RE.search(line)
                if m and "api.trycloudflare" not in m.group(0):
                    self.url = m.group(0)
                    on_url(self.url)
                    return
            fail("Der Tunnel wurde beendet, bevor eine URL erschien "
                 "(keine Internetverbindung? Firewall/Virenschutz?).")

        threading.Thread(target=reader, daemon=True).start()

    def stop(self):
        if self.proc:
            self.proc.terminate()
            self.proc = None
            self.url = None


# --------------------------------------------------------------------------- #
# Studio-Plugin erzeugen / installieren
# --------------------------------------------------------------------------- #

PLUGIN_TEMPLATE = Path(__file__).with_name("plugin") / "ArenaBridgePlugin.lua"
PLUGIN_NAME = "ArenaBridgePlugin.lua"


def plugin_template_path() -> Path | None:
    """Findet plugin/ArenaBridgePlugin.lua - auch bei verschobenem Skript oder EXE."""
    candidates = [
        PLUGIN_TEMPLATE,                                            # neben dem Skript
        app_dir() / "plugin" / PLUGIN_NAME,                         # im App-Ordner
        Path.cwd() / "plugin" / PLUGIN_NAME,                        # aktuelles Verzeichnis
        Path(getattr(sys, "_MEIPASS", app_dir())) / "plugin" / PLUGIN_NAME,  # EXE-Build
    ]
    for cand in candidates:
        if cand.exists():
            return cand
    return None


def plugin_source(bridge_url_local: str, token: str) -> str:
    path = plugin_template_path()
    if not path:
        return ""
    src = path.read_text(encoding="utf-8")
    return src.replace("__BRIDGE_URL__", bridge_url_local).replace("__BRIDGE_TOKEN__", token)


def plugins_folders() -> list[Path]:
    """Alle Ordner, in denen Roblox Studio nach Plugins sucht.

    Standard unter Windows ist %LOCALAPPDATA%\\Roblox\\Plugins. Ist Studio aus
    dem Microsoft Store installiert, liegen die Daten im Paketordner - der wird
    zusaetzlich mitgenommen, wenn er existiert. Mit ARENA_PLUGIN_DIR laesst
    sich alles auf einen eigenen Ordner umbiegen.
    """
    override = os.environ.get("ARENA_PLUGIN_DIR")
    if override:
        return [Path(override).expanduser()]
    if os.name == "nt":
        local = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
        folders = [local / "Roblox" / "Plugins"]
        packages = local / "Packages"
        if packages.is_dir():
            for pkg in sorted(packages.glob("ROBLOXCORPORATION.ROBLOXSTUDIO*")):
                folders.append(pkg / "LocalState" / "Plugins")
        return folders
    return [Path.home() / "Documents" / "Roblox" / "Plugins"]


def plugins_folder() -> Path:
    """Haupt-Plugin-Ordner (das ist der, den Studio unter Windows benutzt)."""
    return plugins_folders()[0]


def install_plugin(port: int, token: str, folders=None) -> list[tuple[Path, str]]:
    """Installiert/aktualisiert das Studio-Plugin in den Plugin-Ordner(n).

    Rueckgabe: Liste aus (Ordner, Status). Status ist "installiert", "aktuell"
    oder eine Fehlermeldung - damit kann die App genau sagen, was passiert ist.
    """
    src = plugin_source(f"http://127.0.0.1:{port}", token)
    if not src:
        return [(app_dir() / "plugin", f"{PLUGIN_NAME} fehlt - ZIP nicht komplett entpackt?")]

    results: list[tuple[Path, str]] = []
    for folder in (folders or plugins_folders()):
        dest = folder / PLUGIN_NAME
        try:
            folder.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                if dest.read_text(encoding="utf-8", errors="replace") == src:
                    results.append((folder, "aktuell"))
                    continue
            dest.write_text(src, encoding="utf-8")
            results.append((folder, "installiert"))
        except OSError as exc:
            results.append((folder, f"nicht moeglich: {exc}"))
    return results


def plugin_status(port: int, token: str) -> tuple[bool, str]:
    """Prueft, ob das Plugin installiert und auf dem aktuellen Stand ist."""
    folder = plugins_folder()
    dest = folder / PLUGIN_NAME
    if not dest.exists():
        return False, f"nicht installiert ({dest})"
    src = plugin_source(f"http://127.0.0.1:{port}", token)
    if src and dest.read_text(encoding="utf-8", errors="replace") != src:
        return False, f"veraltet - bitte App neu starten ({dest})"
    return True, str(dest)


# --------------------------------------------------------------------------- #
# Zwischenablage (ohne Zusatzpakete)
# --------------------------------------------------------------------------- #

PROMPT_FILE = "prompt.txt"


def copy_to_clipboard(text: str) -> tuple[bool, str]:
    """Kopiert Text in die Zwischenablage. Liefert (ok, Werkzeugname).

    Windows: PowerShell "Set-Clipboard" über eine temporäre UTF-8-Datei
    (zuverlässig auch bei Umlauten/mehreren Zeilen), sonst clip.exe.
    Linux (nur zum Testen): wl-copy / xclip / xsel, falls vorhanden.
    """
    if os.name == "nt":
        tmp = None
        try:
            tmp = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False,
                                              encoding="utf-8-sig", newline="\r\n")
            tmp.write(text)
            tmp.close()
            path = repr(tmp.name).replace("'", "''")
            # Setzen und direkt pruefen: so meldet die App keinen Erfolg,
            # wenn die Zwischenablage den Text nicht aufgenommen hat.
            cmd = ("$t = Get-Content -LiteralPath " + path + " -Raw -Encoding UTF8; "
                   "Set-Clipboard -Value $t; "
                   "$c = Get-Clipboard -Raw; "
                   "if ($null -eq $c) { exit 1 }; "
                   "if (($c -replace \"`r`n\", \"`n\") -ne ($t -replace \"`r`n\", \"`n\")) { exit 1 }")
            result = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd],
                capture_output=True, text=True, timeout=30,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if result.returncode == 0:
                return True, "PowerShell Set-Clipboard"
        except Exception:
            pass
        finally:
            if tmp:
                try:
                    os.unlink(tmp.name)
                except OSError:
                    pass
        try:  # Fallback: clip.exe (Konsolen-Codepage, kann Umlaute verlieren)
            subprocess.run(["clip"], input=text, text=True, timeout=15, check=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return True, "clip.exe"
        except Exception as exc:
            return False, str(exc)

    for tool in (["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "-b", "-i"]):
        if shutil.which(tool[0]):
            try:
                subprocess.run(tool, input=text, text=True, timeout=5, check=True)
                return True, tool[0]
            except Exception:
                continue
    return False, "kein Zwischenablage-Werkzeug gefunden"


def save_prompt(prompt: str) -> Path:
    """Legt den Prompt als prompt.txt neben die .bat (zum späteren Kopieren)."""
    path = app_dir() / PROMPT_FILE
    path.write_text(prompt, encoding="utf-8")
    return path


def print_prompt(prompt: str) -> None:
    print("=" * 78)
    print(" PROMPT FÜR ARENA AI  (wird gleich in die Zwischenablage kopiert)")
    print("=" * 78)
    print(prompt)
    print("=" * 78)


def publish_prompt(tunnel_url: str, token: str, port: int, place=None,
                   copy: bool = True) -> Path:
    """Baut den Prompt, speichert ihn und kopiert ihn in die Zwischenablage."""
    local_url = f"http://127.0.0.1:{port}"
    prompt = build_prompt(tunnel_url, token, place, local_url)
    path = save_prompt(prompt)
    copied, tool = copy_to_clipboard(prompt) if copy else (False, "übersprungen")
    print()
    if copied:
        print(f"[OK] Prompt liegt in der Zwischenablage ({tool}).")
    else:
        print(f"[!] Konnte nicht automatisch kopieren ({tool}).")
        print(f"    Prompt-Datei öffnen und den Text von Hand kopieren: {path}")
    print(f"[i] Prompt zusätzlich gespeichert in: {path}")
    return path


def print_connection_box(tunnel_url: str, token: str, port: int) -> None:
    local_url = f"http://127.0.0.1:{port}"
    line = "=" * 78
    thin = "-" * 78
    print(line)
    print(" VERBINDUNGSDATEN")
    print(thin)
    print(f" Tunnel-URL  (fuer Arena AI)   : {tunnel_url}")
    print(f" Token       (Arena + Plugin)  : {token}")
    print(f" Lokale URL  (Studio-Plugin)   : {local_url}")
    print(thin)
    print(" SO GEHT'S")
    print(f"  1. Roblox Studio -> Plugins-Tab -> ArenaBridge")
    print(f"       Bridge-URL = {local_url}")
    print(f"       Token      = {token}")
    print(f"     -> \"Verbinden\" klicken (wird fuer das naechste Mal gespeichert)")
    print("  2. Prompt aus der Zwischenablage bei Arena AI einfuegen und darunter")
    print("     schreiben, was gemacht werden soll")
    print("  3. Fenster offen lassen! Mit Strg+C beendet man Bridge + Tunnel")
    print(line)


# --------------------------------------------------------------------------- #
# GUI
# --------------------------------------------------------------------------- #

def gui_flag_path() -> Path:
    """Datei, die der .bat-Starter abwartet (Beweis: Fenster ist wirklich offen)."""
    return app_dir() / GUI_FLAG


def clear_stale_logs() -> None:
    """Alte Fehler-/Signaldateien wegräumen, damit die .bat eindeutig erkennt,
    ob DIESER Start geklappt hat oder abgestürzt ist."""
    for name in (ERROR_LOG,):
        try:
            (app_dir() / name).unlink()
        except OSError:
            pass


def run_gui():
    import tkinter as tk
    from tkinter import messagebox, ttk

    cfg = load_config()
    clear_stale_logs()
    bridge = Bridge(cfg, token=ensure_bridge_token(cfg))
    tunnel = Tunnel()
    state = {"places": [], "running": False}

    root = tk.Tk()
    root.title(f"{APP_NAME} {APP_VERSION}")
    root.geometry("860x640")
    root.minsize(760, 560)

    top = ttk.Frame(root, padding=10)
    top.pack(fill="x")
    ttk.Label(top, text=f"Arena Studio Connector {APP_VERSION}",
              font=("Segoe UI", 16, "bold")).pack(anchor="w")
    ttk.Label(top, text="1) Username eintragen → Places laden   2) Bridge + Tunnel starten   "
                        "3) Studio öffnen (Plugin wird automatisch installiert)   4) Beim Place auf "
                        "„Prompt kopieren“ klicken → an Arena AI schicken",
              wraplength=820).pack(anchor="w", pady=(2, 6))

    form = ttk.Frame(root, padding=(10, 0))
    form.pack(fill="x")
    ttk.Label(form, text="Roblox-Username:").grid(row=0, column=0, sticky="w")
    user_var = tk.StringVar(value=cfg.get("roblox_username", ""))
    ttk.Entry(form, textvariable=user_var, width=28).grid(row=0, column=1, padx=6, sticky="w")
    ttk.Label(form, text="Roblox API-Key (optional, nur lokal in .env):").grid(row=1, column=0, sticky="w", pady=4)
    key_var = tk.StringVar(value="••••••••" if cfg.get("roblox_api_key") else "")
    ttk.Entry(form, textvariable=key_var, width=28, show="•").grid(row=1, column=1, padx=6, sticky="w")
    ttk.Label(form, text="Anleitung + benötigte Rechte: .env.example im App-Ordner",
              foreground="#666").grid(row=1, column=2, sticky="w")

    status_var = tk.StringVar(value="Bridge: gestoppt")
    tunnel_var = tk.StringVar(value="Tunnel: –")
    plugin_var = tk.StringVar(value="Studio-Plugin: wird automatisch installiert …")

    list_frame = ttk.Frame(root, padding=10)
    list_frame.pack(fill="both", expand=True)
    ttk.Label(list_frame, text="Deine Places / Experiences:", font=("Segoe UI", 11, "bold")).pack(anchor="w")
    canvas = tk.Canvas(list_frame, highlightthickness=0)
    scroll = ttk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
    inner = ttk.Frame(canvas)
    inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.create_window((0, 0), window=inner, anchor="nw")
    canvas.configure(yscrollcommand=scroll.set)
    canvas.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")

    def render_places():
        for w in inner.winfo_children():
            w.destroy()
        if not state["places"]:
            ttk.Label(inner, text="Noch keine Places geladen – Username eintragen und „Places laden“ klicken.").pack(anchor="w", pady=8)
        for p in state["places"]:
            row = ttk.Frame(inner, padding=(4, 6))
            row.pack(fill="x")
            ttk.Label(row, text=f"🎮 {p['name']}", font=("Segoe UI", 10, "bold"), width=44).pack(side="left")
            ttk.Label(row, text=f"PlaceId: {p['placeId']}   UniverseId: {p['universeId']}   ▶ {p.get('playing',0)}   Besuche: {p.get('visits',0)}",
                      foreground="#555").pack(side="left")
            ttk.Button(row, text="📋 Prompt kopieren",
                       command=lambda place=p: copy_prompt(place)).pack(side="right")

    def copy_prompt(place):
        if not tunnel.url:
            messagebox.showwarning(APP_NAME, "Bitte zuerst „Bridge + Tunnel starten“ klicken "
                                             "und warten, bis die Tunnel-URL erscheint.")
            return
        prompt = build_prompt(tunnel.url, bridge.token, place)
        root.clipboard_clear()
        root.clipboard_append(prompt)
        status_var.set(f"✅ Prompt für „{place['name']}“ kopiert – jetzt bei Arena AI einfügen!")

    def load_places():
        username = user_var.get().strip()
        if not username:
            messagebox.showwarning(APP_NAME, "Bitte Roblox-Username eintragen.")
            return
        status_var.set("Lade Places …")
        def work():
            try:
                uid = resolve_user_id(username)
                if not uid:
                    raise RuntimeError("Username nicht gefunden.")
                places = fetch_user_places(uid)
                cfg["roblox_username"] = username
                save_config(cfg)
                root.after(0, lambda: (state.update(places=places), render_places(),
                                       status_var.set(f"{len(places)} Places geladen.")))
            except Exception as e:
                root.after(0, lambda: messagebox.showerror(APP_NAME, str(e)))
        threading.Thread(target=work, daemon=True).start()

    def toggle_bridge():
        if state["running"]:
            tunnel.stop(); bridge.stop(); state["running"] = False
            status_var.set("Bridge: gestoppt"); tunnel_var.set("Tunnel: –")
            btn_bridge.config(text="▶ Bridge + Tunnel starten")
            return
        # API-Key ggf. aus dem Feld in die lokale .env übernehmen
        entered = key_var.get().strip()
        if entered and entered != "••••••••":
            cfg["roblox_api_key"] = entered
            env_path = app_dir() / ".env"
            env_path.write_text(f"ROBLOX_API_KEY={entered}\nROBLOX_USERNAME={user_var.get().strip()}\n",
                                encoding="utf-8")
        bridge.config = cfg
        port = int(cfg.get("port", DEFAULT_PORT))
        if port_in_use(port):
            messagebox.showwarning(APP_NAME, f"Port {port} ist schon belegt.\n\n"
                                   "Läuft die App vielleicht schon in einem anderen Fenster? "
                                   "Dann dieses Fenster schließen – pro PC genügt eine Instanz.\n\n"
                                   f"Sonst bitte in der Datei config.json einen anderen Port "
                                   f"eintragen (z. B. {port + 1}).")
            return
        try:
            bridge.start(port)
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Bridge konnte nicht starten: {exc}")
            return
        status_var.set(f"Bridge läuft lokal auf http://127.0.0.1:{port} – starte Cloudflare-Tunnel …")
        tunnel.start(
            port,
            lambda url: root.after(0, lambda: (
                tunnel_var.set(f"Tunnel: {url}"),
                status_var.set("✅ Bereit! Jetzt Place in Studio öffnen und „Prompt kopieren“ klicken."))),
            lambda err: root.after(0, lambda err=err: (
                tunnel_var.set("Tunnel: – (Fehler)"),
                status_var.set(f"⚠️ {err}"))))
        state["running"] = True
        btn_bridge.config(text="⏹ Stoppen")

    def auto_install_plugin(show_dialog: bool = False) -> None:
        """Installiert/aktualisiert das Studio-Plugin in den Plugin-Ordner."""
        port = int(cfg.get("port", DEFAULT_PORT))
        results = install_plugin(port, bridge.token)
        lines = []
        ok_any = False
        for folder, status in results:
            mark = "✅" if status in ("installiert", "aktuell") else "⚠️"
            ok_any = ok_any or status in ("installiert", "aktuell")
            lines.append(f"{mark} {folder}\n     → {status}")
        report = "\n".join(lines)
        if show_dialog:
            if ok_any:
                messagebox.showinfo(APP_NAME,
                                    "Studio-Plugin:\n\n" + report +
                                    "\n\nRoblox Studio neu starten, die gewünschte Place öffnen und "
                                    "beim ersten Mal den Zugriff auf 127.0.0.1 erlauben "
                                    "(Plugin-Berechtigungen).")
            else:
                messagebox.showerror(APP_NAME,
                                     "Das Plugin konnte nicht installiert werden:\n\n" + report)
        return ok_any

    def install_plugin_clicked():
        auto_install_plugin(show_dialog=True)

    def auto_install_async():
        """Beim Start automatisch - ohne Klick, ohne Dialog, ohne Warten."""
        def work():
            try:
                results = install_plugin(int(cfg.get("port", DEFAULT_PORT)), bridge.token)
                summary = ", ".join(f"{status}" for _, status in results) or "unbekannt"
                first = results[0][0] if results else plugins_folder()
                root.after(0, lambda: plugin_var.set(
                    f"Studio-Plugin: {summary} ({first})"))
            except Exception as exc:  # darf den Start nie verhindern
                root.after(0, lambda exc=exc: plugin_var.set(
                    f"Studio-Plugin: nicht automatisch installiert ({exc}) – "
                    f"Button „Plugin (neu) installieren“ nutzen"))
        threading.Thread(target=work, daemon=True).start()

    bar = ttk.Frame(root, padding=10)
    bar.pack(fill="x")
    ttk.Button(bar, text="Places laden", command=load_places).pack(side="left")
    btn_bridge = ttk.Button(bar, text="▶ Bridge + Tunnel starten", command=toggle_bridge)
    btn_bridge.pack(side="left", padx=8)
    ttk.Button(bar, text="Plugin (neu) installieren",
               command=install_plugin_clicked).pack(side="left")
    ttk.Button(bar, text="App-Ordner öffnen",
               command=lambda: os.startfile(app_dir()) if os.name == "nt" else subprocess.Popen(["xdg-open", str(app_dir())])).pack(side="left", padx=8)

    ttk.Label(root, textvariable=status_var, padding=(10, 2)).pack(fill="x")
    ttk.Label(root, textvariable=tunnel_var, padding=(10, 0)).pack(fill="x")
    ttk.Label(root, textvariable=plugin_var, padding=(10, 0), foreground="#1a6").pack(fill="x")
    ttk.Label(root, text="⚠️ Token & Tunnel-URL nur an Arena AI geben, nirgends öffentlich posten. "
                         "Der Roblox API-Key bleibt immer nur lokal auf diesem PC.",
              foreground="#a33", padding=(10, 4)).pack(fill="x")

    render_places()
    auto_install_async()          # Plugin kommt ohne Klick in den Plugin-Ordner

    # Signal für den .bat-Starter: Ab hier laeuft die GUI wirklich.
    try:
        gui_flag_path().write_text(str(os.getpid()), encoding="utf-8")
    except OSError:
        pass
    try:
        root.mainloop()
    finally:
        try:
            gui_flag_path().unlink()
        except OSError:
            pass


def main() -> int:
    args = [a.lower() for a in sys.argv[1:]]

    if any(a in ("-h", "--help", "/?", "/help") for a in args):
        print(__doc__ or "")
        print(f"Version {APP_VERSION}  -  {APP_NAME}")
        return 0

    if any(a in ("--version", "/version", "-v") for a in args):
        print(f"{APP_NAME} {APP_VERSION}  (Python {sys.version.split()[0]})")
        return 0

    if any(a in ("--check", "/check") for a in args):
        return run_check()

    if any(a in ("--install-plugin", "/install-plugin", "--installplugin") for a in args):
        return run_install_plugin()

    if any(a in ("--new-token", "/new-token", "--newtoken") for a in args):
        return run_install_plugin(rotate=True)

    if any(a in ("--gui", "/gui", "--app") for a in args):
        try:
            run_gui()
        except Exception as exc:  # GUI nicht möglich -> sichtbare Fehlermeldung
            return report_crash(exc)
        return 0

    if any(a in ("--places", "/places") for a in args):
        rest = [a for a in sys.argv[1:] if not a.lower() in ("--places", "/places")]
        return run_places(rest[0] if rest else "")

    # Standard (auch von der .bat aufgerufen): Konsole + Zwischenablage,
    # kein App-Fenster. --headless/--serve sind dieselbe Sache.
    return run_serve(
        no_tunnel=any(a in ("--no-tunnel", "/no-tunnel") for a in args),
        copy=not any(a in ("--keine-zwischenablage", "--no-clipboard") for a in args),
    )


def run_install_plugin(rotate: bool = False) -> int:
    """Installiert/aktualisiert das Studio-Plugin - ohne GUI.

    Mit rotate=True wird vorher ein neuer Bridge-Token erzeugt (z. B. wenn der
    alte Token versehentlich weitergegeben wurde).
    """
    cfg = load_config()
    port = int(cfg.get("port", DEFAULT_PORT))
    print(f"{APP_NAME} {APP_VERSION} - Studio-Plugin installieren")
    print("=" * 66)
    if rotate:
        cfg["bridge_token"] = ""
        save_config(cfg)
        print("[i]  Neuer Bridge-Token wird erzeugt (der alte wird ungültig).")

    token = ensure_bridge_token(cfg)
    print(f"[i]  Bridge-Adresse im Plugin: http://127.0.0.1:{port}")
    print(f"[i]  Plugin-Vorlage: {plugin_template_path() or 'nicht gefunden'}")
    print("-" * 66)

    results = install_plugin(port, token)
    ok = False
    for folder, status in results:
        success = status in ("installiert", "aktuell")
        ok = ok or success
        print(f"[{'OK' if success else 'X'}]  {folder}\n     -> {status}")

    print("-" * 66)
    if not ok:
        print("Das Plugin konnte nicht installiert werden. Ist Roblox Studio")
        print("installiert? Alternativ den Ordner per ARENA_PLUGIN_DIR setzen.")
        return 1
    print("Fertig. Roblox Studio neu starten, die gewuenschte Place oeffnen und")
    print("beim ersten Mal den Zugriff auf 127.0.0.1 erlauben (Plugin-Dialog).")
    print("Der Plugin-Button heisst 'ArenaBridge'.")
    return 0


def run_serve(no_tunnel: bool = False, copy: bool = True) -> int:
    """Standardmodus: Bridge + Tunnel in der Konsole, Prompt in der Zwischenablage.

    Es öffnet sich bewusst KEIN App-Fenster. In der .bat stehen danach
    Tunnel-URL und Token; der Prompt liegt in der Zwischenablage und als
    prompt.txt daneben. Im Studio-Plugin werden URL + Token eingetragen.
    """
    cfg = load_config()
    token = ensure_bridge_token(cfg)
    port = int(cfg.get("port", DEFAULT_PORT))

    print(f"{APP_NAME} {APP_VERSION}")
    print("=" * 78)

    # Studio-Plugin aktualisieren (mit Vorbelegung URL + Token)
    for folder, status in install_plugin(port, token):
        mark = "OK" if status in ("installiert", "aktuell") else "!"
        print(f"[{mark}] Studio-Plugin {status}: {folder}")
    print(f"[i] Plugin-Ordner: {plugins_folder()}")

    if port_in_use(port):
        print(f"[X] Port {port} ist belegt - läuft die .bat schon in einem anderen Fenster?")
        print(f"    Sonst in config.json einen anderen Port eintragen (z. B. {port + 1}).")
        return 1

    bridge = Bridge(cfg, token=token)
    try:
        bridge.start(port)
    except OSError as exc:
        print(f"[X] Bridge konnte nicht starten: {exc}")
        return 1

    print(f"[OK] Bridge läuft lokal auf http://127.0.0.1:{port}")
    print()

    if no_tunnel:
        # Nur zum Testen / ohne Internet: Prompt mit lokaler URL
        local = f"http://127.0.0.1:{port}"
        print("[!] --no-tunnel: Ohne Cloudflare-Tunnel ist die Bridge NUR lokal erreichbar.")
        print("    Arena AI kann sie so nicht erreichen - der Prompt enthält die lokale URL.")
        print()
        print_connection_box(local, token, port)
        publish_prompt(local, token, port, copy=copy)
        print("\n[i] Läuft. Beenden mit Strg+C.")
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            print("\n[i] Beende ...")
        finally:
            bridge.stop()
        return 0

    tunnel = Tunnel()
    state = {"published": False}

    def on_url(url: str) -> None:
        if state["published"]:
            return
        state["published"] = True
        print()
        print_connection_box(url, token, port)
        publish_prompt(url, token, port)
        print("\n[i] Läuft weiter. Fenster offen lassen! Beenden mit Strg+C.")
        print("[i] Prompt nochmal kopieren: prompt.txt öffnen, oder .bat neu starten.")

    def on_error(message: str) -> None:
        print(f"[!] Tunnel: {message}")
        print("[i] Die Bridge läuft trotzdem lokal - ohne Tunnel ist Arena AI aber")
        print("    nicht erreichbar. Internet/Firewall prüfen und .bat neu starten.")

    print("[i] Starte Cloudflare-Tunnel (beim ersten Mal wird cloudflared geladen) ...")
    tunnel.start(port, on_url, on_error)

    try:
        # Offline-Fallback: nach 90 s ohne Tunnel trotzdem Prompt anbieten
        waited = 0
        while not state["published"] and waited < 90:
            time.sleep(1)
            waited += 1
        if not state["published"]:
            print("\n[!] Kein Tunnel zustande gekommen. Prompt mit lokaler URL:")
            print_connection_box(f"http://127.0.0.1:{port}", token, port)
            publish_prompt(f"http://127.0.0.1:{port}", token, port, )
        threading.Event().wait()
    except KeyboardInterrupt:
        print("\n[i] Beende Bridge + Tunnel ...")
    finally:
        tunnel.stop()
        bridge.stop()
    return 0


def run_places(username: str) -> int:
    """Zeigt die Places eines Roblox-Users mit PlaceId/UniverseId (ohne GUI)."""
    username = (username or "").strip()
    if not username:
        print("Aufruf:  ArenaStudioConnector.bat /places <Roblox-Username>")
        return 1
    print(f"{APP_NAME} {APP_VERSION} - Places von {username}")
    print("=" * 66)
    user_id = resolve_user_id(username)
    if not user_id:
        print(f"[X] Username '{username}' nicht gefunden.")
        return 1
    try:
        places = fetch_user_places(user_id)
    except Exception as exc:
        print(f"[X] Places konnten nicht geladen werden: {exc}")
        return 1
    if not places:
        print("[i] Keine öffentlichen Places gefunden.")
        return 0
    for p in places:
        print(f"- {p['name']}")
        print(f"    PlaceId: {p['placeId']}   UniverseId: {p['universeId']}   "
              f"Besuche: {p.get('visits', 0)}")
    print()
    print("[i] Die offene Place erkennt Arena automatisch über /api/status.")
    return 0


# --------------------------------------------------------------------------- #
# Systemcheck (--check): zeigt genau, was fehlt
# --------------------------------------------------------------------------- #

def run_check() -> int:
    print(f"{APP_NAME} {APP_VERSION} - Systemcheck")
    print("=" * 66)
    problems: list[str] = []
    hints: list[str] = []

    # 1) Python
    if sys.version_info >= MIN_PYTHON:
        print(f"[OK] Python {sys.version.split()[0]}  ({sys.executable})")
    else:
        print(f"[X]  Python {sys.version.split()[0]} ist zu alt - bitte {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ installieren")
        problems.append("python")

    # 2) App-Ordner + Schreibrechte
    base = app_dir()
    print(f"[i]  App-Ordner: {base}")
    if is_writable(base):
        print("[OK] App-Ordner ist beschreibbar (.env, config.json, cloudflared moeglich)")
    else:
        print("[X]  App-Ordner ist NICHT beschreibbar - bitte ZIP nach z. B. C:\\Arena entpacken")
        problems.append("schreibrechte")

    # 3) Plugin-Datei
    plugin = plugin_template_path()
    if plugin:
        print(f"[OK] Plugin gefunden: {plugin}")
    else:
        print("[X]  plugin/ArenaBridgePlugin.lua fehlt - ZIP nicht komplett entpackt?")
        problems.append("plugin")

    # 4) tkinter (GUI)
    try:
        import tkinter  # noqa: PLC0415
        print(f"[OK] tkinter {tkinter.TkVersion} - Fenster/GUI moeglich")
    except Exception as exc:
        print(f"[X]  tkinter fehlt ({exc}) - GUI nicht moeglich. Nur --headless laeuft.")
        print("     Behebung: Python neu installieren und 'tcl/tk and IDLE' anhaken.")
        problems.append("tkinter")

    # 5) Roblox-Key (.env / config.json) - nur fuer Dashboard-Aktionen noetig
    cfg = load_config()
    if cfg.get("roblox_api_key"):
        print("[OK] Roblox API-Key lokal gesetzt (bleibt auf diesem PC)")
    else:
        print("[i]  Roblox API-Key: nicht gesetzt - nur fuer Dashboard-Aktionen noetig")
        hints.append("Key optional: .env.example als .env kopieren und ausfuellen")

    print(f"[i]  Roblox-Username: {cfg.get('roblox_username') or '(noch nicht gespeichert)'}")

    # 6) Port
    port = int(cfg.get("port", DEFAULT_PORT))
    if port_in_use(port):
        print(f"[!]  Port {port} ist belegt - evtl. laeuft die App schon, oder in")
        print("     config.json einen anderen Port eintragen (z. B. 8766).")
    else:
        print(f"[OK] Port {port} ist frei (Bridge/Tunnel koennen starten)")

    # 7) cloudflared (Tunnel)
    local_cf = app_dir() / ("cloudflared.exe" if os.name == "nt" else "cloudflared")
    if local_cf.exists():
        print(f"[OK] cloudflared vorhanden: {local_cf}")
    elif shutil.which("cloudflared"):
        print(f"[OK] cloudflared im PATH gefunden: {shutil.which('cloudflared')}")
    else:
        print("[i]  cloudflared fehlt noch - die App laedt es beim ersten Start")
        print("     automatisch von GitHub herunter")

    # 8) Studio-Plugin-Ordner + automatische Installation
    for folder in plugins_folders():
        print(f"[i]  Roblox-Plugin-Ordner: {folder}")
    installed, detail = plugin_status(port, ensure_bridge_token(cfg))
    if installed:
        print(f"[OK] Studio-Plugin ist installiert und aktuell:\n     {detail}")
    else:
        print(f"[i]  Studio-Plugin {detail}")
        print("     Wird beim naechsten App-Start automatisch installiert - oder jetzt:")
        print("     ArenaStudioConnector.bat /plugin")

    print("=" * 66)
    if problems:
        print("Ergebnis: Es fehlt noch etwas:")
        for p in problems:
            print(f"  - {p}")
        print("Tipp: ArenaStudioConnector.bat doppelklicken - der Starter findet")
        print("      Python selbst und bietet die Installation an.")
        return 1
    for h in hints:
        print(f"Hinweis: {h}")
    print("Ergebnis: Alles bereit - ArenaStudioConnector.bat doppelklicken!")
    return 0


# --------------------------------------------------------------------------- #
# Startfehler sichtbar machen (wichtig bei Start ohne Konsole)
# --------------------------------------------------------------------------- #

def crash_log_path() -> Path:
    return app_dir() / ERROR_LOG


def report_crash(exc: BaseException) -> int:
    """Schreibt ein Fehlerlog neben die App und zeigt (unter Windows) ein Fenster."""
    text = (f"{APP_NAME} {APP_VERSION}\n"
            f"Zeit:   {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"Python: {sys.version}\n"
            f"Ordner: {app_dir()}\n\n"
            + "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
    try:
        crash_log_path().write_text(text, encoding="utf-8")
        log_hint = f"\n\nDetails stehen in:\n{crash_log_path()}"
    except Exception:
        log_hint = ""
    print(text, file=sys.stderr, flush=True)

    summary = f"{type(exc).__name__}: {exc}"[:1200]
    if os.name == "nt":
        try:  # auch ohne Konsolenfenster (pythonw) sichtbar
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                None,
                f"{APP_NAME} konnte nicht gestartet werden:\n\n{summary}{log_hint}",
                f"{APP_NAME} - Fehler", 0x10,
            )
        except Exception:
            pass
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
