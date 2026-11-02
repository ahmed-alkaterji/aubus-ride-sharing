
# Handles all persistent data (users, schedules, rides, matches, ratings)
import secrets #for security 
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Optional
DB_FILE = "aubus.db"


def _generate_room_id() -> str:
    return "R" + secrets.token_hex(3).upper() #This ID uniquely identifies the chat room between a driver and passenger.

@contextmanager
def db_connect():
    conn = sqlite3.connect(DB_FILE) #Each thread calling this gets its own connection, which is good because SQLite doesn't allow multi-threaded sharing of the same connection
    conn.execute("PRAGMA foreign_keys = ON") #Enable foreign key constraints,This ensures data integrity.
    conn.row_factory = sqlite3.Row #Return rows as dictionaries ,It makes code cleaner and readabl
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback() # to avoid corrupt or half data
        raise
    finally:
        conn.close() #always runs, ensures connections are always closed

# DATABASE INITIALIZATION
def initialize_database():
    with db_connect() as conn: #When the server starts the first time → it builds the database.

        # USERS TABLE
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL UNIQUE,
                password TEXT NOT NULL,
                is_driver INTEGER NOT NULL,
                area TEXT DEFAULT 'Unknown',
                created_on TEXT NOT NULL
            )
        """)

        # DRIVER SCHEDULES
        conn.execute("""
            CREATE TABLE IF NOT EXISTS driver_schedules (
                schedule_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                depart_time TEXT NOT NULL,
                route TEXT NOT NULL,
                seats_total INTEGER DEFAULT 4,
                seats_available INTEGER DEFAULT 4,
                days TEXT,
                area TEXT NOT NULL DEFAULT '',
                FOREIGN KEY(user_id) REFERENCES users(user_id) 
            )
        """)
            #A schedule cannot exist without a valid driver.
            #If a driver account is deleted, all schedules are also removed (depending on cascade rules).

        schedule_cols = {row["name"] for row in conn.execute("PRAGMA table_info(driver_schedules)")}
        if "days" not in schedule_cols:
            conn.execute("ALTER TABLE driver_schedules ADD COLUMN days TEXT")
        if "area" not in schedule_cols:
            conn.execute("ALTER TABLE driver_schedules ADD COLUMN area TEXT DEFAULT ''")
            conn.execute("UPDATE driver_schedules SET area='' WHERE area IS NULL") #We also added migration logic using PRAGMA table_info to detect missing columns like days and area. If a column doesn’t exist, we ALTER the table to add it. This keeps the database compatible with new app features without wiping existing data.”

        # RIDE REQUESTS
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ride_requests (
                request_id INTEGER PRIMARY KEY AUTOINCREMENT,
                passenger_id INTEGER NOT NULL,
                area TEXT NOT NULL,
                requested_time TEXT NOT NULL,
                route TEXT NOT NULL DEFAULT 'Home → AUB',
                min_driver_rating REAL DEFAULT 0,
                status TEXT DEFAULT 'open',
                FOREIGN KEY(passenger_id) REFERENCES users(user_id)
            )
        """)

        ride_cols = {row["name"] for row in conn.execute("PRAGMA table_info(ride_requests)")}
        if "route" not in ride_cols:
            conn.execute("ALTER TABLE ride_requests ADD COLUMN route TEXT DEFAULT 'Home → AUB'")
        if "min_driver_rating" not in ride_cols:
            conn.execute("ALTER TABLE ride_requests ADD COLUMN min_driver_rating REAL DEFAULT 0")
   

        # RIDE MATCHES
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ride_matches (
                match_id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id INTEGER NOT NULL,
                driver_id INTEGER NOT NULL,
                schedule_id INTEGER,
                accepted_on TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                completed_on TEXT,
                driver_completed INTEGER NOT NULL DEFAULT 0,
                passenger_completed INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(request_id) REFERENCES ride_requests(request_id),
                FOREIGN KEY(driver_id) REFERENCES users(user_id),
                FOREIGN KEY(schedule_id) REFERENCES driver_schedules(schedule_id)
            )
        """)
        match_cols = {row["name"] for row in conn.execute("PRAGMA table_info(ride_matches)")}
        if "completed_on" not in match_cols:
            conn.execute("ALTER TABLE ride_matches ADD COLUMN completed_on TEXT")
        if "driver_completed" not in match_cols:
            conn.execute("ALTER TABLE ride_matches ADD COLUMN driver_completed INTEGER NOT NULL DEFAULT 0")
        if "passenger_completed" not in match_cols:
            conn.execute("ALTER TABLE ride_matches ADD COLUMN passenger_completed INTEGER NOT NULL DEFAULT 0")

        # RATINGS
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ratings (
                rating_id INTEGER PRIMARY KEY AUTOINCREMENT,
                rater_id INTEGER NOT NULL,
                ratee_id INTEGER NOT NULL,
                ride_match_id INTEGER NOT NULL,
                score INTEGER NOT NULL,
                comment TEXT,
                created_on TEXT NOT NULL,
                FOREIGN KEY(rater_id) REFERENCES users(user_id),
                FOREIGN KEY(ratee_id) REFERENCES users(user_id),
                FOREIGN KEY(ride_match_id) REFERENCES ride_matches(match_id)
            )
        """)
        # Requests denied by drivers
        conn.execute("""
            CREATE TABLE IF NOT EXISTS denied_requests (
                driver_id INTEGER NOT NULL,
                request_id INTEGER NOT NULL,
                PRIMARY KEY (driver_id, request_id)
            )
        """)

        # CHAT SESSIONS
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_sessions (
                chat_id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id INTEGER NOT NULL UNIQUE,
                driver_id INTEGER NOT NULL,
                passenger_id INTEGER NOT NULL,
                room_id TEXT NOT NULL UNIQUE,
                listen_ip TEXT,
                listen_port INTEGER,
                status TEXT NOT NULL DEFAULT 'pending',
                created_on TEXT NOT NULL DEFAULT (datetime('now')),
                updated_on TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY(request_id) REFERENCES ride_requests(request_id),
                FOREIGN KEY(driver_id) REFERENCES users(user_id),
                FOREIGN KEY(passenger_id) REFERENCES users(user_id)
            )
        """)


    print(" Database initialized successfully.")


# USERS

def add_user(username, email, password, is_driver, area, created_on):
    with db_connect() as conn:
        cur = conn.execute("""
            INSERT INTO users(username, email, password, is_driver, area, created_on)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (username, email, password, is_driver, area, created_on))
        return cur.lastrowid

