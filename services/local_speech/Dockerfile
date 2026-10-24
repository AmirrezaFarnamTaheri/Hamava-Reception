FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
RUN apt-get update && apt-get install --no-install-recommends -y ffmpeg libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 hamava && useradd --uid 10001 --gid hamava --create-home hamava
WORKDIR /app
COPY pyproject.toml requirements.lock.txt requirements-bootstrap.txt ./
COPY backend ./backend
RUN python -m pip install --upgrade -r requirements-bootstrap.txt \
    && python -m pip install --constraint requirements.lock.txt '.[speech]'
COPY services/local_speech ./services/local_speech
USER 10001:10001
EXPOSE 8090
CMD ["python", "-m", "uvicorn", "services.local_speech.app:app", "--host", "0.0.0.0", "--port", "8090", "--no-access-log"]
