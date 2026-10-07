# Dayline — 5-Minute Demo Script

Login URL: **https://dayline-4lxb.onrender.com/login**  
All demo accounts use PIN **1234**.

---

## 0:00 – 0:30 · The problem (narrate, don't click)

> "Every engineering student in India wastes time on three things every single day —
> the print queue, the canteen queue, and attendance arithmetic.
> These aren't three separate problems. They're one. Everything ties back to your timetable,
> and right now nothing talks to anything else. Dayline fixes that."

---

## 0:30 – 1:00 · Log in as a student

1. Open the demo URL.
2. Click **22CS001 · Ananya Rao** from the demo accounts drawer.
3. PIN: `1234` → **Log in**.
4. The **Today** screen loads. Point out:
   - The day as a vertical timeline — classes, breaks, passes.
   - The demo clock shows **Monday 12:20** (right before lunch break).
   - The "Demo mode" chip at the top.

---

## 1:00 – 2:30 · The showstopper — one sentence, three agents

1. Tap the **Ask Dayline** bar at the bottom.
2. Attach a PDF (any small PDF from your device, or skip the attachment and just type).
3. Type exactly:
   > **"Get me lunch and print my lab record before my next class"**
4. Hit send and narrate what happens:
   - **Orchestrator** receives the request.
   - **Timetable agent** fires → finds next class: DBMS lab at 2:00 PM, free slot at 12:40.
   - **Print agent** fires → sets deadline 10 min before the 2:00 class → proposes print job.
   - **Canteen agent** fires → sets pickup at the 12:40 free slot → proposes lunch order.
   - Agent trace lights up on screen as each one runs.
5. Two proposal cards appear. Show both — print job with cost and deadline, canteen order with pickup time.
6. Tap **Confirm** on both.
7. Back on **Today**, two new passes appear on the timeline: a yellow print pass and a cyan canteen pass.

> "One sentence. Three agents collaborated. Nothing is ordered until I confirmed."

---

## 2:30 – 3:15 · Collection flow — staff side

1. Open a new tab (or use a second device). Log in as **canteen** / PIN `1234`.
2. The canteen staff screen shows the live order queue. Find Ananya's order.
3. Mark it **Ready**.
4. Switch back to the student view — the canteen pass updates automatically (live WebSocket).
5. Tap **Simulate scan** on the canteen pass — or show the barcode on the student ID card.
6. The pass stamps **Collected** in real time.

> "No token, no queue number. Walk in, scan your ID, walk out."

---

## 3:15 – 3:45 · Memory — Qdrant in action

1. Go to the **Memory** tab.
2. Show the memories written by the agents during the previous request — print settings, canteen preference, timetable note.
3. Type in the Ask bar:
   > **"Order my usual"**
4. The canteen agent reads memory, proposes the same lunch with no re-typing.

> "Qdrant stores what the agents learned. Every request makes the next one smarter."

---

## 3:45 – 4:30 · Omi voice loop — simulator

1. Go to **Profile** (avatar, top right on Today) → **Omi Simulator**.
2. In the Speech box, type:
   > **"Hey Dayline, can I skip tomorrow's DBMS class?"**
3. Tap **Send as transcript** (simulates Omi's real-time webhook firing).
4. The Listener agent extracts the request. The Orchestrator answers with attendance data.
5. The reply appears as a notification on the Today screen.
6. In the Conversation box, paste the sample conversation and tap **Extract memories**.
7. Two or three facts are saved to Qdrant — show them in the Memory tab.

> "On the real device, this happens hands-free. The same code path runs."

---

## 4:30 – 5:00 · Close — integrations live

1. Open **https://dayline-4lxb.onrender.com/api/health** in the browser.
2. Show the JSON:
   - `qdrant.ok: true` — vector memory live.
   - `lyzr.agents_configured: 5` — all five agents on Lyzr Studio.
   - `omi.configured: true` — webhook endpoints active.
3. Close:

> "Dayline is a campus OS — timetable, print, canteen, memory and voice, all connected
> through one multi-agent loop built on Lyzr, Qdrant and Omi.
> It's live, it's working, and it's something students actually need every single day."

---

## Fallback if Lyzr times out

The app has a keyword router that handles the request locally and marks the trace as `mock`.
The UI still shows the full agent flow. Keep going — it still demonstrates the architecture.

## Reset between runs

Hit the **Reset demo** chip (top of Today on desktop, bottom of Profile on mobile) to restore
the clock to Monday 12:20 and clear all orders. Takes 2 seconds.
