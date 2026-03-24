FROM python:3.11-slim
WORKDIR /app

# Install gateway deps + test deps in one layer
COPY gateway/requirements.txt /app/gateway-requirements.txt
RUN pip install --no-cache-dir -r /app/gateway-requirements.txt pytest

# Copy source and tests
COPY gateway/ /app/gateway/
COPY consumer/ /app/consumer/
COPY tests/ /app/tests/

ENV PYTHONPATH=/app/gateway:/app/consumer

CMD ["pytest", "tests/", "-v"]
