"""Check the real video player and animated architecture in Chromium."""
import asyncio
from playwright.async_api import async_playwright
from voice_conversation.settings import ROOT, load_settings
from record_demo import chromium_path


async def main():
    config=load_settings()
    base=f'http://localhost:{config["server"]["port"]}/docs'
    async with async_playwright() as p:
        browser=await p.chromium.launch(executable_path=chromium_path(p),args=['--no-sandbox'])
        page=await browser.new_page(viewport={'width':1400,'height':1100})
        errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        response=await page.goto(base+'/demo.html',wait_until='networkidle')
        assert response.status==200
        await page.wait_for_function("document.querySelector('video').readyState>=1",timeout=15000)
        duration=await page.locator('video').evaluate('(v)=>v.duration')
        assert 120 < duration < 600
        await page.locator('video').evaluate('(v)=>{v.muted=true;return v.play()}')
        await page.wait_for_function("document.querySelector('video').currentTime>1",timeout=10000)
        await page.locator('video').evaluate('(v)=>v.pause()')
        for file in ('demo/conversation-demo.mp4','demo/conversation-demo.webm','demo/captions.vtt','demo/transcript.txt','assets/architecture.gif'):
            r=await page.request.get(base+'/'+file)
            assert r.ok, file
        await page.screenshot(path=str(ROOT/'logs/docs-player.png'),full_page=True)
        await page.goto(base+'/architecture.html',wait_until='networkidle')
        await page.get_by_role('button',name='Pause animation',exact=True).click()
        assert await page.locator('svg').evaluate('(s)=>s.animationsPaused()')
        await page.get_by_role('button',name='3 · Show rolling previews, then finalize the transcript',exact=True).click()
        assert 'finalize' in await page.locator('#caption').text_content()
        await page.screenshot(path=str(ROOT/'logs/docs-architecture.png'),full_page=True)
        assert not errors,errors
        await browser.close()
    print(f'Video playback ({duration:.1f}s), captions/download links, diagram controls: PASS')


if __name__=='__main__':
    asyncio.run(main())
