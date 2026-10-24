FROM node:24-bookworm-slim AS frontend
WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN npm ci --ignore-scripts
COPY frontend/ ./
COPY scripts/generate-notices.mjs /build/scripts/generate-notices.mjs
COPY docs/licenses/ /build/docs/licenses/
RUN npm run build

FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 FRONTEND_DIST=/app/frontend/dist
RUN groupadd --gid 10001 hamava && useradd --uid 10001 --gid hamava --create-home hamava
WORKDIR /app
COPY pyproject.toml requirements.lock.txt requirements-bootstrap.txt ./
COPY backend ./backend
RUN python -m pip install --upgrade -r requirements-bootstrap.txt \
    && python -m pip install --constraint requirements.lock.txt '.[media]'
COPY scripts ./scripts
COPY --from=frontend /build/frontend/dist ./frontend/dist
USER 10001:10001
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "receptionist.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
