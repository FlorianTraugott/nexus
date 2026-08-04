# Multi-stage build for the Next.js standalone output.
#
# All stages share node:24-slim (glibc). Do NOT switch to alpine: the lockfile's
# linux-only native optional deps (@tailwindcss/oxide, the emnapi/wasm chain)
# were repaired inside a glibc container, and alpine's musl resolves a DIFFERENT
# native variant set — switching would risk reopening that exact lockfile bug.
# slim also matches CI's setup-node (glibc).

FROM node:24-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci


FROM node:24-slim AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# NEXT_PUBLIC_* are inlined into the CLIENT bundle at `next build`, so the API
# URL must be set BEFORE the build. CI passes a dummy (the image is then not
# deployable); the deployable image must be built with the real backend URL at
# deploy time (12.6) — changing it later requires a REBUILD, not a restart.
# Every NEXT_PUBLIC_* the app reads needs its own ARG: Railway passes service
# variables as build args, but Docker only admits ones the Dockerfile declares.
# An undeclared var is not an error — it is simply undefined at build time, so
# the feature guarded by it silently never renders in the deployed image.
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_DEMO_RESEARCH_TASK_ID
ENV NEXT_PUBLIC_DEMO_RESEARCH_TASK_ID=$NEXT_PUBLIC_DEMO_RESEARCH_TASK_ID
ARG NEXT_PUBLIC_DEMO_EMAIL
ENV NEXT_PUBLIC_DEMO_EMAIL=$NEXT_PUBLIC_DEMO_EMAIL
ARG NEXT_PUBLIC_DEMO_PASSWORD
ENV NEXT_PUBLIC_DEMO_PASSWORD=$NEXT_PUBLIC_DEMO_PASSWORD
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build


FROM node:24-slim AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

RUN useradd --create-home --uid 10001 --user-group nextjs

# server.js does NOT include public/ or .next/static — copy them explicitly.
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nextjs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nextjs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000
CMD ["node", "server.js"]
