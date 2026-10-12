# discord-voice 이미지(IMPL-PLAN-9-parallel): gateway.mjs가 음성·녹음·전사를 맡는다. poc.mjs는 M0 PoC용으로 남긴다.
# ffmpeg은 전사 전 리먹스(ogg→webm)·wav 재시도 변환과 구간 파일 재생 확인(ffprobe)에 쓴다.
FROM node:22-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force
COPY poc.mjs gateway.mjs ./
COPY src ./src
# 이름 있는 볼륨은 처음 만들 때 이미지 폴더의 소유자를 물려받는다(node가 /data/meetings에 쓴다)
RUN mkdir -p /data && chown node:node /data
ENV NODE_ENV=production NODE_OPTIONS=--max-old-space-size=160
USER node
CMD ["node", "gateway.mjs"]
