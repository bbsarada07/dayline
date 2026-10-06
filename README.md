# Dayline

A campus web app for students of one engineering college: the timetable, attendance, canteen pre-orders and print jobs, all tied to the student's day.

> **Status: Phase 7 of `DAYLINE_ADDENDUM_V2.md` section K (Lyzr agents) built.** Foundation, Today screen, attendance, print, canteen, collect by barcode, deployment and Qdrant shared memory are done. The full README (architecture diagram, sponsor integrations, demo script, known limits) is written in Phase 10.

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/bbsarada07/dayline)

Deployment steps, limits and alternatives: [DEPLOY.md](DEPLOY.md).

The product name is set in one place: `app.config.json`.

## Requirements

- Python 3.11 or newer (tested on 3.14)
- Node.js 20 or newer (tested on 24)

## Backend

```sh
cd backend
python -m venv .venv
.venv\Scripts\activate            # Windows
# source .venv/bin/activate       # macOS / Linux
pip install -r requirements-dev.txt   # runtime + test tools
copy .env.example .env            # then set SECRET_KEY (see the comment in the file)
python -m app.seed                # reset the database and load placeholder data
python -m app                     # API on http://0.0.0.0:8000
pytest                            # run the tests
```

## Frontend (development)

```sh
cd frontend
npm install
npm run dev                       # http://localhost:5173, proxies /api and /ws to :8000
```

To use a phone, join the same Wi-Fi or hotspot as the laptop and open the "Network" URL that Vite prints.

## One URL (demo mode)

```sh
cd frontend && npm run build
cd ../backend
# set SERVE_FRONTEND=true in .env, then:
python -m app
```

The server prints its LAN address, for example `http://192.168.1.3:8000`. Open that on a phone on the same network.

## `.env` variables

| Name | Purpose |
|---|---|
| `SECRET_KEY` | Signs login cookies. Required; a random one is used (and logins reset on restart) if missing. |
| `DATABASE_URL` | SQLite file. Default `backend/dayline.db`. |
| `PORT` | API port. Default 8000. |
| `SESSION_DAYS` | How long a login lasts. Default 7. |
| `SERVE_FRONTEND` | `true` to serve `frontend/dist` from the API server. |
| `CORS_ORIGINS` | Only needed when the frontend runs on another origin without the Vite proxy. |
| `AGENT_MODE` | `mock` (keyword router, no key, no credits) or `lyzr` (real agents, once the key and agent ids are set). |
| `LYZR_API_KEY`, `LYZR_*_AGENT_ID` | Lyzr key and the five agent ids printed by `scripts/setup_lyzr.py`. |
| `LYZR_MODEL`, `LYZR_TEMPLATE_AGENT_ID` | Used only by `setup_lyzr.py`: the model, and a hand-made Studio agent whose provider settings it copies. |
| `LYZR_TIMEOUT_SECONDS`, `LYZR_DAILY_CALL_LIMIT` | Per-call wait (default 20) and real calls allowed per day (default 100); past either, the keyword router answers. |
| `TOOL_KEY` | Optional. Turns on `/api/agent-tools/*` for agents hosted elsewhere. |

## Demo accounts (placeholder data)

Every account uses PIN `1234`. The login screen's "Demo accounts" drawer lists them while the `demo_mode` setting is on.

| Who | Log in with |
|---|---|
| Ananya Rao (student, 2 subjects below 75%) | `22CS001` |
| Priya Nair, Rohan Kulkarni, Arjun Mehta, Sneha Patil, Karthik Reddy (students) | `22CS002` to `22CS006` |
| Admin | `admin` |
| Canteen staff | `canteen` |
| Print shop staff | `print` |

Admins can set **demo time** on the admin screen. The app's clock then runs from that moment for everyone, and a banner shows on every screen.

## Print (Phase 2)

- Students upload a PDF on the Print screen, pick copies, colour and sides, see the cost, the deadline (10 minutes before their next class by default) and an estimated ready time, then confirm with a **demo payment: no money moves**.
- Print shop staff log in as `print` and see the queue sorted by deadline, live. Jobs due within 15 minutes are marked "Urgent".
- Uploaded files live in `backend/uploads/` under random names, are only served to the owning student and print staff, and are deleted when a job is collected, cancelled or expires (24 hours). Unpaid uploads are deleted after 24 hours.
- Print rates are placeholders until an admin saves real ones on the admin screen.

## Canteen (Phase 3)

- Students order from the menu, pick a pickup time (suggested: their next break or free slot), pay with the **demo payment** and get a token. The order appears on the day line at its pickup time.
- Canteen staff log in as `canteen`. The kitchen board (dark by default) shows the prep list per 15-minute pickup window, tickets in Placed / Preparing / Ready, and a "Menu and stock" tab with suggested prep (a plain average of the last 4 same weekdays).
- Orders still `ready` 30 minutes after pickup, and unfinished orders from earlier days, become "Not collected" automatically.

