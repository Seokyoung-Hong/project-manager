# 개인 AI "GitHub Copilot(내 구독)" 런타임(core/assist/copilot.py). Copilot SDK 문서의 backend-services 예시 그대로.
# 측정(2026-10-13, linux/amd64, v1.0.96 --headless 유휴): docker stats 약 186MiB, 프로세스 최대 RSS 약 294MB(파일 매핑 포함).
FROM debian:bookworm-slim
ARG COPILOT_VERSION=1.0.96
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates wget \
    && ARCH=$(dpkg --print-architecture) \
    && case "${ARCH}" in amd64) COPILOT_ARCH="x64" ;; arm64) COPILOT_ARCH="arm64" ;; esac \
    && wget -q "https://github.com/github/copilot-cli/releases/download/v${COPILOT_VERSION}/copilot-linux-${COPILOT_ARCH}.tar.gz" \
    && tar -xzf "copilot-linux-${COPILOT_ARCH}.tar.gz" && mv copilot /usr/local/bin/ \
    && rm "copilot-linux-${COPILOT_ARCH}.tar.gz" \
    && apt-get purge -y wget && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*
RUN useradd -m copilot
USER copilot
ENTRYPOINT ["copilot"]
CMD ["--headless", "--host", "0.0.0.0", "--port", "4321", "--session-idle-timeout", "300"]
