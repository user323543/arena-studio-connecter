#!/usr/bin/env python3
"""
Arena Studio Connector
======================
Lokale Windows-App (auch als EXE baubar), die
  1. eine lokale Bridge (HTTP) startet,
  2. diese per Cloudflare-Tunnel (trycloudflare.com) öffentlich erreichbar macht,
  3. deine Roblox-Places auflistet und pro Place einen fertigen Prompt kopiert,
     den du an Arena AI schickst. Arena nutzt dann Tunnel-URL + Token, um über
     die Bridge mit dem Roblox-Studio-Plugin zu sprechen.

Der Roblox Open-Cloud API-Key bleibt IMMER nur lokal (.env / config.json)
und wird NIE in den Prompt kopiert. Arena kann ihn nur indirekt über
/api/roblox/open-cloud benutzen.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

APP_NAME = "Arena Studio Connector"
DEFAULT_PORT = 8765
TUNNEL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com", re.I)

# --------------------------------------------------------------------------- #
# Pfade / Konfiguration
# --------------------------------------------------------------------------- #

def app_dir() -> Path:
    """Ordner der EXE (gefroren) bzw. des Skripts."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


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
    safe = {k: v for k, v in cfg.items() if k != "roblox_api_key"}
    (app_dir() / "config.json").write_text(
        json.dumps(safe, indent=2, ensure_ascii=False), encoding="utf-8"
    )


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

