"""Real browser journeys with frozen synthetic audio, real models and bounded cloud use."""

import argparse, asyncio, hashlib, json, os, signal, subprocess, time, shutil
from pathlib import Path
import httpx, psutil
from playwright.async_api import async_playwright
from voice_conversation.settings import ROOT, load_config, load_settings
from scripts.evaluation.metrics import normalize, score, aggregate
from scripts.evaluation.resources import Resources
from evaluation.config import BROWSER

BOOTSTRAP = r"""
window.__events=[];window.__out=[];
const RealSocket=WebSocket;
window.WebSocket=class extends RealSocket {
 constructor(...args){super(...args);this.addEventListener('message',event=>{const {pcm,...safe}=JSON.parse(event.data);__events.push({...safe,at_ms:performance.now()});});}
 send(value){if(typeof value==='string')__out.push({...JSON.parse(value),at_ms:performance.now()});return super.send(value);}
};
const RealContext=AudioContext;
window.AudioContext=class extends RealContext {
 constructor(){super({sinkId:{type:'none'}});window.__ctx=this;window.__mic=this.createMediaStreamDestination();const quiet=this.createConstantSource();quiet.offset.value=.000001;quiet.connect(__mic);quiet.start();}
};
navigator.mediaDevices.getUserMedia=async()=>__mic.stream;
window.__say=async url=>{const ctx=__ctx;const buffer=await ctx.decodeAudioData(await(await fetch(url)).arrayBuffer());const source=ctx.createBufferSource();source.buffer=buffer;source.connect(__mic);await new Promise(resolve=>{source.onended=resolve;source.start();});};
"""


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + "\n")


def trace_events(folder, start, end):
    events = []
    for path in (folder / "pipeline-traces").glob("*/events.jsonl"):
        for line in path.read_text().splitlines():
            row = json.loads(line)
            if start <= row["monotonic_seconds"] <= end:
                events.append(dict(row, session=path.parent.name))
    return events


