FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core fonts-noto-core fonts-noto-extra ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY vps/requirements.txt /app/vps/requirements.txt
RUN pip install --no-cache-dir -r /app/vps/requirements.txt
COPY . /app
RUN python -m py_compile layout_lock.py vps/config.py vps/source_cache.py vps/source_catalog.py vps/social_metadata.py vps/youtube_publisher.py vps/visual_contract.py vps/local_renderer.py vps/pipeline.py vps/api.py vps/worker.py vps/entrypoint.py vps/stress_test.py vps/service.py vps/source_ingest_smoke.py
CMD ["python", "-m", "vps.worker"]
