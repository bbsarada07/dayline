# Dayline

A campus web app for students of one engineering college: the timetable, attendance, canteen pre-orders and print jobs, all tied to the student's day.

> **Status: Phase 5 of `DAYLINE_ADDENDUM_V2.md` section K (deploy) built.** Foundation, Today screen, attendance, print, canteen and collect by barcode are done. The full README (architecture diagram, sponsor integrations, demo script, known limits) is written in Phase 10.

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
