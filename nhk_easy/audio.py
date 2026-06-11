"""Download NHK Easy narration audio (HLS, Akamai-protected).

The stream lives at
`https://media.vd.st.nhk/news/easy_audio/<voiceId>/index.m3u8?hdnts=<token>`.
The hdnts token comes from `https://mediatoken.web.nhk/v1/token` (fetched in
the browser session, see browser.fetch_media_token). With the token in the
URL no cookies are needed, so ffmpeg downloads playlist, AES key, and
segments directly and remuxes them into an .m4a.
"""

import asyncio
import os

from loguru import logger

from nhk_easy.settings import Settings

AUDIO_BASE_URL = "https://media.vd.st.nhk/news/easy_audio"

# Below this size the output is assumed to be a failed/partial download.
_MIN_AUDIO_BYTES = 10_000


def audio_m3u8_url(voice_uri: str, token: str) -> str:
    voice_id = voice_uri.removesuffix(".m4a")
    return f"{AUDIO_BASE_URL}/{voice_id}/index.m3u8?hdnts={token}"


async def download_audio(
    settings: Settings, voice_uri: str, token: str, dest_path: str
) -> str:
    """Download one article's narration to dest_path (.m4a). Idempotent."""
    if os.path.exists(dest_path) and os.path.getsize(dest_path) > _MIN_AUDIO_BYTES:
        logger.info(f"Audio already exists, skipping: {dest_path}")
        return dest_path

    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    url = audio_m3u8_url(voice_uri, token)
    tmp_path = dest_path + ".part.m4a"

    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    if settings.HTTP_PROXY_URL:
        cmd += ["-http_proxy", settings.HTTP_PROXY_URL]
    cmd += [
        "-user_agent", settings.USER_AGENT,
        "-i", url,
        # The source is HE-AAC (mp4a.40.5); stream-copying it into MP4 via
        # aac_adtstoasc produces files that ffprobe accepts but real decoders
        # cannot play past the first HLS segment (browsers stop after ~6s).
        # Re-encode to plain AAC-LC instead.
        "-c:a", "aac",
        "-b:a", "64k",
        tmp_path,
    ]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()

    size = os.path.getsize(tmp_path) if os.path.exists(tmp_path) else 0
    if process.returncode != 0 or size < _MIN_AUDIO_BYTES:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise RuntimeError(
            f"ffmpeg failed for {voice_uri} (exit={process.returncode}, "
            f"size={size}): {stderr.decode(errors='replace')[-500:]}"
        )

    os.replace(tmp_path, dest_path)
    logger.info(f"Audio saved: {dest_path} ({size} bytes)")
    return dest_path
