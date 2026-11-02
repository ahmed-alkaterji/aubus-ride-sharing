from __future__ import annotations
import os
import sys, re, json
import queue
import threading
import time
from pathlib import Path
from typing import Optional
from functools import lru_cache
from urllib.parse import urlencode
from urllib.request import urlopen
from urllib.error import URLError

from PyQt5.QtCore import (
    Qt,
    QRegularExpression,
    QTimer,
    QIODevice,
    QObject,
    pyqtSignal,
    QUrl
)
from PyQt5.QtGui import (
    QRegularExpressionValidator,
    QPixmap,
    QColor
)
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QStackedWidget,
    QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QPushButton, QCheckBox, QMessageBox, QFrame, QComboBox,
    QCompleter, QInputDialog, QPlainTextEdit, QListView, QDialog,
    QSpinBox, QDoubleSpinBox, QTextBrowser, QFileDialog,
    QSlider, QDialogButtonBox, QScrollArea
)
from PyQt5.QtMultimedia import QAudioDeviceInfo, QAudioFormat, QAudioInput, QMediaContent, QMediaPlayer

from data import net

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))
LOGO_PATH = ROOT_DIR / "img" / "ChatGPT Image Nov 19, 2025, 09_17_30 PM.png"

GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
DOWNLOAD_ROOT = ROOT_DIR / "client" / "downloads"
ATTACHMENT_LIMIT = 4 * 1024 * 1024  # 4 MB per attachment
try:
    DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)
except OSError:
    pass

from p2p_chat.chat import ChatNode, ConnectError, VOICE_UI_PREFIX, IMAGE_UI_PREFIX


# Validation helpers

EMAIL_RE = QRegularExpression(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

def pw_quality(pw: str) -> tuple[bool, str]:
    if len(pw) < 8:
        return False, "At least 8 characters"
    if not re.search(r"[A-Za-z]", pw):
        return False, "Use letters"
    if not re.search(r"\d", pw):
        return False, "Add a digit"
    return True, "OK"


def geocode_location(query: str) -> Optional[tuple[float, float]]:
    if not query:
        return None
    query = query.strip()
    if "," in query:
        try:
            lat_s, lon_s = query.split(",", 1)
            return float(lat_s.strip()), float(lon_s.strip())
        except ValueError:
            pass
    if not GOOGLE_MAPS_API_KEY:
        return None

    params = urlencode({"address": query, "key": GOOGLE_MAPS_API_KEY})
    url = f"https://maps.googleapis.com/maps/api/geocode/json?{params}"
    try:
        with urlopen(url, timeout=5) as resp:
            data = json.load(resp)
        if data.get("status") == "OK" and data.get("results"):
            loc = data["results"][0]["geometry"]["location"]
            return float(loc["lat"]), float(loc["lng"])
    except Exception:
        return None
    return None


def google_maps_link(lat: float, lon: float) -> str:
    return f"https://www.google.com/maps/search/?api=1&query={lat:.6f},{lon:.6f}"


# Palette

BRAND_DEEP_RED = "#66101F"   # wine
BRAND_PRIMARY = "#66101F"
BRAND_LIGHT = "#F9E0D9"      # soft blush
BRAND_ACCENT = "#847577"     # muted taupe
TEXT_DARK = "#01172F"        # deep navy
TEXT_MUTED = "#847577"


@lru_cache(maxsize=6)
def _brand_logo_pixmap(size: int = 360) -> QPixmap:
    size = max(160, int(size))

    logo_file = QPixmap(str(LOGO_PATH))
    if not logo_file.isNull():
        return logo_file.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    # Fallback: simple solid brand block if image is missing
    pix = QPixmap(size, size)
    pix.fill(QColor("#a32026"))
    return pix


def _build_auth_hero(headline: str, subline: str) -> QFrame:
    frame = QFrame()
    frame.setObjectName("authHero")
    frame.setStyleSheet(f"""
        QFrame#authHero {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                        stop:0 #2d0b16, stop:1 {BRAND_DEEP_RED});
            border-radius: 32px;
            border: 1px solid rgba(255, 255, 255, 0.08);
        }}
        QLabel#heroHeadline {{
            font: 800 32px 'Segoe UI';
            color: white;
        }}
        QLabel#heroSub {{
            color: rgba(255, 255, 255, 0.85);
            font: 500 15px 'Segoe UI';
        }}
    """)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(48, 56, 48, 56)
    layout.setSpacing(24)

    logo = QLabel()
    logo.setAlignment(Qt.AlignCenter)
    logo.setPixmap(_brand_logo_pixmap(360))
    layout.addWidget(logo)

    headline_lbl = QLabel(headline)
    headline_lbl.setObjectName("heroHeadline")
    headline_lbl.setWordWrap(True)
    layout.addWidget(headline_lbl)

    sub_lbl = QLabel(subline)
    sub_lbl.setObjectName("heroSub")
    sub_lbl.setWordWrap(True)
    layout.addWidget(sub_lbl)

    layout.addStretch(1)
    return frame



# Card styling

class Card(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet(f"""
            QFrame#card {{
                background: {BRAND_LIGHT};
                border: 1px solid #f0cfd7;
                border-radius: 18px;
                padding: 24px;
                box-shadow: 0 18px 55px rgba(1, 23, 47, 0.18);
            }}
            QLabel {{
                color: {TEXT_DARK};
                font-family: 'Segoe UI';
            }}
            QLineEdit, QComboBox, QPlainTextEdit, QSpinBox, QDoubleSpinBox {{
                background: #fffdfd;
                color: {TEXT_DARK};
                padding: 12px;
                border: 1px solid #f0d0de;
                border-radius: 12px;
            }}
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                            stop:0 {BRAND_PRIMARY}, stop:1 {BRAND_DEEP_RED});
                color: white;
                padding: 12px 16px;
                border-radius: 14px;
                font-weight: 700;
                letter-spacing: 0.2px;
                border: 1px solid rgba(255, 255, 255, 0.18);
            }}
            QPushButton:pressed {{
                background: {BRAND_DEEP_RED};
            }}
            QPushButton.link {{
                background: transparent;
                color: {BRAND_PRIMARY};
                border: none;
            }}
        """)


class _QueueIODevice(QIODevice):
    """Minimal QIODevice sink that forwards microphone frames to a callback."""

    def __init__(self, chunk_cb, parent=None):
        super().__init__(parent)
        self._chunk_cb = chunk_cb
        self.open(QIODevice.WriteOnly)

    def writeData(self, data: bytes) -> int:  # type: ignore[override]
        if self._chunk_cb and data:
            chunk = bytes(data)
            if chunk:
                self._chunk_cb(chunk)
        return len(data)

    def readData(self, maxlen: int) -> bytes:  # type: ignore[override]
        return b""


class MicrophoneStreamer(QObject):
    """
    Capture microphone audio and stream it through ChatNode in near real time.
    """

    started = pyqtSignal()
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, chat: ChatNode, username: str, parent=None):
        super().__init__(parent)
        self.chat = chat
        self.username = username
        self._queue: queue.Queue[bytes] = queue.Queue(maxsize=64)
        self._audio_input: QAudioInput | None = None
        self._io: _QueueIODevice | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._format: QAudioFormat | None = None
        self._start_ts: float | None = None
        self._stop_requested = False

    def start(self):
        device = QAudioDeviceInfo.defaultInputDevice()
        if device.isNull():
            raise RuntimeError("No microphone input device is available.")
        fmt = self._build_format(device)
        self._format = fmt
        self._audio_input = QAudioInput(device, fmt, self)
        self._audio_input.setBufferSize(fmt.sampleRate() * fmt.channelCount())
        self._io = _QueueIODevice(self._enqueue_chunk, parent=self)
        self._audio_input.start(self._io)
        self._start_ts = time.perf_counter()

        self._thread = threading.Thread(target=self._stream_loop, daemon=True)
        self._thread.start()
        self.started.emit()

    def stop(self):
        if self._stop_requested:
            return
        self._stop_requested = True
        self._stop.set()
        if self._audio_input:
            self._audio_input.stop()
        if self._io:
            self._io.close()

    def duration_seconds(self) -> float:
        if not self._start_ts:
            return 0.0
        return max(0.0, time.perf_counter() - self._start_ts)

    def _build_format(self, device: QAudioDeviceInfo) -> QAudioFormat:
        fmt = QAudioFormat()
        fmt.setSampleRate(16000)
        fmt.setChannelCount(1)
        fmt.setSampleSize(16)
        fmt.setCodec("audio/pcm")
        fmt.setByteOrder(QAudioFormat.LittleEndian)
        fmt.setSampleType(QAudioFormat.SignedInt)
        if not device.isFormatSupported(fmt):
            fmt = device.nearestFormat(fmt)
        return fmt

    def _enqueue_chunk(self, chunk: bytes):
        if not chunk:
            return
        try:
            self._queue.put_nowait(chunk)
        except queue.Full:
            # Drop the chunk if the network thread is briefly busy.
            pass

    def _stream_loop(self):
        try:
            if not self._format:
                raise RuntimeError("Audio format not initialized.")
            self.chat.send_voice_stream(
                self.username,
                self._chunk_iter(),
                sample_rate=self._format.sampleRate(),
                channels=self._format.channelCount(),
                sample_width=max(1, self._format.sampleSize() // 8),
                name="voice_note.raw"
            )
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))
        else:
            self.finished.emit()

    def _chunk_iter(self):
        while not self._stop.is_set() or not self._queue.empty():
            try:
                chunk = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if chunk:
                yield chunk


class VoiceRecorderDialog(QDialog):
    """Modal dialog that records microphone audio and streams it to the peer."""

    def __init__(self, parent, chat: ChatNode, username: str):
        super().__init__(parent)
        self.setWindowTitle("Send Voice Note")
        self.setModal(True)
        self.chat = chat
        self.username = username
        self.streamer: MicrophoneStreamer | None = None
        self._closing = False

        layout = QVBoxLayout(self)
        self.status_label = QLabel("Opening microphone...")
        layout.addWidget(self.status_label)

        self.timer_label = QLabel("00:00")
        self.timer_label.setAlignment(Qt.AlignCenter)
        self.timer_label.setStyleSheet("font-size: 28px; font-weight: 600;")
        layout.addWidget(self.timer_label)

        self.stop_btn = QPushButton("Stop & Send")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_recording)
        layout.addWidget(self.stop_btn)

        note = QLabel("Recording is live. Use the button above to stop and send.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{TEXT_MUTED};")
        layout.addWidget(note)

        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self._update_timer)

        QTimer.singleShot(0, self._start_streaming)

    def _start_streaming(self):
        streamer = MicrophoneStreamer(self.chat, self.username, self)
        streamer.started.connect(self._on_started)
        streamer.finished.connect(self._on_finished)
        streamer.error.connect(self._on_error)
        try:
            streamer.start()
        except RuntimeError as e:
            QMessageBox.warning(self, "Voice Note", str(e))
            self.reject()
            return
        self.streamer = streamer

    def _on_started(self):
        self.status_label.setText("Recording...")
        self.stop_btn.setEnabled(True)
        self.timer.start()

    def _on_finished(self):
        self.timer.stop()
        self.status_label.setText("Voice note sent.")
        self.timer_label.setText("Done")
        self.stop_btn.setEnabled(False)
        if not self._closing:
            self._closing = True
            QTimer.singleShot(600, self.accept)

    def _on_error(self, message: str):
        self.timer.stop()
        QMessageBox.warning(self, "Voice Note", message)
        self.reject()

    def _update_timer(self):
        if not self.streamer:
            self.timer_label.setText("00:00")
            return
        seconds = int(self.streamer.duration_seconds())
        minutes = seconds // 60
        secs = seconds % 60
        self.timer_label.setText(f"{minutes:02d}:{secs:02d}")

    def stop_recording(self):
        if not self.streamer:
            self.reject()
            return
        self.stop_btn.setEnabled(False)
        self.status_label.setText("Finishing...")
        self.streamer.stop()

    def closeEvent(self, event):  # noqa: N802
        if self.streamer:
            self.streamer.stop()
        super().closeEvent(event)