async def execute(page, case, folder, monitor):
    begin = time.monotonic()
    monitor.label = case["case_id"]
    failure = None
    timing = {}
    before = await page.evaluate("__events.length")
    sent = await page.evaluate("__out.length")
    previous = await page.evaluate("playing?.id??null")
    try:
        if case.get("barge_in"):
            await page.wait_for_function("Boolean(playing)", timeout=10000)
        else:
            await page.wait_for_function(
                "!playing&&!queue.length&&!responsePending",
                timeout=BROWSER["turn_timeout_ms"],
            )
        if case.get("fault"):
            r = await page.request.post("/__qa__/fault", data={"kind": case["fault"]})
            assert r.ok
        await page.wait_for_timeout(
            50 if case.get("barge_in") else BROWSER["idle_settle_ms"]
        )
        before = await page.evaluate("__events.length")
        sent = await page.evaluate("__out.length")
        begin = time.monotonic()
        timing = await asyncio.wait_for(
            page.evaluate(
                "async url=>{const start=performance.now();await __say(url);return {start,end:performance.now()};}",
                "/__flow__/" + case["case_id"] + ".wav",
            ),
            timeout=case["signal"]["seconds"] + BROWSER["input_timeout_margin_seconds"],
        )
        if case.get("expect_silence"):
            await page.wait_for_timeout(1800)
        elif case.get("leave_playing"):
            await page.wait_for_function(
                "Boolean(playing)", timeout=BROWSER["turn_timeout_ms"]
            )
        else:
            await page.wait_for_function(
                "n=>{const events=__events.slice(n);return events.some(e=>e.type==='final')&&events.some(e=>['audio','error','notice'].includes(e.type)&&(e.turn===undefined||e.turn===turn))&&!playing&&!queue.length&&!responsePending;}",
                arg=before,
                timeout=BROWSER["turn_timeout_ms"],
            )
    except Exception as error:
        failure = {"type": type(error).__name__, "message": str(error)[:350]}
    end = time.monotonic()
    events = await page.evaluate("n=>__events.slice(n)", before)
    acks = await page.evaluate("n=>__out.slice(n)", sent)
    state = await page.evaluate(
        "({active,turn,socket_state:ws?.readyState,buffered_bytes:ws?.bufferedAmount,error:document.getElementById('error').textContent,error_visible:!document.getElementById('error').hidden})"
    )
    traces = trace_events(folder, begin, end)
    finals = [e["text"] for e in events if e["type"] == "final"]
    text = " ".join(finals)
    answer = "".join(
        e["text"]
        for e in events
        if e["type"] == "token" and e.get("turn") == state["turn"]
    )
    audio = [
        e for e in events if e["type"] == "audio" and e.get("turn") == state["turn"]
    ]
    errors = [e for e in events if e["type"] == "error"]
    checks = {"no_timeout": failure is None, "session_active": state["active"]}
    if case.get("expect_silence"):
        checks.update(
            no_false_turn=not finals, no_false_reply=not audio, no_error=not errors
        )
    else:
        checks.update(
            one_final_input=len(finals) == 1,
            expected_error=bool(errors) == bool(case.get("expected_error")),
        )
        if not case.get("expected_error"):
            checks["no_stale_error_banner"] = not state["error_visible"]
            checks["audio_emitted"] = bool(audio)
            for index, alternatives in enumerate(case["expected_any"]):
                checks["answer_" + str(index)] = any(
                    normalize(x) in normalize(answer) for x in alternatives
                )
            for name, alternatives in case.get("semantic", {}).items():
                checks[name] = any(
                    normalize(x) in normalize(answer) for x in alternatives
                )
            for phrase in case.get("forbidden", []):
                checks["avoid_" + phrase] = normalize(phrase) not in normalize(answer)
            if not case.get("leave_playing"):
                heard = {
                    p["id"]
                    for p in acks
                    if p.get("type") == "played" and p.get("complete")
                }
                checks["playback_complete"] = all(e["id"] in heard for e in audio)
    interruption = None
    if case.get("barge_in"):
        packets = [
            e
            for e in events
            if e["type"] == "interrupt" and e["at_ms"] >= timing.get("start", 0)
        ]
        checks["old_playback_cancelled"] = any(
            p.get("id") == previous
            and p.get("type") == "played"
            and p.get("complete") is False
            for p in acks
        )
        checks["interrupt_received"] = bool(packets)
        interruption = (
            (packets[0]["at_ms"] - timing["start"]) / 1000
            if packets and timing
            else None
        )
    first_audio = (
        (audio[0]["at_ms"] - timing["end"]) / 1000 if audio and timing else None
    )
    row = {
        "case_id": case["case_id"],
        "session_id": case["session_id"],
        "reference": case["text"],
        "hypothesis": text,
        "answer": answer,
        "metrics": score(case["text"], text),
        "checks": checks,
        "passed": all(checks.values()),
        "failure": failure,
        "browser_connection": state,
        "timing": {
            "first_audio_after_recording_seconds": first_audio,
            "elapsed_seconds": end - begin,
            "recording_seconds": case["signal"]["seconds"],
            "interruption_seconds": interruption,
        },
        "events": events,
        "playback_acks": acks,
        "pipeline_trace": traces,
        "resources": monitor.summary(begin, end),
        "scope": "Real-time synthetic microphone; actual STT/cloud/TTS and silent browser playback. Assertions are necessary checks, not comprehensive semantic scoring.",
    }
    save(folder / "cases" / (case["case_id"] + ".json"), row)
    print(
        json.dumps(
            {
                "case": case["case_id"],
                "passed": row["passed"],
                "failed_checks": [k for k, v in checks.items() if not v],
                "first_audio": first_audio,
            }
        ),
        flush=True,
    )
    return row


