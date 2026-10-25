FROM python:3.12-alpine
WORKDIR /app
COPY --chown=10001:10001 proxy.py ./
USER 10001:10001
EXPOSE 3128
CMD ["python","proxy.py"]
