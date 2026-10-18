FROM python:3.13.9-slim@sha256:326df678c20c78d465db501563f3492d17c42a4afe33a1f2bf5406a1d56b0e86
ARG SOURCE_REVISION=unknown
ARG SERVICE_ROLE=worker
WORKDIR /app
COPY services/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY services ./services
LABEL org.opencontainers.image.revision=${SOURCE_REVISION} \
      com.speech-platform.service-role=${SERVICE_ROLE} \
      com.speech-platform.service="tts" \
      com.speech-platform.runtime-variant="health-only"
USER 65532:65532
ENTRYPOINT ["python", "-m"]
