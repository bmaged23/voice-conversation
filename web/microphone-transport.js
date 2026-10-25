'use strict';
// Preserve ordered audio across short browser/network scheduling bursts.
class MicrophoneTransport {
  constructor(socket, settings, onError) {
    this.socket = socket;
    this.settings = settings;
    this.onError = onError;
    this.frames = [];
    this.closed = false;
    this.timer = setInterval(() => this.flush(), settings.transport_poll_ms);
  }
  push(frame) {
    if (this.closed) return;
    if (this.frames.length >= this.settings.max_queued_frames) {
      this.close();
      this.onError('The audio connection fell behind for too long. Please start a new session.');
      return;
    }
    this.frames.push(frame);
    this.flush();
  }
  flush() {
    if (this.closed || this.socket.readyState !== WebSocket.OPEN) return;
    try {
      // Bound work per callback as well as memory and WebSocket buffering.
      for (let count = 0; count < 16 && this.frames.length; count++) {
        const frame = this.frames[0];
        if (this.socket.bufferedAmount + frame.byteLength > this.settings.max_buffered_bytes) break;
        this.socket.send(frame);
        this.frames.shift();
      }
    } catch {
      this.close();
      this.onError('Unable to send microphone audio. Please start a new session.');
    }
  }
  close() {
    this.closed = true;
    clearInterval(this.timer);
    this.frames.length = 0;
  }
}
window.MicrophoneTransport = MicrophoneTransport;
