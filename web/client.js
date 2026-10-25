'use strict';
const el = id => document.getElementById(id);
const clock = seconds => `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
let ws, context, stream, microphone, capture, inputMeter, outputMeter, outputGain;
let queue = [], playing = null, turn = 0, active = false, muted = false, generation = 0;
let userMessage = null, assistantMessage = null, responsePending = false, totalTurns = 0;
let timer = null, sessionStart = 0, lastLatency = null;
let microphoneTransport = null;

function state(mode, detail) {
  const effective = muted && mode === 'listening' ? 'muted' : mode;
  document.body.dataset.state = effective;
  const labels = {
    idle: ['Ready when you are.', 'One click. A more natural way to talk.', 'Microphone off', 'STANDBY'],
    connecting: ['Getting comfortable…', 'Connecting your microphone and assistant.', 'Connecting', 'CONNECTING'],
    listening: ['I’m all ears.', 'Speak freely. Pause when you’re ready for a reply.', 'Listening to you', 'LIVE'],
    thinking: ['A thought is taking shape.', 'Your assistant is putting a reply together.', 'Thinking', 'THINKING'],
    speaking: ['Let’s keep talking.', 'Jump in whenever something comes to mind.', 'Speaking · feel free to interrupt', 'SPEAKING'],
    muted: ['Take your time.', 'You can still listen. Unmute whenever you’re ready.', 'Microphone muted', 'MUTED']
  };
  const [title, description, status, badge] = labels[effective] || labels.idle;
  el('stage-title').textContent = title;
  el('stage-description').textContent = description;
  el('status').textContent = detail || status;
  el('live-pill').querySelector('span').textContent = badge;
}
function connection(online, text) {
  el('connection').className = `connection ${online ? 'online' : 'offline'}`;
  el('connection-text').textContent = text;
}
function showError(text = '') {
  el('error').textContent = text;
  el('error').hidden = !text;
}
function send(packet, socket = ws) {
  if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(packet));
}
function scrollTranscript() {
  const panel = el('conversation-scroll');
  // Preserve the reader’s position when they have scrolled up.
  if (panel.scrollHeight - panel.scrollTop - panel.clientHeight < 160) panel.scrollTop = panel.scrollHeight;
}
function message(role) {
  el('empty-state').hidden = true;
  const article = document.createElement('article');
  article.className = `message ${role}`;
  const meta = document.createElement('div'); meta.className = 'message-meta';
  const avatar = document.createElement('span'); avatar.className = 'message-avatar';
  avatar.textContent = role === 'user' ? 'BM' : 'V';
  const name = document.createElement('span'); name.textContent = role === 'user' ? 'You' : 'Voca';
  const timestamp = document.createElement('time'); timestamp.className = 'message-time';
  timestamp.dateTime = new Date().toISOString();
  timestamp.textContent = new Date().toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
  const body = document.createElement('div'); body.className = 'message-body';
  meta.append(avatar, name, timestamp); article.append(meta, body); el('messages').append(article);
  scrollTranscript();
  return {article, body};
}
function haltPlayback() {
  queue = [];
  if (playing) {
    const old = playing; playing = null; old.source.onended = null;
    try { old.source.stop(); } catch { /* already stopped */ }
    send({type: 'played', id: old.id, complete: false});
  }
}
function playNext() {
  if (playing || !active) return;
  while (queue.length && queue[0].turn !== turn) queue.shift();
  if (!queue.length) {
    state(responsePending ? 'thinking' : 'listening');
    return;
  }
  const chunk = queue.shift();
  const bytes = Uint8Array.from(atob(chunk.pcm), c => c.charCodeAt(0));
  const view = new DataView(bytes.buffer);
  const buffer = context.createBuffer(1, bytes.length / 2, chunk.sample_rate);
  const audio = buffer.getChannelData(0);
  for (let i = 0; i < audio.length; i++) audio[i] = view.getInt16(i * 2, true) / 32768;
  const source = context.createBufferSource(); source.buffer = buffer; source.connect(outputGain);
  playing = {id: chunk.id, source}; state('speaking');
  const thisGeneration = generation;
  source.onended = () => {
    if (thisGeneration !== generation) return;
    send({type: 'played', id: chunk.id, complete: true});
    playing = null; playNext();
  };
  source.start();
}
async function listMicrophones() {
  if (!navigator.mediaDevices?.enumerateDevices) return;
  const devices = await navigator.mediaDevices.enumerateDevices();
  const select = el('microphone-select'), selected = select.value;
  select.replaceChildren(new Option('System default', ''));
  let index = 0;
  for (const device of devices.filter(item => item.kind === 'audioinput')) {
    if (device.deviceId && device.deviceId !== 'default') {
      select.add(new Option(device.label || `Microphone ${++index}`, device.deviceId));
    }
  }
  if ([...select.options].some(option => option.value === selected)) select.value = selected;
}
async function stopSession(detail = 'Microphone off') {
  generation++;
  active = false; responsePending = false;
  microphoneTransport?.close(); microphoneTransport = null;
  haltPlayback();
  clearInterval(timer); timer = null;
  const oldStream = stream, oldContext = context, oldSocket = ws;
  stream = context = ws = null;
  oldStream?.getTracks().forEach(track => track.stop());
  capture?.disconnect(); microphone?.disconnect();
  capture = microphone = inputMeter = outputMeter = outputGain = null;
  if (oldSocket && oldSocket.readyState === WebSocket.OPEN) send({type: 'stop'}, oldSocket);
  if (oldSocket && oldSocket.readyState < WebSocket.CLOSING) oldSocket.close();
  if (oldContext && oldContext.state !== 'closed') {
    try { await oldContext.close(); } catch { /* already closing */ }
  }
  muted = false;
  el('mute').disabled = true; el('mute').setAttribute('aria-pressed', 'false');
  el('mute').setAttribute('aria-label', 'Mute microphone');
  el('start').disabled = false; el('start').classList.remove('is-active');
  el('start-label').textContent = 'Start conversation';
  el('start-icon').querySelector('use').setAttribute('href', '#i-mic');
  el('control-hint').textContent = 'Your microphone turns on only when you start.';
  el('transcript-indicator').lastChild.textContent = 'Session stopped';
  el('partial').textContent = '';
  connection(true, 'Server ready');
  state('idle', detail);
}
function onPacket(packet) {
  switch (packet.type) {
    case 'interrupt':
      showError();
      if ((playing || responsePending) && assistantMessage) assistantMessage.article.classList.add('interrupted');
      haltPlayback(); turn = packet.turn; userMessage = assistantMessage = null;
      responsePending = false; el('partial').textContent = ''; state('listening');
      break;
    case 'partial':
      el('empty-state').hidden = true;
      el('partial').textContent = packet.text; scrollTranscript(); break;
    case 'final':
      el('partial').textContent = '';
      if (packet.text) {
        userMessage = message('user'); userMessage.body.textContent = packet.text;
        totalTurns++; el('turn-count').textContent = totalTurns; scrollTranscript();
      }
      break;
    case 'token':
      if (packet.turn !== turn) break;
      if (!assistantMessage) assistantMessage = message('assistant');
      assistantMessage.body.append(document.createTextNode(packet.text)); scrollTranscript(); break;
    case 'audio':
      if (packet.turn === turn) { queue.push(packet); playNext(); } break;
    case 'status':
      if (packet.turn != null && packet.turn !== turn) break;
      if (packet.text === 'Thinking') { responsePending = true; if (!playing) state('thinking'); }
      else if (packet.text === 'Listening') { responsePending = false; if (!playing) state('listening'); }
      else if (!playing) state('listening');
      break;
    case 'latency':
      lastLatency = packet.seconds;
      el('latency').replaceChildren(document.createTextNode(packet.seconds.toFixed(2)));
      const unit = document.createElement('span'); unit.textContent = ' s'; el('latency').append(unit);
      break;
    case 'error':
      showError(packet.text); responsePending = false;
      if (active && !playing) state('listening', 'Ready to try again');
      break;
  }
}
async function startSession() {
  const token = ++generation;
  el('start').disabled = true; showError(); state('connecting');
  try {
    if (!navigator.mediaDevices?.getUserMedia) throw new Error('Open this page on localhost or HTTPS to use your microphone.');
    const response = await fetch('/client-config');
    if (!response.ok) throw new Error('The voice server is unavailable. Start it, then try again.');
    const audioConfig = await response.json();
    if (token !== generation) return;
    context = new AudioContext(); await context.resume();
    outputGain = context.createGain(); outputGain.gain.value = Number(el('volume').value) / 100;
    outputMeter = context.createAnalyser(); outputMeter.fftSize = 512;
    outputGain.connect(outputMeter); outputMeter.connect(context.destination);
    if (audioConfig.output_device_id && context.setSinkId) await context.setSinkId(audioConfig.output_device_id);
    const constraints = {channelCount: audioConfig.input_channels, echoCancellation: audioConfig.echo_cancellation,
      noiseSuppression: audioConfig.noise_suppression, autoGainControl: audioConfig.auto_gain_control};
    const device = el('microphone-select').value || audioConfig.input_device_id;
    if (device) constraints.deviceId = {exact: device};
    const selectedStream = await navigator.mediaDevices.getUserMedia({audio: constraints});
    if (token !== generation) { selectedStream.getTracks().forEach(track => track.stop()); return; }
    stream = selectedStream;
    await listMicrophones();
    await context.audioWorklet.addModule('/static/capture.js');
    const socket = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`);
    ws = socket;
    socket.onmessage = event => {
      if (token !== generation) return;
      const packet = JSON.parse(event.data);
      if (packet.type === 'ready') {
        active = true; turn = 0; userMessage = assistantMessage = null;
        el('messages').replaceChildren(); el('empty-state').hidden = false;
        totalTurns = 0; lastLatency = null;
        el('turn-count').textContent = '0'; el('latency').textContent = '—';
        sessionStart = performance.now();
        clearInterval(timer); timer = setInterval(() => { el('duration').textContent = clock(Math.floor((performance.now() - sessionStart) / 1000)); }, 1000);
        el('duration').textContent = '00:00'; el('mute').disabled = false;
        el('start').disabled = false; el('start').classList.add('is-active');
        el('start-label').textContent = 'End conversation';
        el('start-icon').querySelector('use').setAttribute('href', '#i-stop');
        el('control-hint').textContent = 'Speak naturally. You can interrupt at any time.';
        el('transcript-indicator').lastChild.textContent = 'Live';
        el('model-name').textContent = packet.model;
        connection(true, 'Connected'); state('listening');
        microphone = context.createMediaStreamSource(stream);
        inputMeter = context.createAnalyser(); inputMeter.fftSize = 512;
        capture = new AudioWorkletNode(context, 'microphone-capture');
        microphoneTransport = new MicrophoneTransport(socket, audioConfig, message => {
          showError(message); stopSession();
        });
        capture.port.onmessage = e => {
          if (!active || socket.readyState !== WebSocket.OPEN || token !== generation) return;
          microphoneTransport?.push(e.data);
        };
        microphone.connect(inputMeter); inputMeter.connect(capture); capture.connect(context.destination);
      } else onPacket(packet);
    };
    socket.onerror = () => { if (token === generation) showError('Unable to connect to the voice server. Check that it is running.'); };
    socket.onclose = () => {
      if (token !== generation) return;
      if (active) showError('The connection closed. Start again to continue.');
      stopSession('Session ended'); connection(false, 'Disconnected');
    };
  } catch (error) {
    if (token !== generation) return;
    const descriptions = {NotAllowedError: 'Microphone access was denied. Allow microphone access in your browser, then try again.',
      NotFoundError: 'No microphone was found. Connect one and try again.',
      NotReadableError: 'Your microphone is busy or unavailable. Close other recording apps and try again.',
      OverconstrainedError: 'The selected microphone is unavailable. Choose System default in audio settings.'};
    showError(descriptions[error.name] || error.message);
    await stopSession();
  }
}
el('start').onclick = () => active ? stopSession('Session ended') : startSession();
el('mute').onclick = () => {
  if (!active) return;
  muted = !muted; stream.getAudioTracks().forEach(track => { track.enabled = !muted; });
  el('mute').setAttribute('aria-pressed', String(muted));
  el('mute').setAttribute('aria-label', muted ? 'Unmute microphone' : 'Mute microphone');
  if (!playing && !responsePending) state('listening');
};
el('audio-settings').onclick = async () => {
  const open = el('settings-panel').hidden;
  el('settings-panel').hidden = !open; el('audio-settings').setAttribute('aria-expanded', String(open));
  try { if (open) await listMicrophones(); } catch { /* Permission may not be granted yet. */ }
};
el('volume').oninput = event => {
  const value = Number(event.target.value); el('volume-label').textContent = `${value}%`;
  if (outputGain) outputGain.gain.value = value / 100;
};
el('new-session').onclick = async () => {
  el('new-session').disabled = true;
  await stopSession();
  el('messages').replaceChildren(); el('empty-state').hidden = false;
  userMessage = assistantMessage = null; totalTurns = 0; lastLatency = null;
  el('turn-count').textContent = '0'; el('duration').textContent = '00:00';
  el('latency').textContent = '—'; showError();
  el('new-session').disabled = false;
};
window.addEventListener('pagehide', () => {
  active = false; stream?.getTracks().forEach(track => track.stop()); ws?.close();
});

