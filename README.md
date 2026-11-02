<div align="center">

# 🚌 AUBus — Campus Ride-Sharing

**A multi-threaded client/server ride-sharing app for AUB students, with peer-to-peer chat and voice notes.**

![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![PyQt5](https://img.shields.io/badge/PyQt5-41CD52?style=for-the-badge&logo=qt&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-003B57?style=for-the-badge&logo=sqlite&logoColor=white)
![Sockets](https://img.shields.io/badge/TCP%2FUDP-Sockets-orange?style=for-the-badge)

</div>

---

## ✨ Features

- **Drivers & passengers**: drivers publish weekly schedules, passengers request rides, and the server matches them.
- **Full ride lifecycle**: request → accept / deny → complete → rate, with per-user average ratings and ride history.
- **Peer-to-peer chat**: once a ride is matched, driver and passenger connect **directly** over TCP (no server relay) to exchange text, images and **voice notes**.
- **Live context**: Beirut weather (Open-Meteo) and Google Maps geocoding / map links for pickup points.
- **Desktop GUI** built with PyQt5.

## 🏗️ Architecture

```
┌──────────────┐   JSON over TCP    ┌──────────────────────┐
│  PyQt5 client│ ─────────────────▶ │ server.py (port 5050)│
│  (qt_main.py)│ ◀───────────────── │  thread per client   │
└──────┬───────┘                    │  client_handler.py   │
       │  direct P2P TCP            │  database.py (SQLite)│
       ▼                            └──────────────────────┘
┌──────────────┐
│  other client│   p2p_chat/chat.py: text · images · voice
└──────────────┘
```

The server speaks a small JSON protocol with actions such as `register`, `login`, `add_schedule`, `request_ride`, `accept_ride`, `complete_ride`, `rate_user`, `view_history` and `chat_publish_listener`.

**Database tables:** `users`, `driver_schedules`, `ride_requests`, `ride_matches`, `ratings`, `denied_requests`, `chat_sessions`.

## 🚀 Run it

```bash
pip install PyQt5
python server.py              # starts the server on 127.0.0.1:5050
python client/app/qt_main.py  # launch one or more clients
```

Optional, for map lookups:

```bash
set GOOGLE_MAPS_API_KEY=your-key   # Windows (use export on macOS/Linux)
```

## 📁 Structure

```
server.py           # TCP server, one thread per client
client_handler.py   # request routing / business logic
database.py         # SQLite schema + queries
client/app/         # PyQt5 desktop client
p2p_chat/chat.py    # direct peer-to-peer chat & voice streaming
```

---

<sub>Built for EECE 351 (Computer Networks) at the American University of Beirut.</sub>
