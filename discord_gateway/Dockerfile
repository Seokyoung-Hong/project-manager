# 운영 discord-bot 자리를 이어받을 게이트웨이 이미지(M0는 poc.mjs만 돈다).
# ffmpeg은 M3 리먹스(ogg→webm)와 서버에서 구간 파일 재생 확인(ffprobe)에 쓴다(설계서 v1 §2.3).
FROM node:22-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force
COPY poc.mjs ./
COPY src ./src
ENV NODE_ENV=production NODE_OPTIONS=--max-old-space-size=160
USER node
CMD ["node", "poc.mjs"]
