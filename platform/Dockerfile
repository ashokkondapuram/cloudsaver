# syntax=docker/dockerfile:1
# zafin-platform-identity: identity-service, its migrations and the billing jobs.
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY requirements.txt .
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home appuser
COPY --chown=appuser:appuser identity identity
COPY --chown=appuser:appuser identity_migrations identity_migrations
COPY --chown=appuser:appuser identity_alembic.ini .
USER appuser
EXPOSE 8005
CMD ["uvicorn", "identity.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8005"]
