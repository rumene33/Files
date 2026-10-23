"""Заместител на mpv за тестове: слуша на --input-ipc-server и записва командите."""
import json
import os
import socket
import sys

sock_path = next(a.split("=", 1)[1] for a in sys.argv if a.startswith("--input-ipc-server="))
log_path = os.environ["FAKE_MPV_LOG"]
if os.path.exists(sock_path):
    os.unlink(sock_path)
srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
srv.bind(sock_path)
srv.listen(1)
conn, _ = srv.accept()
buf = b""
with open(log_path, "a", encoding="utf-8") as log:
    while True:
        data = conn.recv(4096)
        if not data:
            break
        buf += data
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            msg = json.loads(line)
            cmd = msg["command"]
            log.write(json.dumps(cmd) + "\n")
            log.flush()
            reply = {"error": "success"}
            if "request_id" in msg:
                reply["request_id"] = msg["request_id"]
                reply["data"] = {"time-pos": 1.5, "pause": False, "current-ao": "alsa"}.get(cmd[1])
            conn.sendall((json.dumps(reply) + "\n").encode())
            if cmd[0] == "loadfile":
                conn.sendall(b'{"event":"file-loaded"}\n')
            if cmd[0] == "quit":
                sys.exit(0)
