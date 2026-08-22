FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl unzip ca-certificates \
    && ARCH=$(dpkg --print-architecture) \
    && case "$ARCH" in \
         amd64) XRAY_ARCH=64 ;; \
         arm64) XRAY_ARCH=arm64-v8a ;; \
         *) echo "Unsupported architecture: $ARCH" && exit 1 ;; \
       esac \
    && curl -fsSL -o /tmp/xray.zip \
       "https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-${XRAY_ARCH}.zip" \
    && unzip -q /tmp/xray.zip -d /tmp/xray \
    && mv /tmp/xray/xray /usr/local/bin/xray \
    && chmod +x /usr/local/bin/xray \
    && rm -rf /tmp/xray.zip /tmp/xray \
    && apt-get purge -y unzip \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1
ENV FUNCTIONAL_TEST_ENABLED=false

CMD ["python", "main.py"]
