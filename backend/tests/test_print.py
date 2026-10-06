import io
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from sqlmodel import Session, delete, select

from app.db import engine
from app.main import app
from app.models import PrintJob, PrintUpload
from app.services import maintenance, settings_service
from tests.conftest import login


def make_pdf(pages: int = 3, password: str | None = None) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)
    if password:
        writer.encrypt(password)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def as_user(kind: str, username: str) -> TestClient:
    client = TestClient(app)
    assert login(client, kind, username).status_code == 200
    return client


def set_demo(local: str) -> None:
    admin = as_user("staff", "admin")
    assert admin.put("/api/admin/demo-time", json={"local": local}).status_code == 200


def upload(client: TestClient, data: bytes | None = None, name: str = "notes.pdf"):
    return client.post("/api/print/uploads", files={"file": (name, data if data is not None else make_pdf(), "application/pdf")})


def new_job(client: TestClient, pages: int = 3, **options) -> dict:
    up = upload(client, make_pdf(pages)).json()
    body = {"upload_id": up["upload_id"], "copies": 1, "color": False, "double_sided": False} | options
    response = client.post("/api/print/jobs", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def stored_path(job_id: int) -> str | None:
    with Session(engine) as session:
        return session.get(PrintJob, job_id).stored_path


@pytest.fixture(autouse=True)
def empty_print_tables():
    with Session(engine) as session:
        for path in session.exec(select(PrintJob.stored_path)).all() + session.exec(select(PrintUpload.stored_path)).all():
            if path:
                Path(path).unlink(missing_ok=True)
        session.exec(delete(PrintJob))
        session.exec(delete(PrintUpload))
        session.commit()
    set_demo("2026-10-05T12:20")  # Monday; next class is the DBMS lab at 1:30
    yield
    settings_service.set_value("print_rates", settings_service.DEFAULTS["print_rates"])


@pytest.fixture
def ananya():
    return as_user("student", "22CS001")


@pytest.fixture
def priya():
    return as_user("student", "22CS002")


@pytest.fixture
def shop():
    return as_user("staff", "print")


# --- upload validation --------------------------------------------------------

def test_upload_counts_pages(ananya):
    response = upload(ananya, make_pdf(7), "Lab record.pdf")
    assert response.status_code == 200
    assert response.json()["pages"] == 7
    assert response.json()["original_filename"] == "Lab record.pdf"


def test_non_pdf_renamed_to_pdf_is_rejected(ananya):
    response = upload(ananya, b"PK\x03\x04 this is really a zip/docx", "essay.pdf")
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "not_a_pdf"


def test_password_protected_pdf_rejected(ananya):
    response = upload(ananya, make_pdf(1, password="secret"))
    assert response.status_code == 422 and response.json()["error"]["code"] == "pdf_locked"


def test_damaged_pdf_rejected(ananya):
    response = upload(ananya, b"%PDF-1.4 not really a pdf")
    assert response.status_code == 422 and response.json()["error"]["code"] == "pdf_unreadable"


def test_file_over_20mb_rejected(ananya):
    big = b"%PDF-1.4\n" + b"0" * (20 * 1024 * 1024 + 10)
    response = upload(ananya, big)
    assert response.status_code == 413 and response.json()["error"]["code"] == "file_too_large"


def test_uploads_are_private_to_their_owner(ananya, priya):
    up = upload(ananya).json()
    response = priya.post("/api/print/quote", json={"upload_id": up["upload_id"], "copies": 1})
    assert response.status_code == 404


# --- quote ----------------------------------------------------------------------

def test_quote_cost_uses_rate_settings(ananya):
    up = upload(ananya, make_pdf(3)).json()
    q = ananya.post("/api/print/quote", json={"upload_id": up["upload_id"], "copies": 2}).json()
    assert q["rate"] == 200 and q["cost"] == 3 * 2 * 200
    q = ananya.post("/api/print/quote", json={"upload_id": up["upload_id"], "copies": 2, "color": True,
                                               "double_sided": True}).json()
    assert q["cost"] == 3 * 2 * 800


def test_default_deadline_is_ten_minutes_before_next_class(ananya):
    up = upload(ananya).json()
    q = ananya.post("/api/print/quote", json={"upload_id": up["upload_id"], "copies": 1}).json()
    assert q["deadline"].startswith("2026-10-05T13:20")
    assert q["deadline_is_default"] is True
    assert q["deadline_reason"] == "Your DBMS lab starts at 1:30, so it's set 10 minutes before."
    assert q["warning"] is None


def test_default_deadline_without_more_classes_is_one_hour(ananya):
    set_demo("2026-10-05T17:00")
    up = upload(ananya).json()
    q = ananya.post("/api/print/quote", json={"upload_id": up["upload_id"], "copies": 1}).json()
    assert q["deadline"].startswith("2026-10-05T18:00")


def test_estimate_formula_and_late_warning(ananya):
    set_demo("2026-10-05T13:15")  # deadline defaults to 13:20
    up = upload(ananya, make_pdf(5)).json()
    q = ananya.post("/api/print/quote", json={"upload_id": up["upload_id"], "copies": 20}).json()
    # 100 pages x 4 s + 60 s = 460 s after 13:15 -> 13:22:40
    assert q["est_ready_at"].startswith("2026-10-05T13:22:40")
    assert q["warning"] == "This may not be ready before your 1:30 lab."


def test_custom_deadline_warning_and_validation(ananya):
    up = upload(ananya, make_pdf(5)).json()
    q = ananya.post("/api/print/quote", json={"upload_id": up["upload_id"], "copies": 20,
                                               "deadline": "2026-10-05T12:25"}).json()
    assert q["deadline_is_default"] is False and q["warning"] == "This may not be ready by 12:25."
    past = ananya.post("/api/print/quote", json={"upload_id": up["upload_id"], "copies": 1,
                                                  "deadline": "2026-10-05T12:00"})
    assert past.status_code == 422 and past.json()["error"]["code"] == "deadline_past"
    too_many = ananya.post("/api/print/quote", json={"upload_id": up["upload_id"], "copies": 21})
    assert too_many.status_code == 422


# --- jobs, queue order, payment -------------------------------------------------

def test_job_is_paid_demo_and_queued(ananya):
    job = new_job(ananya)
    assert job["status"] == "queued" and job["payment_status"] == "paid_demo"
    assert job["code"] == f"P-{job['id']:04d}"
    mine = ananya.get("/api/print/jobs/mine").json()["jobs"]
    assert [j["id"] for j in mine] == [job["id"]]
    today = ananya.get("/api/today").json()
    assert [j["code"] for j in today["print_jobs"]] == [job["code"]]


def test_upload_can_only_be_used_once(ananya):
    up = upload(ananya).json()
    body = {"upload_id": up["upload_id"], "copies": 1}
    assert ananya.post("/api/print/jobs", json=body).status_code == 200
    assert ananya.post("/api/print/jobs", json=body).status_code == 404


def test_earlier_deadline_goes_first_even_if_uploaded_second(ananya, priya, shop):
    first = new_job(ananya, deadline="2026-10-05T15:30")
    second = new_job(priya, deadline="2026-10-05T14:00")
    queue = shop.get("/api/print/queue").json()["to_print"]
    assert [j["code"] for j in queue] == [second["code"], first["code"]]
    assert queue[0]["student_name"] == "Priya Nair"
    # The later-deadline job's estimate now accounts for the job ahead of it.
    mine = {j["id"]: j for j in ananya.get("/api/print/jobs/mine").json()["jobs"]}
    assert mine[first["id"]]["est_ready_at"] > queue[0]["est_ready_at"]


def test_printing_job_stays_first(ananya, priya, shop):
    later = new_job(ananya, deadline="2026-10-05T15:30")
    shop.post(f"/api/print/jobs/{later['id']}/status", json={"status": "printing"})
    earlier = new_job(priya, deadline="2026-10-05T13:00")
    queue = shop.get("/api/print/queue").json()["to_print"]
    assert [j["id"] for j in queue] == [later["id"], earlier["id"]]


# --- status, files on disk ------------------------------------------------------

def test_shop_flow_deletes_file_on_collect(ananya, shop):
    job = new_job(ananya)
    path = stored_path(job["id"])
    assert path and Path(path).is_file()
    for status in ("printing", "ready"):
        assert shop.post(f"/api/print/jobs/{job['id']}/status", json={"status": status}).status_code == 200
    assert Path(path).is_file()
    assert shop.get("/api/print/queue").json()["ready"][0]["id"] == job["id"]
    done = shop.post(f"/api/print/jobs/{job['id']}/status", json={"status": "collected"}).json()
    assert done["status"] == "collected" and done["has_file"] is False
    assert not Path(path).exists()
    assert stored_path(job["id"]) is None
    assert ananya.get(f"/api/print/jobs/{job['id']}/file").status_code == 410


def test_steps_cannot_be_skipped(ananya, shop):
    job = new_job(ananya)
    response = shop.post(f"/api/print/jobs/{job['id']}/status", json={"status": "ready"})
    assert response.status_code == 409 and response.json()["error"]["code"] == "bad_transition"


def test_cancel_while_queued_deletes_file(ananya, shop):
    job = new_job(ananya)
    path = stored_path(job["id"])
    cancelled = ananya.post(f"/api/print/jobs/{job['id']}/cancel").json()
    assert cancelled["status"] == "cancelled"
    assert not Path(path).exists()
    assert shop.get("/api/print/queue").json()["to_print"] == []


def test_cannot_cancel_once_printing(ananya, shop):
    job = new_job(ananya)
    shop.post(f"/api/print/jobs/{job['id']}/status", json={"status": "printing"})
    response = ananya.post(f"/api/print/jobs/{job['id']}/cancel")
    assert response.status_code == 409 and response.json()["error"]["code"] == "cannot_cancel"


def test_uncollected_jobs_expire_after_24_hours(ananya, fixed_real_time):
    job = new_job(ananya)
    path = stored_path(job["id"])
    fixed_real_time["now"] += timedelta(hours=25)
    maintenance.run_once()
    mine = ananya.get("/api/print/jobs/mine").json()["jobs"]
    assert mine[0]["status"] == "expired" and mine[0]["has_file"] is False
    assert not Path(path).exists()


def test_stale_uploads_are_removed(ananya, fixed_real_time):
    up = upload(ananya).json()
    with Session(engine) as session:
        path = session.get(PrintUpload, up["upload_id"]).stored_path
    fixed_real_time["now"] += timedelta(hours=25)
    maintenance.run_once()
    assert not Path(path).exists()


# --- permissions ------------------------------------------------------------------

def test_file_access(ananya, priya, shop):
    job = new_job(ananya)
    own = ananya.get(f"/api/print/jobs/{job['id']}/file")
    assert own.status_code == 200 and own.headers["content-type"] == "application/pdf"
    assert own.content.startswith(b"%PDF-")
    assert shop.get(f"/api/print/jobs/{job['id']}/file").status_code == 200
    assert priya.get(f"/api/print/jobs/{job['id']}/file").status_code == 404
    assert as_user("staff", "canteen").get(f"/api/print/jobs/{job['id']}/file").status_code == 403


def test_students_cannot_use_shop_routes(ananya, priya):
    job = new_job(ananya)
    assert ananya.get("/api/print/queue").status_code == 403
    assert ananya.post(f"/api/print/jobs/{job['id']}/status", json={"status": "printing"}).status_code == 403
    assert priya.post(f"/api/print/jobs/{job['id']}/cancel").status_code == 404
    assert as_user("staff", "canteen").get("/api/print/queue").status_code == 403


# --- admin rates ------------------------------------------------------------------

def test_admin_rates_change_quotes(ananya):
    admin = as_user("staff", "admin")
    assert admin.get("/api/admin/settings").json()["print_rates_confirmed"] is False
    rates = {"bw_single": 150, "bw_double": 100, "colour_single": 900, "colour_double": 700}
    saved = admin.put("/api/admin/settings", json={"print_rates": rates}).json()
    assert saved["print_rates"] == rates and saved["print_rates_confirmed"] is True
    up = upload(ananya, make_pdf(2)).json()
    assert ananya.post("/api/print/quote", json={"upload_id": up["upload_id"], "copies": 1}).json()["cost"] == 300
    assert ananya.put("/api/admin/settings", json={"print_rates": rates}).status_code == 403
    settings_service.set_value("print_rates_confirmed", False)


def test_shop_step_after_cancel_is_refused(ananya, shop):
    """A cancel and a shop step that race: the second loses with 409 and the job stays cancelled."""
    from app.errors import ApiError
    from app.services import print_service

    job = new_job(ananya)
    with Session(engine) as shop_session:
        loaded = print_service._get_job(shop_session, job["id"])  # the shop reads "queued"
        assert ananya.post(f"/api/print/jobs/{job['id']}/cancel").status_code == 200
        with pytest.raises(ApiError) as refused:
            print_service._transition(shop_session, loaded, "queued", "printing", "changed")
        assert refused.value.status == 409
    assert ananya.get("/api/print/jobs/mine").json()["jobs"][0]["status"] == "cancelled"
