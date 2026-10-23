# syntax=docker/dockerfile:1
FROM node:24.22.1-alpine AS build
WORKDIR /app
COPY web-dashboard/package*.json ./
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/proxy_ca; fi; \
    npm ci --strict-ssl=true
COPY web-dashboard/ .
COPY docs/MANAGED_IDENTITY_ROLES.md docs/CLOUD_SOURCES.md docs/ENVIRONMENT.md ./docs/
ARG API_GATEWAY_URL=http://api-gateway:8000
ENV API_GATEWAY_URL=$API_GATEWAY_URL NEXT_TELEMETRY_DISABLED=1
RUN npm run build
FROM node:24.22.1-alpine
WORKDIR /app
ENV NODE_ENV=production PORT=3000 HOSTNAME=0.0.0.0
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
USER node
EXPOSE 3000
CMD ["node", "server.js"]
