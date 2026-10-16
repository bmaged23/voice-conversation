"""Render the README's clickable demo cover as a single portable image."""
import asyncio
import base64
from playwright.async_api import async_playwright
from voice_conversation.settings import ROOT
from record_demo import chromium_path


async def main():
    preview = base64.b64encode((ROOT / 'docs/demo/poster.png').read_bytes()).decode()
    html = '''<!doctype html><html><head><style>
*{box-sizing:border-box}body{margin:0;width:1600px;height:900px;background:#101f19;color:#f4f7ee;font-family:Arial,sans-serif}
.cover{width:1600px;height:900px;position:relative;overflow:hidden;background:radial-gradient(ellipse at 18% 35%,#223e2d 0%,#101f19 62%)}
.left{position:absolute;left:56px;top:78px;width:460px}.brand{font-size:56px;font-weight:750;letter-spacing:-3px}.tag{font-size:18px;letter-spacing:3px;color:#b4d58a;margin-top:13px}
h1{font-size:60px;line-height:1.08;letter-spacing:-2px;margin:103px 0 30px}p{font-size:24px;color:#cad6c8;line-height:1.6;margin:0 0 17px}
.play{margin-top:65px;display:flex;align-items:center;gap:17px;width:355px;height:78px;border-radius:17px;background:#c9e9a2;color:#172c21;padding:0 30px;font-size:24px;font-weight:750;box-shadow:0 10px 40px #0003}.triangle{width:0;height:0;border-top:12px solid transparent;border-bottom:12px solid transparent;border-left:20px solid #172c21}.duration{font-size:14px;letter-spacing:1px;color:#a3b79e;margin-top:19px}
.preview{position:absolute;left:560px;top:100px;width:1000px;height:730px;border-radius:18px;overflow:hidden;border:1px solid #ffffff20;box-shadow:0 24px 70px #0006}.preview img{width:100%;height:100%;object-fit:cover;object-position:top}
</style></head><body><div class="cover"><div class="left"><div class="brand">voca.</div><div class="tag">ENGLISH VOICE CONVERSATION</div><h1>Let's talk.<br>Keep it flowing.</h1><p>Listen. Think. Speak.</p><p>Live replies. Natural interruptions.</p><div class="play"><span class="triangle"></span>WATCH THE DEMO</div><div class="duration">4:49 · A REAL TEN-TURN CONVERSATION</div></div><div class="preview"><img src="data:image/png;base64,PREVIEW"></div></div></body></html>'''.replace('PREVIEW', preview)
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=chromium_path(p), args=['--no-sandbox'])
        page = await browser.new_page(viewport={'width':1600,'height':900},device_scale_factor=1)
        await page.set_content(html, wait_until='load')
        await page.screenshot(path=str(ROOT / 'docs/demo/demo-cover.png'))
        await browser.close()


if __name__ == '__main__':
    asyncio.run(main())
