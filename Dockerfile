FROM python:3.12-slim AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim AS runtime
LABEL org.opencontainers.image.source="https://github.com/artur-matkowski/frigate-gotify"
LABEL org.opencontainers.image.description="Frigate -> Gotify MQTT bridge"
LABEL org.opencontainers.image.licenses="MIT"

COPY --from=builder /install /usr/local
WORKDIR /app
COPY src/ /app/

RUN useradd --system --no-create-home --uid 10001 bridge
USER bridge
ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "bridge"]
