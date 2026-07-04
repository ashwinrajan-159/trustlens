# TrustLens AI — API/worker image
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps (psycopg/asyncpg build, healthcheck curl, libgomp1 for paddlepaddle)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential curl libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# PaddleOCR — real OCR for scanned images (PAN/Aadhaar photos). Heavy native dep,
# kept out of requirements.txt; without it image documents yield no text/entities
# (PyMuPDF only extracts embedded text from digital PDFs). Models download to
# ~/.paddleocr on first use — bundle them into the image for air-gapped deploys.
RUN pip install paddlepaddle==3.0.0 "paddleocr>=2.9,<3"
# paddlepaddle imports setuptools at runtime (python-slim doesn't ship it), and
# paddleocr pulls the GUI OpenCV build, which needs libxcb/X libs the server lacks —
# swap every cv2 variant for the single headless-contrib build.
RUN pip install setuptools \
    && pip uninstall -y opencv-python opencv-contrib-python opencv-python-headless opencv-contrib-python-headless \
    && pip install opencv-contrib-python-headless

COPY . .

# Non-root runtime user
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
