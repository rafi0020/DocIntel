FROM python:3.12-slim

# Tesseract for OCR; libglib + libGL for OpenCV (pulled in by RapidOCR)
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng libglib2.0-0 libgl1 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt

# Bake the embedding model into the image so search works offline
ENV MODEL_DIR=/models
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir='/models')"

COPY app ./app
COPY eval ./eval
COPY tests ./tests

RUN useradd --create-home --uid 10001 app && mkdir -p /data && chown -R app /data /models
USER app
ENV STORAGE_DIR=/data PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--proxy-headers"]