class DriverChatHubDialog(QDialog):
    """Display all current driver chats in a modern, card-based view."""

    def __init__(self, parent, driver_name: str, sessions: list[dict], on_open_chat):
        super().__init__(parent)
        self.setObjectName("driverHub")
        self.setWindowTitle("Driver Chats")
        self.setModal(True)
        self.resize(560, 520)
        self.sessions = [s for s in sessions if s.get("chat")]
        self.on_open_chat = on_open_chat

        self.setStyleSheet(f"""
            QDialog#driverHub {{
                background: #f6f4ff;
            }}
            QLabel#hubTitle {{
                font:800 26px 'Segoe UI';
                color:{TEXT_DARK};
            }}
            QLabel#hubSubtitle {{
                color:#7c88b0;
                font:600 14px 'Segoe UI';
            }}
            QPushButton#pillButton {{
                background: transparent;
                border: none;
                padding: 6px 14px;
                border-radius: 16px;
                color:#9aa2c7;
                font-weight:600;
            }}
            QPushButton#pillButton:checked {{
                background: #e3d5ff;
                color: {BRAND_PRIMARY};
            }}
            QPushButton#avatarBtn {{
                border-radius: 30px;
                border: none;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                            stop:0 {BRAND_PRIMARY}, stop:1 {BRAND_DEEP_RED});
                color:white;
                font:700 16px 'Segoe UI';
            }}
            QFrame#hubCard {{
                background:white;
                border-radius:18px;
                border:1px solid #ede9fe;
            }}
            QFrame#chatCard {{
                background:#fdfbff;
                border-radius:16px;
                border:1px solid #ede9fe;
            }}
            QPushButton#openChat {{
                background:{BRAND_PRIMARY};
                color:white;
                border:none;
                border-radius:12px;
                padding:10px 18px;
                font-weight:600;
            }}
            QLabel.chatName {{
                font:700 15px 'Segoe UI';
                color:{TEXT_DARK};
            }}
            QLabel.chatMeta {{
                color:#a0a4c1;
                font:500 13px 'Segoe UI';
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        title = QLabel(f"Hello, {driver_name}")
        title.setObjectName("hubTitle")
        layout.addWidget(title)

        subtitle = QLabel("All chats at a glance")
        subtitle.setObjectName("hubSubtitle")
        layout.addWidget(subtitle)

        pill_row = QHBoxLayout()
        pill_row.setSpacing(8)
        for label in ("All Chats", "Groups", "Contacts"):
            pill = QPushButton(label)
            pill.setCheckable(True)
            pill.setChecked(label == "All Chats")
            pill.setObjectName("pillButton")
            pill_row.addWidget(pill)
        pill_row.addStretch(1)
        layout.addLayout(pill_row)

        avatar_scroll = QScrollArea()
        avatar_scroll.setFixedHeight(100)
        avatar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        avatar_scroll.setWidgetResizable(True)
        avatar_container = QWidget()
        avatar_layout = QHBoxLayout(avatar_container)
        avatar_layout.setContentsMargins(0, 0, 0, 0)
        avatar_layout.setSpacing(14)

        if self.sessions:
            for entry in self.sessions:
                btn = QPushButton(self._initials(entry))
                btn.setFixedSize(60, 60)
                btn.setObjectName("avatarBtn")
                meta = entry.get("meta") or {}
                btn.setToolTip(self._display_name(entry))
                btn.clicked.connect(
                    lambda _, chat=entry["chat"], info=meta: self._open_chat(chat, info)
                )
                avatar_layout.addWidget(btn)
        else:
            placeholder = QLabel("Chats will appear here once you accept rides.")
            placeholder.setStyleSheet("color:#b5b9d8; font-size:13px;")
            avatar_layout.addWidget(placeholder)

        avatar_layout.addStretch(1)
        avatar_scroll.setWidget(avatar_container)
        layout.addWidget(avatar_scroll)

        hub_card = QFrame()
        hub_card.setObjectName("hubCard")
        hub_layout = QVBoxLayout(hub_card)
        hub_layout.setContentsMargins(18, 18, 18, 18)
        hub_layout.setSpacing(12)

        if not self.sessions:
            empty = QLabel("No active chats yet. Accept a ride to start a conversation.")
            empty.setStyleSheet("color:#a0a4c1; font:600 14px 'Segoe UI';")
            hub_layout.addWidget(empty)
        else:
            for entry in self.sessions:
                card = QFrame()
                card.setObjectName("chatCard")
                card_layout = QHBoxLayout(card)
                card_layout.setContentsMargins(16, 12, 16, 12)
                card_layout.setSpacing(12)

                info_box = QVBoxLayout()
                name_lbl = QLabel(self._display_name(entry))
                name_lbl.setProperty("class", "chatName")
                meta_lbl = QLabel(self._meta_line(entry))
                meta_lbl.setProperty("class", "chatMeta")
                info_box.addWidget(name_lbl)
                info_box.addWidget(meta_lbl)
                card_layout.addLayout(info_box, 1)

                btn_open = QPushButton("Open Chat")
                btn_open.setObjectName("openChat")
                meta = entry.get("meta") or {}
                btn_open.clicked.connect(
                    lambda _, chat=entry["chat"], info=meta: self._open_chat(chat, info)
                )
                card_layout.addWidget(btn_open, 0, Qt.AlignRight)

                hub_layout.addWidget(card)

        hub_layout.addStretch(1)
        layout.addWidget(hub_card)

    def _initials(self, entry: dict) -> str:
        meta = entry.get("meta") or {}
        name = meta.get("passenger_name") or f"#{entry['chat'].get('passenger_id', '?')}"
        parts = [p for p in name.split() if p]
        if not parts:
            return "P"
        if len(parts) == 1:
            return parts[0][:2].upper()
        return (parts[0][0] + parts[1][0]).upper()

    def _display_name(self, entry: dict) -> str:
        meta = entry.get("meta") or {}
        return meta.get("passenger_name") or f"Passenger #{entry['chat'].get('passenger_id', '?')}"

    def _meta_line(self, entry: dict) -> str:
        meta = entry.get("meta") or {}
        time_text = meta.get("requested_time") or "Time TBD"
        area = meta.get("area") or "Unknown area"
        return f"{time_text}  -  {area}"

    def _open_chat(self, chat: dict, info: Optional[dict]):
        if self.on_open_chat:
            self.on_open_chat(chat, info or {})
        self.accept()


class ImageBubble(QFrame):
    """Display an inline image preview with caption metadata."""

    def __init__(self, path: str, sender_name: str, meta_text: str, is_self: bool):
        super().__init__()
        self.setObjectName("imageBubble")
        self._path = path
        self.is_self = is_self
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        caption = QLabel(sender_name or "Image")
        caption.setWordWrap(True)
        caption.setAlignment(Qt.AlignLeft)
        caption.setStyleSheet("font-weight:600;")
        layout.addWidget(caption)

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setStyleSheet("background:rgba(0,0,0,0.03); border-radius:8px;")
        layout.addWidget(self.image_label)

        self.meta_label = QLabel(meta_text)
        self.meta_label.setWordWrap(True)
        self.meta_label.setStyleSheet("color:#7c84a0; font-size:12px;")
        layout.addWidget(self.meta_label)

        self._load_image()
        self._apply_style()

    def _load_image(self):
        pix = QPixmap(self._path)
        if pix.isNull():
            self.image_label.setText("Image unavailable")
            self.image_label.setStyleSheet("color:#a0a0a0; font-style:italic;")
            return
        max_width = 260
        if pix.width() > max_width:
            pix = pix.scaledToWidth(max_width, Qt.SmoothTransformation)
        self.image_label.setPixmap(pix)

    def _apply_style(self):
        if self.is_self:
            self.setStyleSheet("""
                QFrame#imageBubble {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                                stop:0 #8b1e3f, stop:1 #4a0f23);
                    border-radius: 18px;
                }
                QFrame#imageBubble QLabel {
                    color: white;
                }
                QFrame#imageBubble QLabel[objectName="meta"] {
                    color: rgba(255,255,255,0.8);
                }
            """)
            self.meta_label.setObjectName("meta")
            self.meta_label.setStyleSheet("color:rgba(255,255,255,0.8); font-size:12px;")
            self.image_label.setStyleSheet("background:rgba(255,255,255,0.15); border-radius:8px;")
        else:
            self.setStyleSheet("""
                QFrame#imageBubble {
                    background:white;
                    border-radius:18px;
                    border:1px solid #efeafc;
                }
                QFrame#imageBubble QLabel {
                    color:#1f1b2e;
                }
            """)
            self.meta_label.setStyleSheet("color:#7c84a0; font-size:12px;")


class VoiceNoteBubble(QFrame):
    """Stylized, looping playback control for received voice notes."""

    def __init__(self, path: str, sender_name: str, meta_text: str, is_self: bool):
        super().__init__()
        self.setObjectName("voiceBubble")
        self.sender_name = (sender_name or "").strip()
        self.meta_text = (meta_text or "").strip()
        self.is_self = is_self
        self._loop_active = False
        self._user_stop = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(12)

        self.play_btn = QPushButton("Play")
        self.play_btn.setCursor(Qt.PointingHandCursor)
        self.play_btn.setMinimumWidth(80)
        self.play_btn.clicked.connect(self.toggle_playback)
        layout.addWidget(self.play_btn, 0)

        text_box = QVBoxLayout()
        text_box.setContentsMargins(0, 0, 0, 0)
        text_box.setSpacing(2)
        self.title_label = QLabel(self._title_text())
        self.title_label.setWordWrap(False)
        self.meta_label = QLabel(self.meta_text or "Tap to listen")
        self.meta_label.setWordWrap(False)
        text_box.addWidget(self.title_label)
        text_box.addWidget(self.meta_label)
        layout.addLayout(text_box, 1)
        layout.addStretch(1)

        resolved = Path(path).expanduser()
        try:
            resolved = resolved.resolve()
        except Exception:
            pass
        self.audio_path = str(resolved)
        self._media_ready = resolved.exists()

        self.player = QMediaPlayer(self)
        self.player.setVolume(100)
        self.player.stateChanged.connect(self._sync_state)

        if self._media_ready:
            media = QMediaContent(QUrl.fromLocalFile(self.audio_path))
            self.player.setMedia(media)
            self.setToolTip(Path(self.audio_path).name)
        else:
            self.play_btn.setEnabled(False)
            self.meta_label.setText("Voice note unavailable")
            self.setToolTip("Audio file missing")

        self._apply_style()

    def _title_text(self) -> str:
        if self.is_self:
            return "Your voice note"
        if self.sender_name:
            return f"{self.sender_name}'s voice"
        return "Voice note"

    def _apply_style(self):
        if self.is_self:
            self.setStyleSheet("""
                QFrame#voiceBubble {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                                stop:0 #8b1e3f, stop:1 #4a0f23);
                    border-radius: 20px;
                }
                QFrame#voiceBubble QPushButton {
                    background: rgba(255, 255, 255, 0.2);
                    color: white;
                    border: none;
                    padding: 8px 18px;
                    border-radius: 18px;
                    font-weight: 600;
                }
                QFrame#voiceBubble QPushButton:disabled {
                    color: rgba(255, 255, 255, 0.5);
                }
            """)
            self.title_label.setStyleSheet("color:white; font-weight:600;")
            self.meta_label.setStyleSheet("color:rgba(255,255,255,0.8); font-size:12px;")
        else:
            self.setStyleSheet("""
                QFrame#voiceBubble {
                    background: white;
                    border-radius: 18px;
                    border: 1px solid #efeafc;
                }
                QFrame#voiceBubble QPushButton {
                    background: #f0ecff;
                    color: #4a0f23;
                    border: none;
                    padding: 8px 18px;
                    border-radius: 18px;
                    font-weight: 600;
                }
            """)
            self.title_label.setStyleSheet("color:#1f1b2e; font-weight:600;")
            self.meta_label.setStyleSheet("color:#7c84a0; font-size:12px;")

    def toggle_playback(self):
        if not self._media_ready:
            return
        if self.player.state() == QMediaPlayer.PlayingState:
            self._loop_active = False
            self._user_stop = True
            self.player.stop()
        else:
            self._loop_active = True
            self._user_stop = False
            self.player.setPosition(0)
            self.player.play()

    def _sync_state(self, state: QMediaPlayer.State):
        if state == QMediaPlayer.PlayingState:
            self.play_btn.setText("Stop")
        else:
            self.play_btn.setText("Play")
        if state == QMediaPlayer.StoppedState:
            if self._loop_active and not self._user_stop:
                self.player.setPosition(0)
                self.player.play()
                return
            self._user_stop = False


class ChatBubbleBoard(QFrame):
    """Scrollable list of stylized chat bubbles."""

    def __init__(self, self_username: str):
        super().__init__()
        self.self_username = self_username
        self._self_lower = (self_username or "").lower()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setFrameShape(QFrame.NoFrame)
        layout.addWidget(self.scroll)

        self.container = QWidget()
        self.vbox = QVBoxLayout(self.container)
        self.vbox.setContentsMargins(0, 0, 0, 0)
        self.vbox.setSpacing(10)
        self.vbox.addStretch(1)
        self.scroll.setWidget(self.container)

    def append_line(self, line: str):
        if not line:
            return
        clean = line.strip()
        if clean.startswith(IMAGE_UI_PREFIX):
            payload = clean[len(IMAGE_UI_PREFIX):]
            try:
                info = json.loads(payload)
            except Exception:
                return
            self._append_image(info)
            return
        if clean.startswith(VOICE_UI_PREFIX):
            payload = clean[len(VOICE_UI_PREFIX):]
            try:
                info = json.loads(payload)
            except Exception:
                return
            self._append_voice(info)
            return

        bubble_type, text = self._classify(clean)
        bubble = QLabel(text)
        bubble.setWordWrap(True)
        bubble.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextBrowserInteraction)
        bubble.setOpenExternalLinks(True)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        if bubble_type == "status":
            bubble.setAlignment(Qt.AlignCenter)
            bubble.setStyleSheet("color:#9aa9c6; font:600 12px 'Segoe UI';")
            row.addStretch(1)
            row.addWidget(bubble)
            row.addStretch(1)
        elif bubble_type == "self":
            bubble.setStyleSheet("""
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                            stop:0 #8b1e3f, stop:1 #4a0f23);
                color:white;
                padding:10px 16px;
                border-radius:20px;
                font:500 14px 'Segoe UI';
            """)
            row.addStretch(1)
            row.addWidget(bubble, 0, Qt.AlignRight)
        else:
            bubble.setStyleSheet("""
                background:white;
                color:#1f1b2e;
                padding:10px 16px;
                border-radius:18px;
                font:500 14px 'Segoe UI';
            """)
            row.addWidget(bubble, 0, Qt.AlignLeft)
            row.addStretch(1)
        if bubble_type == "self":
            row.setAlignment(Qt.AlignRight)

        self._add_row(row)

    def _append_image(self, info: dict):
        path = info.get("path")
        if not path:
            return
        sender = (info.get("sender") or "").strip()
        sender_lower = sender.lower()
        is_self = bool(sender_lower and sender_lower == self._self_lower)
        display_name = "You" if is_self else (sender or "Image")
        size_bytes = info.get("bytes") or 0
        try:
            size_bytes = int(size_bytes)
        except (TypeError, ValueError):
            size_bytes = 0
        meta_parts = []
        file_name = info.get("name")
        if file_name:
            meta_parts.append(file_name)
        if size_bytes > 0:
            meta_parts.append(f"{size_bytes / 1024:.0f} KB")
        meta_text = " - ".join(meta_parts)
        bubble = ImageBubble(path, display_name, meta_text, is_self)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        if is_self:
            row.addStretch(1)
            row.addWidget(bubble, 0, Qt.AlignRight)
        else:
            row.addWidget(bubble, 0, Qt.AlignLeft)
            row.addStretch(1)
        self._add_row(row)

    def _append_voice(self, info: dict):
        path = info.get("path")
        if not path:
            return
        sender = (info.get("sender") or "").strip()
        sender_lower = sender.lower()
        is_self = bool(sender_lower and sender_lower == self._self_lower)
        duration = 0.0
        try:
            duration = float(info.get("duration") or 0.0)
        except (TypeError, ValueError):
            duration = 0.0
        size_bytes = info.get("bytes") or 0
        try:
            size_bytes = int(size_bytes)
        except (TypeError, ValueError):
            size_bytes = 0
        details = []
        if duration > 0:
            details.append(f"{duration:.1f}s")
        if size_bytes > 0:
            details.append(f"{size_bytes / 1024:.0f} KB")
        meta_text = " - ".join(details)
        bubble = VoiceNoteBubble(path, sender, meta_text, is_self)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        if is_self:
            row.addStretch(1)
            row.addWidget(bubble, 0, Qt.AlignRight)
        else:
            row.addWidget(bubble, 0, Qt.AlignLeft)
            row.addStretch(1)
        self._add_row(row)

    def _classify(self, line: str) -> tuple[str, str]:
        if not line:
            return "status", ""
        if line.startswith("[") and "]" in line.split(" ", 1)[0]:
            return "status", line
        prefix = f"{self.self_username}>"
        if line.startswith(prefix):
            payload = line[len(prefix):].strip()
            return "self", payload or line
        if "> " in line:
            _, payload = line.split("> ", 1)
            return "peer", payload
        return "peer", line

    def _add_row(self, row: QHBoxLayout):
        self.vbox.insertLayout(self.vbox.count() - 1, row)
        QTimer.singleShot(0, lambda: self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().maximum()
        ))


# LOGIN PAGE

class LoginPage(QWidget):
    def __init__(self, controller: "MainWindow"):
        super().__init__()
        self.controller = controller

        root = QHBoxLayout(self)
        root.setContentsMargins(48, 32, 48, 32)
        root.setSpacing(42)

        hero = _build_auth_hero(
            "Welcome back to AUB Carpool",
            "Sign in to coordinate rides, stay updated with your match, "
            "and keep the commute stress-free."
        )
        root.addWidget(hero, 1)

        form_shell = Card()
        form_shell.setMinimumWidth(400)
        form_shell.setMaximumWidth(520)
        form_layout = QVBoxLayout(form_shell)
        form_layout.setSpacing(18)

        heading = QLabel("Sign in")
        heading.setStyleSheet("font:800 28px 'Segoe UI'; color:#1f1b2e;")
        description = QLabel("Use your ride credentials to continue")
        description.setStyleSheet(f"color:{TEXT_MUTED}; font:500 14px 'Segoe UI';")
        form_layout.addWidget(heading)
        form_layout.addWidget(description)

        form = QFormLayout()
        form.setSpacing(12)
        form.setLabelAlignment(Qt.AlignLeft)

        self.email = QLineEdit()
        self.email.setPlaceholderText("Email or username")
        self.email.setValidator(QRegularExpressionValidator(EMAIL_RE))

        self.pw = QLineEdit()
        self.pw.setEchoMode(QLineEdit.Password)

        show = QCheckBox("Show password")
        show.stateChanged.connect(
            lambda s: self.pw.setEchoMode(QLineEdit.Normal if s else QLineEdit.Password)
        )

        pw_row = QWidget()
        pw_l = QHBoxLayout(pw_row)
        pw_l.setContentsMargins(0, 0, 0, 0)
        pw_l.addWidget(self.pw, 1)
        pw_l.addWidget(show, 0)

        form.addRow("Email/Username", self.email)
        form.addRow("Password", pw_row)
        form_layout.addLayout(form)

        self.error = QLabel("")
        self.error.setStyleSheet(f"color:{BRAND_PRIMARY}; font-weight:600;")
        form_layout.addWidget(self.error)

        btn_login = QPushButton("Sign in")
        btn_login.setCursor(Qt.PointingHandCursor)
        btn_login.setStyleSheet("font-size:16px; padding:14px; border-radius:14px;")
        btn_login.clicked.connect(self.on_login)
        form_layout.addWidget(btn_login)

        footer = QHBoxLayout()
        ask = QLabel("New to AUB Carpool?")
        ask.setStyleSheet(f"color:{TEXT_MUTED}; font:500 13px 'Segoe UI';")
        link_reg = QPushButton("Create an account")
        link_reg.setProperty("class", "link")
        link_reg.setStyleSheet(f"color:{BRAND_PRIMARY}; font-weight:600;")
        link_reg.setCursor(Qt.PointingHandCursor)
        link_reg.clicked.connect(lambda: self.controller.goto("register"))
        footer.addWidget(ask)
        footer.addWidget(link_reg)
        footer.addStretch(1)
        form_layout.addLayout(footer)

        root.addWidget(form_shell, 1, Qt.AlignVCenter)

    def on_login(self):
        ident = self.email.text().strip()
        pw = self.pw.text()

        payload = {"email": ident, "password": pw} if EMAIL_RE.match(ident) else {
            "username": ident,
            "password": pw
        }

        reply = net.send_request("login", payload)

        if reply.get("ok"):
            # Store the logged-in user info
            self.controller.current_user = reply

            # Ask drivers for a schedule only if they don't already have one
            if reply.get("is_driver"):
                schedule_reply = net.send_request("get_schedule", {
                    "user_id": reply["user_id"]
                })
                existing_schedule = schedule_reply.get("schedule") if schedule_reply.get("ok", True) else None
                if not existing_schedule:
                    dlg = ScheduleDialog(driver_id=reply["user_id"], parent=self)
                    dlg.exec_()

            QMessageBox.information(self, "Login", f"Welcome, {reply['username']}!")
            self.controller.dashboard.set_user(reply["username"])
            self.controller.goto("dashboard")
        else:
            self.error.setText(reply.get("msg", "Login failed"))

    def on_show(self):
        self.email.clear()
        self.pw.clear()
        self.error.clear()



# REGISTER PAGE

class RegisterPage(QWidget):
    def __init__(self, controller: "MainWindow"):
        super().__init__()
        self.controller = controller

        root = QHBoxLayout(self)
        root.setContentsMargins(48, 32, 48, 32)
        root.setSpacing(42)

        hero = _build_auth_hero(
            "Create your shared ride profile",
            "Join the AUB community of drivers and passengers working together "
            "to reduce traffic and commute smarter."
        )
        root.addWidget(hero, 1)

        card = Card()
        card.setMinimumWidth(420)
        card.setMaximumWidth(560)
        form_wrap = QVBoxLayout(card)
        form_wrap.setSpacing(18)

        head = QLabel("Create account")
        head.setStyleSheet("font:800 26px 'Segoe UI'; color:#1f1b2e;")
        sub = QLabel("Tell us who you are to match with the right rides")
        sub.setStyleSheet(f"color:{TEXT_MUTED}; font:500 14px 'Segoe UI';")
        form_wrap.addWidget(head)
        form_wrap.addWidget(sub)

        form = QFormLayout()
        form.setSpacing(12)
        form.setLabelAlignment(Qt.AlignLeft)

        self.username = QLineEdit()
        self.username.setPlaceholderText("Choose a handle passengers will see")
        self.email = QLineEdit()
        self.email.setPlaceholderText("you@aub.edu.lb")
        self.email.setValidator(QRegularExpressionValidator(EMAIL_RE))
        self.pw = QLineEdit()
        self.pw.setEchoMode(QLineEdit.Password)
        self.pw2 = QLineEdit()
        self.pw2.setEchoMode(QLineEdit.Password)

        show = QCheckBox("Show passwords")
        show.stateChanged.connect(lambda s: [
            self.pw.setEchoMode(QLineEdit.Normal if s else QLineEdit.Password),
            self.pw2.setEchoMode(QLineEdit.Normal if s else QLineEdit.Password)
        ])

        form.addRow("Username", self.username)
        form.addRow("Email", self.email)
        form.addRow("Password", self.pw)
        form.addRow("Confirm", self.pw2)
        form.addRow("", show)

        self.type = QComboBox()
        self.type.addItems(["Passenger", "Driver"])
        form.addRow("Account type", self.type)

        form_wrap.addLayout(form)

        self.info = QLabel("")
        self.info.setStyleSheet(f"color:{BRAND_PRIMARY}; font-weight:600;")
        form_wrap.addWidget(self.info)

        btn_reg = QPushButton("Create my account")
        btn_reg.setCursor(Qt.PointingHandCursor)
        btn_reg.setStyleSheet("font-size:16px; padding:14px; border-radius:14px;")
        btn_reg.clicked.connect(self.on_register)
        form_wrap.addWidget(btn_reg)

        back = QHBoxLayout()
        prompt = QLabel("Already have an account?")
        prompt.setStyleSheet(f"color:{TEXT_MUTED}; font:500 13px 'Segoe UI';")
        link = QPushButton("Back to login")
        link.setProperty("class", "link")
        link.setCursor(Qt.PointingHandCursor)
        link.setStyleSheet(f"color:{BRAND_PRIMARY}; font-weight:600;")
        link.clicked.connect(lambda: self.controller.goto("login"))
        back.addWidget(prompt)
        back.addWidget(link)
        back.addStretch(1)
        form_wrap.addLayout(back)

        root.addWidget(card, 1, Qt.AlignVCenter)

    def on_register(self):
        u = self.username.text().strip()
        e = self.email.text().strip()
        p = self.pw.text()
        p2 = self.pw2.text()

        if p != p2:
            self.info.setText("Passwords do not match")
            return

        reply = net.send_request("register", {
            "username": u,
            "email": e,
            "password": p,
            "is_driver": self.type.currentText() == "Driver"
        })

        if not reply.get("ok"):
            self.info.setText(reply.get("msg"))
            return

        QMessageBox.information(self, "Register", "Account created!")
        self.controller.goto("login")

    def on_show(self):
        pass



# DRIVER SCHEDULE DIALOG

class ScheduleDialog(QDialog):
    """Modal dialog shown after driver login to capture their commute details."""
    def __init__(self, driver_id: int, parent: QWidget | None = None):
        super().__init__(parent)
        self.driver_id = driver_id

        self.setWindowTitle("Setup Driving Schedule")
        self.setModal(True)
        self.setFixedSize(460, 360)

        frame = QFrame()
        frame.setStyleSheet(f"""
            background:{BRAND_LIGHT};
            border:1px solid #f0d0de;
            border-radius:16px;
        """)

        layout = QVBoxLayout(frame)
        title = QLabel("Add Your Commute Time")
        title.setStyleSheet(f"font:600 18px 'Segoe UI'; color:{BRAND_PRIMARY};")
        layout.addWidget(title)

        subtitle = QLabel(
            "Add at least one time when you usually drive so that passengers\n"
            "can be matched to you."
        )
        subtitle.setStyleSheet(f"color:{TEXT_MUTED}; font-size:12px;")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)

        # Route (direction)
        self.route_box = QComboBox()
        self.route_box.addItems(["Home -> AUB", "AUB -> Home"])
        form.addRow("Route:", self.route_box)

        areas = [
            "Hamra", "Achrafieh", "Verdun", "Mar Mikhael", "Gemmayzeh",
            "Ras Beirut", "Ain El Mreisseh", "Tayouneh", "Badaro",
            "Furn El Chebbak", "Kantari", "Karantina", "Jnah",
            "Ain El Remmaneh", "Hazmieh"
        ]

        self.area_label = QLabel()
        self.area_box = QComboBox()
        self.area_box.setEditable(True)
        self.area_box.addItems(areas)
        self.area_box.setFixedWidth(200)

        def update_area_label():
            route = self.route_box.currentText()
            self.area_label.setText("Home / Pickup Area:" if route.startswith("Home") else "Drop-off Area:")

        self.route_box.currentTextChanged.connect(lambda _: update_area_label())
        update_area_label()

        form.addRow(self.area_label, self.area_box)

        # Time (HH:MM) using combos similar to passenger request dialog
        hours = [f"{h:02d}" for h in range(0, 24)]
        minutes = ["00", "15", "30", "45"]

        self.hour_box = QComboBox()
        self.hour_box.addItems(hours)
        self.hour_box.setFixedWidth(85)

        self.minute_box = QComboBox()
        self.minute_box.addItems(minutes)
        self.minute_box.setFixedWidth(85)

        colon = QLabel(":")
        colon.setStyleSheet("font-size:18px; color:#e5e7eb;")
        colon.setAlignment(Qt.AlignCenter)
        colon.setFixedWidth(12)

        time_row = QHBoxLayout()
        time_row.addWidget(self.hour_box)
        time_row.addSpacing(4)
        time_row.addWidget(colon)
        time_row.addSpacing(4)
        time_row.addWidget(self.minute_box)

        form.addRow("Departure Time:", time_row)

        # Seats
        self.seats_box = QSpinBox()
        self.seats_box.setRange(1, 4)
        self.seats_box.setValue(2)
        form.addRow("Seats available:", self.seats_box)

        # Optional days
        self.days_field = QLineEdit()
        self.days_field.setPlaceholderText("Optional e.g. Mon-Fri")
        form.addRow("Days (optional):", self.days_field)

        layout.addLayout(form)

        note = QLabel(
            "Passengers only see you when their request matches this route, area, "
            "and is within +/-30 minutes of your selected time."
        )
        note.setStyleSheet(f"color:{TEXT_MUTED}; font-size:12px;")
        note.setWordWrap(True)
        layout.addWidget(note)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.btn_save = QPushButton("Save & Continue")
        self.btn_save.setCursor(Qt.PointingHandCursor)
        self.btn_save.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                            stop:0 {BRAND_PRIMARY}, stop:1 {BRAND_DEEP_RED});
                color:white;
                padding:10px 18px;
                border-radius:10px;
                font-weight:600;
            }}
            QPushButton:pressed {{
                background:{BRAND_DEEP_RED};
            }}
        """)
        self.btn_save.clicked.connect(self.on_save)
        btn_row.addWidget(self.btn_save)
        layout.addLayout(btn_row)

        outer = QVBoxLayout(self)
        outer.addWidget(frame)

    def on_save(self):
        hh = self.hour_box.currentText()
        mm = self.minute_box.currentText()
        depart_time = f"{hh}:{mm}"
        route = self.route_box.currentText()
        seats_total = int(self.seats_box.value())
        days = self.days_field.text().strip()
        area = self.area_box.currentText().strip()

        if not area:
            QMessageBox.warning(self, "Missing Area", "Please provide the area associated with this route.")
            return

        reply = net.send_request("add_schedule", {
            "user_id": self.driver_id,
            "depart_time": depart_time,
            "route": route,
            "seats_total": seats_total,
            "days": days,
            "area": area
        })

        if reply.get("ok"):
            QMessageBox.information(self, "Schedule", "Schedule saved successfully.")
            self.accept()
        else:
            QMessageBox.warning(self, "Schedule", reply.get("msg", "Failed to save schedule."))