// Display actual microphone/playback energy. Decorative idle bars stay quiet.
const canvas = el('waveform'), pen = canvas.getContext('2d');
const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
const samples = new Float32Array(512);
let energy = 0;
function drawWave(time) {
  const rect = canvas.getBoundingClientRect(), dpr = Math.min(devicePixelRatio || 1, 2);
  if (canvas.width !== Math.round(rect.width * dpr) || canvas.height !== Math.round(rect.height * dpr)) {
    canvas.width = Math.round(rect.width * dpr); canvas.height = Math.round(rect.height * dpr);
  }
  pen.setTransform(dpr, 0, 0, dpr, 0, 0); pen.clearRect(0, 0, rect.width, rect.height);
  const meter = playing ? outputMeter : muted ? null : inputMeter;
  let rms = 0;
  if (meter) { meter.getFloatTimeDomainData(samples); for (const value of samples) rms += value * value; rms = Math.sqrt(rms / samples.length); }
  energy = energy * .72 + Math.min(rms * 5, 1) * .28;
  const count = 49, gap = 5, width = 2, start = (rect.width - (count - 1) * gap - width) / 2;
  for (let i = 0; i < count; i++) {
    const taper = Math.sin(Math.PI * (i + 1) / (count + 1));
    const phase = reducedMotion ? i : i * .9 + time / 130;
    const height = 3 + energy * 32 * taper * (.35 + .65 * Math.abs(Math.sin(phase)));
    pen.fillStyle = active ? `rgba(90,139,88,${.28 + taper * .5})` : `rgba(145,166,125,${.18 + taper * .28})`;
    pen.beginPath(); pen.roundRect(start + i * gap, (rect.height - height) / 2, width, height, 2); pen.fill();
  }
  requestAnimationFrame(drawWave);
}
requestAnimationFrame(drawWave);
async function checkServer() {
  try {
    const response = await fetch('/health'); if (!response.ok) throw new Error('Unavailable');
    const health = await response.json();
    if (!active) connection(true, 'Server ready'); el('model-name').textContent = health.model;
  } catch { if (!active) connection(false, 'Server offline'); }
}
checkServer();
