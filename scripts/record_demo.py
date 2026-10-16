"""Record an actual automated voice conversation, without narration or mocked replies.

The demo user is synthesized locally, fed into a virtual browser microphone,
and processed by the real AudioWorklet/VAD/STT/Ollama/TTS path. Capture browser
frames and a WebAudio mix, then mux a synchronized, playable H.264/AAC MP4.
"""
import asyncio
import base64
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import wave

import numpy as np

from playwright.async_api import async_playwright

from voice_conversation.settings import ROOT, load_settings
from voice_conversation.workers import init_tts, synthesize

PROMPTS = [
    "Hey! I'm excited. I'm planning a surprise birthday picnic for my sister this Saturday. Can you help me make it special? Keep it conversational.",
    "There will be six of us, my budget is eighty dollars, and she loves space. What could we do?",
    "Actually, one important detail! One friend is vegan, so let's make all the food vegan. How would you split the budget?",
    "Great! We already have blankets and a speaker. What easy food would fit that plan without needing to cook at the park?",
    "I like the idea of a space theme. Can you suggest one fun activity that works for six people and costs almost nothing?",
    "Let's call this a birthday mission! Give me a short opening line I can say when she arrives. Make it exciting!",
    "Now the tricky part. The forecast might change. If it rains, how can we keep the same theme indoors without spending more?",
    "We can use my living room as the backup. Help me plan a simple preparation timeline, starting Friday evening.",
    "Before I invite everyone, remind me of our guest count, total budget, food restriction, and backup location.",
    "Perfect! Give me a cheerful invitation message with the space theme, but don't spoil the surprise. I'll add the time and address myself."
]

BOOTSTRAP = r'''
window.__serverEvents = [];
window.__playedSources = [];
const RealSocket = window.WebSocket;
window.WebSocket = class extends RealSocket {
  constructor(...args) {
    super(...args);
    this.addEventListener('message', event => {
      const {pcm, ...safe} = JSON.parse(event.data);
      window.__serverEvents.push({time:performance.now(), ...safe});
    });
  }
};
const realStart = AudioBufferSourceNode.prototype.start;
const realStop = AudioBufferSourceNode.prototype.stop;
AudioBufferSourceNode.prototype.start = function(...args) {
  if (this.buffer) {
    const item={start:performance.now(),contextStart:this.context.currentTime,
      rate:this.buffer.sampleRate,samples:this.buffer.getChannelData(0).slice(),duration:this.buffer.duration};
    window.__playedSources.push(item);this.__recordingItem=item;
    this.addEventListener('ended',()=>{item.contextEnd=this.context.currentTime;});
  }
  return realStart.apply(this,args);
};
AudioBufferSourceNode.prototype.stop = function(...args) {
  if(this.__recordingItem)this.__recordingItem.contextEnd=this.context.currentTime;
  return realStop.apply(this,args);
};
const RealContext = window.AudioContext;
window.AudioContext = class extends RealContext {
  constructor(...args) {
    super(...args);window.__demoContext=this;
    window.__microphoneSink=this.createMediaStreamDestination();
    // Keep the virtual microphone producing silence between spoken inputs.
    const quiet=this.createConstantSource();quiet.offset.value=0.000001;
    quiet.connect(window.__microphoneSink);quiet.start();
  }
};
navigator.mediaDevices.getUserMedia = async () => window.__microphoneSink.stream;
window.__say = async url => {
  const ctx=window.__demoContext;
  const buffer=await ctx.decodeAudioData(await(await fetch(url)).arrayBuffer());
  const source=ctx.createBufferSource();source.buffer=buffer;
  source.connect(window.__microphoneSink);
  await new Promise(resolve=>{source.onended=resolve;source.start();});
};
window.__exportAudio = () => window.__playedSources.map(item=>{
  const bytes=new Uint8Array(item.samples.buffer);let binary='';
  for(let i=0;i<bytes.length;i+=16384)binary+=String.fromCharCode(...bytes.subarray(i,i+16384));
  return {start:item.start,rate:item.rate,samples:btoa(binary),
    duration:Math.min(item.duration,Math.max(0,(item.contextEnd??window.__demoContext.currentTime)-item.contextStart))};
});
'''


