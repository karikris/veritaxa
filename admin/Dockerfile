# Immutable base; update the digest deliberately during dependency reviews.
FROM python:3.12-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e AS build
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential perl pkg-config bison flex bzip2 ca-certificates && rm -rf /var/lib/apt/lists/*
COPY admin/native-deps.json /build/admin/native-deps.json
COPY scripts/build-native-runtime.py /build/scripts/build-native-runtime.py
RUN python /build/scripts/build-native-runtime.py
ENV LD_LIBRARY_PATH=/opt/veritaxa-native/lib \
    PATH=/opt/veritaxa-native/bin:$PATH \
    PSYCOPG_IMPL=c \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/veritaxa/.venv
RUN pip install --no-cache-dir uv==0.11.19
WORKDIR /opt/veritaxa
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

FROM build AS test
RUN uv sync --frozen --group dev
COPY tools ./tools
COPY benchmarks ./benchmarks
COPY supabase/migrations ./supabase/migrations
COPY schemas ./schemas
ENV PYTHONPATH=/opt/veritaxa PATH=/opt/veritaxa/.venv/bin:$PATH
CMD ["python", "-m", "tools.native_runtime"]

FROM python:3.12-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e AS runtime
COPY --from=build /opt/veritaxa-native /opt/veritaxa-native
COPY --from=build /opt/veritaxa/.venv /opt/veritaxa/.venv
COPY tools /opt/veritaxa/tools
ENV PATH=/opt/veritaxa/.venv/bin:/opt/veritaxa-native/bin:$PATH \
    LD_LIBRARY_PATH=/opt/veritaxa-native/lib \
    PYTHONPATH=/opt/veritaxa \
    PSYCOPG_IMPL=c \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    SSL_CERT_DIR=/etc/ssl/certs
USER 10001:10001
WORKDIR /tmp
ENTRYPOINT ["python", "-m"]
CMD ["tools.native_runtime"]
