FROM python:3.13.9-slim@sha256:326df678c20c78d465db501563f3492d17c42a4afe33a1f2bf5406a1d56b0e86
ARG SOURCE_REVISION=unknown
ARG SERVICE_ROLE=stt-worker
ARG STT_CPU_LOCK_SHA256
WORKDIR /app
COPY services/requirements-stt-cpu.lock ./requirements.lock
RUN python -c 'import hashlib, os; expected=hashlib.sha256(open("requirements.lock", "rb").read()).hexdigest(); assert os.environ.get("STT_CPU_LOCK_SHA256") == expected, "CPU lock digest mismatch"'
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
COPY services ./services
LABEL org.opencontainers.image.revision=${SOURCE_REVISION} \
      com.speech-platform.service-role=${SERVICE_ROLE} \
      com.speech-platform.service="stt" \
      com.speech-platform.runtime-variant="cpu" \
      com.speech-platform.cpu-lock-sha256=${STT_CPU_LOCK_SHA256}
USER 65532:65532
ENTRYPOINT ["python", "-m"]
