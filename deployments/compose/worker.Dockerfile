FROM python:3.13.9-slim
WORKDIR /app
COPY services/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY services ./services
USER 65532:65532
ENTRYPOINT ["python", "-m"]