async def run(args):
    folder = (ROOT / args.output).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "cases").mkdir(exist_ok=True)
    if (folder / "results.json").exists():
        raise RuntimeError("Preserve existing run")
    source = ROOT / args.dataset
    dataset = json.loads(source.read_text())
    inputs = json.loads((ROOT / args.inputs).read_text())
    assert inputs["dataset_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    cases = {r["case_id"]: r for r in inputs["cases"]}
    for row in cases.values():
        assert (
            hashlib.sha256((ROOT / row["audio"]).read_bytes()).hexdigest()
            == row["audio_sha256"]
        )
    sessions = [
        s
        for s in dataset["sessions"]
        if not args.session or s["session_id"] in args.session
    ]
    if not sessions:
        raise ValueError(
            "No matching evaluation sessions; refusing an empty successful run"
        )
    env = os.environ.copy()
    env["VOCA_EVALUATION_OUTPUT"] = str(folder.relative_to(ROOT))
    env["VOCA_EVALUATION_MAX_REQUESTS"] = "30"
    save(
        folder / "configuration.json",
        {
            "application": load_config(),
            "cloud_model": load_settings()["llm"]["model"],
            "dataset_sha256": inputs["dataset_sha256"],
            "external_server": args.external_server,
            "source_hashes": {
                str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in [
                    ROOT / "config.py",
                    *sorted((ROOT / "src/voice_conversation").glob("*.py")),
                    *sorted((ROOT / "web").glob("*.js")),
                ]
            },
        },
    )
    for path in [
        ROOT / "config.py",
        source,
        *sorted((ROOT / "src/voice_conversation").glob("*.py")),
        *sorted((ROOT / "web").glob("*.js")),
    ]:
        target = folder / "source" / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    server = None
    server_log = (folder / "server.log").open("w")
    rows = []
    errors = []
    monitor = Resources(folder / "resources.jsonl", BROWSER["resource_sample_seconds"])
    try:
        if not args.external_server:
            server = subprocess.Popen(
                [
                    str(ROOT / ".venv/bin/python"),
                    "-m",
                    "scripts.application.start_voice_app",
                    "-m",
                    "scripts.validation.start_evaluation_server",
                ],
                cwd=ROOT,
                env=env,
                stdout=server_log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        async with httpx.AsyncClient(timeout=3) as client:
            deadline = time.monotonic() + BROWSER["startup_timeout_seconds"]
            while True:
                try:
                    r = await client.get(f"http://127.0.0.1:{BROWSER['port']}/health")
                    if r.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                if time.monotonic() > deadline:
                    raise RuntimeError(
                        "Server did not become ready; inspect server.log"
                    )
                if server and server.poll() is not None:
                    raise RuntimeError("Evaluation server exited")
                await asyncio.sleep(0.5)
        monitor.start()
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                args=["--no-sandbox", "--autoplay-policy=no-user-gesture-required"]
            )
            try:
                for session in sessions:
                    context = await browser.new_context(
                        viewport={"width": 1400, "height": 1050},
                        base_url=f"http://127.0.0.1:{BROWSER['port']}",
                    )
                    await context.add_init_script(BOOTSTRAP)
                    page = await context.new_page()
                    page.on("pageerror", lambda error: errors.append(str(error)))

                    async def route(request):
                        identity = Path(request.request.url).stem
                        if identity in cases:
                            await request.fulfill(
                                path=str(ROOT / cases[identity]["audio"]),
                                content_type="audio/wav",
                            )
                        else:
                            await request.abort()

                    await page.route("**/__flow__/*", route)
                    await page.goto(
                        f"http://127.0.0.1:{BROWSER['port']}", wait_until="networkidle"
                    )
                    await page.locator("#start").click()
                    await page.wait_for_function(
                        "active&&context.state==='running'", timeout=30000
                    )
                    for spec in session["turns"]:
                        result = await execute(
                            page, cases[spec["case_id"]], folder, monitor
                        )
                        rows.append(result)
                        save(
                            folder / "results.json",
                            {
                                "complete": False,
                                "cases": rows,
                                "javascript_errors": errors,
                            },
                        )
                        if not result["browser_connection"]["active"]:
                            break
                    await page.screenshot(
                        path=str(folder / (session["session_id"] + ".png")),
                        full_page=True,
                    )
                    if await page.evaluate("active"):
                        await page.locator("#start").click()
                    await context.close()
                    await asyncio.sleep(0.5)
            finally:
                await browser.close()
    finally:
        if hasattr(monitor, "thread"):
            monitor.stop()
        if server and server.poll() is None:
            children = psutil.Process(server.pid).children()
            for child in children:
                try:
                    child.send_signal(signal.SIGINT)
                except psutil.Error:
                    pass
            try:
                server.wait(timeout=25)
            except subprocess.TimeoutExpired:
                os.killpg(server.pid, signal.SIGTERM)
                server.wait(timeout=10)
        server_log.close()
    save(
        folder / "results.json",
        {"complete": True, "cases": rows, "javascript_errors": errors},
    )
    summary = {
        "selected": sum(len(s["turns"]) for s in sessions),
        "completed": len(rows),
        "passed": sum(r["passed"] for r in rows),
        "javascript_errors": errors,
        "failed": [
            {
                "case_id": r["case_id"],
                "checks": [k for k, v in r["checks"].items() if not v],
            }
            for r in rows
            if not r["passed"]
        ],
        "metrics": aggregate([r for r in rows if r["reference"]]),
        "resources": monitor.summary(),
        "scope": "Actual browser, real-time synthetic input, actual model/cloud path except explicitly injected fault. Native process tree includes child server; external-server mode excludes its CPU/RAM.",
    }
    save(folder / "summary.json", summary)
    return int(summary["passed"] != summary["selected"] or bool(errors))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--session", action="append")
    parser.add_argument("--external-server", action="store_true")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("evaluation/datasets/conversation-flows-v1.json"),
    )
    parser.add_argument(
        "--inputs",
        type=Path,
        default=Path(".evaluation-local/flow-inputs-v1/inputs.json"),
    )
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
