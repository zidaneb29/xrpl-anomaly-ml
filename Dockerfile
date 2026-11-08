FROM python:3.14.7-slim-trixie@sha256:51dafde81dbdb6ebde285137a295cf18a47ca95234fe388a343719cb97305b3d

ENV PYTHONPATH=/app/src \
    PYTHONDONTWRITEBYTECODE=1 \
    XRPL_MODEL_PATH=/models/model.json
WORKDIR /app
COPY requirements-service-py314.txt ./
RUN python -m pip install --no-cache-dir --only-binary=:all: --require-hashes -r requirements-service-py314.txt \
    && python -m pip check \
    && mkdir /models
COPY src/xrpl_anomaly/ src/xrpl_anomaly/
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=5s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "from http.client import HTTPConnection; c = HTTPConnection('127.0.0.1', 8000, timeout=2); c.request('GET', '/health'); r = c.getresponse(); raise SystemExit(0 if r.status == 200 and r.read() == b'{\"status\":\"ready\"}' else 1)"]
CMD ["python", "-m", "uvicorn", "xrpl_anomaly.service:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--http", "h11", "--no-proxy-headers", "--no-access-log"]
