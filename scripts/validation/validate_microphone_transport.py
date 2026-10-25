"""Exercise browser audio backpressure without models, microphone permission or cloud."""

import asyncio
from playwright.async_api import async_playwright
from voice_conversation.settings import ROOT, load_config


async def main():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(args=["--no-sandbox"])
        page = await browser.new_page()
        await page.add_script_tag(path=str(ROOT / "web/microphone-transport.js"))
        result = await page.evaluate(
            """async settings => {
          const sent = [], errors = [];
          const socket = {readyState: WebSocket.OPEN, bufferedAmount: settings.max_buffered_bytes,
            send(frame) { sent.push(new Uint32Array(frame)[0]); this.bufferedAmount += frame.byteLength; }};
          const transport = new MicrophoneTransport(socket, settings, error => errors.push(error));
          for (let index = 0; index < 80; index++) {
            const frame = new ArrayBuffer(2048); new Uint32Array(frame)[0] = index; transport.push(frame);
          }
          const queuedBeforeDrain = transport.frames.length;
          for (let attempt = 0; attempt < 100 && sent.length < 80; attempt++) {
            socket.bufferedAmount = 0; await new Promise(resolve => setTimeout(resolve, settings.transport_poll_ms + 2));
          }
          const ordered = sent.length === 80 && sent.every((value, index) => value === index);
          transport.close();
          const overflowErrors = [];
          socket.bufferedAmount = settings.max_buffered_bytes;
          const blocked = new MicrophoneTransport(socket, settings, error => overflowErrors.push(error));
          for (let index = 0; index <= settings.max_queued_frames; index++) blocked.push(new ArrayBuffer(2048));
          const bounded = blocked.closed && blocked.frames.length === 0 && overflowErrors.length === 1;
          blocked.close();
          return {queuedBeforeDrain, sent: sent.length, ordered, errors, overflowIsBounded: bounded};
        }""",
            load_config()["audio"],
        )
        await browser.close()
    assert (
        result["ordered"] and not result["errors"] and result["queuedBeforeDrain"] == 80
    )
    assert result["overflowIsBounded"]
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
