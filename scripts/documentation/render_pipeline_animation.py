"""Render the self-contained animated diagram as a GitHub-compatible GIF."""

import asyncio
from pathlib import Path
import subprocess
import time

from playwright.async_api import async_playwright
from voice_conversation.settings import ROOT
from scripts.demo.record_conversation_demo import chromium_path


async def main():
    frames = ROOT / "logs/architecture-frames"
    frames.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            executable_path=chromium_path(p), args=["--no-sandbox"]
        )
        page = await browser.new_page(
            viewport={"width": 1460, "height": 900}, device_scale_factor=1
        )
        await page.goto((ROOT / "docs/architecture.html").as_uri())
        svg = page.locator("svg")
        for frame in range(76):
            # Sample SVG time deterministically rather than recording network/UI delays.
            await page.evaluate(
                """(frame) => {
              const s=document.querySelector('svg');s.pauseAnimations();s.setCurrentTime(frame/6);
              paused=true;step(Math.floor((frame/6)/1.4)%steps.length);
            }""",
                frame,
            )
            await svg.screenshot(path=str(frames / f"{frame:03}.png"))
        await browser.close()
    output = ROOT / "docs/assets/architecture.gif"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-framerate",
            "6",
            "-i",
            str(frames / "%03d.png"),
            "-filter_complex",
            "scale=1500:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=96[p];[b][p]paletteuse=dither=bayer",
            "-loop",
            "0",
            str(output),
        ],
        check=True,
    )
    print("Animated diagram:", output)


if __name__ == "__main__":
    asyncio.run(main())