def build_prompt(tunnel_url: str, token: str, place: dict | None) -> str:
    place = place or {}
    name = place.get("name") or place.get("placeName") or "(noch keine Place gewählt)"
    pid, uid = place.get("placeId"), place.get("universeId")
    return f"""Verbinde dich mit meinem Roblox Studio und arbeite NUR an dieser Place:

- Place / Experience: {name}
- PlaceId: {pid}
- UniverseId (Experience-Id): {uid}

VERBINDUNGSDATEN (streng vertraulich, nirgends posten/loggen):
- Bridge-URL (Cloudflare Tunnel): {tunnel_url}
- Token: {token}

SO NUTZT DU DIE VERBINDUNG (Arena AI → lies das genau und führe es aus):
1. Prüfe zuerst die Verbindung:
   curl -s "{tunnel_url}/api/status" -H "Authorization: Bearer {token}"
   Erwartet: "studio_connected": true und studio.placeId == {pid}.
   Wenn studio_connected false ist oder die PlaceId nicht übereinstimmt: STOPPE,
   sag mir kurz Bescheid (ich muss die Place in Roblox Studio öffnen / das Plugin
   aktivieren) und ändere NICHTS.
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
     -d '{{"method":"GET","path":"/cloud/v2/universes/{uid}","body":null}}'
   Die Bridge hängt meinen Key lokal an apis.roblox.com an. Komfort-Endpunkte:
   POST {tunnel_url}/api/roblox/game-pass        {{"universeId":{uid},"name":"...","description":"...","price":100}}
   POST {tunnel_url}/api/roblox/developer-product {{"universeId":{uid},"name":"...","description":"...","price":100}}
   Wenn Roblox 401/403 antwortet, sag mir exakt, welche Berechtigung fehlt –
   erfinde keine Daten und wiederhole die Aktion nicht endlos.
5. Volle Endpunkt-Doku: GET {tunnel_url}/api/docs (mit Token-Header).

REGELN:
- Arbeite ausschließlich an PlaceId {pid} / UniverseId {uid}.
- Mache nur das, worum ich dich danach bitte; frage bei destruktiven Aktionen
  (Löschen, Überschreiben von Scripts) vorher kurz nach.
- Fasse am Ende kurz zusammen, was du geändert hast, inkl. der Plugin-Antworten.
- Der Token gilt nur, solange meine Connector-App läuft. Bei 401 ist die
  Verbindung abgelaufen – dann brauchst du einen neuen Prompt von mir."""


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

    def start(self, port: int, on_url):
        exe = self.cloudflared_path()
        if not exe:
            exe = str(self.download_cloudflared(
                app_dir() / ("cloudflared.exe" if os.name == "nt" else "cloudflared")))
        self.proc = subprocess.Popen(
            [exe, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            bufsize=1, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

        def reader():
            assert self.proc and self.proc.stdout
            for line in self.proc.stdout:
                m = TUNNEL_RE.search(line)
                if m and "api.trycloudflare" not in m.group(0):
                    self.url = m.group(0)
                    on_url(self.url)
                    return
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


def plugin_source(bridge_url_local: str, token: str) -> str:
    src = ""
    if PLUGIN_TEMPLATE.exists():
        src = PLUGIN_TEMPLATE.read_text(encoding="utf-8")
    else:  # in der EXE ist die Datei über _MEIPASS eingebettet
        bundled = Path(getattr(sys, "_MEIPASS", app_dir())) / "plugin" / "ArenaBridgePlugin.lua"
        if bundled.exists():
            src = bundled.read_text(encoding="utf-8")
    return src.replace("__BRIDGE_URL__", bridge_url_local).replace("__BRIDGE_TOKEN__", token)


def plugins_folder() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Roblox" / "Plugins"
    return Path.home() / "Documents" / "Roblox" / "Plugins"


# --------------------------------------------------------------------------- #
# GUI
# --------------------------------------------------------------------------- #

def run_gui():
    import tkinter as tk
    from tkinter import messagebox, ttk

    cfg = load_config()
    bridge = Bridge(cfg)
    tunnel = Tunnel()
    state = {"places": [], "running": False}

    root = tk.Tk()
    root.title(APP_NAME)
    root.geometry("860x640")
    root.minsize(760, 560)

    top = ttk.Frame(root, padding=10)
    top.pack(fill="x")
    ttk.Label(top, text="Arena Studio Connector", font=("Segoe UI", 16, "bold")).pack(anchor="w")
    ttk.Label(top, text="1) Username eintragen → Places laden   2) Bridge + Tunnel starten   "
                        "3) Studio öffnen (Plugin)   4) Beim Place auf „Prompt kopieren“ klicken → an Arena AI schicken",
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
        bridge.start(port)
        status_var.set(f"Bridge läuft lokal auf http://127.0.0.1:{port} – starte Cloudflare-Tunnel …")
        tunnel.start(port, lambda url: root.after(0, lambda: (
            tunnel_var.set(f"Tunnel: {url}"),
            status_var.set("✅ Bereit! Jetzt Place in Studio öffnen und „Prompt kopieren“ klicken."))))
        state["running"] = True
        btn_bridge.config(text="⏹ Stoppen")

    def install_plugin():
        port = int(cfg.get("port", DEFAULT_PORT))
        src = plugin_source(f"http://127.0.0.1:{port}", bridge.token)
        if not src:
            messagebox.showerror(APP_NAME, "Plugin-Datei plugin/ArenaBridgePlugin.lua nicht gefunden.")
            return
        folder = plugins_folder()
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / "ArenaBridgePlugin.lua"
        dest.write_text(src, encoding="utf-8")
        messagebox.showinfo(APP_NAME, f"Plugin installiert:\n{dest}\n\nBitte Roblox Studio neu starten, "
                                       "die gewünschte Place öffnen und beim ersten Mal den "
                                       "Zugriff auf 127.0.0.1 erlauben (Plugin-Berechtigungen).")

    bar = ttk.Frame(root, padding=10)
    bar.pack(fill="x")
    ttk.Button(bar, text="Places laden", command=load_places).pack(side="left")
    btn_bridge = ttk.Button(bar, text="▶ Bridge + Tunnel starten", command=toggle_bridge)
    btn_bridge.pack(side="left", padx=8)
    ttk.Button(bar, text="Studio-Plugin installieren", command=install_plugin).pack(side="left")
    ttk.Button(bar, text="App-Ordner öffnen",
               command=lambda: os.startfile(app_dir()) if os.name == "nt" else subprocess.Popen(["xdg-open", str(app_dir())])).pack(side="left", padx=8)

    ttk.Label(root, textvariable=status_var, padding=(10, 2)).pack(fill="x")
    ttk.Label(root, textvariable=tunnel_var, padding=(10, 0)).pack(fill="x")
    ttk.Label(root, text="⚠️ Token & Tunnel-URL nur an Arena AI geben, nirgends öffentlich posten. "
                         "Der Roblox API-Key bleibt immer nur lokal auf diesem PC.",
              foreground="#a33", padding=(10, 4)).pack(fill="x")

    render_places()
    root.mainloop()


def main():
    if "--headless" in sys.argv:  # nur Bridge+Tunnel ohne GUI (zum Testen / Server)
        cfg = load_config()
        bridge = Bridge(cfg)
        port = int(cfg.get("port", DEFAULT_PORT))
        bridge.start(port)
        print(f"Bridge: http://127.0.0.1:{port}  Token: {bridge.token}", flush=True)
        Tunnel().start(port, lambda u: print(f"Tunnel: {u}\nTOKEN={bridge.token}", flush=True),
                       lambda e: print(e, flush=True))
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
    else:
        run_gui()


if __name__ == "__main__":
    main()
