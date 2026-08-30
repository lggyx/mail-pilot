# 多阶段构建：bun 构建前端 → uv 运行后端（前后端同仓同进程）
# 构建上下文为仓库根目录：docker build -f deploy/Dockerfile .

# ---------- 阶段 1：前端构建 ----------
FROM oven/bun:1 AS frontend
WORKDIR /build
COPY frontend/package.json frontend/bun.lock* ./
RUN bun install --frozen-lockfile || bun install
COPY frontend/ ./
RUN bun run build

# ---------- 阶段 2：运行时（uv + Python 3.12） ----------
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app

# 先装依赖（利用层缓存）
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev

# 后端代码与前端产物
COPY backend/app ./app
COPY --from=frontend /build/dist ./frontend-dist

ENV PYTHONUNBUFFERED=1 \
    DATA_DIR=/app/data \
    STATIC_DIR=/app/frontend-dist \
    RUN_SCHEDULER=true

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health')" || exit 1

CMD ["/app/.venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
