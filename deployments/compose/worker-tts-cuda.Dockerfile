FROM nvidia/cuda:12.8.1-base-ubuntu24.04@sha256:133c78a0575303be34164d0b90137a042172bdf60696af01a3c424ab402d86e2
ARG SOURCE_REVISION=unknown
ARG TTS_MODEL_REVISION=32279effe8c19989596f05d353d1447f51d9e915
ARG TTS_SOURCE_REVISION=cce58a5b59303c9bd63d12f23afe6a49a4a80c59
ARG TTS_LOCK_SHA256
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates git libsndfile1 python3.12 python3.12-venv \
    && rm -rf /var/lib/apt/lists/* \
    && python3.12 -m venv /opt/tts-venv
ENV PATH=/opt/tts-venv/bin:$PATH \
    HF_HUB_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 TRANSFORMERS_OFFLINE=1 \
    PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY services/requirements-tts.lock ./requirements-tts.lock
RUN python -c 'import hashlib,os; assert hashlib.sha256(open("requirements-tts.lock","rb").read()).hexdigest()==os.environ.get("TTS_LOCK_SHA256"), "TTS lock digest mismatch"' \
    && python -m pip install --no-cache-dir --require-hashes --extra-index-url https://download.pytorch.org/whl/cu128 -r requirements-tts.lock \
    && git clone https://github.com/OpenBMB/VoxCPM.git /tmp/VoxCPM \
    && git -C /tmp/VoxCPM checkout ${TTS_SOURCE_REVISION} \
    && python -m pip install --no-cache-dir --no-deps --no-build-isolation /tmp/VoxCPM \
    && rm -rf /tmp/VoxCPM
COPY services ./services
LABEL org.opencontainers.image.revision=${SOURCE_REVISION} \
      com.speech-platform.service-role="tts-worker" \
      com.speech-platform.service="tts" \
      com.speech-platform.runtime-variant="cuda" \
      com.speech-platform.model-revision=${TTS_MODEL_REVISION} \
      com.speech-platform.source-provider-revision=${TTS_SOURCE_REVISION}
USER 65532:65532
ENTRYPOINT ["python", "-m"]