def get_user(identifier):
    with db_connect() as conn:
        row = conn.execute("""
            SELECT user_id, username, email, password, is_driver, area
            FROM users
            WHERE username = ? OR email = ?
        """, (identifier, identifier)).fetchone()
        return dict(row) if row else None


# DRIVER SCHEDULES

def add_schedule(user_id, depart_time, route, seats_total=4, days="", area=""):
    with db_connect() as conn:
        cur = conn.execute("""
            INSERT INTO driver_schedules(user_id, depart_time, route, seats_total, seats_available, days, area)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (user_id, depart_time, route, seats_total, seats_total, days or None, (area or "").strip()))
        schedule_id = cur.lastrowid
        row = conn.execute("""
            SELECT schedule_id, user_id, depart_time, route, seats_total,
                   seats_available, IFNULL(days, '') AS days, IFNULL(area, '') AS area
            FROM driver_schedules
            WHERE schedule_id = ?
        """, (schedule_id,)).fetchone()
        return dict(row) if row else None


def get_driver_schedules(user_id):
    with db_connect() as conn:
        #filteringggggggggggggg
        rows = conn.execute("""
            SELECT schedule_id, user_id, depart_time, route, seats_total,
                   seats_available, IFNULL(days, '') AS days, IFNULL(area, '') AS area 
            FROM driver_schedules
            WHERE user_id = ?
            ORDER BY schedule_id DESC
        """, (user_id,)).fetchall()
        return [dict(r) for r in rows]


def get_driver_schedule(user_id):
    schedules = get_driver_schedules(user_id)
    return schedules[0] if schedules else None

def get_driver_times_for_area(area):
    with db_connect() as conn:
        rows = conn.execute("""
            SELECT DISTINCT depart_time
            FROM driver_schedules
            WHERE LOWER(area) = LOWER(?)
            ORDER BY depart_time
        """, (area,)).fetchall()
        return [r["depart_time"] for r in rows]


# RIDE REQUESTS

def add_ride_request(passenger_id, area, requested_time, route, min_driver_rating):
    with db_connect() as conn:
        cur = conn.execute("""
            INSERT INTO ride_requests(passenger_id, area, requested_time, route, min_driver_rating, status)
            VALUES (?, ?, ?, ?, ?, 'open')
        """, (passenger_id, area, requested_time, route, min_driver_rating))
        return cur.lastrowid

def cancel_ride_request(request_id, user_id):
    with db_connect() as conn:
        req = conn.execute("""
            SELECT passenger_id, status
            FROM ride_requests
            WHERE request_id = ?
        """, (request_id,)).fetchone()

        if not req or req["status"] != "open" or req["passenger_id"] != user_id:
            return False

        conn.execute("""
            UPDATE ride_requests
            SET status='cancelled'
            WHERE request_id = ?
        """, (request_id,))
        return True


# RATINGS

def add_rating(rater_id, ratee_id, match_id, score, comment, timestamp, conn=None):
    def _insert(target):
        cur = target.execute("""
            INSERT INTO ratings(rater_id, ratee_id, ride_match_id, score, comment, created_on)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (rater_id, ratee_id, match_id, score, comment, timestamp))
        return cur.lastrowid

    if conn is not None:
        return _insert(conn)

    with db_connect() as conn_obj:
        return _insert(conn_obj)
    
