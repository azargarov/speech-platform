FROM python:3.13.9-slim
WORKDIR /app
COPY services/requirements-stt-cuda.lock ./requirements.lock
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
ENV LD_LIBRARY_PATH=/usr/local/lib/python3.13/site-packages/nvidia/cublas/lib:/usr/local/lib/python3.13/site-packages/nvidia/cudnn/lib
COPY services ./services
USER 65532:65532
ENTRYPOINT ["python", "-m"]