## Collect by barcode (Phase 4)

- Every student ID card carries a Code 128 barcode of the roll number. Students also see it on their Profile ID card and on any pass that is ready, so it can be scanned from a phone.
- The kitchen board and the print queue each have a **Collect** field that keeps focus. A USB barcode scanner types the code and presses Enter; everything ready for that student at that desk is handed over, and their pass is stamped "Collected" live.
- Results: Collected, Not ready yet, Nothing to collect, Unknown card, each shown large for 4 seconds with a distinct sound (toggle on the desk). A second scan of the same card within 3 seconds is ignored. Every scan is logged.
- No scanner? In demo mode, use **Simulate scan** beside the field.

## Deploy and demo mode (Phase 5)

- One Docker container (`Dockerfile`) serves the API, the realtime socket and the built frontend. `render.yaml` deploys it to Render's free plan in one click; see [DEPLOY.md](DEPLOY.md).
- An empty database is seeded on boot, so a fresh deployment is ready to use.
- With `DEMO_MODE=true` the clock starts at this week's **Monday 12:20** and runs forward. The banner offers **Reset demo**, which re-seeds everything and puts the clock back. Seed it the same way locally with `python -m app.seed --demo`.
- `GET /api/health` reports the database and whether Qdrant, Lyzr and Omi are configured (it never returns secret values).

## Shared memory with Qdrant (Phase 6)

- One memory every agent reads and writes, in the Qdrant collection `dayline_memory` (one tenant per student: payload index `student_id` with `is_tenant`). Code: `backend/app/services/memory_service.py` and `memory_backends.py`.
- Embeddings come from **Qdrant Cloud Inference** with the free model `sentence-transformers/all-minilm-l6-v2` (384 dimensions), so no paid key and no model on our server.
- Every read, update and delete is filtered by the student id from the login session. `pytest tests/test_memory.py` proves isolation offline; `DAYLINE_LIVE_QDRANT=1 pytest tests/test_memory_live.py` proves it on the real cluster.
- Written automatically after each order ("Ordered Veg fried rice × 1 for 12:40 pickup on a Monday") and print job ("Printed lab_record.pdf: 2 copies, black and white, double sided"), and when the student says "Remember that …" on the Memory screen.
- The **Memory** screen lists memories newest first, searches by meaning, shows who wrote each one and when it was last used, and deletes one or all.
- If Qdrant can't be reached, memories go to a temporary in-process store and the Memory screen says so; the app keeps working and reconnects automatically.

## Agents with Lyzr (Phase 7)

- **Ask Dayline**: on phones, the bar above the dock opens a full-height sheet; on laptops, it's a panel on Today and a button on every other screen. Type, hold the mic to talk (where the browser supports it; spoken replies can be muted), attach a PDF, or tap a shortcut.
- **Five agents:** Orchestrator, Timetable, Print, Canteen (and a Listener for Omi in Phase 8). Their instructions are `backend/app/agents/prompts/*.md`; `python -m scripts.setup_lyzr --apply` creates or updates them in Lyzr and prints their ids.
- **Our backend orchestrates** (addendum H fallback): the free plan's custom tools would need a public tool server for every call, so Lyzr agents answer in JSON (which agents to ask, which tools to call) and the backend runs the tools itself (`backend/app/agents/orchestrator.py`, `tools.py`). Each agent call falls back to the keyword router (`mock_router.py`) on timeout, error, bad JSON or the daily call limit, and the trace says so.
- **The model never sees who the student is.** Each message starts a run with a random 5-minute run token; tools take no student id and their arguments reject unknown fields; Lyzr sees a pseudonymous user id. Questions about another student are refused before any model is called.
- **Numbers come from tools.** An answer with a number that isn't in the tool results is replaced by the router's answer from the same results.
- **Agents never spend money.** Food orders and print jobs come back as dashed proposal cards; "Confirm and pay" uses the normal canteen and print endpoints, and "Edit" opens those screens filled in.
- **The trace:** each agent joins as a chip and fills with its colour when it's done (Timetable magenta, Print cyan, Canteen yellow), with every tool call and memory read or write listed underneath; it folds to one line when the answer arrives.
- **Shared memory in action:** "Get me lunch" uses your usual for that weekday; "Print this like last time" reuses the last settings; "My DBMS lab record is due Thursday" sets that file's deadline. The demo seeds these for Ananya.
- **Nudges on Today** (at most two, from rules, not a model): something ready to collect, a lab within an hour and nothing printing, lunch within 30 minutes and nothing ordered, a subject below the threshold.
- Tests: `pytest tests/test_agents.py` (mock mode, plus a fake Lyzr that checks the exact request shape and that no request carries the student's name, roll number or id).
