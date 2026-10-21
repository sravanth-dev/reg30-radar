# One image for every Reg30 Radar process: collector, orders --follow, sheets, and one-off
# jobs such as migrations and catch-ups (ARCHITECTURE.md §9). Python 3.14, the same as the
# laptop (D12); building this image is also the check that every approved dependency has a
# Linux cp314 wheel.
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # The code runs from /app/src rather than being pip-installed, so that
    # common/config.py's ROOT (three levels above that file) is /app, where config/,
    # prompts/ and migrations/ live.
    PYTHONPATH=/app/src

WORKDIR /app

# Dependencies in their own layer, read from pyproject.toml so the approved list (§9) stays
# in one place. A code change then rebuilds in seconds instead of reinstalling everything.
COPY pyproject.toml ./
RUN python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']))" > /tmp/requirements.txt \
    && pip install -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

# Every timestamp at the edges is Asia/Kolkata (D17). Fail the build, not a 3am poll, if
# the image cannot resolve that zone.
RUN python -c "from zoneinfo import ZoneInfo; ZoneInfo('Asia/Kolkata')"

COPY src ./src
COPY config ./config
COPY prompts ./prompts
COPY migrations ./migrations

# Run as an unprivileged user. /app/data holds in-flight PDFs (deleted after extraction,
# D8) and the live order reports; compose mounts a named volume there, which inherits this
# ownership on first use.
RUN useradd --create-home --uid 10001 tradebot \
    && mkdir -p /app/data \
    && chown tradebot:tradebot /app/data
USER tradebot

CMD ["python", "-m", "reg30_radar.collector"]
