"""Download NHK Easy narration audio (HLS, Akamai-protected).

The stream lives at
`https://media.vd.st.nhk/news/easy_audio/<voiceId>/index.m3u8?hdnts=<token>`.
The hdnts token comes from `https://mediatoken.web.nhk/v1/token` (fetched in
the browser session, see browser.fetch_media_token). With the token in the
URL no cookies are needed.

The segments are raw-ADTS HE-AAC (mp4a.40.5, implicit SBR), AES-128 encrypted.
We deliberately do NOT let ffmpeg's HLS demuxer read the playlist: on these
streams it mis-frames a handful of frames (~27 per clip), which the AAC decoder
then drops, silently swallowing whole words (e.g. "東日本" in ne2026061812496).
Instead we fetch + AES-decrypt + concatenate the segments ourselves into a
single clean ADTS stream, then hand that file to ffmpeg only for the final
decode + re-encode to browser-friendly AAC-LC. Feeding ffmpeg a plain .aac file
(its AAC demuxer, not the HLS demuxer) decodes every frame without error.
"""

import asyncio
import os
import re
import urllib.parse

import httpx
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from loguru import logger

from nhk_easy.settings import Settings

AUDIO_BASE_URL = "https://media.vd.st.nhk/news/easy_audio"

# Below this size the output is assumed to be a failed/partial download.
_MIN_AUDIO_BYTES = 10_000
_HTTP_TIMEOUT = 30.0


def audio_m3u8_url(voice_uri: str, token: str) -> str:
    voice_id = voice_uri.removesuffix(".m4a")
    return f"{AUDIO_BASE_URL}/{voice_id}/index.m3u8?hdnts={token}"


def _parse_attrs(s: str) -> dict[str, str]:
    """Parse an M3U8 attribute list (e.g. the EXT-X-KEY tag body)."""
    attrs: dict[str, str] = {}
    for m in re.finditer(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)', s):
        key, val = m.group(1), m.group(2)
        if val.startswith('"'):
            val = val[1:-1]
        attrs[key] = val
    return attrs


def _aes_cbc_decrypt(data: bytes, key: bytes, iv: bytes) -> bytes:
    """AES-128-CBC decrypt one HLS segment and strip its PKCS7 padding."""
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    plain = decryptor.update(data) + decryptor.finalize()
    pad = plain[-1]
    if 1 <= pad <= 16:
        plain = plain[:-pad]
    return plain


async def _fetch_concatenated_adts(settings: Settings, master_url: str) -> bytes:
    """Fetch, decrypt and concatenate the HLS segments into one ADTS stream.

    Bypasses ffmpeg's HLS demuxer (which corrupts these streams) by doing the
    playlist parsing, key fetch and AES-128 decryption directly.
    """
    proxy = settings.HTTP_PROXY_URL or None
    headers = {"User-Agent": settings.USER_AGENT}
    async with httpx.AsyncClient(
        proxy=proxy, headers=headers, timeout=_HTTP_TIMEOUT, follow_redirects=True
    ) as client:
        master = (await client.get(master_url)).text

        # The master playlist points at a single bitrate variant; follow it.
        media_url = master_url
        media = master
        if "#EXTINF" not in master:
            variant = next(
                ln.strip()
                for ln in master.splitlines()
                if ln.strip() and not ln.startswith("#")
            )
            media_url = urllib.parse.urljoin(master_url, variant)
            media = (await client.get(media_url)).text

        key: bytes | None = None
        iv_attr: bytes | None = None
        media_seq = 0
        seg_uris: list[str] = []
        for line in media.splitlines():
            line = line.strip()
            if line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
                media_seq = int(line.split(":", 1)[1])
            elif line.startswith("#EXT-X-KEY:"):
                attrs = _parse_attrs(line.split(":", 1)[1])
                if attrs.get("METHOD") == "AES-128":
                    key_url = urllib.parse.urljoin(media_url, attrs["URI"])
                    key = (await client.get(key_url)).content
                    if "IV" in attrs:
                        hex_iv = attrs["IV"]
                        if hex_iv.lower().startswith("0x"):
                            hex_iv = hex_iv[2:]
                        iv_attr = bytes.fromhex(hex_iv)
                elif attrs.get("METHOD") not in (None, "NONE"):
                    raise RuntimeError(f"unsupported HLS key method: {attrs}")
            elif line and not line.startswith("#"):
                seg_uris.append(line)

        if not seg_uris:
            raise RuntimeError(f"no segments in playlist {media_url}")

        buf = bytearray()
        for i, seg in enumerate(seg_uris):
            seg_url = urllib.parse.urljoin(media_url, seg)
            resp = await client.get(seg_url)
            resp.raise_for_status()
            data = resp.content
            if key is not None:
                iv = iv_attr if iv_attr is not None else (media_seq + i).to_bytes(
                    16, "big"
                )
                data = _aes_cbc_decrypt(data, key, iv)
            buf += data
        return bytes(buf)


async def download_audio(
    settings: Settings, voice_uri: str, token: str, dest_path: str
) -> str:
    """Download one article's narration to dest_path (.m4a). Idempotent."""
    if os.path.exists(dest_path) and os.path.getsize(dest_path) > _MIN_AUDIO_BYTES:
        logger.info(f"Audio already exists, skipping: {dest_path}")
        return dest_path

    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    url = audio_m3u8_url(voice_uri, token)

    adts = await _fetch_concatenated_adts(settings, url)
    if len(adts) < _MIN_AUDIO_BYTES:
        raise RuntimeError(
            f"concatenated audio too small for {voice_uri} ({len(adts)} bytes)"
        )

    adts_path = dest_path + ".concat.aac"
    tmp_path = dest_path + ".part.m4a"
    with open(adts_path, "wb") as f:
        f.write(adts)

    # ffmpeg only decodes the already-clean local ADTS file (its AAC demuxer,
    # not the HLS demuxer) and re-encodes to plain AAC-LC so browsers can play
    # the full clip past the first segment.
    cmd = [
        "ffmpeg", "-y", "-loglevel", "warning",
        "-i", adts_path,
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
    try:
        if process.returncode != 0 or size < _MIN_AUDIO_BYTES:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise RuntimeError(
                f"ffmpeg failed for {voice_uri} (exit={process.returncode}, "
                f"size={size}): {stderr.decode(errors='replace')[-500:]}"
            )
        stderr_text = stderr.decode(errors="replace").strip()
        if stderr_text:
            logger.warning(f"ffmpeg notes for {voice_uri}: {stderr_text[-300:]}")
        os.replace(tmp_path, dest_path)
    finally:
        if os.path.exists(adts_path):
            os.remove(adts_path)

    logger.info(f"Audio saved: {dest_path} ({size} bytes)")
    return dest_path
