FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim AS build
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.11-slim-bookworm
RUN useradd --create-home --uid 10001 assay \
    && mkdir -p /work/results && chown -R assay:assay /work
COPY --from=build /app/.venv /app/.venv
COPY data/golden /app/data/golden
ENV PATH="/app/.venv/bin:$PATH" \
    ASSAY_GOLDEN_DIR=/app/data/golden \
    ASSAY_RESULTS_DIR=/work/results
WORKDIR /work
USER assay
VOLUME /work
ENTRYPOINT ["assay"]
CMD ["--help"]
