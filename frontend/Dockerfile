FROM node:22.18.0-alpine AS base
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8100
ARG COCKPIT_RELEASE=development
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
ENV NEXT_PUBLIC_COCKPIT_RELEASE=${COCKPIT_RELEASE}
ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0
RUN corepack enable && corepack prepare pnpm@11.9.0 --activate
WORKDIR /app
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .

FROM base AS development
RUN chown node:node /app /app/next-env.d.ts
USER node
CMD ["pnpm", "dev", "--hostname", "0.0.0.0"]

FROM base AS build
RUN pnpm build

FROM node:22.18.0-alpine AS production
WORKDIR /app
ENV NODE_ENV=production
ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
USER node
CMD ["node", "server.js"]
