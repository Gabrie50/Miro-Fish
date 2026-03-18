FROM node:18-slim AS node-builder

WORKDIR /app

# Copy only Node dependency manifests so npm layers stay cacheable.
COPY package.json package-lock.json ./
COPY frontend/package.json frontend/package-lock.json ./frontend/

RUN npm ci \
  --no-audit --no-fund \
  && npm ci --prefix frontend --no-audit --no-fund \
  && npm cache clean --force


FROM python:3.11-slim AS python-builder

WORKDIR /app/backend

ENV VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:${PATH}" \
    PIP_NO_CACHE_DIR=1

# Install runtime Python dependencies from requirements for faster container builds.
COPY backend/requirements.txt ./requirements.txt

RUN python -m venv "${VIRTUAL_ENV}" \
  && pip install -r requirements.txt


FROM python:3.11-slim

WORKDIR /app

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Final image needs both Python and Node because `npm run dev` starts frontend and backend.
RUN apt-get update \
  && apt-get install -y --no-install-recommends nodejs npm \
  && rm -rf /var/lib/apt/lists/*

# Copy prebuilt dependency layers first.
COPY --from=node-builder /app/node_modules ./node_modules
COPY --from=node-builder /app/frontend/node_modules ./frontend/node_modules
COPY --from=python-builder /opt/venv /opt/venv

# Copy source code last to maximize layer cache reuse.
COPY package.json package-lock.json ./
COPY frontend/ ./frontend/
COPY backend/ ./backend/

EXPOSE 3000 5001

CMD ["npm", "run", "dev"]
