FROM python:3.13.9-slim
WORKDIR /app
COPY services/requirements-stt-cpu.lock ./requirements.lock
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
COPY services ./services
USER 65532:65532
ENTRYPOINT ["python", "-m"]
