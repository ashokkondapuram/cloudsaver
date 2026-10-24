# syntax=docker/dockerfile:1
FROM node:24.22.1-alpine
WORKDIR /app
ENV NODE_ENV=production NODE_USE_ENV_PROXY=1
COPY --chown=node:node package.json package-lock.json ./
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/proxy_ca; fi; \
    npm ci --omit=dev --ignore-scripts && npm cache clean --force
COPY --chown=node:node src/*.ts ./src/
USER node
CMD ["node", "--disable-proto=throw", "src/main.ts"]
