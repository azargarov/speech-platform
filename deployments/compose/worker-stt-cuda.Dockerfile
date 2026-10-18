# A deployment build must supply an immutable, linux/amd64 Python base reference.
# No mutable default is provided: builds fail closed until provenance is reviewed.
ARG STT_CUDA_BASE_IMAGE
FROM ${STT_CUDA_BASE_IMAGE}
ARG STT_CUDA_BASE_IMAGE
ARG STT_SOURCE_REVISION
ARG STT_CUDA_LOCK_SHA256
WORKDIR /app
COPY services/requirements-stt-cuda.lock ./requirements.lock
RUN python -c 'import hashlib, os, re; base=os.environ.get("STT_CUDA_BASE_IMAGE", ""); revision=os.environ.get("STT_SOURCE_REVISION", ""); lock=os.environ.get("STT_CUDA_LOCK_SHA256", ""); expected=hashlib.sha256(open("requirements.lock", "rb").read()).hexdigest(); assert re.fullmatch(r"python:3\.13\.9-slim@sha256:[0-9a-f]{64}", base), "base image must be the reviewed immutable Python 3.13.9 linux/amd64 reference"; assert re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", revision), "source revision must be immutable"; assert lock == expected, "CUDA lock digest mismatch"'
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
ENV LD_LIBRARY_PATH=/usr/local/lib/python3.13/site-packages/nvidia/cublas/lib:/usr/local/lib/python3.13/site-packages/nvidia/cuda_nvrtc/lib:/usr/local/lib/python3.13/site-packages/nvidia/cudnn/lib
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY services/stt ./services/stt
COPY services/worker ./services/worker
LABEL org.opencontainers.image.revision=${STT_SOURCE_REVISION} \
      com.speech-platform.image-role="stt-worker" \
      com.speech-platform.service-role="stt-worker" \
      com.speech-platform.service="stt" \
      com.speech-platform.runtime-variant="cuda" \
      com.speech-platform.base-image=${STT_CUDA_BASE_IMAGE} \
      com.speech-platform.source-revision=${STT_SOURCE_REVISION} \
      com.speech-platform.cuda-lock-sha256=${STT_CUDA_LOCK_SHA256}
USER 65532:65532
ENTRYPOINT ["python", "-m"]
