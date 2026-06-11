# Runtime image for the nhk-easy fetch flow and the local reader.
# Follows MiraiGuard's Dockerfile.runner pattern (slim base + browser libs +
# uv sync + playwright chromium), plus ffmpeg for HLS audio downloads.

FROM python:3.12-slim

# Chromium runtime libraries (crawl4ai/Playwright) + ffmpeg
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    libnss3 \
    libdbus-1-3 \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libatspi2.0-0 \
    libcairo2 \
    libcups2 \
    libexpat1 \
    libfontconfig1 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libpango-1.0-0 \
    libx11-6 \
    libxcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxkbcommon0 \
    libxrandr2 \
    fonts-liberation \
    fonts-noto-cjk \
    xdg-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip3 install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
RUN uv run playwright install chromium

COPY prefect.yaml .prefectignore ./
COPY nhk_easy ./nhk_easy

# Keep mutable state (browser profile, downloaded audio) outside /app so it
# can be volume-mounted and survive container recreation.
ENV PROFILE_DIR=/data/chromium \
    DATA_DIR=/data/nhk \
    RUN_IN_DOCKER=true

CMD ["uv", "run", "python", "-m", "nhk_easy.flows.daily_fetch"]
