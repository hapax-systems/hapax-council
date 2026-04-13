import json
import socket
import sys
import time

text = sys.argv[1] if len(sys.argv) > 1 else "hi"
sock_path = "/run/user/1000/hapax-daimonion-tts.sock"

s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.settimeout(90.0)
t0 = time.monotonic()
s.connect(sock_path)
t_connect = time.monotonic() - t0
req = json.dumps({"text": text, "use_case": "conversation"})
s.sendall(req.encode() + b"\n")
try:
    s.shutdown(socket.SHUT_WR)
except OSError:
    pass

# read header
buf = b""
while b"\n" not in buf:
    chunk = s.recv(4096)
    if not chunk:
        break
    buf += chunk
t_header = time.monotonic() - t0
header_bytes, _, tail = buf.partition(b"\n")
try:
    header = json.loads(header_bytes.decode())
except Exception as e:
    print(f"ERR decoding header: {e} raw={header_bytes[:100]!r}")
    sys.exit(1)

pcm_len = header.get("pcm_len", 0)
remaining = pcm_len - len(tail)
while remaining > 0:
    chunk = s.recv(min(remaining, 65536))
    if not chunk:
        break
    remaining -= len(chunk)
t_done = time.monotonic() - t0
s.close()
print(
    f"text_len={len(text)} connect={t_connect * 1000:.1f}ms header={t_header * 1000:.1f}ms total={t_done * 1000:.1f}ms header={header}"
)