def get_user_rating(user_id):
    with db_connect() as conn:
        row = conn.execute("""
            SELECT IFNULL(AVG(score), 0) AS avg_score,
                   COUNT(*) AS total_ratings
            FROM ratings
            WHERE ratee_id = ?
        """, (user_id,)).fetchone()
        if not row:
            return {"avg_score": 0, "total_ratings": 0}
        return dict(row)

def get_driver_average_rating(driver_id):
    return get_user_rating(driver_id)


def complete_ride_with_rating(match_id, rater_id, score, comment, timestamp):
    with db_connect() as conn:
        match = conn.execute("""
            SELECT m.match_id, m.driver_id, m.status,
                   IFNULL(m.driver_completed, 0) AS driver_completed,
                   IFNULL(m.passenger_completed, 0) AS passenger_completed,
                   r.passenger_id
            FROM ride_matches m
            JOIN ride_requests r ON r.request_id = m.request_id
            WHERE m.match_id = ?
        """, (match_id,)).fetchone()
        if not match:
            return None

        if rater_id == match["driver_id"]:
            role = "driver"
            ratee_id = match["passenger_id"]
            already_done = match["driver_completed"]
        elif rater_id == match["passenger_id"]:
            role = "passenger"
            ratee_id = match["driver_id"]
            already_done = match["passenger_completed"]
        else:
            return None

        if already_done:
            existing = conn.execute("""
                SELECT rating_id FROM ratings
                WHERE rater_id = ? AND ride_match_id = ?
            """, (rater_id, match_id)).fetchone()
            return {
                "match_id": match_id,
                "role": role,
                "rating_id": existing["rating_id"] if existing else None,
                "driver_completed": match["driver_completed"],
                "passenger_completed": match["passenger_completed"],
                "ride_completed": match["driver_completed"] and match["passenger_completed"]
            }

        existing = conn.execute("""
            SELECT rating_id FROM ratings
            WHERE rater_id = ? AND ride_match_id = ?
        """, (rater_id, match_id)).fetchone()
        if existing:
            return {
                "match_id": match_id,
                "role": role,
                "rating_id": existing["rating_id"],
                "driver_completed": match["driver_completed"],
                "passenger_completed": match["passenger_completed"],
                "ride_completed": match["driver_completed"] and match["passenger_completed"]
            }

        rating_id = add_rating(rater_id, ratee_id, match_id, score, comment, timestamp, conn=conn)

        driver_completed = match["driver_completed"] or (1 if role == "driver" else 0)
        passenger_completed = match["passenger_completed"] or (1 if role == "passenger" else 0)

        ride_completed = bool(driver_completed and passenger_completed)
        if ride_completed:
            conn.execute("""
                UPDATE ride_matches
                SET driver_completed=?, passenger_completed=?,
                    status='completed',
                    completed_on=COALESCE(completed_on, datetime('now'))
                WHERE match_id=?
            """, (driver_completed, passenger_completed, match_id))
        else:
            conn.execute("""
                UPDATE ride_matches
                SET driver_completed=?, passenger_completed=?,
                    status='accepted'
                WHERE match_id=?
            """, (driver_completed, passenger_completed, match_id))

        return {
            "match_id": match_id,
            "role": role,
            "rating_id": rating_id,
            "driver_completed": driver_completed,
            "passenger_completed": passenger_completed,
            "ride_completed": ride_completed,
            "ratee_id": ratee_id
        }


