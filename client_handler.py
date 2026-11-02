import json
import time
from database import (
    add_user,
    get_user,
    add_ride_request,
    accept_ride_request,
    add_rating,
    get_driver_average_rating,
    add_schedule,
    cancel_ride_request,
    get_user_history,
    get_driver_times_for_area,
    get_request_status,
    get_open_requests,
    get_driver_schedule,
    deny_request,
    publish_chat_listener,
    get_chat_session,
    mark_chat_closed,
    complete_ride_with_rating
)

def send(conn, obj):
    conn.send(json.dumps(obj).encode())


def _chat_payload(session):
    if not session:
        return None
    return {
        "chat_id": session.get("chat_id"),
        "request_id": session.get("request_id"),
        "driver_id": session.get("driver_id"),
        "passenger_id": session.get("passenger_id"),
        "room_id": session.get("room_id"),
        "listen_ip": session.get("listen_ip"),
        "listen_port": session.get("listen_port"),
        "status": session.get("status"),
        "match_id": session.get("match_id"),
        "match_status": session.get("match_status"),
        "driver_completed": session.get("driver_completed"),
        "passenger_completed": session.get("passenger_completed")
    }


def process_client(conn, addr):
    print(f"[HANDLER] Serving client {addr}")

    while True:
        try:
            raw = conn.recv(4096)
            if not raw:
                break

            msg = raw.decode("utf-8")
            print(f"[RECEIVED from {addr}] {msg}")

            # Parse JSON
            try:
                data = json.loads(msg)
                action = data.get("action", "").lower()
                payload = data.get("payload", {})
            except Exception:
                send(conn, {"ok": False, "msg": "Invalid JSON"})
                continue

            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

            
            # REGISTER
            
            if action == "register":
                try:
                    username = payload["username"]
                    email = payload["email"]
                    password = payload["password"]
                    is_driver = 1 if payload.get("is_driver", False) else 0
                    area = payload.get("area", "Unknown")
                except KeyError:
                    send(conn, {"ok": False, "msg": "Missing fields"})
                    continue

                try:
                    user_id = add_user(username, email, password, is_driver, area, timestamp)
                    send(conn, {"ok": True, "msg": "Registration successful", "user_id": user_id})
                except Exception as e:
                    send(conn, {"ok": False, "msg": f"Registration failed: {e}"})


            
            # LOGIN
            
            elif action == "login":
                try:
                    identifier = payload.get("email") or payload.get("username")
                    password = payload["password"]
                except KeyError:
                    send(conn, {"ok": False, "msg": "Missing fields"})
                    continue

                user = get_user(identifier)
                if user and user["password"] == password:
                    send(conn, {
                        "ok": True,
                        "msg": "Login successful",
                        "username": user["username"],
                        "is_driver": user["is_driver"],
                        "user_id": user["user_id"]
                    })
                else:
                    send(conn, {"ok": False, "msg": "Invalid credentials"})


            
            # DRIVER: FETCH EXISTING SCHEDULE
            
            elif action == "get_schedule":
                try:
                    user_id = int(payload["user_id"])
                except KeyError:
                    send(conn, {"ok": False, "msg": "Missing user_id"})
                    continue

                schedule = get_driver_schedule(user_id)
                send(conn, {"ok": True, "schedule": schedule})


            
            # GET DRIVER TIMES FOR AREA
            
            elif action == "get_times":
                try:
                    area = payload["area"]
                except KeyError:
                    send(conn, {"ok": False, "msg": "Missing area"})
                    continue

                times = get_driver_times_for_area(area)
                send(conn, {"ok": True, "times": times})


            
            # PASSENGER: REQUEST RIDE
            
            elif action == "request_ride":
                try:
                    passenger_id = int(payload["passenger_id"])
                    area = payload["area"]
                    requested_time = payload["requested_time"]
                    route = payload["route"]
                    min_driver_rating = float(payload.get("min_driver_rating", 0))
                except KeyError:
                    send(conn, {"ok": False, "msg": "Missing request fields"})
                    continue

                try:
                    req_id = add_ride_request(passenger_id, area, requested_time, route, min_driver_rating)                   
                    send(conn, {
                        "ok": True,
                        "msg": "Ride request created",
                        "request_id": req_id
                    })
                except Exception as e:
                    send(conn, {"ok": False, "msg": f"Failed to create ride request: {e}"})


            
            # PASSENGER: CANCEL RIDE
            
            elif action == "cancel_ride":
                try:
                    request_id = int(payload["request_id"])
                    user_id = int(payload["user_id"])
                except KeyError:
                    send(conn, {"ok": False, "msg": "Missing cancel fields"})
                    continue

                success = cancel_ride_request(request_id, user_id)
                send(conn, {
                    "ok": success,
                    "msg": "Ride cancelled" if success else "Cancel failed or unauthorized"
                })


            
            # DRIVER: ACCEPT RIDE
            
            elif action == "accept_ride":
                try:
                    request_id = int(payload["request_id"])
                    driver_id = int(payload["driver_id"])
                except KeyError:
                    send(conn, {"ok": False, "msg": "Missing fields"})
                    continue

                session = accept_ride_request(request_id, driver_id)
                send(conn, {
                    "ok": bool(session),
                    "msg": "Ride accepted" if session else "Failed to accept ride",
                    "chat": _chat_payload(session)
                })


            
            # ADD DRIVER SCHEDULE
            
            elif action == "add_schedule":
                try:
                    user_id = int(payload["user_id"])
                    depart_time = payload["depart_time"]
                    route = payload["route"]
                    seats_total = int(payload.get("seats_total", 4))
                    days = payload.get("days", "")
                    area = payload["area"]
                except KeyError:
                    send(conn, {"ok": False, "msg": "Missing schedule fields"})
                    continue

                schedule = add_schedule(user_id, depart_time, route, seats_total, days, area)
                send(conn, {
                    "ok": True,
                    "msg": "Schedule added",
                    "schedule": schedule
                })


            
            # RATE USER
            
            elif action == "complete_ride":
                try:
                    match_id = int(payload["match_id"])
                    rater_id = int(payload["rater_id"])
                    score = int(payload["score"])
                    comment = payload.get("comment", "")
                except (KeyError, ValueError):
                    send(conn, {"ok": False, "msg": "Missing completion fields"})
                    continue

                score = max(1, min(5, score))
                result = complete_ride_with_rating(match_id, rater_id, score, comment, timestamp)
                if not result:
                    send(conn, {"ok": False, "msg": "Unable to record ride completion"})
                else:
                    send(conn, {
                        "ok": True,
                        "match_id": result["match_id"],
                        "rating_id": result.get("rating_id"),
                        "ride_completed": result.get("ride_completed"),
                        "driver_completed": result.get("driver_completed"),
                        "passenger_completed": result.get("passenger_completed")
                    })


            
            # RATE USER (legacy manual flow)
            
            elif action == "rate_user":
                try:
                    rater_id = int(payload["rater_id"])
                    ratee_id = int(payload["ratee_id"])
                    match_id = int(payload["match_id"])
                    score = int(payload["score"])
                    comment = payload.get("comment", "")
                except KeyError:
                    send(conn, {"ok": False, "msg": "Missing rating fields"})
                    continue

                rating_id = add_rating(rater_id, ratee_id, match_id, score, comment, timestamp)
                send(conn, {"ok": True, "msg": "Rating submitted", "rating_id": rating_id})


            
            # GET DRIVER AVERAGE RATING
            
            elif action == "get_avg_rating":
                try:
                    driver_id = int(payload["driver_id"])
                except KeyError:
                    send(conn, {"ok": False, "msg": "Missing driver_id"})
                    continue

                rating_info = get_driver_average_rating(driver_id)
                send(conn, {
                    "ok": True,
                    "avg_score": rating_info["avg_score"],
                    "total_ratings": rating_info["total_ratings"]
                })


            
            # USER HISTORY
            
            elif action == "view_history":
                try:
                    user_id = int(payload["user_id"])
                except KeyError:
                    send(conn, {"ok": False, "msg": "Missing user_id"})
                    continue

                history = get_user_history(user_id)
                send(conn, {"ok": True, "history": history, "count": len(history)})


            
            # PASSENGER POLLING STATUS
            
            elif action == "check_request_status":
                try:
                    request_id = int(payload["request_id"])
                except KeyError:
                    send(conn, {"ok": False, "msg": "Missing request_id"})
                    continue

                row = get_request_status(request_id) or {}
                response = {
                    "ok": True,
                    "status": row.get("status", "unknown")
                }
                if row.get("driver_id"):
                    response["driver"] = {
                        "driver_id": row.get("driver_id"),
                        "name": row.get("driver_name"),
                        "email": row.get("driver_email")
                    }
                chat_info = {
                    "request_id": request_id,
                    "driver_id": row.get("driver_id"),
                    "passenger_id": row.get("passenger_id"),
                    "room_id": row.get("chat_room_id"),
                    "listen_ip": row.get("chat_ip"),
                    "listen_port": row.get("chat_port"),
                    "status": row.get("chat_status"),
                    "match_id": row.get("match_id"),
                    "match_status": row.get("match_status"),
                    "driver_completed": row.get("driver_completed"),
                    "passenger_completed": row.get("passenger_completed")
                }
                if chat_info["room_id"]:
                    response["chat"] = chat_info
                send(conn, response)


            
            # DRIVER: GET ALL OPEN RIDE REQUESTS
            
            elif action == "get_open_requests":
                driver_id = int(payload.get("driver_id", 0))
                min_passenger_rating = float(payload.get("min_passenger_rating", 0))
                requests = get_open_requests(driver_id, min_passenger_rating)
                send(conn, {"ok": True, "requests": requests})


            
            # DRIVER: DENY REQUEST
            
            elif action == "deny_request":
                try:
                    driver_id = int(payload["driver_id"])
                    request_id = int(payload["request_id"])
                except KeyError:
                    send(conn, {"ok": False, "msg": "Missing fields"})
                    continue

                deny_request(driver_id, request_id)
                send(conn, {"ok": True})

            
            # CHAT: DRIVER PUBLISHES LISTENER
            
            elif action == "chat_publish_listener":
                try:
                    request_id = int(payload["request_id"])
                    driver_id = int(payload["driver_id"])
                    listen_ip = payload["listen_ip"]
                    listen_port = int(payload["listen_port"])
                except (KeyError, ValueError):
                    send(conn, {"ok": False, "msg": "Missing chat fields"})
                    continue

                session = publish_chat_listener(request_id, driver_id, listen_ip, listen_port)
                send(conn, {
                    "ok": bool(session),
                    "chat": _chat_payload(session),
                    "msg": "Chat endpoint shared" if session else "Unable to publish chat endpoint"
                })

            
            # CHAT: PASSENGER POLLS STATUS
            
            elif action == "chat_poll_status":
                try:
                    request_id = int(payload["request_id"])
                except (KeyError, ValueError):
                    send(conn, {"ok": False, "msg": "Missing request_id"})
                    continue

                session = get_chat_session(request_id)
                send(conn, {
                    "ok": True,
                    "chat": _chat_payload(session)
                })

            
            # CHAT: CLOSE SESSION
            
            elif action == "chat_close":
                try:
                    request_id = int(payload["request_id"])
                    status = payload.get("status", "closed")
                except (KeyError, ValueError):
                    send(conn, {"ok": False, "msg": "Missing request_id"})
                    continue

                session = mark_chat_closed(request_id, status=status)
                send(conn, {
                    "ok": bool(session),
                    "chat": _chat_payload(session)
                })


            
            # UNKNOWN ACTION
            
            else:
                send(conn, {"ok": False, "msg": f"Unknown action: {action}"})

        except Exception as e:
            print(f"[ERROR] {addr} -> {e}")
            break

    conn.close()
    print(f"[DISCONNECTED] Client {addr} disconnected")
