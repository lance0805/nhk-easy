"""Diagnostic script for the NHK ONE consent gate inside crawl4ai.

Gathers evidence at each step: gate marker presence, checkbox/button state,
JS execution results, and screenshots. No fixes here - observation only.
"""

import asyncio
import base64
import json

from crawl4ai import AsyncWebCrawler, CacheMode, CrawlerRunConfig

from nhk_easy.browser import EASY_TOP_URL, SESSION_ID, build_browser_config
from nhk_easy.settings import Settings

# crawl4ai wraps js_code as the body of an async function, so top-level
# statements with await/return are the correct form (an IIFE would run
# detached and its value would be discarded).
DIAG_JS = """
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const diag = {steps: []};
  const snap = (label) => {
    const checkbox = document.querySelector('input[type=checkbox]');
    const button = [...document.querySelectorAll('button')]
      .find((b) => b.textContent.includes('サービスの利用を開始する'));
    diag.steps.push({
      label,
      url: location.href,
      gate: document.body.textContent.includes('ご利用にあたって'),
      checkbox: checkbox ? {checked: checkbox.checked} : null,
      button: button ? {disabled: button.disabled} : null,
      radios: document.querySelectorAll('input[type=radio]').length,
    });
  };
  snap('initial');
  const checkbox = document.querySelector('input[type=checkbox]');
  if (checkbox && !checkbox.checked) checkbox.click();
  await sleep(800);
  snap('after-check');
  for (let i = 0; i < 3; i++) {
    const button = [...document.querySelectorAll('button')]
      .find((b) => b.textContent.includes('サービスの利用を開始する'));
    if (!button) break;
    if (button.disabled) { diag.steps.push({label: 'button-disabled-' + i}); break; }
    button.click();
    await sleep(3000);
    snap('after-click-' + i);
    if (!document.body.textContent.includes('ご利用にあたって')) break;
  }
  return diag;
"""


async def main() -> None:
    settings = Settings()
    config = build_browser_config(settings)
    async with AsyncWebCrawler(config=config) as crawler:
        result = await crawler.arun(
            EASY_TOP_URL,
            config=CrawlerRunConfig(
                session_id=SESSION_ID, cache_mode=CacheMode.BYPASS, screenshot=True
            ),
        )
        html = result.html or ""
        print("=== step1 navigate ===")
        print("success:", result.success, "| len(html):", len(html))
        print("gate marker in html:", "ご利用にあたって" in html)
        print("article list marker:", "article" in html)
        if result.screenshot:
            with open("/tmp/consent_step1.png", "wb") as f:
                f.write(base64.b64decode(result.screenshot))
            print("screenshot: /tmp/consent_step1.png")

        result = await crawler.arun(
            EASY_TOP_URL,
            config=CrawlerRunConfig(
                session_id=SESSION_ID,
                cache_mode=CacheMode.BYPASS,
                js_code=[DIAG_JS],
                js_only=True,
            ),
        )
        print("=== step2 consent js ===")
        print("success:", result.success, "| error:", result.error_message)
        print("js_execution_result:")
        print(json.dumps(result.js_execution_result, ensure_ascii=False, indent=1))

        result = await crawler.arun(
            EASY_TOP_URL,
            config=CrawlerRunConfig(
                session_id=SESSION_ID, cache_mode=CacheMode.BYPASS, screenshot=True
            ),
        )
        html = result.html or ""
        print("=== step3 reload ===")
        print("gate marker in html:", "ご利用にあたって" in html)
        if result.screenshot:
            with open("/tmp/consent_step3.png", "wb") as f:
                f.write(base64.b64decode(result.screenshot))
            print("screenshot: /tmp/consent_step3.png")


if __name__ == "__main__":
    asyncio.run(main())
