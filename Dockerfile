FROM node:18-slim AS node-builder

WORKDIR /app

# Copy only Node dependency manifests so npm layers stay cacheable.
COPY package.json package-lock.json ./
COPY frontend/package.json frontend/package-lock.json ./frontend/

RUN npm ci \
  && npm ci --prefix frontend


FROM python:3.11-slim AS python-builder

WORKDIR /app/backend

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

# Reuse the official uv binaries and install Python deps before copying app code.
COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /uvx /bin/
COPY backend/pyproject.toml backend/uv.lock ./

RUN uv venv \
  && uv sync --frozen


FROM python:3.11-slim

WORKDIR /app

ENV PATH="/app/backend/.venv/bin:${PATH}"

# Final image needs both Python and Node because `npm run dev` starts frontend and backend.
RUN apt-get update \
  && apt-get install -y --no-install-recommends nodejs npm \
  && rm -rf /var/lib/apt/lists/*

# Copy prebuilt dependency layers first.
COPY --from=node-builder /app/node_modules ./node_modules
COPY --from=node-builder /app/frontend/node_modules ./frontend/node_modules
COPY --from=python-builder /app/backend/.venv ./backend/.venv

# Copy source code last to maximize layer cache reuse.
COPY package.json package-lock.json ./
COPY frontend/ ./frontend/
COPY backend/ ./backend/
COPY static/ ./static/

EXPOSE 3000 5001

CMD ["npm", "run", "dev"]
