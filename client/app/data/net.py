import socket, json

SERVER_ADDR = ("10.169.44.168", 5050)  # TODO-A: confirm with Member A
TIMEOUT = 5

def send_request(action, payload):
    """Send a JSON dict {action, payload} to the server; return a dict reply."""
    try:
        with socket.create_connection(SERVER_ADDR, timeout=TIMEOUT) as s:
            msg = json.dumps({"action": action, "payload": payload}).encode()
            print(f"[client -> server] {msg!r}")  # visible in PowerShell
            s.sendall(msg)
            data = s.recv(4096)
            print(f"[server -> client] {data!r}")
            return json.loads(data.decode())
    except Exception as e:
        return {"ok": False, "msg": f"Connection error: {e}"}