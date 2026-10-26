FROM python:3.11-slim AS builder
WORKDIR /app
RUN pip install uv --quiet
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev

FROM python:3.11-slim
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY backend/ .
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
EXPOSE 8001
# --limit-concurrency: 管理画面のニアリアルタイム連動(SSE /events/stream)は接続が張りっぱなしで
# 各接続がこの上限枠を1つ占有する。50 だと通常リクエストと取り合って枯渇し得るため 300 へ引き上げ
# てヘッドルームを確保する（あくまで同時受理の上限＝天井であり予約ではない。アイドルSSEはDB接続を
# 握らず軽量なので低トラフィックの本番でメモリを圧迫しない）。単一ワーカー維持(--workers 1)で
# in-memory pub/sub が全接続へ届く前提は不変。
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", \
     "--workers", "1", "--loop", "uvloop", "--limit-concurrency", "300"]
