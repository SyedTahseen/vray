FROM python:3.12-slim

ARG XRAY_VERSION=v26.11.9

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl unzip ca-certificates \
    && ARCH=$(dpkg --print-architecture) \
    && case "$ARCH" in \
         amd64) XRAY_ARCH=64 ;; \
         arm64) XRAY_ARCH=arm64-v8a ;; \
         *) echo "Unsupported architecture: $ARCH" && exit 1 ;; \
       esac \
    && if [ "$XRAY_VERSION" = "latest" ]; then \
         XRAY_URL="https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-${XRAY_ARCH}.zip"; \
       else \
         XRAY_URL="https://github.com/XTLS/Xray-core/releases/download/${XRAY_VERSION}/Xray-linux-${XRAY_ARCH}.zip"; \
       fi \
    && curl -fsSL -o /tmp/xray.zip "$XRAY_URL" \
    && curl -fsSL -o /tmp/xray.zip.dgst "${XRAY_URL}.dgst" \
    && EXPECTED=$(grep -i '256' /tmp/xray.zip.dgst | grep -oE '[0-9a-fA-F]{64}' | head -n1) \
    && [ -n "$EXPECTED" ] \
    && echo "$EXPECTED  /tmp/xray.zip" | sha256sum -c - \
    && unzip -q /tmp/xray.zip -d /tmp/xray \
    && mv /tmp/xray/xray /usr/local/bin/xray \
    && chmod +x /usr/local/bin/xray \
    && rm -rf /tmp/xray.zip /tmp/xray.zip.dgst /tmp/xray \
    && apt-get purge -y curl unzip \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /data

VOLUME ["/data"]

ENV PYTHONUNBUFFERED=1
ENV DB_PATH=/data/v2ray_bot.sqlite3

CMD ["python", "-m", "app"]
