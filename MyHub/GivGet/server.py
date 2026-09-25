import socket
import sys
import threading
import json
import time
import uuid
from datetime import datetime
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *

LISTEN_PORT = 1455

class RobloxPlayer:
    def __init__(self, username, user_id, job_id, display_name=""):
        self.username = username
        self.user_id = user_id
        self.job_id = job_id
        self.display_name = display_name or username
        self.connected_time = datetime.now()
        self.last_heartbeat = datetime.now()
        self.team = "None"
        self.account_age = 0
        self.status = "Online"
        self.client_id = ""
        self.total_heartbeats = 0

class ServerThread(QThread):
    player_connected = pyqtSignal(object)
    player_disconnected = pyqtSignal(str)
    log_message = pyqtSignal(str, str)
    heartbeat_received = pyqtSignal(str)

    def __init__(self, port=LISTEN_PORT):
        super().__init__()
        self.port = port
        self.running = True
        self.tcp_clients = {}
        self.http_commands = {}
        self.http_commands_lock = threading.Lock()

    def run(self):
        self.start_server()

    def start_server(self):
        try:
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(("0.0.0.0", self.port))
            server.listen(20)
            self.log_message.emit(f"Server OK - port {self.port}", "info")
            while self.running:
                try:
                    client, addr = server.accept()
                    t = threading.Thread(target=self.handle_client, args=(client, addr), daemon=True)
                    t.start()
                except:
                    if self.running:
                        pass
        except Exception as e:
            self.log_message.emit(f"Server error: {str(e)}", "error")

    def handle_client(self, client, addr):
        client.settimeout(30)
        try:
            data = client.recv(8192)
            if not data:
                client.close()
                return
            raw = data.decode("utf-8", errors="replace")
            if raw.startswith(("GET ", "POST ", "PUT ", "DELETE ", "HEAD ", "OPTIONS ", "PATCH ")):
                self.handle_http(client, raw, addr)
            else:
                self.handle_tcp(client, raw, addr)
        except Exception as e:
            self.log_message.emit(f"Client error {addr[0]}: {str(e)}", "error")
            client.close()

    def handle_http(self, client, raw, addr):
        try:
            first_line, rest = raw.split("\r\n", 1)
            parts = first_line.split(" ")
            method = parts[0]
            path = parts[1] if len(parts) > 1 else "/"
            header_section, _, body = rest.partition("\r\n\r\n")
            headers = {}
            for line in header_section.split("\r\n"):
                if ":" in line:
                    k, v = line.split(":", 1)
                    headers[k.strip().lower()] = v.strip()
            content_length = int(headers.get("content-length", 0))
            while len(body) < content_length:
                chunk = client.recv(content_length - len(body))
                if not chunk:
                    break
                body += chunk.decode("utf-8", errors="replace")

            if method == "GET" and path.startswith("/poll/"):
                user_id = path.split("/")[-1]
                cmds = self.pop_http_commands(user_id)
                self._http_ok(client, {"commands": cmds})
                client.close()
                return

            if method == "GET" and path == "/players":
                players_data = []
                try:
                    if hasattr(self, "get_players_cb") and self.get_players_cb:
                        for p in self.get_players_cb():
                            players_data.append({
                                "username": p.username,
                                "user_id": p.user_id,
                                "team": p.team,
                                "status": p.status
                            })
                except:
                    pass
                self._http_ok(client, {"players": players_data})
                client.close()
                return

            if method == "POST" and body:
                data = json.loads(body)
                msg_type = data.get("type", "")
                if msg_type == "connect":
                    player_data = {
                        "client_id": f"http_{addr[0]}_{int(time.time())}",
                        "username": data.get("username", "Unknown"),
                        "user_id": str(data.get("userId", "0")),
                        "job_id": data.get("jobId", ""),
                        "display_name": data.get("displayName", data.get("username", "Unknown")),
                        "team": data.get("team", "None"),
                        "account_age": data.get("accountAge", 0),
                        "ip": addr[0],
                        "source": "HTTP"
                    }
                    self.player_connected.emit(player_data)
                    self.log_message.emit(f"HTTP connect: {player_data['username']}", "success")
                elif msg_type == "heartbeat":
                    uid = str(data.get("userId", ""))
                    self.heartbeat_received.emit(uid)
                elif msg_type == "disconnect":
                    uid = str(data.get("userId", ""))
                    self.player_disconnected.emit(uid)
                self._http_ok(client, {"status": "ok"})
                client.close()
                return

            self._http_err(client, 404, "not found")
        except json.JSONDecodeError:
            self._http_err(client, 400, "bad json")
        except Exception as e:
            self._http_err(client, 500, str(e))
        finally:
            client.close()

    def _http_ok(self, client, data):
        self._http_send(client, 200, data)

    def _http_err(self, client, code, msg):
        self._http_send(client, code, {"error": msg})

    def _http_send(self, client, code, data):
        body = json.dumps(data)
        resp = (
            f"HTTP/1.1 {code} {'OK' if code == 200 else 'Error'}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Access-Control-Allow-Origin: *\r\n"
            f"Connection: close\r\n"
            f"\r\n{body}"
        )
        try:
            client.send(resp.encode("utf-8"))
        except:
            pass

    def handle_tcp(self, client, initial_data, addr):
        client_id = f"{addr[0]}:{addr[1]}"
        buffer = initial_data
        while self.running:
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    msg_type = data.get("type", "")
                    if msg_type == "connect":
                        player_data = {
                            "client_id": client_id,
                            "username": data.get("username", "Unknown"),
                            "user_id": str(data.get("userId", "0")),
                            "job_id": data.get("jobId", ""),
                            "display_name": data.get("displayName", data.get("username", "Unknown")),
                            "team": data.get("team", "None"),
                            "account_age": data.get("accountAge", 0),
                            "ip": addr[0],
                            "source": "TCP"
                        }
                        self.player_connected.emit(player_data)
                        self.tcp_clients[client_id] = {
                            "socket": client,
                            "data": player_data,
                            "last_heartbeat": datetime.now()
                        }
                    elif msg_type == "heartbeat":
                        uid = str(data.get("userId", ""))
                        self.heartbeat_received.emit(uid)
                        if client_id in self.tcp_clients:
                            self.tcp_clients[client_id]["last_heartbeat"] = datetime.now()
                    elif msg_type == "disconnect":
                        self._tcp_disconnect(client_id)
                        client.close()
                        return
                    elif msg_type == "command_result":
                        self.log_message.emit(f"Result: {data.get('result', '?')}", "info")
                except json.JSONDecodeError:
                    self.log_message.emit(f"Bad JSON: {line[:50]}", "warning")
                except Exception as e:
                    self.log_message.emit(f"Process error: {str(e)}", "error")
            try:
                chunk = client.recv(4096)
                if not chunk:
                    break
                buffer += chunk.decode("utf-8", errors="replace")
            except socket.timeout:
                continue
            except:
                break
        self._tcp_disconnect(client_id)
        client.close()

    def _tcp_disconnect(self, client_id):
        if client_id in self.tcp_clients:
            pd = self.tcp_clients[client_id].get("data", {})
            self.player_disconnected.emit(client_id)
            del self.tcp_clients[client_id]
            self.log_message.emit(f"TCP disconnect: {pd.get('username', '?')}", "info")

    def send_tcp(self, client_id, data):
        if client_id in self.tcp_clients:
            try:
                msg = json.dumps(data) + "\n"
                self.tcp_clients[client_id]["socket"].send(msg.encode("utf-8"))
                return True
            except:
                return False
        return False

    def broadcast_tcp(self, data):
        n = 0
        for cid in list(self.tcp_clients.keys()):
            if self.send_tcp(cid, data):
                n += 1
        return n

    def kick_tcp(self, client_id, reason="Kicked"):
        if self.send_tcp(client_id, {"type": "kick", "reason": reason}):
            self._tcp_disconnect(client_id)
            return True
        return False

    def queue_http_cmd(self, user_id, command):
        with self.http_commands_lock:
            if user_id not in self.http_commands:
                self.http_commands[user_id] = []
            self.http_commands[user_id].append(command)

    def pop_http_commands(self, user_id):
        with self.http_commands_lock:
            return self.http_commands.pop(user_id, [])

    def stop(self):
        self.running = False
        for c in list(self.tcp_clients.values()):
            try:
                c["socket"].close()
            except:
                pass

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.players = {}
        self.player_map = {}
        self.server = None
        self.init_ui()
        self.start_server()

    def init_ui(self):
        self.setWindowTitle(f"Roblox Gateway (port {LISTEN_PORT})")
        self.setGeometry(100, 100, 1200, 800)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)

        hdr = QHBoxLayout()
        title = QLabel("Roblox Gateway")
        title.setStyleSheet("font-size: 22px; font-weight: bold;")
        hdr.addWidget(title)
        hdr.addStretch()

        self.lbl_status = QLabel("Online")
        self.lbl_status.setStyleSheet("color: #00cc66; font-weight: bold; font-size: 14px;")
        hdr.addWidget(self.lbl_status)

        self.lbl_count = QLabel("0 players")
        self.lbl_count.setStyleSheet("color: #ffcc00; font-weight: bold; font-size: 14px;")
        hdr.addWidget(self.lbl_count)

        self.lbl_uptime = QLabel("00:00:00")
        self.lbl_uptime.setStyleSheet("color: #999; font-size: 13px;")
        hdr.addWidget(self.lbl_uptime)

        btn_restart = QPushButton("Restart")
        btn_restart.clicked.connect(self.restart_server)
        hdr.addWidget(btn_restart)

        btn_stop = QPushButton("Stop")
        btn_stop.setStyleSheet("background: #cc4444;")
        btn_stop.clicked.connect(self.stop_server)
        hdr.addWidget(btn_stop)

        layout.addLayout(hdr)

        split = QSplitter(Qt.Horizontal)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(QLabel("Players"))

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search...")
        self.search.textChanged.connect(self.refresh_list)
        lv.addWidget(self.search)

        self.list = QListWidget()
        self.list.itemClicked.connect(self.on_select)
        lv.addWidget(self.list)

        acts = QHBoxLayout()
        btn_kick = QPushButton("Kick")
        btn_kick.setStyleSheet("background: #cc4444;")
        btn_kick.clicked.connect(self.kick_player)
        acts.addWidget(btn_kick)

        btn_whisper = QPushButton("Whisper")
        btn_whisper.clicked.connect(self.whisper_player)
        acts.addWidget(btn_whisper)

        btn_info = QPushButton("Info")
        btn_info.clicked.connect(self.show_info)
        acts.addWidget(btn_info)

        acts.addStretch()
        lv.addLayout(acts)
        split.addWidget(left)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)

        tabs = QTabWidget()

        det = QWidget()
        det_layout = QVBoxLayout(det)

        self.info_group = QGroupBox("Player Info")
        grid = QGridLayout()

        fields = ["Username", "Display Name", "User ID", "Job ID", "Team", "Status", "Ping", "Playtime", "Heartbeats", "Connected", "Last HB", "Source"]
        self.info_labels = {}
        for i, name in enumerate(fields):
            lbl = QLabel(name + ":")
            lbl.setStyleSheet("font-weight: bold; color: #aaa;")
            grid.addWidget(lbl, i, 0)
            val = QLabel("N/A")
            grid.addWidget(val, i, 1)
            self.info_labels[name.lower().replace(" ", "_")] = val

        self.info_group.setLayout(grid)
        det_layout.addWidget(self.info_group)
        det_layout.addStretch()
        tabs.addTab(det, "Details")

        con = QWidget()
        con_layout = QVBoxLayout(con)

        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setMaximumHeight(250)
        con_layout.addWidget(self.console)

        inp_layout = QHBoxLayout()
        self.cmd_input = QLineEdit()
        self.cmd_input.setPlaceholderText("/help")
        self.cmd_input.returnPressed.connect(self.run_cmd)
        inp_layout.addWidget(self.cmd_input)

        btn_send = QPushButton("Send")
        btn_send.clicked.connect(self.run_cmd)
        inp_layout.addWidget(btn_send)

        con_layout.addLayout(inp_layout)
        tabs.addTab(con, "Console")

        rv.addWidget(tabs)
        split.addWidget(right)
        split.setSizes([400, 800])
        layout.addWidget(split)

        self.statusBar().showMessage("Ready")

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_ui)
        self.timer.start(1000)

        self.start_time = datetime.now()

    def start_server(self):
        if self.server:
            return
        self.server = ServerThread()
        self.server.player_connected.connect(self.on_connect)
        self.server.player_disconnected.connect(self.on_disconnect)
        self.server.log_message.connect(self.log)
        self.server.heartbeat_received.connect(self.on_heartbeat)
        self.server.get_players_cb = lambda: list(self.players.values())
        self.server.start()
        self.log("Server started", "info")

    def stop_server(self):
        if self.server:
            self.server.stop()
            self.server = None
            self.lbl_status.setText("Offline")
            self.lbl_status.setStyleSheet("color: #ff4444; font-weight: bold; font-size: 14px;")
            self.log("Server stopped", "warning")

    def restart_server(self):
        self.stop_server()
        QTimer.singleShot(500, self.start_server)

    def on_connect(self, data):
        try:
            uid = str(data.get("user_id", "0"))
            cid = data.get("client_id", "")
            if not cid or not uid:
                self.log(f"Invalid connect data: {data}", "error")
                return
            if cid in self.players:
                return
            if uid in self.player_map:
                old_cid = self.player_map[uid]
                if old_cid in self.players:
                    del self.players[old_cid]
                del self.player_map[uid]
            p = RobloxPlayer(
                data.get("username", "?"), uid, data.get("job_id", ""),
                data.get("display_name", "")
            )
            p.team = data.get("team", "None")
            p.account_age = data.get("account_age", 0)
            p.client_id = cid
            p.connected_time = datetime.now()
            self.players[cid] = p
            self.player_map[uid] = cid
            self.refresh_list()
            src = data.get("source", "?")
            self.log(f"Connected: {p.username} ({uid}) via {src}", "success")
            self.log(f"Player count: {len(self.players)}", "info")
        except Exception as e:
            self.log(f"on_connect error: {e}", "error")

    def on_disconnect(self, cid_or_uid):
        found = None
        for cid, p in list(self.players.items()):
            if cid == cid_or_uid or p.user_id == cid_or_uid:
                found = cid
                break
        if found:
            p = self.players[found]
            self.log(f"Disconnected: {p.username}", "warning")
            if p.user_id in self.player_map and self.player_map[p.user_id] == found:
                del self.player_map[p.user_id]
            del self.players[found]
            self.refresh_list()

    def on_heartbeat(self, uid):
        uid = str(uid)
        cid = self.player_map.get(uid)
        if cid and cid in self.players:
            p = self.players[cid]
            p.last_heartbeat = datetime.now()
            p.total_heartbeats += 1
            p.status = "Online"

    def refresh_list(self):
        self.list.clear()
        search = self.search.text().lower()
        for cid, p in sorted(self.players.items(), key=lambda x: x[1].username.lower()):
            if search and search not in p.username.lower() and search not in p.user_id:
                continue
            diff = (datetime.now() - p.last_heartbeat).total_seconds()
            icon = "G" if diff < 30 else "Y" if diff < 60 else "R"
            src = "H" if cid.startswith("http_") else "T"
            playtime = self._format_playtime(p)
            item = QListWidgetItem(f"[{icon}|{src}] {p.username}  {p.user_id}  {p.team}  [{playtime}]")
            item.setData(Qt.UserRole, cid)
            self.list.addItem(item)
        self.lbl_count.setText(f"{len(self.players)} players")

    def on_select(self, item):
        cid = item.data(Qt.UserRole)
        p = self.players.get(cid)
        if not p:
            return

        self.info_labels["username"].setText(p.username)
        self.info_labels["display_name"].setText(p.display_name)
        self.info_labels["user_id"].setText(p.user_id)
        self.info_labels["job_id"].setText(p.job_id)
        self.info_labels["team"].setText(p.team)

        diff = (datetime.now() - p.last_heartbeat).total_seconds()
        status = "Online" if diff < 30 else "Away" if diff < 60 else "Offline"
        self.info_labels["status"].setText(status)

        ping = int(diff * 100) if diff < 30 else 0
        self.info_labels["ping"].setText(f"{ping}ms")

        playtime = datetime.now() - p.connected_time
        hours = playtime.seconds // 3600
        minutes = (playtime.seconds % 3600) // 60
        seconds = playtime.seconds % 60
        self.info_labels["playtime"].setText(f"{hours:02d}:{minutes:02d}:{seconds:02d}")

        self.info_labels["heartbeats"].setText(str(p.total_heartbeats))
        self.info_labels["connected"].setText(p.connected_time.strftime("%H:%M:%S"))
        self.info_labels["last_hb"].setText(p.last_heartbeat.strftime("%H:%M:%S"))
        self.info_labels["source"].setText("HTTP" if cid.startswith("http_") else "TCP")

    def get_selected_cid(self):
        item = self.list.currentItem()
        if not item:
            QMessageBox.warning(self, "Hey", "Select a player first")
            return None
        return item.data(Qt.UserRole)

    def kick_player(self):
        cid = self.get_selected_cid()
        if not cid:
            return
        p = self.players.get(cid)
        if not p:
            return
        reason, ok = QInputDialog.getText(self, "Kick", f"Kick {p.username}? Reason:")
        if not ok:
            return
        if cid.startswith("http_"):
            self.server.queue_http_cmd(p.user_id, {"type": "kick", "reason": reason})
            self.log(f"Kick queued for {p.username}", "warning")
            if p.user_id in self.player_map:
                del self.player_map[p.user_id]
            del self.players[cid]
            self.refresh_list()
        elif self.server.kick_tcp(cid, reason):
            self.log(f"Kicked {p.username}: {reason}", "warning")
        else:
            QMessageBox.critical(self, "Error", "Kick failed")

    def whisper_player(self):
        cid = self.get_selected_cid()
        if not cid:
            return
        p = self.players.get(cid)
        if not p:
            return
        msg, ok = QInputDialog.getText(self, "Whisper", f"To {p.username}:")
        if not ok or not msg:
            return
        if cid.startswith("http_"):
            self.server.queue_http_cmd(p.user_id, {"type": "whisper", "message": msg})
            self.log(f"Whisper queued to {p.username}", "info")
        elif self.server.send_tcp(cid, {"type": "whisper", "message": msg}):
            self.log(f"Whisper sent to {p.username}", "info")
        else:
            QMessageBox.critical(self, "Error", "Whisper failed")

    def show_info(self):
        cid = self.get_selected_cid()
        if not cid:
            return
        p = self.players.get(cid)
        if not p:
            return
        QMessageBox.information(self, p.username,
            f"Username: {p.username}\n"
            f"Display: {p.display_name}\n"
            f"User ID: {p.user_id}\n"
            f"Job ID: {p.job_id}\n"
            f"Team: {p.team}\n"
            f"Source: {'HTTP' if cid.startswith('http_') else 'TCP'}\n"
            f"Connected: {p.connected_time.strftime('%H:%M:%S')}\n"
            f"Playtime: {self._format_playtime(p)}\n"
            f"Heartbeats: {p.total_heartbeats}\n"
            f"Account Age: {p.account_age} days"
        )

    def run_cmd(self):
        cmd = self.cmd_input.text().strip()
        if not cmd:
            return
        self.cmd_input.clear()
        self.log(f"$ {cmd}", "info")

        parts = cmd.split()
        c = parts[0].lower()

        if c == "/help":
            self.log("Commands: /players /kick <uid> <reason> /broadcast <msg> /bc <msg> /clear /stats", "info")
        elif c == "/players":
            if not self.players:
                self.log("No players", "info")
            else:
                for p in self.players.values():
                    self.log(f"  {p.username} ({p.user_id}) {p.team}", "info")
        elif c == "/kick" and len(parts) > 1:
            uid = parts[1]
            reason = " ".join(parts[2:]) or "Kicked"
            found = False
            for cid, p in list(self.players.items()):
                if p.user_id == uid:
                    if cid.startswith("http_"):
                        self.server.queue_http_cmd(uid, {"type": "kick", "reason": reason})
                        if uid in self.player_map:
                            del self.player_map[uid]
                        del self.players[cid]
                    else:
                        self.server.kick_tcp(cid, reason)
                    self.log(f"Kicked {p.username}", "warning")
                    found = True
                    break
            if not found:
                self.log(f"User {uid} not found", "warning")
        elif c in ("/broadcast", "/bc") and len(parts) > 1:
            msg = " ".join(parts[1:])
            tcp_n = self.server.broadcast_tcp({"type": "broadcast", "message": msg}) if self.server else 0
            http_n = 0
            for cid, p in self.players.items():
                if cid.startswith("http_"):
                    self.server.queue_http_cmd(p.user_id, {"type": "broadcast", "message": msg})
                    http_n += 1
            self.log(f"Broadcasted to {tcp_n + http_n} players", "info")
        elif c == "/clear":
            self.console.clear()
        elif c == "/stats":
            self.log(f"Players: {len(self.players)}  Uptime: {self.get_uptime()}", "info")
        else:
            self.log(f"Unknown: {cmd}", "warning")

    def update_ui(self):
        self.lbl_uptime.setText(self.get_uptime())
        now = datetime.now()
        changed = False
        for cid, p in list(self.players.items()):
            diff = (now - p.last_heartbeat).total_seconds()
            if diff > 30:
                uid = p.user_id
                self.log(f"Removed stale: {p.username} ({uid})", "warning")
                if uid in self.player_map and self.player_map[uid] == cid:
                    del self.player_map[uid]
                del self.players[cid]
                changed = True
            elif diff > 10 and p.status != "Offline":
                p.status = "Offline"
                changed = True
        if changed:
            self.refresh_list()
        else:
            self.refresh_playtime()

    def refresh_playtime(self):
        item = self.list.currentItem()
        if item:
            cid = item.data(Qt.UserRole)
            p = self.players.get(cid)
            if p:
                self.on_select(item)

    def _format_playtime(self, p):
        d = datetime.now() - p.connected_time
        hours = d.seconds // 3600
        minutes = (d.seconds % 3600) // 60
        seconds = d.seconds % 60
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def get_uptime(self):
        d = datetime.now() - self.start_time
        return f"{d.seconds//3600:02d}:{(d.seconds%3600)//60:02d}:{d.seconds%60:02d}"

    def log(self, msg, level="info"):
        ts = datetime.now().strftime("%H:%M:%S")
        tag = {"info": "[I]", "success": "[OK]", "warning": "[WARN]", "error": "[ERR]"}
        self.console.append(f"{ts} {tag.get(level, '[I]')} {msg}")
        self.console.ensureCursorVisible()

    def closeEvent(self, e):
        if self.server:
            self.server.stop()
        e.accept()

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