class RatingDialog(QDialog):
    """Prompt presented when finishing a ride to collect a quick rating."""
    def __init__(self, peer_label: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Rate your ride")
        self.setModal(True)
        self.setFixedSize(360, 260)

        layout = QVBoxLayout(self)
        prompt = QLabel(f"Please rate {peer_label} (1-5 stars).")
        prompt.setWordWrap(True)
        layout.addWidget(prompt)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(1, 5)
        self.slider.setValue(5)
        layout.addWidget(self.slider)

        self.value_label = QLabel("5 *")
        self.slider.valueChanged.connect(lambda v: self.value_label.setText(f"{v} *"))
        layout.addWidget(self.value_label)

        note = QLabel("Optional comment:")
        layout.addWidget(note)

        self.comment_box = QPlainTextEdit()
        self.comment_box.setPlaceholderText("Share any quick feedback (optional)")
        layout.addWidget(self.comment_box, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_rating(self) -> tuple[int, str]:
        return self.slider.value(), self.comment_box.toPlainText().strip()



# DASHBOARD PAGE

class DashboardPage(QWidget):
    def __init__(self, controller: "MainWindow"):
        super().__init__()
        self.controller = controller

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(18, 18, 18, 18)
        self.main_layout.setSpacing(18)

        # Top nav
        nav = QFrame()
        nav.setObjectName("navBar")
        nav.setStyleSheet(f"""
            QFrame#navBar {{
                background: #F9E0D9;
                border: 1px solid #e7c7bf;
                border-radius: 14px;
                padding: 10px 14px;
            }}
            QPushButton[nav=\"true\"] {{
                background: rgba(1, 23, 47, 0.06);
                color: {TEXT_DARK};
                border: 1px solid rgba(1, 23, 47, 0.08);
                border-radius: 10px;
                padding: 8px 14px;
                font:700 13px 'Segoe UI';
            }}
            QPushButton[nav=\"true\"]:checked {{
                background: white;
                border: 1px solid {BRAND_DEEP_RED};
                color: {BRAND_DEEP_RED};
            }}
            QPushButton#logoutNav {{
                background: {BRAND_DEEP_RED};
                color: white;
                border: none;
                border-radius: 10px;
                padding: 10px 16px;
                font:800 13px 'Segoe UI';
            }}
            QPushButton#logoutNav:pressed {{
                background: #4b0b1c;
            }}
        """)
        nav_lay = QHBoxLayout(nav)
        nav_lay.setContentsMargins(8, 6, 8, 6)
        nav_lay.setSpacing(12)

        self.logo = QLabel()
        self.logo.setPixmap(_brand_logo_pixmap(220).scaledToHeight(56, Qt.SmoothTransformation))
        self.logo.setFixedHeight(64)
        self.logo.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        nav_lay.addWidget(self.logo, 0, Qt.AlignLeft | Qt.AlignVCenter)

        self.home_btn = QPushButton("Home")
        self.home_btn.setProperty("nav", "true")
        self.home_btn.setCheckable(True)
        self.home_btn.clicked.connect(lambda: self.show_section("home"))
        nav_lay.addWidget(self.home_btn, 0, Qt.AlignVCenter)

        self.primary_nav_btn = QPushButton("")
        self.primary_nav_btn.setProperty("nav", "true")
        self.primary_nav_btn.setCheckable(True)
        self.primary_nav_btn.clicked.connect(self._on_primary_nav_clicked)
        self.primary_nav_btn.setText("Offer a ride")
        nav_lay.addWidget(self.primary_nav_btn, 0, Qt.AlignVCenter)

        nav_lay.addStretch(1)

        self.fun_link = QLabel('<a style="text-decoration:none;" href="https://flappybird.io">🐦 Play Flappy Bird</a>')
        self.fun_link.setStyleSheet("font:800 14px 'Segoe UI'; color:#01172F;")
        self.fun_link.setOpenExternalLinks(True)
        nav_lay.addWidget(self.fun_link, 0, Qt.AlignVCenter)

        self.weather_label = QLabel("🌤 Weather  -  updating...")
        self.weather_label.setStyleSheet("color:#01172F; font:800 14px 'Segoe UI'; padding: 8px 12px;"
                                         "background: rgba(1, 23, 47, 0.06); border-radius: 12px;"
                                         "border: 1px solid rgba(1, 23, 47, 0.08);")
        nav_lay.addWidget(self.weather_label, 0, Qt.AlignVCenter)

        self.logout_nav_btn = QPushButton("Logout")
        self.logout_nav_btn.setObjectName("logoutNav")
        self.logout_nav_btn.clicked.connect(lambda: self.controller.goto("login"))
        nav_lay.addWidget(self.logout_nav_btn, 0, Qt.AlignVCenter)

        self.main_layout.addWidget(nav)

        # Card container
        self.card = Card()
        self.card.setMaximumWidth(660)
        self.card_box = QVBoxLayout(self.card)
        self.card_box.setContentsMargins(22, 22, 22, 22)
        self.card_box.setSpacing(20)
        self.main_layout.addWidget(self.card, alignment=Qt.AlignHCenter)
        self.main_layout.addStretch()

        # Welcome label
        self.welcome = QLabel("")
        self.welcome.setStyleSheet("font:700 20px 'Segoe UI'; color:white;")
        self.card_box.addWidget(self.welcome)

        # Dynamic area (passenger actions or driver requests)
        self.dynamic_area = QVBoxLayout()
        self.dynamic_area.setSpacing(18)
        self.dynamic_area.setContentsMargins(4, 8, 4, 8)
        self.card_box.addLayout(self.dynamic_area)

        self.driver_passenger_rating_filter = 0.0
        self.active_driver_chat = None
        self.active_passenger_chat = None
        self.driver_chat_sessions = {}
        self.chat_windows = {}
        self.active_section = "home"
        self._weather_refresh_ms = 15 * 60 * 1000
        self._weather_request_active = False

        
        # AUTO-REFRESH FOR DRIVERS
        
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.refresh_driver_if_needed)
        self.refresh_timer.start(2000)
        self.fetch_weather()

    def _update_nav_labels(self):
        user = self.controller.current_user or {}
        is_driver = user.get("is_driver", 0) == 1
        self.primary_nav_btn.setText("Offer a ride" if is_driver else "Find a ride")
        self.home_btn.setChecked(self.active_section == "home")
        self.primary_nav_btn.setChecked(self.active_section in ("driver", "passenger"))

    def _on_primary_nav_clicked(self):
        user = self.controller.current_user or {}
        is_driver = user.get("is_driver", 0) == 1
        target = "driver" if is_driver else "passenger"
        self.show_section(target)

    def show_section(self, section: str):
        self.active_section = section
        self._update_nav_labels()
        self.refresh_dashboard(section_override=section)

    def _build_home_hero(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("homeHero")
        frame.setStyleSheet(f"""
            QFrame#homeHero {{
                background: rgba(249, 224, 217, 0.9);
                border: 1px solid #e7c7bf;
                border-radius: 18px;
                padding: 22px;
            }}
            QFrame#homeHero QLabel#title {{
                font:800 26px 'Segoe UI';
                color:{BRAND_DEEP_RED};
            }}
            QFrame#homeHero QLabel#pill {{
                background: rgba(1, 23, 47, 0.06);
                color:{TEXT_DARK};
                padding: 8px 12px;
                border-radius: 12px;
                font:700 13px 'Segoe UI';
                border: 1px solid rgba(1, 23, 47, 0.08);
            }}
            QFrame#homeHero QLabel#muted {{
                color:{TEXT_MUTED};
                font:600 13px 'Segoe UI';
            }}
            QFrame#homeHero QLabel#item {{
                color:{TEXT_DARK};
                font:700 14px 'Segoe UI';
            }}
        """)

        layout = QVBoxLayout(frame)
        layout.setSpacing(16)

        title = QLabel("Find Affordable, Safe, and Fast Rides")
        title.setObjectName("title")
        layout.addWidget(title)

        sub = QLabel("Plan smarter commutes with trusted rides across Lebanon.")
        sub.setObjectName("muted")
        layout.addWidget(sub)

        chips = QHBoxLayout()
        chips.setSpacing(10)
        for text in ["Save Money", "Eco-Friendly", "Verified Drivers"]:
            pill = QLabel(text)
            pill.setObjectName("pill")
            chips.addWidget(pill)
        chips.addStretch(1)
        layout.addLayout(chips)

        routes_card = QFrame()
        routes_card.setStyleSheet(f"""
            QFrame {{
                background: white;
                border: 1px solid #e7c7bf;
                border-radius: 14px;
                padding: 12px 14px;
            }}
        """)
        routes_layout = QVBoxLayout(routes_card)
        routes_layout.setContentsMargins(10, 8, 10, 10)
        routes_layout.setSpacing(8)
        routes_title = QLabel("Popular Routes")
        routes_title.setStyleSheet(f"color:{TEXT_DARK}; font:800 15px 'Segoe UI';")
        routes_layout.addWidget(routes_title)
        for route in ["Beirut → Tripoli", "Saida → Beirut", "Jounieh → AUB"]:
            lbl = QLabel(route)
            lbl.setObjectName("item")
            routes_layout.addWidget(lbl)
        layout.addWidget(routes_card)

        return frame

    
    def fetch_weather(self):
        if getattr(self, '_weather_request_active', False):
            return
        self._weather_request_active = True
        self.weather_label.setText('Weather  -  updating...')
        threading.Thread(target=self._weather_worker, daemon=True).start()

    def _weather_worker(self):
        def fetch_open_meteo() -> str:
            url = ("https://api.open-meteo.com/v1/forecast?latitude=33.8938&longitude=35.5018"
                   "&current_weather=true&timezone=auto")
            with urlopen(url, timeout=10) as resp:
                payload = json.loads(resp.read().decode('utf-8'))
            current = payload.get('current_weather') or {}
            temp = current.get('temperature')
            wind = current.get('windspeed')
            code = int(current.get('weathercode', -1)) if current.get('weathercode') is not None else -1
            code_map = {
                0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
                45: "Foggy", 48: "Fog", 51: "Light drizzle", 53: "Drizzle", 55: "Dense drizzle",
                61: "Light rain", 63: "Rain", 65: "Heavy rain",
                71: "Light snow", 73: "Snow", 75: "Heavy snow",
                80: "Rain showers", 81: "Moderate showers", 82: "Heavy showers",
                95: "Thunderstorm", 96: "Thunder & hail", 99: "Severe thunder"
            }
            desc = code_map.get(code, "Weather update")
            bits = [desc]
            if temp is not None:
                bits.append(f"{temp:.1f}°C")
            if wind is not None:
                bits.append(f"Wind {wind:.0f} km/h")
            return 'Weather  -  ' + ' | '.join(bits)

        def fetch_fallback() -> str:
            url = "https://goweather.herokuapp.com/weather/Beirut"
            with urlopen(url, timeout=8) as resp:
                payload = json.loads(resp.read().decode('utf-8'))
            desc = (payload.get('description') or 'Beirut skies').strip().capitalize()
            temp = (payload.get('temperature') or '').strip()
            wind = (payload.get('wind') or '').strip()
            bits = [desc]
            if temp:
                bits.append(temp)
            if wind:
                bits.append(f"Wind {wind}")
            return 'Weather  -  ' + ' | '.join(bits)

        summary = 'Weather  -  unavailable'
        try:
            summary = fetch_open_meteo()
        except Exception:
            try:
                summary = fetch_fallback()
            except Exception:
                summary = 'Weather  -  unavailable'

        def _apply():
            self.weather_label.setText(f"🌤 {summary}")
            self._weather_request_active = False
            QTimer.singleShot(getattr(self, '_weather_refresh_ms', 15 * 60 * 1000), self.fetch_weather)

        QTimer.singleShot(0, _apply)

    def set_user(self, username: str):
        self.welcome.setText(f"Welcome, {username}")
        self.active_section = "home"
        self._update_nav_labels()
        self.refresh_dashboard(section_override="home")

    
    def refresh_dashboard(self, section_override: Optional[str] = None):
        user = self.controller.current_user
        is_driver = user.get("is_driver", 0) == 1
        section = section_override or getattr(self, "active_section", "home")
        if section == "driver" and not is_driver:
            section = "passenger"

        # Clear UI
        while self.dynamic_area.count():
            item = self.dynamic_area.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if section == "home":
            hero = self._build_home_hero()
            self.dynamic_area.addWidget(hero)
        elif section == "driver":
            self.build_driver_dashboard()
        else:
            self.build_passenger_dashboard()

    
    def refresh_driver_if_needed(self):
        user = self.controller.current_user
        if not user:
            return
        if user.get("is_driver", 0) == 1 and getattr(self, "active_section", "home") == "driver":
            self.refresh_dashboard()

    
    # PASSENGER DASHBOARD
    
    def build_passenger_dashboard(self):
        btn_req = QPushButton("Request Ride")
        btn_req.clicked.connect(self.request_ride)

        btn_cancel = QPushButton("Cancel Ride")
        btn_cancel.clicked.connect(self.cancel_ride)

        self.dynamic_area.addWidget(btn_req)
        self.dynamic_area.addWidget(btn_cancel)

        btn_chat = QPushButton("Open Current Chat")
        btn_chat.setEnabled(bool(self.active_passenger_chat))
        btn_chat.clicked.connect(self.open_passenger_chat_dialog)
        self.dynamic_area.addWidget(btn_chat)

    
    # DRIVER DASHBOARD
    
    def build_driver_dashboard(self):
        panel = QFrame()
        panel.setObjectName("driverPanel")
        panel.setStyleSheet(f"""
            QFrame#driverPanel {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                            stop:0 #fffaf8, stop:1 #f6e7e3);
                border: 1px solid #f0cfd7;
                border-radius: 18px;
                padding: 20px;
            }}
            QFrame#driverPanel QLabel#title {{
                font:800 18px 'Segoe UI';
                color:{BRAND_DEEP_RED};
                letter-spacing: 0.4px;
            }}
            QFrame#driverPanel QLabel#muted {{
                color:{TEXT_MUTED};
                font:500 13px 'Segoe UI';
            }}
        """)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(6, 6, 6, 6)
        panel_layout.setSpacing(16)

        title = QLabel("Incoming Ride Requests")
        title.setObjectName("title")
        panel_layout.addWidget(title)

        controls = QVBoxLayout()
        controls.setSpacing(12)

        primary_btn_style = f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                            stop:0 {BRAND_PRIMARY}, stop:1 {BRAND_DEEP_RED});
                color: white;
                padding: 12px 18px;
                border-radius: 14px;
                font:700 13px 'Segoe UI';
                border: 1px solid rgba(255,255,255,0.16);
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                            stop:0 {BRAND_DEEP_RED}, stop:1 {BRAND_PRIMARY});
            }}
            QPushButton:disabled {{
                background: #f1d7e6;
                color: #b98ca3;
                border: 1px solid #f1d7e6;
            }}
        """
        subtle_btn_style = """
            QPushButton {
                background: rgba(102, 16, 31, 0.08);
                color: #66101F;
                padding: 11px 16px;
                border-radius: 12px;
                font:700 12px 'Segoe UI';
                border: 1px solid rgba(102, 16, 31, 0.15);
            }
            QPushButton:hover {
                background: rgba(102, 16, 31, 0.14);
            }
            QPushButton:disabled {
                color: #c7a4b2;
                background: rgba(102, 16, 31, 0.06);
                border: 1px solid rgba(102, 16, 31, 0.08);
            }
        """

        add_schedule_btn = QPushButton("Add Timeline / Schedule")
        add_schedule_btn.clicked.connect(self.open_schedule_dialog)
        add_schedule_btn.setStyleSheet(primary_btn_style)
        controls.addWidget(add_schedule_btn, 0, Qt.AlignLeft)

        filter_wrap = QHBoxLayout()
        filter_wrap.setSpacing(10)
        filter_label = QLabel("Min passenger rating:")
        filter_label.setObjectName("muted")
        filter_wrap.addWidget(filter_label)

        rating_box = QDoubleSpinBox()
        rating_box.setRange(0.0, 5.0)
        rating_box.setDecimals(1)
        rating_box.setSingleStep(0.5)
        rating_box.setSuffix(" *")
        rating_box.setValue(self.driver_passenger_rating_filter)
        rating_box.setStyleSheet("""
            QDoubleSpinBox {
                background: #fff;
                border: 1px solid #f0d0de;
                border-radius: 10px;
                padding: 8px 10px;
                min-width: 90px;
                font:600 13px 'Segoe UI';
                color: #4a0f23;
            }
            QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
                background: transparent;
                border: none;
                width: 14px;
            }
        """)
        rating_box.valueChanged.connect(self.on_driver_rating_filter_changed)
        filter_wrap.addWidget(rating_box)
        filter_wrap.addStretch(1)
        controls.addLayout(filter_wrap, 0)

        chat_row = QHBoxLayout()
        chat_row.setSpacing(10)
        open_chat_btn = QPushButton('Open Active Chat')
        open_chat_btn.setEnabled(bool(self.active_driver_chat))
        open_chat_btn.clicked.connect(self.open_driver_chat_dialog)
        open_chat_btn.setStyleSheet(subtle_btn_style)
        chat_row.addWidget(open_chat_btn)

        chat_hub_btn = QPushButton("Chat Hub")
        chat_hub_btn.setEnabled(bool(self.driver_chat_sessions))
        chat_hub_btn.clicked.connect(self.open_driver_chat_hub)
        chat_hub_btn.setStyleSheet(subtle_btn_style)
        chat_row.addWidget(chat_hub_btn)
        chat_row.addStretch(1)
        controls.addLayout(chat_row, 0)

        panel_layout.addLayout(controls)

        user = self.controller.current_user
        reply = net.send_request("get_open_requests", {
            "driver_id": user["user_id"],
            "min_passenger_rating": self.driver_passenger_rating_filter
        })

        requests = reply.get("requests", [])

        if not requests:
            empty = QLabel("No open ride requests match your current filters.")
            empty.setObjectName("muted")
            panel_layout.addWidget(empty)
            self.dynamic_area.addWidget(panel)
            return

        for req in requests:
            item = QFrame()
            item.setStyleSheet(f"""
                QFrame {{
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                                stop:0 #fff, stop:1 #ffe8f0);
                    border:1px solid #f2d6e1;
                    border-radius:12px;
                }}
                QLabel {{
                    color:{TEXT_DARK};
                    font:600 13px 'Segoe UI';
                }}
            """)

            lay = QVBoxLayout(item)
            lay.setContentsMargins(12, 10, 12, 12)
            lay.setSpacing(6)

            route = req.get("route", "Home -> AUB")
            area_value = req.get("area", "Unknown")
            location_label = "Pickup" if route.startswith("Home") else "Drop-off"
            info = QLabel(
                f"<b>{req['passenger_name']}</b>  ·  {route}  ·  {location_label}: {area_value}  ·  {req['requested_time']}"
            )
            lay.addWidget(info)

            rating_text = (
                f"Passenger rating: {req.get('passenger_rating', 0):.1f} * "
                f"({req.get('passenger_rating_count', 0)} reviews)"
            )
            rating_lbl = QLabel(rating_text)
            rating_lbl.setStyleSheet(f"color:{BRAND_DEEP_RED}; font:600 12px 'Segoe UI';")
            lay.addWidget(rating_lbl)

            driver_req_lbl = QLabel(
                f"Needs driver rating >= {req.get('min_driver_rating', 0):.1f} *"
            )
            driver_req_lbl.setStyleSheet("color:#c05621; font-size:12px; font-weight:600;")

            if not req.get("driver_rating_ok", 1):
                driver_rating = req.get("driver_rating_value", 0)
                shortfall = req.get("driver_rating_shortfall", 0)
                warn_lbl = QLabel(
                    f"⚠ Your rating ({driver_rating:.1f} ★) is below this request by {shortfall:.1f}."
                )
                warn_lbl.setStyleSheet("color:#b91c1c; font-size:12px; font-weight:600;")
                lay.addWidget(warn_lbl)
            lay.addWidget(driver_req_lbl)

            btn_row = QHBoxLayout()
            btn_row.setSpacing(10)
            btn_accept = QPushButton("Accept")
            btn_accept.setStyleSheet(primary_btn_style)
            btn_deny = QPushButton("Deny")
            btn_deny.setStyleSheet(subtle_btn_style)

            btn_accept.clicked.connect(
                lambda _, data=req: self.accept_request(data)
            )

            btn_deny.clicked.connect(
                lambda _, rid=req["request_id"]: self.deny_request(rid)
            )

            btn_row.addWidget(btn_accept)
            btn_row.addWidget(btn_deny)
            btn_row.addStretch(1)
            lay.addLayout(btn_row)

            panel_layout.addWidget(item)

        self.dynamic_area.addWidget(panel)

    def on_driver_rating_filter_changed(self, value: float):
        self.driver_passenger_rating_filter = value
        self.refresh_dashboard()

    def open_schedule_dialog(self):
        user = self.controller.current_user
        if not user:
            return
        dlg = ScheduleDialog(driver_id=user["user_id"], parent=self)
        if dlg.exec_() == QDialog.Accepted:
            self.refresh_dashboard()

    
    def accept_request(self, request):
        user = self.controller.current_user
        request_meta = {}
        if isinstance(request, dict):
            request_id = request.get("request_id")
            if not request_id:
                return
            if not request.get("driver_rating_ok", 1):
                min_driver = request.get("min_driver_rating", 0)
                driver_rating = request.get("driver_rating_value", 0)
                msg = (
                    f"This passenger requested drivers rated at least {min_driver:.1f} *.\n"
                    f"Your rating is {driver_rating:.1f} *. Accept anyway?"
                )
                confirm = QMessageBox.question(
                    self,
                    "Rating Requirement",
                    msg,
                    QMessageBox.Yes | QMessageBox.No
                )
                if confirm != QMessageBox.Yes:
                    return
            request_meta = {
                "passenger_name": request.get("passenger_name"),
                "area": request.get("area"),
                "route": request.get("route"),
                "requested_time": request.get("requested_time")
            }
        else:
            request_id = int(request)

        reply = net.send_request("accept_ride", {
            "driver_id": user["user_id"],
            "request_id": request_id
        })

        if reply.get("ok"):
            QMessageBox.information(self, "Ride Accepted",
                                    "You have accepted this ride request!")
            if reply.get("chat"):
                self.register_chat_session(
                    "driver",
                    reply["chat"],
                    metadata=request_meta,
                    refresh=False
                )
                self.open_chat_dialog("driver", reply["chat"], metadata=request_meta)
        else:
            QMessageBox.warning(self, "Error",
                                reply.get("msg", "Unable to accept."))

        self.refresh_dashboard()

    
    # CHAT HELPERS
    
    def register_chat_session(
        self,
        role: str,
        chat_info: dict,
        metadata: Optional[dict] = None,
        refresh: bool = False
    ):
        if not chat_info:
            return
        metadata = metadata or {}
        changed = False
        if role == "driver":
            request_id = chat_info.get("request_id")
            if request_id:
                entry = self.driver_chat_sessions.get(request_id, {"meta": {}})
                entry["chat"] = chat_info
                merged_meta = dict(entry.get("meta") or {})
                for key, value in metadata.items():
                    if value not in (None, "", 0):
                        merged_meta[key] = value
                entry["meta"] = merged_meta
                self.driver_chat_sessions[request_id] = entry
            if chat_info != self.active_driver_chat:
                self.active_driver_chat = chat_info
                changed = True
        else:
            if chat_info != self.active_passenger_chat:
                self.active_passenger_chat = chat_info
                changed = True
        if changed and refresh:
            self.refresh_dashboard()

    def open_driver_chat_dialog(self):
        if not self.active_driver_chat:
            QMessageBox.information(self, "Chat", "No active chat yet.")
            return
        self.open_chat_dialog("driver", self.active_driver_chat)

    def open_passenger_chat_dialog(self):
        if not self.active_passenger_chat:
            QMessageBox.information(self, "Chat", "No active chat yet.")
            return
        self.open_chat_dialog("passenger", self.active_passenger_chat)

    def open_chat_dialog(self, role: str, chat_info: dict, metadata: Optional[dict] = None):
        if not chat_info:
            return None
        key = chat_info.get("request_id") or chat_info.get("room_id")
        existing = self.chat_windows.get(key)
        if existing:
            existing.raise_()
            existing.activateWindow()
            return existing

        def _on_update(updated):
            self.register_chat_session(role, updated, refresh=False)

        if role == "driver" and metadata is None:
            req_id = chat_info.get("request_id")
            entry = self.driver_chat_sessions.get(req_id or -1)
            if entry:
                metadata = entry.get("meta")

        available = None
        select_cb = None
        if role == "driver":
            available = list(self.driver_chat_sessions.values())
            select_cb = lambda info, meta=None: self.open_chat_dialog("driver", info, metadata=meta)

        dlg = ChatDialog(
            parent=self,
            role=role,
            chat_info=chat_info,
            user=self.controller.current_user,
            on_chat_update=_on_update,
            chat_meta=metadata,
            available_chats=available,
            on_select_chat=select_cb
        )
        dlg.finished.connect(lambda _: self.chat_windows.pop(key, None))
        self.chat_windows[key] = dlg
        dlg.show()
        return dlg

    def open_driver_chat_hub(self):
        if not self.driver_chat_sessions:
            QMessageBox.information(self, "Chats", "No passenger conversations yet.")
            return
        driver_name = self.controller.current_user.get("username", "Driver")
        sessions = list(self.driver_chat_sessions.values())
        hub = DriverChatHubDialog(
            parent=self,
            driver_name=driver_name,
            sessions=sessions,
            on_open_chat=lambda chat, meta=None: self.open_chat_dialog("driver", chat, metadata=meta)
        )
        hub.exec_()

    
    # PASSENGER POPUPS AND FUNCTIONS
    
    def show_confirmation_popup(self, message: str):
        dlg = QDialog(self)
        dlg.setWindowTitle("Ride Confirmed")
        dlg.setModal(True)
        dlg.setFixedSize(360, 180)

        frame = QFrame()
        frame.setStyleSheet(f"""
            QFrame {{
                background-color:{BRAND_LIGHT};
                border:2px solid {BRAND_PRIMARY};
                border-radius:14px;
            }}
            QLabel {{
                color:{TEXT_DARK};
                font-size:16px;
            }}
            QPushButton {{
                background:{BRAND_PRIMARY};
                color:white;
                padding:8px 18px;
                border-radius:10px;
            }}
            QPushButton:pressed {{
                background:{BRAND_DEEP_RED};
            }}
        """)

        v = QVBoxLayout(frame)

        title = QLabel("Ride Request Confirmed")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(f"font-size:18px; font-weight:700; color:{BRAND_PRIMARY};")
        v.addWidget(title)

        msg = QLabel(message)
        msg.setAlignment(Qt.AlignCenter)
        msg.setWordWrap(True)
        v.addWidget(msg)

        ok = QPushButton("OK")
        ok.clicked.connect(dlg.accept)
        v.addWidget(ok, alignment=Qt.AlignCenter)

        main = QVBoxLayout(dlg)
        main.addWidget(frame)
        dlg.exec_()

    def show_waiting_popup(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Waiting for Driver")
        dlg.setModal(True)
        dlg.setFixedSize(360, 160)

        frame = QFrame()
        frame.setStyleSheet(f"""
            QFrame {{
                background-color:{BRAND_LIGHT};
                border:2px solid {BRAND_PRIMARY};
                border-radius:14px;
            }}
            QLabel {{
                color:{TEXT_DARK};
                font-size:16px;
                font-weight:600;
            }}
        """)

        v = QVBoxLayout(frame)
        lbl = QLabel("Waiting for a driver to accept...")
        lbl.setAlignment(Qt.AlignCenter)
        v.addWidget(lbl)

        main = QVBoxLayout(dlg)
        main.addWidget(frame)
        dlg.show()

        return dlg

    
    def request_ride(self):
        user = self.controller.current_user

        common_areas = [
            "Hamra", "Achrafieh", "Verdun", "Mar Mikhael", "Gemmayzeh",
            "Ras Beirut", "Ain El Mreisseh", "Tayouneh", "Badaro",
            "Furn El Chebbak", "Kantari", "Karantina", "Jnah",
            "Ain El Remmaneh", "Hazmieh"
        ]

        route_box = QComboBox()
        route_box.addItems(["Home -> AUB", "AUB -> Home"])

        area_box = QComboBox()
        area_box.setEditable(True)
        area_box.addItems(common_areas)
        area_box.setFixedWidth(200)

        rating_box = QDoubleSpinBox()
        rating_box.setRange(0.0, 5.0)
        rating_box.setDecimals(1)
        rating_box.setSingleStep(0.5)
        rating_box.setSuffix(" *")

        hours = [f"{h:02d}" for h in range(0, 24)]
        minutes = ["00", "15", "30", "45"]

        hour_box = QComboBox()
        hour_box.addItems(hours)
        hour_box.setFixedWidth(85)

        minute_box = QComboBox()
        minute_box.addItems(minutes)
        minute_box.setFixedWidth(85)

        colon = QLabel(":")
        colon.setStyleSheet("font-size:18px; color:#e5e7eb;")
        colon.setAlignment(Qt.AlignCenter)
        colon.setFixedWidth(12)

        dlg = QDialog(self)
        dlg.setWindowTitle("Request Ride")
        dlg.setFixedSize(440, 380)

        frame = QFrame()
        frame.setStyleSheet(f"""
            QFrame {{
                background:{BRAND_LIGHT};
                border:2px solid {BRAND_PRIMARY};
                border-radius:16px;
            }}
            QLabel {{
                color:{TEXT_DARK};
                font-family:'Segoe UI';
            }}
            QComboBox {{
                background:white;
                border:1px solid #f0d0de;
                border-radius:8px;
                padding:6px;
            }}
        """)

        layout = QVBoxLayout(frame)
        title = QLabel("Request a Ride")
        title.setStyleSheet(f"font:700 20px 'Segoe UI'; color:{BRAND_PRIMARY};")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        form = QFormLayout()
        form.addRow("Route:", route_box)

        area_label = QLabel()

        def update_area_label():
            text = route_box.currentText()
            area_label.setText("Pickup Area:" if text.startswith("Home") else "Drop-off Area:")

        route_box.currentTextChanged.connect(lambda _: update_area_label())
        update_area_label()

        form.addRow(area_label, area_box)

        trow = QHBoxLayout()
        trow.addWidget(hour_box)
        trow.addSpacing(4)
        trow.addWidget(colon)
        trow.addSpacing(4)
        trow.addWidget(minute_box)

        form.addRow("Departure Time:", trow)
        form.addRow("Min Driver Rating:", rating_box)
        layout.addLayout(form)

        btn_ok = QPushButton("Submit")
        btn_ok.setCursor(Qt.PointingHandCursor)
        btn_ok.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                            stop:0 {BRAND_PRIMARY}, stop:1 {BRAND_DEEP_RED});
                color:white;
                padding:10px 18px;
                border-radius:10px;
                font-weight:600;
            }}
            QPushButton:pressed {{
                background:{BRAND_DEEP_RED};
            }}
        """)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.setStyleSheet(f"""
            QPushButton {{
                background:white;
                color:{BRAND_PRIMARY};
                border:1px solid #f0d0de;
                padding:10px 18px;
                border-radius:10px;
                font-weight:600;
            }}
            QPushButton:pressed {{
                background:#ffe5ec;
            }}
        """)
        btn_ok.clicked.connect(dlg.accept)
        btn_cancel.clicked.connect(dlg.reject)

        row = QHBoxLayout()
        row.addWidget(btn_ok)
        row.addWidget(btn_cancel)
        layout.addLayout(row)

        main = QVBoxLayout(dlg)
        main.addWidget(frame)

        if dlg.exec_() != QDialog.Accepted:
            return

        pickup_area = area_box.currentText().strip()
        if not pickup_area:
            QMessageBox.warning(self, "Missing Area", "Please specify your area before requesting a ride.")
            return

        dept_time = f"{hour_box.currentText()}:{minute_box.currentText()}"
        route_choice = route_box.currentText()
        min_driver_rating = rating_box.value()

        reply = net.send_request("request_ride", {
            "passenger_id": user["user_id"],
            "area": pickup_area,
            "requested_time": dept_time,
            "route": route_choice,
            "min_driver_rating": min_driver_rating
        })

        if not reply.get("ok"):
            QMessageBox.warning(self, "Request Failed", reply.get("msg", "Unable to submit ride request."))
            return

        request_id = reply["request_id"]
        self.show_confirmation_popup("Your ride request has been successfully submitted!")

        wait_popup = self.show_waiting_popup()

        notified_driver = False
        chat_opened = False

        def poll_status():
            nonlocal notified_driver, chat_opened
            status_reply = net.send_request("check_request_status", {
                "request_id": request_id
            })

            if status_reply.get("status") == "accepted" and not notified_driver:
                driver = status_reply.get("driver") or {}
                name = driver.get("name", "A driver")
                email = driver.get("email", "No contact info provided")
                QMessageBox.information(
                    self,
                    "Ride Accepted",
                    f"{name} has accepted your request.\nContact: {email}"
                )
                if wait_popup.isVisible():
                    wait_popup.close()
                notified_driver = True

            chat = status_reply.get("chat")
            if chat:
                first_chat = self.active_passenger_chat is None
                self.register_chat_session("passenger", chat, refresh=False)
                if first_chat:
                    self.refresh_dashboard()

            if chat and chat.get("listen_ip") and chat.get("listen_port") and not chat_opened:
                wait_popup.close()
                timer.stop()
                chat_opened = True
                self.open_chat_dialog("passenger", chat)

        timer = QTimer()
        timer.timeout.connect(poll_status)
        timer.start(1000)

    def deny_request(self, request_id):
        user = self.controller.current_user

        net.send_request("deny_request", {
            "driver_id": user["user_id"],
            "request_id": request_id
        })

    
    def cancel_ride(self):
        user = self.controller.current_user
        req, ok = QInputDialog.getInt(self, "Cancel Ride", "Request ID:", 1, 1)
        if not ok:
            return
        reply = net.send_request("cancel_ride", {
            "request_id": req,
            "user_id": user["user_id"]
        })
        if reply.get("ok"):
            QMessageBox.information(self, "Cancel", reply.get("msg", "Ride cancelled"))
        else:
            QMessageBox.warning(self, "Cancel", reply.get("msg", "Unable to cancel ride"))

    
    def rate_driver(self):
        user = self.controller.current_user
        driver_id = QInputDialog.getInt(self, "Rate", "Driver ID:", 1, 1)[0]
        match_id = QInputDialog.getInt(self, "Rate", "Match ID:", 1, 1)[0]
        score = QInputDialog.getInt(self, "Rate", "Score 1-5:", 5, 1, 5)[0]
        comment, _ = QInputDialog.getText(self, "Comment", "Say something:")

        reply = net.send_request("rate_user", {
            "rater_id": user["user_id"],
            "ratee_id": driver_id,
            "match_id": match_id,
            "score": score,
            "comment": comment
        })
        QMessageBox.information(self, "Rating", reply.get("msg", ""))



