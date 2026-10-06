# Dayline: one container serves the API, the realtime socket and the built frontend.
# Works on Render (sets PORT) and Hugging Face Spaces (port 7860, user 1000).

# ---- 1. Build the frontend ------------------------------------------------------
FROM node:24-slim AS web
WORKDIR /src/frontend
COPY app.config.json /src/app.config.json
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- 2. Run the backend -----------------------------------------------------------
FROM python:3.13-slim
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user     PATH=/home/user/.local/bin:$PATH     PYTHONUNBUFFERED=1     PYTHONDONTWRITEBYTECODE=1
WORKDIR /home/user/app

COPY --chown=user backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir --user -r backend/requirements.txt

COPY --chown=user app.config.json ./
COPY --chown=user backend/app backend/app
COPY --from=web --chown=user /src/frontend/dist frontend/dist

# The disk is temporary on free hosts: the database and uploads reset on restart,
# and the app re-seeds an empty database on boot (addendum F).
ENV SERVE_FRONTEND=true     DEMO_MODE=true     DATABASE_URL=sqlite:////tmp/dayline.db     UPLOAD_DIR=/tmp/dayline-uploads     PORT=7860

WORKDIR /home/user/app/backend
EXPOSE 7860
CMD ["python", "-m", "app"]
