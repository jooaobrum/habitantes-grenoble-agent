# WhatsApp (Baileys) adapter — Node/TypeScript service.
# Built from the repo root (docker-compose sets context: .), so all COPY paths
# below are relative to the repo root.
FROM node:20-alpine

# Repo root maps to /app inside the container (same convention as the Python
# services). The bot code therefore lives at /app/app/whatsapp_bot so that the
# config loader's repoRoot() — resolve(__dirname, "..","..","..") from the
# compiled dist/*.js — cleanly resolves to /app. That makes the relative
# auth_dir ("artifacts/whatsapp/auth" from base.yaml) land on the mounted
# /app/artifacts volume, so the login session survives rebuilds.
WORKDIR /app/app/whatsapp_bot

# 1. Install dependencies first for better layer caching. A lockfile ships with
#    the service, so use the deterministic `npm ci`. Dev deps (typescript, types)
#    are needed for the build, so do NOT omit them here.
COPY app/whatsapp_bot/package*.json ./
RUN npm ci

# 2. Copy only what the TypeScript build needs — never the host's node_modules
#    (wrong platform: darwin vs alpine) or a stale dist. .dockerignore documents
#    the same intent; the selective copy makes it robust regardless.
COPY app/whatsapp_bot/tsconfig.json ./
COPY app/whatsapp_bot/src ./src

# 3. Compile TS -> dist/ (tsc, per package.json "build"; test files are excluded
#    by tsconfig).
RUN npm run build

# config is mounted at /app/config (CONFIG_DIR overrides the loader's default);
# the Baileys auth session persists under /app/artifacts/whatsapp/auth.
CMD ["node", "dist/index.js"]