def get_request_status(request_id):
    with db_connect() as conn:
        row = conn.execute("""
            SELECT r.status,
                   r.passenger_id,
                   m.driver_id,
                   m.match_id,
                   IFNULL(m.driver_completed, 0) AS driver_completed,
                   IFNULL(m.passenger_completed, 0) AS passenger_completed,
                   IFNULL(m.status, 'pending') AS match_status,
                   u.username AS driver_name,
                   u.email AS driver_email,
                   cs.room_id AS chat_room_id,
                   cs.listen_ip AS chat_ip,
                   cs.listen_port AS chat_port,
                   cs.status AS chat_status
            FROM ride_requests r
            LEFT JOIN ride_matches m
                   ON m.request_id = r.request_id
                   AND m.status IN ('accepted', 'completed')
            LEFT JOIN users u
                   ON u.user_id = m.driver_id
            LEFT JOIN chat_sessions cs
                   ON cs.request_id = r.request_id
            WHERE r.request_id = ?
        """, (request_id,)).fetchone()
        return dict(row) if row else None


# DRIVER OPEN REQUESTS

def _time_to_minutes(value: str) -> Optional[int]:
    try:
        value = value.strip()
        hours, minutes = value.split(":")
        return int(hours) * 60 + int(minutes)
    except Exception:
        return None


def get_open_requests(driver_id, min_passenger_rating=0):
    schedules = get_driver_schedules(driver_id)
    if not schedules:
        return []

    slots = []
    for schedule in schedules:
        minutes = _time_to_minutes(schedule["depart_time"])
        route = schedule.get("route", "Home → AUB")
        area = (schedule.get("area") or "").strip().lower()
        if minutes is None or not area:
            continue
        slots.append({
            "minutes": minutes,
            "route": route,
            "area": area
        })

    if not slots:
        return []

    driver_rating = get_user_rating(driver_id).get("avg_score", 0) or 0
    min_passenger_rating = float(min_passenger_rating or 0)

    with db_connect() as conn:
        rows = conn.execute("""
            SELECT r.request_id, r.area, r.requested_time, r.route, r.min_driver_rating,
                   u.username AS passenger_name, u.user_id AS passenger_id,
                   IFNULL(pr.avg_score, 0) AS passenger_rating,
                   IFNULL(pr.total_ratings, 0) AS passenger_rating_count
            FROM ride_requests r
            JOIN users u ON r.passenger_id = u.user_id
            LEFT JOIN (
                SELECT ratee_id, AVG(score) AS avg_score, COUNT(*) AS total_ratings
                FROM ratings
                GROUP BY ratee_id
            ) pr ON pr.ratee_id = u.user_id
            WHERE r.status='open'
              AND r.request_id NOT IN (
                  SELECT request_id FROM denied_requests WHERE driver_id = ?
              )
            ORDER BY r.requested_time ASC
        """, (driver_id,)).fetchall()

    matches = {}
    for row in rows:
        req_minutes = _time_to_minutes(row["requested_time"])
        if req_minutes is None:
            continue

        passenger_rating = row["passenger_rating"] or 0
        if passenger_rating < min_passenger_rating:
            continue

        min_driver = row["min_driver_rating"] or 0

        req_area = (row["area"] or "").strip().lower()
        req_route = row["route"] or "Home → AUB"
        if not req_area:
            continue

        for slot in slots:
            if slot["route"] != req_route:
                continue
            if slot["area"] != req_area:
                continue
            if abs(slot["minutes"] - req_minutes) <= 30:
                matches[row["request_id"]] = dict(row)
                matches[row["request_id"]]["passenger_rating"] = passenger_rating
                matches[row["request_id"]]["driver_rating_ok"] = 1 if driver_rating >= min_driver else 0
                matches[row["request_id"]]["driver_rating_value"] = driver_rating
                matches[row["request_id"]]["driver_rating_shortfall"] = max(0.0, float(min_driver) - float(driver_rating))
                break

    return list(matches.values())


