FROM python:3.11-slim

# ffmpeg is required by faster-whisper to decode mp4/mkv/avi audio tracks.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first so the layer is cached across code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code and static frontend.
COPY app/ ./app/
COPY frontend/ ./frontend/

# The Whisper model is NOT baked into the image on purpose — it is downloaded
# at runtime into the whisper-cache named volume (see docker-compose.yml).
ENV HF_HOME=/root/.cache/huggingface

EXPOSE 8000

# Default command runs the API. The worker service overrides this in compose.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