def prepare_prompts(config, directory):
    settings = dict(config['tts'])
    settings['voice'] = 'am_michael'
    settings['model_path'] = config['paths']['tts_model']
    settings['voices_path'] = config['paths']['tts_voices']
    init_tts(settings, ROOT)
    for index, prompt in enumerate(PROMPTS):
        pcm, rate = synthesize(prompt)
        with wave.open(str(directory / f'input-{index}.wav'), 'wb') as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(rate)
            output.writeframes(pcm)


def chromium_path(playwright):
    installed = Path.home() / '.cache/ms-playwright/chromium-1194/chrome-linux/chrome'
    return str(installed) if installed.exists() else playwright.chromium.executable_path


async def main():
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        raise SystemExit('Install ffmpeg and ffprobe before recording.')
    config = load_settings()
    timestamp = time.strftime('%Y%m%d-%H%M%S')
    work = ROOT / 'logs' / f'demo-{timestamp}'
    work.mkdir(parents=True)
    frames = work / 'frames'
    frames.mkdir()
    media = ROOT / 'docs/demo'
    media.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(prepare_prompts, config, work)
    frame_times = []
    capture = True
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(executable_path=chromium_path(playwright),
            args=['--no-sandbox', '--autoplay-policy=no-user-gesture-required'])
        context = await browser.new_context(viewport={'width':1440,'height':1050}, device_scale_factor=1)
        await context.add_init_script(BOOTSTRAP)
        page = await context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))

        async def prompt_route(route):
            filename = route.request.url.rsplit('/', 1)[-1]
            if filename not in {f'input-{i}.wav' for i in range(len(PROMPTS))}:
                await route.abort()
                return
            await route.fulfill(path=str(work / filename), content_type='audio/wav')

        await page.route('**/__demo_input__/*', prompt_route)
        await page.goto(f'http://localhost:{config["server"]["port"]}', wait_until='networkidle')
        await page.screenshot(path=str(media / 'poster.png'))
        before=time.monotonic()
        browser_time=await page.evaluate('performance.now()')
        clock_offset=(before+time.monotonic())/2-browser_time/1000

        async def record_frames():
            index = 0
            while capture:
                began = time.monotonic()
                await page.screenshot(path=str(frames / f'{index:06}.jpg'), type='jpeg', quality=88)
                frame_times.append(began)
                index += 1
                await asyncio.sleep(max(0, .16 - (time.monotonic() - began)))

        frame_task = asyncio.create_task(record_frames())
        try:
            await page.wait_for_timeout(900)
            await page.get_by_role('button', name='Start conversation', exact=True).click()
            await page.wait_for_function("document.body.dataset.state === 'listening'", timeout=20000)
            await page.wait_for_timeout(600)

            async def say(index):
                print(f'Demo user turn {index+1}: {PROMPTS[index]}', flush=True)
                await page.evaluate('(url) => window.__say(url)', f'/__demo_input__/input-{index}.wav')
                await page.wait_for_function('(n) => document.querySelectorAll(".message.user").length >= n', arg=index+1, timeout=30000)

            async def wait_reply(index):
                await page.wait_for_function('''(n) => document.querySelectorAll('.message.assistant').length >= n
                  && document.body.dataset.state === 'listening'
                  && window.__serverEvents.filter(p=>p.type==='audio').length >= n''', arg=index+1, timeout=60000)
                if await page.locator('#error').is_visible():
                    raise RuntimeError(await page.locator('#error').inner_text())

            for index in range(len(PROMPTS)):
                if index == 1:
                    await say(index)
                    await page.wait_for_function("document.body.dataset.state === 'speaking'", timeout=45000)
                    await page.wait_for_timeout(1100)
                    # Correct a constraint while speech is actually playing.
                    await say(index + 1)
                    await wait_reply(index + 1)
                    assert await page.locator('.message.interrupted').count() >= 1
                elif index == 2:
                    continue
                else:
                    await say(index)
                    await wait_reply(index)
                await page.wait_for_timeout(800)
            await page.wait_for_timeout(1000)
            await page.screenshot(path=str(media / 'conversation.png'))
            events = await page.evaluate('window.__serverEvents')
            transcript = await page.evaluate(r'''() => [...document.querySelectorAll('#messages .message')].map(node => {
              const who=node.classList.contains('user')?'You':'Voca';
              const interrupted=node.classList.contains('interrupted')?' — interrupted; not all displayed text was played':'';
              return '['+who+interrupted+']\n'+node.querySelector('.message-body').textContent;
            }).join('\n\n')''')
            (media / 'transcript.txt').write_text(transcript + '\n')
            (work / 'events.json').write_text(json.dumps(events, indent=2) + '\n')
            # End the screen capture before serializing the large audio payload.
            # Serialization can stall the browser microphone on long recordings.
            capture = False
            await frame_task
            audio_segments = await page.evaluate('window.__exportAudio()')
            (work / 'audio-segments.json').write_text(json.dumps(audio_segments))
            (work / 'frame-timeline.json').write_text(json.dumps({'clock_offset':clock_offset,'frames':frame_times}))
            stop = page.get_by_role('button', name='End conversation', exact=True)
            if await stop.count():
                await stop.click(timeout=3000)
            await page.wait_for_timeout(1000)
        finally:
            capture = False
            await frame_task
            await context.close()
            await browser.close()
        if errors:
            raise RuntimeError('Browser errors: ' + '; '.join(errors))
    if not audio_segments or len(frame_times) < 2:
        raise RuntimeError('Missing screen or audio capture')
    concat = frames / 'frames.ffconcat'
    entries = ['ffconcat version 1.0']
    for index, stamp in enumerate(frame_times):
        duration = frame_times[index+1]-stamp if index+1 < len(frame_times) else .16
        entries += [f"file '{index:06}.jpg'", f'duration {duration:.6f}']
    entries.append(f"file '{len(frame_times)-1:06}.jpg'")
    concat.write_text('\n'.join(entries) + '\n')
    duration = frame_times[-1]-frame_times[0] + .16
    # Reconstruct the digital mix from actual scheduled browser buffers and
    # actual stop times. This preserves silence and interruption cuts without
    # MediaRecorder timestamp/dropout issues in headless Chromium.
    rate=48000
    mix=np.zeros(round(duration*rate),dtype=np.float32)
    for segment in audio_segments:
        samples=np.frombuffer(base64.b64decode(segment['samples']),dtype='<f4')
        samples=samples[:round(segment['duration']*segment['rate'])]
        if not len(samples):continue
        samples=np.interp(np.arange(0,len(samples),segment['rate']/rate),np.arange(len(samples)),samples)
        offset=round((clock_offset+segment['start']/1000-frame_times[0])*rate)
        if offset<0:samples=samples[-offset:];offset=0
        count=min(len(samples),max(0,len(mix)-offset))
        if count:mix[offset:offset+count]+=samples[:count]
    with wave.open(str(work/'audio.wav'),'wb') as handle:
        handle.setnchannels(1);handle.setsampwidth(2);handle.setframerate(rate)
        handle.writeframes((np.clip(mix,-1,1)*32767).astype('<i2').tobytes())
    delay=0
    output = media / 'conversation-demo.mp4'
    print('Encoding synchronized MP4...', flush=True)
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-f','concat','-safe','0','-i',str(concat),
        '-i',str(work/'audio.wav'),
        '-map','0:v:0','-map','1:a:0','-vf','scale=1280:-2','-r','24','-c:v','libx264',
        '-preset','medium','-crf','21','-pix_fmt','yuv420p','-c:a','aac','-b:a','128k',
        '-t',f'{duration:.3f}','-movflags','+faststart',str(output)], check=True)
    print('Encoding browser-compatible WebM...', flush=True)
    # A WebM fallback covers Chromium builds without proprietary H.264/AAC codecs.
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(output),
        '-c:v','libvpx-vp9','-crf','36','-b:v','0','-deadline','good','-cpu-used','4',
        '-row-mt','1','-threads','4','-c:a','libopus','-b:a','96k',str(media/'conversation-demo.webm')],check=True)
    probe = json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(output)]))
    report = {'recorded_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
              'llm_model':config['llm']['model'], 'user_voice':'Kokoro am_michael (synthetic)',
              'assistant_voice':config['tts']['voice'], 'mocked_responses':False,
              'prompt_count':len(PROMPTS), 'duration_seconds':float(probe['format']['duration']),
              'video_bytes':output.stat().st_size, 'audio_offset_ms':delay, 'soundtrack_capture':'actual browser audio buffers with playback start/stop timestamps',
              'codecs':[stream['codec_name'] for stream in probe['streams']],
              'real_interruption_verified':True}
    (media/'recording.json').write_text(json.dumps(report,indent=2)+'\n')
    subprocess.run([sys.executable, str(ROOT/'scripts/serve.py'), str(ROOT/'scripts/caption_demo.py')], check=True)
    print('Recorded actual conversation:', output, flush=True)
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