# DRIVER ACCEPTS RIDE

def accept_ride_request(request_id, driver_id):
    with db_connect() as conn:

        req = conn.execute("""
            SELECT status FROM ride_requests WHERE request_id=?
        """, (request_id,)).fetchone()

        if not req or req["status"] != "open":
            return None

        conn.execute("""
            INSERT INTO ride_matches(request_id, driver_id, schedule_id, accepted_on, status)
            VALUES (?, ?, NULL, datetime('now'), 'accepted')
        """, (request_id, driver_id))

        conn.execute("""
            UPDATE ride_requests SET status='accepted'
            WHERE request_id=?
        """, (request_id,))

        session = _ensure_chat_session_locked(conn, request_id, driver_id)
        return session


def _select_chat_session(conn, request_id):
    row = conn.execute("""
        SELECT cs.chat_id, cs.request_id, cs.driver_id, cs.passenger_id,
               cs.room_id, cs.listen_ip, cs.listen_port, cs.status,
               m.match_id, IFNULL(m.status, 'pending') AS match_status,
               IFNULL(m.driver_completed, 0) AS driver_completed,
               IFNULL(m.passenger_completed, 0) AS passenger_completed
        FROM chat_sessions cs
        LEFT JOIN ride_matches m
               ON m.request_id = cs.request_id
              AND m.status IN ('accepted', 'completed')
        WHERE cs.request_id = ?
        ORDER BY m.match_id DESC
        LIMIT 1
    """, (request_id,)).fetchone()
    return dict(row) if row else None


def _ensure_chat_session_locked(conn, request_id, driver_id):
    existing = conn.execute("""
        SELECT * FROM chat_sessions WHERE request_id=?
    """, (request_id,)).fetchone()
    if existing:
        return _select_chat_session(conn, request_id)

    req = conn.execute("""
        SELECT passenger_id FROM ride_requests WHERE request_id=?
    """, (request_id,)).fetchone()
    if not req:
        return None

    room_id = _generate_room_id()
    conn.execute("""
        INSERT INTO chat_sessions(request_id, driver_id, passenger_id, room_id, status)
        VALUES (?, ?, ?, ?, 'pending')
    """, (request_id, driver_id, req["passenger_id"], room_id))

    return _select_chat_session(conn, request_id)


def publish_chat_listener(request_id, driver_id, listen_ip, listen_port):
    with db_connect() as conn:
        cur = conn.execute("""
            UPDATE chat_sessions
            SET listen_ip=?, listen_port=?, status='ready', updated_on=datetime('now')
            WHERE request_id=? AND driver_id=?
        """, (listen_ip, listen_port, request_id, driver_id))
        if cur.rowcount == 0:
            return None
        return _select_chat_session(conn, request_id)


def get_chat_session(request_id):
    with db_connect() as conn:
        return _select_chat_session(conn, request_id)


def mark_chat_closed(request_id, status="closed"):
    with db_connect() as conn:
        conn.execute("""
            UPDATE chat_sessions
            SET status=?, updated_on=datetime('now')
            WHERE request_id=?
        """, (status, request_id))
        return _select_chat_session(conn, request_id)

def deny_request(driver_id, request_id):
    with db_connect() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO denied_requests(driver_id, request_id)
            VALUES (?, ?)
        """, (driver_id, request_id))


# USER HISTORY

def get_user_history(user_id):
    with db_connect() as conn:
        rows = conn.execute("""
            SELECT r.request_id, r.area, r.requested_time, r.status
            FROM ride_requests r
            WHERE r.passenger_id = ?
        """, (user_id,)).fetchall()
        return [dict(r) for r in rows]


if __name__ == "__main__":
    initialize_database()
