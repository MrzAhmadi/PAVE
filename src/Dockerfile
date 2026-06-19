FROM python:3.13-slim-bookworm

RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends \
       curl \
       ca-certificates \
       unzip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN set -eux; \
    ARCH="$(dpkg --print-architecture)"; \
    case "$ARCH" in \
        amd64)  XRAY_ARCH="64" ;; \
        arm64)  XRAY_ARCH="arm64-v8a" ;; \
        armhf)  XRAY_ARCH="arm32-v7a" ;; \
        *)      XRAY_ARCH="64" ;; \
    esac; \
    VERSION="$(curl -fsSL https://api.github.com/repos/XTLS/Xray-core/releases/latest \
               | grep '"tag_name"' | head -1 | cut -d'"' -f4)"; \
    echo "Installing xray ${VERSION} (${XRAY_ARCH})"; \
    curl -fsSL "https://github.com/XTLS/Xray-core/releases/download/${VERSION}/Xray-linux-${XRAY_ARCH}.zip" \
         -o /tmp/xray.zip; \
    unzip /tmp/xray.zip xray -d /usr/local/bin/; \
    chmod +x /usr/local/bin/xray; \
    rm /tmp/xray.zip; \
    xray version

RUN set -eux; \
    ARCH="$(dpkg --print-architecture)"; \
    case "$ARCH" in \
        amd64) HY2_ARCH="linux-amd64" ;; \
        arm64) HY2_ARCH="linux-arm64" ;; \
        armhf) HY2_ARCH="linux-arm-6" ;; \
        *)     HY2_ARCH="linux-amd64" ;; \
    esac; \
    VERSION="$(curl -fsSL https://api.github.com/repos/apernet/hysteria/releases/latest \
               | grep '"tag_name"' | head -1 | cut -d'"' -f4)"; \
    echo "Installing hysteria2 ${VERSION} (${HY2_ARCH})"; \
    curl -fsSL "https://github.com/apernet/hysteria/releases/download/${VERSION}/hysteria-${HY2_ARCH}" \
         -o /usr/local/bin/hysteria2; \
    chmod +x /usr/local/bin/hysteria2; \
    hysteria2 version

RUN set -eux; \
    ARCH="$(dpkg --print-architecture)"; \
    case "$ARCH" in \
        amd64) SB_ARCH="linux-amd64" ;; \
        arm64) SB_ARCH="linux-arm64" ;; \
        armhf) SB_ARCH="linux-armv7" ;; \
        *)     SB_ARCH="linux-amd64" ;; \
    esac; \
    VERSION="$(curl -fsSL https://api.github.com/repos/SagerNet/sing-box/releases/latest \
               | grep '"tag_name"' | head -1 | cut -d'"' -f4)"; \
    VER="${VERSION#v}"; \
    echo "Installing sing-box ${VERSION} (${SB_ARCH})"; \
    curl -fsSL "https://github.com/SagerNet/sing-box/releases/download/${VERSION}/sing-box-${VER}-${SB_ARCH}.tar.gz" \
         -o /tmp/sing-box.tar.gz; \
    tar -xzf /tmp/sing-box.tar.gz -C /tmp/; \
    mv "/tmp/sing-box-${VER}-${SB_ARCH}/sing-box" /usr/local/bin/sing-box; \
    chmod +x /usr/local/bin/sing-box; \
    rm -rf /tmp/sing-box.tar.gz "/tmp/sing-box-${VER}-${SB_ARCH}"; \
    sing-box version

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY configprobe/ ./configprobe/
COPY main.py .

RUN mkdir -p /results

ENTRYPOINT ["python", "main.py"]

CMD ["-i", "/subs/subscriptions.txt", "-w", "10", "-o", "/results"]
