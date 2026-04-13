# OncoCITE — LangChain extraction pipeline
# Mirrors the deployment recipe in Supplementary Note S2.4 of the manuscript.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt pyproject.toml README.md ./
COPY config ./config
COPY graphs ./graphs
COPY hooks ./hooks
COPY runtime ./runtime
COPY tools ./tools
COPY scripts ./scripts
COPY client.py run_extraction.py ./

RUN pip install -r requirements.txt

VOLUME ["/app/data", "/app/outputs"]

ENTRYPOINT ["python", "run_extraction.py"]
CMD ["--help"]
