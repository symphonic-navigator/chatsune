# ---------- Build stage ----------
FROM node:22-alpine AS builder

RUN corepack enable && corepack prepare pnpm@latest --activate

WORKDIR /app

# Install deps first for better layer caching
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# Copy only the download script (not full source) so the 40 MB Vosk model
# layer stays cached across source-file changes — re-downloading on every
# build wastes ~30 seconds and bandwidth in CI.
COPY scripts/download-vosk-model.mjs ./scripts/
RUN pnpm run vosk:download

COPY . .

# The VITE_* values are BAKED into the JS bundle at build time. To get a
# single image that still works across dev/staging/prod, we build with literal
# placeholder strings and rewrite them at container startup (see
# docker-entrypoint.sh). Keep this list in sync with that script.
ENV VITE_API_URL=__VITE_API_URL__
ENV VITE_WS_URL=__VITE_WS_URL__
RUN pnpm run build

# ---------- Runtime stage ----------
FROM nginx:1.27-alpine

# Build-time version metadata. CI injects these; local builds fall back
# to inert placeholders. The VERSION file is served as-is by nginx at
# ``/VERSION`` (plain text) so external tooling can fetch the running
# frontend build without parsing HTML.
ARG VERSION=0.0.0-dev
ARG CHATSUNE_GIT_SHA=""
ARG CHATSUNE_BUILT_AT=""
ENV CHATSUNE_VERSION=$VERSION
ENV CHATSUNE_GIT_SHA=$CHATSUNE_GIT_SHA
ENV CHATSUNE_BUILT_AT=$CHATSUNE_BUILT_AT

# Static assets
COPY --from=builder /app/dist /usr/share/nginx/html

# Plain-text version marker. Written after the dist copy so it is not
# clobbered by a stray ``VERSION`` artifact from the build stage.
RUN echo "$VERSION" > /usr/share/nginx/html/VERSION

# SPA-friendly nginx config (fallback to index.html for client-side routing)
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Runtime env var substitution — the nginx image runs every script placed in
# /docker-entrypoint.d/ before starting the server, so this rewrites the
# __VITE_*__ placeholders using the container's env vars.
COPY docker-entrypoint.sh /docker-entrypoint.d/40-chatsune-envsubst.sh
RUN chmod +x /docker-entrypoint.d/40-chatsune-envsubst.sh

EXPOSE 80
