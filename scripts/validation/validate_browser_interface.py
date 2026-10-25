"""Browser UI checks with synthetic events; no paid LLM requests."""

import asyncio
import base64
import json
from pathlib import Path

from playwright.async_api import async_playwright

from voice_conversation.settings import ROOT

FAKE_SOCKET = """
class DemoSocket {
  static OPEN=1; static CLOSING=2; static CLOSED=3;
  constructor(){this.readyState=1;this.bufferedAmount=0;window.demoSocket=this;
    setTimeout(()=>this.emit({type:'ready',model:'nemotron-3-nano:30b'}),30);}
  send(value){}
  emit(packet){this.onmessage?.({data:JSON.stringify(packet)});}
  close(){this.readyState=3;this.onclose?.();}
}
window.WebSocket=DemoSocket;
"""


async def main():
    output = ROOT / "logs/ui"
    output.mkdir(parents=True, exist_ok=True)
    errors = []
    async with async_playwright() as playwright:
        from scripts.demo.record_conversation_demo import chromium_path

        executable = chromium_path(playwright)
        browser = await playwright.chromium.launch(
            executable_path=str(executable),
            args=["--use-fake-device-for-media-stream", "--no-sandbox"],
        )
        context = await browser.new_context(
            viewport={"width": 1440, "height": 1050}, permissions=["microphone"]
        )
        await context.add_init_script(FAKE_SOCKET)
        page = await context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        await page.goto("http://localhost:8765", wait_until="networkidle")
        await page.screenshot(path=str(output / "desktop-idle.png"), full_page=True)
        await page.get_by_role("button", name="Audio settings", exact=True).click()
        assert await page.locator("#settings-panel").is_visible()
        await page.locator("#volume").fill("45")
        await page.locator("#volume").dispatch_event("input")
        assert await page.locator("#volume-label").inner_text() == "45%"
        await page.get_by_role("button", name="Audio settings", exact=True).click()
        await page.get_by_role("button", name="Start conversation", exact=True).click()
        await page.wait_for_function("document.body.dataset.state === 'listening'")
        await page.get_by_role("button", name="Mute microphone", exact=True).click()
        assert await page.locator("body").get_attribute("data-state") == "muted"
        await page.get_by_role("button", name="Unmute microphone", exact=True).click()
        for packet in [
            {"type": "interrupt", "turn": 1},
            {"type": "partial", "text": "Can you help me plan..."},
            {"type": "final", "text": "Can you help me plan my day?"},
            {"type": "status", "text": "Thinking"},
            {
                "type": "token",
                "turn": 1,
                "text": "Of course. What is the most important thing you would like to get done today?",
            },
        ]:
            await page.evaluate("(packet) => window.demoSocket.emit(packet)", packet)
        assert await page.locator(".message").count() == 2
        assert await page.locator("#turn-count").inner_text() == "1"
        await page.screenshot(
            path=str(output / "desktop-conversation.png"), full_page=True
        )
        await page.evaluate(
            "(packet) => window.demoSocket.emit(packet)",
            {
                "type": "audio",
                "turn": 1,
                "id": "1:1",
                "sample_rate": 24000,
                "pcm": base64.b64encode(bytes(24000 * 2 * 2)).decode(),
            },
        )
        assert await page.locator("body").get_attribute("data-state") == "speaking"
        await page.evaluate(
            "(packet) => window.demoSocket.emit(packet)",
            {"type": "latency", "seconds": 1.23},
        )
        assert "1.23" in await page.locator("#latency").inner_text()
        await page.screenshot(path=str(output / "desktop-speaking.png"), full_page=True)
        await page.evaluate(
            "(packet) => window.demoSocket.emit(packet)",
            {"type": "interrupt", "turn": 2},
        )
        assert await page.locator(".message.interrupted").count() == 1
        await page.evaluate(
            "(packet) => window.demoSocket.emit(packet)",
            {"type": "final", "text": "<img src=x onerror=alert(1)>"},
        )
        assert await page.locator("#messages img").count() == 0
        await page.get_by_role("button", name="New conversation", exact=True).click()
        assert await page.locator(".message").count() == 0
        assert await page.locator("#empty-state").is_visible()
        assert await page.locator("body").get_attribute("data-state") == "idle"
        await page.set_viewport_size({"width": 390, "height": 844})
        await page.screenshot(path=str(output / "mobile.png"), full_page=True)
        assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        await page.add_init_script(
            "navigator.mediaDevices.getUserMedia = async () => { throw new DOMException('Denied','NotAllowedError'); }"
        )
        await page.reload(wait_until="networkidle")
        await page.get_by_role("button", name="Start conversation", exact=True).click()
        await page.wait_for_function("!document.getElementById('error').hidden")
        assert "denied" in (await page.locator("#error").inner_text()).lower()
        assert await page.get_by_role(
            "button", name="Start conversation", exact=True
        ).is_enabled()
        assert not errors, errors
        await browser.close()
    print(
        "Desktop/mobile layout, start/stop, mute, settings, transcript, interruptions, escaping and permission errors: PASS"
    )
    print("Screenshots:", output)


if __name__ == "__main__":
    asyncio.run(main())
