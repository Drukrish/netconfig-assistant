# Two stages: install deps in a builder layer, copy only the installed
# packages + app code into a slim runtime layer. Mirrors growth-os's
# Dockerfile pattern (secrets never baked in, non-root runtime user) - but
# NOT its deps/build split at the copy level: npm can install from
# package.json alone, while `pip install .` builds the local package's own
# wheel, which pyproject.toml's explicit `packages = ["app", ...]` (see its
# comment) requires actually existing on disk. Copying pyproject.toml alone
# here fails with "package directory 'app' does not exist" - confirmed by a
# real CI build failure, not anticipated. app/ has to be present before
# `pip install .` runs, so the layer-cache boundary sits after that install
# instead of before it.
FROM python:3.12-slim AS builder
WORKDIR /app
COPY pyproject.toml ./
COPY app ./app
# No lockfile in this project (see pyproject.toml) - pip install . resolves
# from the dependencies list directly, same as a local dev install.
RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.12-slim AS runtime
WORKDIR /app

COPY --from=builder /install /usr/local
COPY app ./app

# fastembed downloads its model from HuggingFace on first use and caches it -
# confirmed by testing the built image: the non-root user below has no
# writable HOME, so a runtime download fails with a permission error, and
# even fixed, it would mean the container needs network egress to HuggingFace
# on every cold start. Pre-downloading here (still root, still build time)
# means the runtime container is self-contained and starts offline-capable.
ENV HF_HOME=/app/.cache/huggingface
# Model name is hardcoded here, not imported from app.config.settings: that
# import instantiates Settings(), which requires DATABASE_URL - unset at
# build time since .env is deliberately excluded (see .dockerignore). Must
# stay in sync with settings.embedding_model's default by hand.
RUN python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='BAAI/bge-small-en-v1.5')"

# fastembed also keeps a separate sparse-index cache under /tmp (distinct
# from HF_HOME above) - the pre-download RUN above touched it as root, so it
# needs the same ownership fix or every cold start logs a (non-fatal, but
# noisy) permission-denied warning.
RUN addgroup --system --gid 1001 appuser && adduser --system --uid 1001 --gid 1001 appuser \
    && chown -R appuser:appuser /app/.cache /tmp/fastembed_cache
USER appuser

EXPOSE 8000

# Corpus and .env are deliberately absent from this image (see
# .dockerignore) - ingestion is a one-off job run against the corpus
# directly, not something the serving container needs, and the API key is
# supplied at run time only:
#   docker run -p 8000:8000 -e ANTHROPIC_API_KEY=sk-... -e DATABASE_URL=... netconfig-assistant
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
