"""Microphone framing must continue through an empty/silent input quantum."""

from pathlib import Path
import shutil
import subprocess

import pytest


def test_capture_emits_clocked_silence_and_resamples_voice():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is needed for the AudioWorklet regression check")
    script = Path(__file__).resolve().parents[1] / "web/capture.js"
    code = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const sent=[];let Processor;
class Base {constructor(){this.port={postMessage:buffer=>sent.push(new Float32Array(buffer).slice())};}}
const sandbox={AudioWorkletProcessor:Base,sampleRate:48000,Float32Array,
 registerProcessor:(name,cls)=>{Processor=cls;}};
vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),sandbox);
const worker=new Processor();
for(let i=0;i<12;i++)worker.process([[]],[[new Float32Array(128)]]);
assert.equal(sent.length,1);assert.equal(sent[0].length,512);
assert(sent[0].every(value=>value===0));
for(let i=0;i<12;i++)worker.process([[new Float32Array(128).fill(.2)]],[[new Float32Array(128)]]);
assert.equal(sent.length,2);assert(sent[1].every(value=>Math.abs(value-.2)<1e-6));
"""
    subprocess.run(
        [node, "-e", code, str(script)], check=True, capture_output=True, text=True
    )
