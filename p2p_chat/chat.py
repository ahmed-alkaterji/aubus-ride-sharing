import base64
import json
import os
import socket
import tempfile
import threading
import time
import uuid
import wave
from array import array
from pathlib import Path
from typing import Callable, Iterable, Optional, Tuple, Union

VOICE_UI_PREFIX = "__VOICE__::"
IMAGE_UI_PREFIX = "__IMAGE__::"



# Utility functions

def _get_local_ip() -> str:  #This function finds your computer’s LAN IP address, which is the real IP you use inside your home network
    """
    Return the machine's LAN IP address (not 0.0.0.0).
    If detection fails, defaults to 127.0.0.1.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)# UDP Socket creation
    try:
        # No packets actually sent – just selects outbound interface.
        s.connect(("8.8.8.8", 80))  # connect to Google DNS 8.8.8.8 but not to send packets just to get the ip without passing in the network traffic
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


class ConnectError(RuntimeError): # custom exception
    """Raised when the passenger fails to connect."""
    pass


VoiceChunkSource = Union[Iterable[bytes], Callable[[], Optional[bytes]]]# This is only a typing alias used for static type checking.
                                                                        # i can send an audio either from mic or function i call repeatedly 

class _VoiceStreamState: #It manages the receiving side of a voice message
# Keeps track of sequence numbers
# Writes audio into a .wav file
# Stores metadata such as sender, name, channel count…
# Ensures the final voice message is a valid playable audio file
    """Track progress while assembling a streaming voice attachment."""

    __slots__ = (
        "path",
        "wave",
        "expected_seq",
        "total_bytes",
        "name",
        "sender",
        "sample_rate",
        "channels",
        "width"
    )

    def __init__(self, path: Path, sender: str, name: str,
                 channels: int, sample_width: int, sample_rate: int):
        self.path = str(path)
        self.wave = wave.open(self.path, "wb")
        self.wave.setnchannels(max(1, channels))
        self.wave.setsampwidth(max(1, sample_width))
        self.wave.setframerate(max(sample_rate, 8000))
        self.expected_seq = 0
        self.total_bytes = 0
        self.name = name
        self.sender = sender
        self.sample_rate = sample_rate
        self.channels = channels
        self.width = sample_width

    def append(self, seq: int, chunk: bytes):
        # If we missed chunks we still append so the stream can continue.
        if seq != self.expected_seq:
            self.expected_seq = seq
        self.wave.writeframes(chunk)
        self.expected_seq = seq + 1
        self.total_bytes += len(chunk)

    def close(self):
        try:
            self.wave.close()
        except Exception:
            pass





class ChatNode:
    
    # ChatNode handles the actual TCP communication between driver and passenger.

    # Public API used by the GUI or handlers:
    #     - start_listener(host="", port=0) -> (ip, port)
    #     - start_connector(peer_ip, peer_port, timeout_sec=5.0)
    #     - send_text(sender, body)
    #     - send_loc(lat, lon)
    #     - send_voice_stream(sender, chunks, sample_rate, ...)
    #     - close()

    # ui_sink(room_id, line) is called for every message/status to update the GUI.


    def __init__(
        self,
        room_id: str,
        ui_sink: Optional[Callable[[str, str], None]] = None, #A callback function that the chat system uses to push messages/events to the GUI.
        download_root: Optional[Path] = None #A folder where files/voice messages will be saved
    ):
        self.room_id = room_id
        self.ui_sink = ui_sink
        self.download_root = download_root or (Path.home() / "AUBusChat")
        try:
            self.download_root.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

        self._srv_sock: Optional[socket.socket] = None
        self._conn: Optional[socket.socket] = None
        self._rx_thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._voice_streams: dict[str, _VoiceStreamState] = {}
        self._voice_lock = threading.Lock()

    
    # DRIVER side

    def start_listener(self, host: str = "", port: int = 0) -> Tuple[str, int]:
      
        # Start listening for one incoming passenger connection.
        # Returns (LAN_IP, PORT) that the passenger can connect to.

        # Creates a fresh TCP server socket.
        # Binds it to an available port.
        # Starts listening for a passenger.
        # Starts a background thread waiting for the first connection.
        # Returns the IP + port to display in the GUI.
       
        self.close()  # ensure clean state

        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((host, port))
        srv.listen(1)
        self._srv_sock = srv

        advertise_ip = _get_local_ip()
        real_port = srv.getsockname()[1]

        def _accept_once():
            try:
                conn, addr = srv.accept()
                self._attach_connection(conn, addr)
            except OSError:
                return

        threading.Thread(target=_accept_once, daemon=True).start()
        return advertise_ip, int(real_port)


    # PASSENGER side

    def start_connector(self, peer_ip: str, peer_port: int, timeout_sec: float = 5.0) -> None:
        
        # Connect to a driver who is listening at (peer_ip, peer_port).
        # Raises ConnectError if fails.
      
        self.close()  # reset

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout_sec)
        try:
            s.connect((peer_ip, int(peer_port)))
        except Exception as e:
            s.close()
            raise ConnectError(str(e))

        s.settimeout(None)
        self._attach_connection(s, (peer_ip, peer_port))


    # Core attach + receive loop

    # Stores the active TCP socket
    # Clears stop flag
    # Starts background receiving thread
    

    # Sends them to _deliver() for routing
    # Handles disconnect
    # Cleans up gracefully

    def _attach_connection(self, conn: socket.socket, addr: Tuple[str, int]) -> None:
        with self._lock:
            self._conn = conn
            self._stop.clear()

        self._ui(f"[STATUS] Connected to {addr[0]}:{addr[1]}")

        def _rx_loop():
            # Reads raw bytes → assembles complete JSON messages
            # Safely decodes each message
            buf = b""  #a byte buffer used to assemble complete messages.
            try:
                while not self._stop.is_set():
                    chunk = conn.recv(4096)  # it will read at most 4096 bytes
                    if not chunk:
                        break
                    buf += chunk    # append 
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        if not line:
                            continue
                        try:
                            msg = json.loads(line.decode("utf-8")) # Try to decode JSON
                        except json.JSONDecodeError:
                            continue
                        self._deliver(msg)
            except Exception as e:
                self._ui(f"[WARN] Receive error: {e}")
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
                self._conn = None
                self._ui("[STATUS] Connection closed.")

        self._rx_thread = threading.Thread(target=_rx_loop, daemon=True)
        self._rx_thread.start()

    
    # Sending messages
   
    def _send(self, obj: dict):
        data = (json.dumps(obj, separators=(",", ":")) + "\n").encode("utf-8") #converts the dict to a compact JSON string
        with self._lock:
            if not self._conn:
                raise ConnectError("No active connection.")
            self._conn.sendall(data)

    def send_text(self, sender: str, body: str):
        """Send a text message to the peer."""
        payload = {"t": "text", "room": self.room_id, "sender": sender, "body": body} #Build the JSON packet
        self._send(payload)
        self._ui(f"{sender}> {body}")

    def send_loc(self, lat: float, lon: float, link: Optional[str] = None):
        """Send location coordinates to the peer."""
        payload = {"t": "loc", "room": self.room_id, "lat": lat, "lon": lon}
        if link:
            payload["link"] = link
        self._send(payload)
        msg = f"[LOC SENT] {lat},{lon}"
        if link:
            msg += f" -> {link}"
        self._ui(msg)

    def send_file(
        self,
        kind: str,
        sender: str,
        name: str,
        data: bytes,
        source_path: Optional[str] = None
    ):
        """Send a binary payload (image/audio) to the peer."""
        encoded = base64.b64encode(data).decode("ascii")
        payload = {
            "t": "file",
            "room": self.room_id,
            "kind": kind,
            "sender": sender,
            "name": name,
            "data": encoded
        }
        self._send(payload)

        lower_kind = (kind or "").lower()
        normalized_path = None
        if source_path:
            normalized_path = self._normalize_local_path(source_path)
        if lower_kind == "image" and not normalized_path:
            try:
                normalized_path = self._store_file(kind, name, data)
            except OSError:
                normalized_path = None

        if lower_kind == "image" and normalized_path:
            notice = {
                "type": "image",
                "sender": sender,
                "path": normalized_path,
                "name": name,
                "bytes": len(data)
            }
            self._emit_image_notice(notice)
        else:
            self._ui(f"[{kind.upper()} SENT] {name} ({len(data)} bytes)")

    def send_voice_stream(
        self,
        sender: str,
        chunk_source: VoiceChunkSource,
        *,
        sample_rate: int,
        channels: int = 1,
        sample_width: int = 2,
        name: Optional[str] = None,
        stream_id: Optional[str] = None,
    ):
        """
        Stream microphone data to the peer in (near) real time.

        chunk_source can either be an iterable of bytes objects or a callable that
        returns the next chunk (returning None to stop). Providing a blocking
        generator/callable lets the data travel as it is produced by the microphone.
        """
        base_name = name or "voice_note.wav"
        stream_token = stream_id or uuid.uuid4().hex
        base_payload = {
            "t": "voice",
            "room": self.room_id,
            "sender": sender,
            "stream": stream_token,
            "rate": int(sample_rate),
            "channels": int(channels),
            "width": int(sample_width),
            "name": base_name,
        }

        def _iter_chunks():
            if callable(chunk_source):
                while True:
                    piece = chunk_source()
                    if piece is None:
                        break
                    yield piece
            else:
                yield from chunk_source

        seq = 0
        total_bytes = 0
        started = time.time()
        send_error: Optional[BaseException] = None
        try:
            for raw_chunk in _iter_chunks():
                if raw_chunk is None:
                    continue
                if isinstance(raw_chunk, memoryview):
                    chunk = raw_chunk.tobytes()
                elif isinstance(raw_chunk, bytearray):
                    chunk = bytes(raw_chunk)
                elif isinstance(raw_chunk, bytes):
                    chunk = raw_chunk
                else:
                    continue
                if not chunk:
                    continue
                payload = dict(base_payload)
                payload["seq"] = seq
                payload["final"] = False
                payload["data"] = base64.b64encode(chunk).decode("ascii")
                self._send(payload)
                seq += 1
                total_bytes += len(chunk)
        except Exception as exc:
            send_error = exc
            raise
        finally:
            elapsed = max(0.0, time.time() - started)
            final_payload = dict(base_payload)
            final_payload["seq"] = seq
            final_payload["final"] = True
            final_payload["data"] = ""
            final_payload["duration"] = elapsed
            final_payload["bytes"] = total_bytes
            try:
                self._send(final_payload)
            except Exception:
                if send_error is None:
                    raise
                # When you send a voice note, the microphone produces small raw-audio chunks,
                # and each chunk is base64-encoded and sent as a separate JSON packet containing its sequence number and stream ID.
                # The receiver uses the stream ID to group chunks, writes them in order into a .wav file, and when it receives
                # the final “end of stream” packet,it closes the file and displays the voice message in the chat.

    
    # Deliver incoming messages
    
    def _deliver(self, msg: dict):
        # Every JSON message that arrives from the socket ends up here, and _deliver decides what to do based on the "t" field
        t = msg.get("t") 

        # cases
        if t == "text":
            sender = msg.get("sender", "peer")
            body = msg.get("body", "")
            self._ui(f"{sender}> {body}")
        elif t == "loc":
            lat = msg.get("lat")
            lon = msg.get("lon")
            link = msg.get("link")
            text = f"[LOC RECEIVED] {lat},{lon}"
            if link:
                text += f" -> {link}"
            self._ui(text)
        elif t == "file":
            name = msg.get("name") or f"file_{int(time.time())}"
            kind = msg.get("kind", "file")
            sender = msg.get("sender", "peer")
            data = msg.get("data")
            if not isinstance(data, str):
                self._ui(f"[WARN] Malformed {kind} payload from {sender}")
                return
            try:
                raw = base64.b64decode(data.encode("ascii"))
            except Exception:
                self._ui(f"[WARN] Unable to decode {kind} from {sender}")
                return
            path = self._store_file(kind, name, raw)
            if kind.lower() == "image":
                notice = {
                    "type": "image",
                    "sender": sender,
                    "path": path,
                    "name": name,
                    "bytes": len(raw)
                }
                self._emit_image_notice(notice)
            else:
                self._ui(f"[{kind.upper()} RECEIVED] from {sender} saved to {path}")
        elif t == "voice":
            self._handle_voice(msg)
        else:
            self._ui(f"[WARN] Unknown message: {msg}")

    def _handle_voice(self, msg: dict):
        """Incrementally assemble streaming voice data."""
        stream_token = msg.get("stream")
        if not stream_token:
            self._ui("[WARN] Voice frame missing stream id.")
            return

        sender = msg.get("sender", "peer")
        seq = int(msg.get("seq", 0))
        final = bool(msg.get("final"))
        sample_rate = int(msg.get("rate", 16000))
        channels = int(msg.get("channels", 1))
        sample_width = int(msg.get("width", 2))
        chunk = b""
        data_field = msg.get("data")
        if isinstance(data_field, str) and data_field:
            try:
                chunk = base64.b64decode(data_field.encode("ascii"))
            except Exception:
                self._ui(f"[WARN] Unable to decode voice chunk from {sender}")
                chunk = b""

        warn_msg = None
        creation_error = None
        voice_notice = None

        with self._voice_lock:
            state = self._voice_streams.get(stream_token)
            if state is None and (chunk or final):
                target_name = msg.get("name") or f"voice_{stream_token}.wav"
                base = Path(target_name)
                if not base.suffix:
                    target_name = base.name + ".wav"
                try:
                    path = self._reserve_download_path("voice", target_name)
                    state = _VoiceStreamState(
                        path,
                        sender,
                        target_name,
                        channels,
                        sample_width,
                        sample_rate
                    )
                except OSError as e:
                    creation_error = f"[WARN] Unable to prepare voice download: {e}"
                    state = None
                else:
                    self._voice_streams[stream_token] = state

            if state and chunk:
                if seq != state.expected_seq:
                    warn_msg = (
                        f"[WARN] Voice chunk out of order "
                        f"(expected {state.expected_seq}, got {seq})"
                    )
                state.append(seq, chunk)

            if final and state:
                state.close()
                self._voice_streams.pop(stream_token, None)
                try:
                    self._amplify_voice_file(state.path, state.width)
                except Exception:
                    pass
                duration = float(msg.get("duration") or 0)
                if duration <= 0 and state.total_bytes:
                    bytes_per_second = max(
                        1,
                        state.sample_rate * state.channels * state.width
                    )
                    duration = state.total_bytes / bytes_per_second
                voice_notice = {
                    "type": "voice",
                    "sender": sender,
                    "path": state.path,
                    "name": state.name,
                    "bytes": state.total_bytes,
                    "duration": round(duration, 2),
                    "rate": state.sample_rate,
                    "channels": state.channels,
                    "width": state.width,
                }

        if creation_error:
            self._ui(creation_error)
            return
        if warn_msg:
            self._ui(warn_msg)
        if voice_notice:
            encoded = json.dumps(voice_notice, separators=(",", ":"))
            self._ui(f"{VOICE_UI_PREFIX}{encoded}")

    def _store_file(self, kind: str, name: str, blob: bytes) -> str:
        path = self._reserve_download_path(kind, name)
        with open(path, "wb") as fh:
            fh.write(blob)
        return str(path)

    def _reserve_download_path(self, kind: str, name: Optional[str]) -> Path:
        target_dir = self.download_root / self.room_id
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        base = Path(name) if name else Path(f"{kind}_{int(time.time())}")
        path = target_dir / base.name
        counter = 1
        while path.exists():
            path = target_dir / f"{base.stem}_{counter}{base.suffix}"
            counter += 1
        return path

    @staticmethod
    def _amplify_voice_file(path: str, sample_width: int, *, gain: float = 1.8):
        if sample_width not in (1, 2):
            return

        def _scale_chunk(chunk: bytes) -> bytes:
            if not chunk:
                return chunk
            if sample_width == 1:
                arr = array("b")
                clip_min, clip_max = -128, 127
            else:
                arr = array("h")
                clip_min, clip_max = -32768, 32767
            arr.frombytes(chunk)
            for idx, sample in enumerate(arr):
                boosted = int(sample * gain)
                if boosted > clip_max:
                    boosted = clip_max
                elif boosted < clip_min:
                    boosted = clip_min
                arr[idx] = boosted
            return arr.tobytes()

        tmp_fd = None
        tmp_path = None
        try:
            tmp_fd, tmp_path = tempfile.mkstemp(suffix=".wav")
            os.close(tmp_fd)
            with wave.open(path, "rb") as src, wave.open(tmp_path, "wb") as dst:
                dst.setparams(src.getparams())
                while True:
                    chunk = src.readframes(4096)
                    if not chunk:
                        break
                    boosted = _scale_chunk(chunk)
                    dst.writeframes(boosted)
            os.replace(tmp_path, path)
        except Exception:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    def _emit_image_notice(self, notice: dict):
        path = notice.get("path")
        if not path:
            return
        try:
            payload = json.dumps(notice, separators=(",", ":"))
        except Exception:
            return
        self._ui(f"{IMAGE_UI_PREFIX}{payload}")

    @staticmethod
    def _normalize_local_path(path: str) -> Optional[str]:
        if not path:
            return None
        candidate = Path(path).expanduser()
        try:
            candidate = candidate.resolve()
        except Exception:
            pass
        if not candidate.exists():
            return None
        return str(candidate)

    
    # UI output

    def _ui(self, line: str):
        if self.ui_sink:
            try:
                self.ui_sink(self.room_id, line)
            except Exception:
                pass


    # Close sockets safely

    def close(self):
        """Stop threads and close sockets safely."""
        self._stop.set()
        try:
            if self._srv_sock:
                self._srv_sock.close()
        except Exception:
            pass
        try:
            if self._conn:
                self._conn.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        try:
            if self._conn:
                self._conn.close()
        except Exception:
            pass
        self._srv_sock = None
        self._conn = None
        with self._voice_lock:
            for state in self._voice_streams.values():
                state.close()
            self._voice_streams.clear()
