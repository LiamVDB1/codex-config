FROM docker.io/library/python:3.13-alpine@sha256:540c7d91f98ff6880174c40e99067bf5941eb54d818a7a5e094d188b196a934d

ARG SOURCE_COMMIT
ARG APP_VERSION
LABEL org.opencontainers.image.source="https://github.com/LiamVDB1/codex-config" \
      org.opencontainers.image.revision="${SOURCE_COMMIT}" \
      org.opencontainers.image.version="${APP_VERSION}"

WORKDIR /app
COPY app.py VERSION ./
USER 65532:65532
EXPOSE 8080
HEALTHCHECK --interval=5s --timeout=3s --retries=12 --start-period=5s CMD ["wget", "-qO-", "http://127.0.0.1:8080/healthz"]
ENTRYPOINT ["python3", "/app/app.py"]
