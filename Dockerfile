FROM python:3.11-slim

WORKDIR /action
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

# GitHub passes inputs as INPUT_* env vars; action_entry reads them.
ENTRYPOINT ["python", "-m", "docforgeai.action_entry"]
