from datetime import timedelta

from tests.conftest import login


def _set_demo(admin, local: str):
    response = admin.put("/api/admin/demo-time", json={"local": local})
    assert response.status_code == 200, response.text
    return response.json()


# --- auth and permissions -------------------------------------------------

def test_login_and_me(student):
    me = student.get("/api/auth/me").json()
    assert me["role"] == "student"
    assert me["roll_no"] == "22CS001"
    assert me["card_linked"] is True


def test_roll_number_is_case_insensitive(client):
    assert login(client, "student", "22cs002").status_code == 200


def test_wrong_pin_gives_plain_error(client):
    response = login(client, "student", "22CS001", "9999")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "wrong_credentials"


def test_requires_login(client):
    response = client.get("/api/attendance")
    assert response.status_code == 401
    assert response.json() == {"error": {"code": "not_logged_in", "message": "Please log in to continue."}}


def test_tampered_cookie_rejected(student):
    token = student.cookies.get("dayline_session")
    student.cookies.set("dayline_session", token[:-2] + "xx")
    assert student.get("/api/auth/me").status_code == 401


def test_logout(student):
    student.post("/api/auth/logout")
    assert student.get("/api/auth/me").status_code == 401


def test_student_cannot_set_demo_time(student):
    assert student.put("/api/admin/demo-time", json={"local": "2026-10-05T12:20"}).status_code == 403


def test_staff_cannot_read_student_endpoints(client):
    login(client, "staff", "canteen")
    assert client.get("/api/attendance").status_code == 403
    assert client.put("/api/admin/demo-time", json={"local": "2026-10-05T12:20"}).status_code == 403


def test_demo_accounts_listed_only_in_demo_mode(client):
    from app.services import settings_service

    data = client.get("/api/auth/demo-accounts").json()
    assert data["enabled"] is True and data["pin"] == "1234" and len(data["students"]) == 6
    settings_service.set_value("demo_mode", False)
    try:
        assert client.get("/api/auth/demo-accounts").json() == {
            "enabled": False, "pin": None, "students": [], "staff": []}
    finally:
        settings_service.set_value("demo_mode", True)


def test_unknown_api_path_uses_error_shape(client):
    response = client.get("/api/nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


# --- attendance -------------------------------------------------------------

def test_attendance_sorted_below_first(student):
    data = student.get("/api/attendance").json()
    statuses = [s["standing"]["status"] for s in data["subjects"]]
    assert statuses[:2] == ["below", "below"]
    assert "below" not in statuses[2:]
    dbms = next(s for s in data["subjects"] if s["short_name"] == "DBMS")
    assert dbms["standing"]["statement"] == "Attend the next 8 classes to reach 75%"
    cn = next(s for s in data["subjects"] if s["short_name"] == "CN")
    assert cn["standing"]["percentage"] == 75.0 and cn["standing"]["status"] == "ok"


def test_attendance_uses_threshold_setting(student):
    from app.services import settings_service

    settings_service.set_value("attendance_threshold", 80)
    data = student.get("/api/attendance").json()
    assert data["threshold"] == 80
    toc = next(s for s in data["subjects"] if s["short_name"] == "TOC")
    assert toc["standing"]["statement"] == "You can miss 5 more classes and stay at 80%"


def test_what_if(student):
    subjects = student.get("/api/attendance").json()["subjects"]
    toc = next(s for s in subjects if s["short_name"] == "TOC")  # 36 of 40
    result = student.post("/api/attendance/what-if", json={"subject_id": toc["subject_id"], "miss": 3}).json()
    assert result["after"]["held"] == 43 and result["after"]["attended"] == 36
    assert result["after"]["percentage"] == 83.7
    assert result["current"]["percentage"] == 90.0


def test_what_if_unknown_subject(student):
    response = student.post("/api/attendance/what-if", json={"subject_id": 9999, "miss": 1})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "subject_not_found"


def test_what_if_rejects_negative(student):
    assert student.post("/api/attendance/what-if", json={"subject_id": 1, "miss": -1}).status_code == 422


# --- timetable and the clock ------------------------------------------------

def test_today_schedule_monday(student, admin):
    _set_demo(admin, "2026-10-05T08:00")  # Monday
    login(student, "student", "22CS001")
    data = student.get("/api/today").json()
    assert data["date"] == "2026-10-05"
    kinds = [(i["kind"], i["label"], i["start"][11:16]) for i in data["items"]]
    assert kinds == [
        ("class", "DBMS", "09:00"),
        ("class", "OS", "09:50"),
        ("break", "Short break", "10:40"),
        ("class", "CN", "11:00"),
        ("class", "TOC", "11:50"),
        ("break", "Lunch break", "12:40"),
        ("class", "DBMS lab", "13:30"),
    ]
    assert data["next_class"]["label"] == "DBMS"
    assert data["items"][-1]["room_code"] == "B-204"


def test_demo_time_changes_next_class_without_restart(client):
    login(client, "staff", "admin")
    _set_demo(client, "2026-10-05T09:30")
    login(client, "student", "22CS001")
    assert client.get("/api/timetable/next").json()["next"]["label"] == "OS"

    login(client, "staff", "admin")
    _set_demo(client, "2026-10-05T12:20")
    login(client, "student", "22CS001")
    today = client.get("/api/today").json()
    assert today["next_class"]["label"] == "DBMS lab"
    assert today["current"]["label"] == "TOC"

    login(client, "staff", "admin")
    _set_demo(client, "2026-10-05T17:00")
    login(client, "student", "22CS001")
    assert client.get("/api/timetable/next").json()["next"] is None


def test_demo_time_keeps_ticking(admin, fixed_real_time):
    clock_before = _set_demo(admin, "2026-10-06T12:20")
    assert clock_before["demo"] is True and clock_before["now"].startswith("2026-10-06T12:20")
    fixed_real_time["now"] += timedelta(minutes=10)
    assert admin.get("/api/clock").json()["now"].startswith("2026-10-06T12:30")
    cleared = admin.delete("/api/admin/demo-time").json()
    assert cleared["demo"] is False


def test_free_slots(student, admin):
    _set_demo(admin, "2026-10-06T12:00")  # Tuesday: last afternoon period is free
    login(student, "student", "22CS001")
    items = student.get("/api/timetable/free-slots").json()["items"]
    assert [(i["kind"], i["start"][11:16], i["end"][11:16]) for i in items] == [
        ("break", "10:40", "11:00"),
        ("break", "12:40", "13:30"),
        ("free", "15:10", "16:00"),
    ]
    assert items[0]["status"] == "past" and items[1]["status"] == "upcoming"


def test_sunday_has_no_classes(student, admin):
    _set_demo(admin, "2026-10-11T10:00")
    login(student, "student", "22CS001")
    data = student.get("/api/today").json()
    assert data["items"] == [] and data["next_class"] is None


def test_websocket_answers_ping(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_text("ping")
        assert ws.receive_json() == {"type": "pong", "payload": {}}


def test_websocket_gets_events_for_its_own_student_only(client):
    from app.events import hub

    login(client, "student", "22CS001")
    with client.websocket_connect("/ws") as ws:
        hub.publish("print.updated", {"id": 1}, student_id=2, roles=("print",))  # someone else's job
        hub.publish("print.updated", {"id": 2}, student_id=1)  # this student's job
        assert ws.receive_json() == {"type": "print.updated", "payload": {"id": 2}}
