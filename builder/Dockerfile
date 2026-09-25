# Pinned by digest rather than by tag. python:3.12-slim moves, and an image
# that moves takes the RDF with it.
FROM python:3.12-slim@sha256:2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=0 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    HF_HUB_DISABLE_PROGRESS_BARS=1 \
    HF_HUB_OFFLINE=0

WORKDIR /app
COPY requirements.txt .
# Exact versions, no ranges. PyPI refuses to re-upload a version that already
# exists, so a pinned version is an immutable artefact.
RUN pip install --no-cache-dir --disable-pip-version-check -r requirements.txt

COPY build_rdf.py sources.py rcc8.py triples.py ./
ENTRYPOINT ["python", "build_rdf.py"]