class ChatDialog(QDialog):
    line_received = pyqtSignal(str)

    def __init__(
        self,
        parent,
        role: str,
        chat_info: dict,
        user: dict | None,
        on_chat_update=None,
        chat_meta: Optional[dict] = None,
        available_chats: Optional[list] = None,
        on_select_chat=None
    ):
        super().__init__(parent)
        self.role = role
        self.chat_info = chat_info or {}
        self.user = user or {}
        self.username = self.user.get("username", role)
        self.user_id = self.user.get("user_id")
        self.on_chat_update = on_chat_update
        self.request_id = self.chat_info.get("request_id")
        self.room_id = self.chat_info.get("room_id") or f"R{self.request_id or 'chat'}"
        self.chat_meta = chat_meta or {}
        self.available_chats = available_chats or []
        self.on_select_chat = on_select_chat
        self.chat = ChatNode(
            self.room_id,
            ui_sink=lambda _, line: self._append_line(line),
            download_root=DOWNLOAD_ROOT
        )
        self.poll_timer: Optional[QTimer] = None

        self.setObjectName("chatDialog")
        self.setWindowTitle("AUBus Messenger")
        self.resize(720, 560)
        peer_name = self._peer_display_name()

        self.setStyleSheet(f"""
            QDialog#chatDialog {{
                background:#f5f3ff;
            }}
            QFrame#chatShell {{
                background:white;
                border-radius:28px;
            }}
            QFrame#chatHero {{
                background:qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                           stop:0 {BRAND_PRIMARY}, stop:1 {BRAND_DEEP_RED});
                border-radius:24px;
            }}
            QLabel#peerAvatar {{
                background:white;
                color:{BRAND_PRIMARY};
                border-radius:30px;
                font:700 22px 'Segoe UI';
                min-width:60px;
                min-height:60px;
            }}
            QFrame#inputFrame {{
                background:#f3f0ff;
                border-radius:22px;
            }}
            QLineEdit#messageField {{
                border:none;
                background:transparent;
                padding:8px 4px;
                font:500 14px 'Segoe UI';
                color:{TEXT_DARK};
            }}
            QPushButton#sendButton {{
                background:{BRAND_PRIMARY};
                color:white;
                border:none;
                border-radius:18px;
                min-width:70px;
                font-weight:600;
            }}
            QPushButton#sendButton:pressed {{
                background:{BRAND_DEEP_RED};
            }}
            QPushButton[chatAction="true"] {{
                background:white;
                border:1px solid #e0d7fb;
                border-radius:18px;
                padding:8px 14px;
                color:#6b5d97;
                font-weight:600;
            }}
            QPushButton[chatAction="true"]:hover {{
                background:#ece5ff;
            }}
            QPushButton#chatChip {{
                background:white;
                border:1px solid #e0d7fb;
                border-radius:18px;
                padding:8px 16px;
                color:#6b5d97;
                font-weight:600;
            }}
            QPushButton#chatChip:disabled {{
                background:{BRAND_PRIMARY};
                color:white;
            }}
            QPushButton#closeChat {{
                background:transparent;
                color:#9d8cc3;
                border:none;
                font-weight:600;
            }}
            QPushButton#closeChat:hover {{
                color:{BRAND_PRIMARY};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("AUBus Messenger")
        title.setStyleSheet("font:800 24px 'Segoe UI'; color:#1f1b2e;")
        layout.addWidget(title)

        self.lbl_room = QLabel(f"Room  -  {self.room_id}")
        self.lbl_room.setStyleSheet("color:#8b95b2; font:500 12px 'Segoe UI';")
        layout.addWidget(self.lbl_room)

        if self.role == "driver" and isinstance(self.available_chats, list) and len(self.available_chats) > 1:
            layout.addWidget(self._build_chat_selector(), 0)

        shell = QFrame()
        shell.setObjectName("chatShell")
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(24, 24, 24, 24)
        shell_layout.setSpacing(16)
        layout.addWidget(shell, 1)

        hero = self._build_header_card(peer_name)
        shell_layout.addWidget(hero)

        self.transcript = ChatBubbleBoard(self.username)
        self.line_received.connect(self.transcript.append_line)
        shell_layout.addWidget(self.transcript, 1)

        input_frame = QFrame()
        input_frame.setObjectName("inputFrame")
        input_layout = QHBoxLayout(input_frame)
        input_layout.setContentsMargins(12, 6, 12, 6)
        input_layout.setSpacing(10)
        shell_layout.addWidget(input_frame)

        self.msg_input = QLineEdit()
        self.msg_input.setObjectName("messageField")
        self.msg_input.setPlaceholderText("Type a message...")
        input_layout.addWidget(self.msg_input, 1)

        self.btn_send = QPushButton("Send")
        self.btn_send.setObjectName("sendButton")
        self.btn_send.clicked.connect(self.send_message)
        input_layout.addWidget(self.btn_send, 0)

        action_row = QHBoxLayout()
        action_row.setSpacing(10)
        shell_layout.addLayout(action_row)

        self.btn_loc = QPushButton("Location")
        self.btn_loc.setProperty("chatAction", "true")
        self.btn_loc.clicked.connect(self.send_location)
        action_row.addWidget(self.btn_loc)

        self.btn_image = QPushButton("Image")
        self.btn_image.setProperty("chatAction", "true")
        self.btn_image.clicked.connect(self.send_image)
        action_row.addWidget(self.btn_image)

        self.btn_audio = QPushButton("Voice Note")
        self.btn_audio.setProperty("chatAction", "true")
        self.btn_audio.clicked.connect(self.send_voice_note)
        action_row.addWidget(self.btn_audio)

        self.btn_end_ride = QPushButton("End Ride & Rate")
        self.btn_end_ride.setProperty("chatAction", "true")
        self.btn_end_ride.clicked.connect(self.prompt_end_ride)
        action_row.addWidget(self.btn_end_ride)

        action_row.addStretch(1)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_btn = QPushButton("Close Chat")
        close_btn.setObjectName("closeChat")
        close_btn.clicked.connect(self.close)
        close_row.addWidget(close_btn)
        layout.addLayout(close_row)

        self.msg_input.returnPressed.connect(self.send_message)
        self._refresh_end_ride_state()

        if self.role == "driver":
            QTimer.singleShot(0, self.start_driver_mode)
        else:
            if self.chat_info.get("listen_ip") and self.chat_info.get("listen_port"):
                QTimer.singleShot(0, lambda: self.connect_to_driver(
                    self.chat_info["listen_ip"], self.chat_info["listen_port"]
                ))
            else:
                QTimer.singleShot(0, self.start_passenger_poll)

    
    def _build_header_card(self, peer_name: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName("chatHero")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(16)

        avatar = QLabel(self._initials_from_name(peer_name))
        avatar.setObjectName("peerAvatar")
        avatar.setAlignment(Qt.AlignCenter)
        avatar.setFixedSize(64, 64)
        layout.addWidget(avatar)

        info_box = QVBoxLayout()
        info_box.setSpacing(2)
        peer_lbl = QLabel(peer_name)
        peer_lbl.setStyleSheet("color:white; font:700 18px 'Segoe UI';")
        info_box.addWidget(peer_lbl)

        self.status_label = QLabel("Initializing chat...")
        self.status_label.setStyleSheet("color:#fde9ff; font:500 12px 'Segoe UI';")
        info_box.addWidget(self.status_label)

        layout.addLayout(info_box, 1)

        badge = QLabel("Secure P2P")
        badge.setStyleSheet("color:#fde9ff; background:rgba(255,255,255,0.15);"
                            "padding:6px 12px; border-radius:14px; font:600 12px 'Segoe UI';")
        layout.addWidget(badge, 0, Qt.AlignRight | Qt.AlignTop)
        return frame

    def _build_chat_selector(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setFixedHeight(80)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        for entry in self.available_chats or []:
            chat = entry.get("chat")
            if not chat:
                continue
            meta = entry.get("meta") or {}
            name = meta.get("passenger_name") or f"Passenger #{chat.get('passenger_id', '?')}"
            btn = QPushButton(name)
            btn.setObjectName("chatChip")
            req_id = chat.get("request_id")
            btn.setEnabled(req_id != self.request_id)
            btn.clicked.connect(
                lambda _, info=chat, extra=meta: self._handle_chat_selection(info, extra)
            )
            row.addWidget(btn)
        row.addStretch(1)
        scroll.setWidget(container)
        return scroll

    def _handle_chat_selection(self, chat: dict | None, meta: Optional[dict]):
        if not chat or not self.on_select_chat:
            return
        self.on_select_chat(chat, meta or {})

    def _peer_display_name(self) -> str:
        if self.role == "driver":
            return (
                self.chat_meta.get("passenger_name")
                or f"Passenger #{self.chat_info.get('passenger_id', '?')}"
            )
        return (
            self.chat_meta.get("driver_name")
            or f"Driver #{self.chat_info.get('driver_id', '?')}"
        )

    def _initials_from_name(self, name: str) -> str:
        if not name:
            return "P"
        parts = [p for p in name.split() if p]
        if not parts:
            return name[:2].upper()
        if len(parts) == 1:
            return parts[0][:2].upper()
        return (parts[0][0] + parts[1][0]).upper()

    
    def _append_line(self, text: str):
        self.line_received.emit(text)

    def _update_chat_info(self, chat: dict | None):
        if not chat:
            return
        self.chat_info = chat
        if self.on_chat_update:
            self.on_chat_update(chat)
        self._refresh_end_ride_state()

    
    def start_driver_mode(self):
        if self.request_id is None:
            self._append_line("[ERROR] Missing request id for chat session.")
            return
        try:
            ip, port = self.chat.start_listener()
            self.status_label.setText(f"Listening on {ip}:{port}")
            payload = {
                "request_id": self.request_id,
                "driver_id": self.chat_info.get("driver_id"),
                "listen_ip": ip,
                "listen_port": port
            }
            reply = net.send_request("chat_publish_listener", payload)
            if reply.get("chat"):
                self._update_chat_info(reply["chat"])
            if not reply.get("ok"):
                self._append_line(f"[ERROR] {reply.get('msg', 'Unable to notify passenger')}")
        except Exception as e:
            self.status_label.setText("Failed to start listener.")
            self._append_line(f"[ERROR] Listen error: {e}")

    def start_passenger_poll(self):
        if self.request_id is None:
            self._append_line("[ERROR] Missing request id; cannot poll chat status.")
            return
        if self.poll_timer:
            self.poll_timer.stop()
        self.status_label.setText("Waiting for driver to start chat...")
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(1500)
        self.poll_timer.timeout.connect(self._poll_endpoint)
        self.poll_timer.start()

    def _poll_endpoint(self):
        reply = net.send_request("chat_poll_status", {
            "request_id": self.request_id
        })
        chat = reply.get("chat")
        if chat:
            self._update_chat_info(chat)
        chat = chat or self.chat_info
        if chat and chat.get("listen_ip") and chat.get("listen_port"):
            if self.poll_timer:
                self.poll_timer.stop()
                self.poll_timer = None
            self.connect_to_driver(chat["listen_ip"], chat["listen_port"])

    def connect_to_driver(self, ip: str, port: int):
        try:
            self.chat.start_connector(ip, int(port))
            self.status_label.setText(f"Connected to {ip}:{port}")
        except ConnectError as e:
            self._append_line(f"[ERROR] Connect failed: {e}")
            self.start_passenger_poll()

    
    def send_message(self):
        text = self.msg_input.text().strip()
        if not text:
            return
        try:
            self.chat.send_text(self.username, text)
            self.msg_input.clear()
        except ConnectError as e:
            self._append_line(f"[ERROR] {e}")

    def send_location(self):
        entry, ok = QInputDialog.getText(
            self,
            "Share Location",
            "Enter an address or coordinates (lat, lon):"
        )
        if not ok or not entry.strip():
            return
        coords = geocode_location(entry.strip())
        if not coords:
            hint = "Enter coordinates like 33.8911, 35.5018"
            if not GOOGLE_MAPS_API_KEY:
                hint += " or set GOOGLE_MAPS_API_KEY for address lookups."
            QMessageBox.warning(
                self,
                "Location",
                f"Unable to resolve that location.\n{hint}"
            )
            return
        lat, lon = coords
        link = google_maps_link(lat, lon)
        try:
            self.chat.send_loc(lat, lon, link)
        except ConnectError as e:
            self._append_line(f"[ERROR] {e}")

    def send_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Send Image",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.gif);;All Files (*)"
        )
        if path:
            self._send_file(path, kind="image")

    def send_voice_note(self):
        if not self.chat:
            return
        dialog = VoiceRecorderDialog(self, self.chat, self.username)
        dialog.exec_()

    def _send_file(self, file_path: str, kind: str):
        try:
            data = Path(file_path).read_bytes()
        except OSError as e:
            QMessageBox.warning(self, "Attachment", f"Unable to read file: {e}")
            return
        if len(data) > ATTACHMENT_LIMIT:
            QMessageBox.warning(
                self,
                "Attachment too large",
                f"Please choose a file smaller than {ATTACHMENT_LIMIT // (1024 * 1024)} MB."
            )
            return
        file_path_obj = Path(file_path)
        name = file_path_obj.name
        try:
            self.chat.send_file(
                kind,
                self.username,
                name,
                data,
                source_path=str(file_path_obj)
            )
        except ConnectError as e:
            self._append_line(f"[ERROR] {e}")

    def prompt_end_ride(self):
        match_id = self.chat_info.get("match_id")
        if not match_id or not self.user_id:
            QMessageBox.information(self, "End Ride", "Ride is not associated with a match yet.")
            return
        role_label = "your passenger" if self.role == "driver" else "your driver"
        dlg = RatingDialog(role_label, self)
        if dlg.exec_() != QDialog.Accepted:
            return
        score, comment = dlg.get_rating()
        reply = net.send_request("complete_ride", {
            "match_id": match_id,
            "rater_id": self.user_id,
            "score": score,
            "comment": comment
        })
        if not reply.get("ok"):
            QMessageBox.warning(self, "Rate Ride", reply.get("msg", "Unable to save rating."))
            return

        self.chat_info["driver_completed"] = reply.get("driver_completed")
        self.chat_info["passenger_completed"] = reply.get("passenger_completed")
        if reply.get("ride_completed"):
            self.chat_info["match_status"] = "completed"
        self._refresh_end_ride_state()

        QMessageBox.information(self, "Thank you", "Your rating has been submitted.")
        if reply.get("ride_completed"):
            QMessageBox.information(self, "Ride Completed", "Both sides have completed the ride.")
            self.close()

    def _refresh_end_ride_state(self):
        if not hasattr(self, "btn_end_ride"):
            return
        enabled = bool(self.chat_info.get("match_id") and self.user_id)
        if enabled:
            if self.role == "driver":
                enabled = not bool(self.chat_info.get("driver_completed"))
            else:
                enabled = not bool(self.chat_info.get("passenger_completed"))
        self.btn_end_ride.setEnabled(enabled)

    
    def closeEvent(self, event):
        if self.poll_timer:
            self.poll_timer.stop()
            self.poll_timer = None
        try:
            reply = net.send_request("chat_close", {
                "request_id": self.request_id,
                "status": f"closed_by_{self.role}"
            })
            if reply.get("chat"):
                self._update_chat_info(reply["chat"])
        except Exception:
            pass

        try:
            self.chat.close()
        except Exception:
            pass
        super().closeEvent(event)



# Main Window

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AUBus")
        self.resize(600, 700)
        self.setStyleSheet("""
            QMainWindow {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                            stop:0 #0c0a10,
                                            stop:0.5 #1c1222,
                                            stop:1 #2a1a2f);
            }
        """)

        self.current_user = None

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.login = LoginPage(self)
        self.register = RegisterPage(self)
        self.dashboard = DashboardPage(self)

        self.stack.addWidget(self.login)
        self.stack.addWidget(self.register)
        self.stack.addWidget(self.dashboard)

        self.goto("login")

    def goto(self, name: str):
        if name == "login":
            self.stack.setCurrentWidget(self.login)
            self.login.on_show()
        elif name == "register":
            self.stack.setCurrentWidget(self.register)
            self.register.on_show()
        elif name == "dashboard":
            self.stack.setCurrentWidget(self.dashboard)



# Run Application

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


