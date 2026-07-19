# --- Stage 1: build the React (Vite) frontend into static assets ------------
FROM node:20-slim AS frontend
WORKDIR /ui
COPY frontend/package.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# --- Stage 2: Python runtime (api / worker / bot share this image) ----------
FROM python:3.11-slim

# ffmpeg is required by faster-whisper to decode mp4/mkv/avi audio tracks.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first so the layer is cached across code changes.
# torch/torchaudio come from the CPU-only wheel index BEFORE requirements.txt so
# pyannote.audio doesn't pull the multi-GB CUDA build into the image.
COPY requirements.txt .
RUN pip install --no-cache-dir torch==2.5.1 torchaudio==2.5.1 \
        --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt

# Application code and the built frontend (from stage 1).
COPY app/ ./app/
COPY --from=frontend /ui/dist ./frontend/dist

# The Whisper model is NOT baked into the image on purpose — it is downloaded
# at runtime into the whisper-cache named volume (see docker-compose.yml).
ENV HF_HOME=/root/.cache/huggingface

EXPOSE 8000

# Default command runs the API. The worker service overrides this in compose.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
