# --- builder
FROM python:3.11-slim AS builder
WORKDIR /app
RUN pip install --no-cache-dir uv==0.2
COPY pyproject.toml README.md ./
COPY src ./src
RUN uv pip install --system --no-cache .

# --- runtime
FROM python:3.11-slim
RUN useradd --create-home --uid 10001 tl_towerwatch
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY src ./src
ENV TOWERWATCH_DATA_DIR=/data
EXPOSE 8000
USER tl_towerwatch
CMD ["tl_towerwatch", "serve", "--host", "0.0.0.0", "--port", "8000"]