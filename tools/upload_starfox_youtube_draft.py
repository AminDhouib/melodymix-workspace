import argparse
import asyncio
import json
import pathlib
import sys
import time
import urllib.request

import websockets


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


PORT = 62352
DEFAULT_TARGET_ID = "EF2F0710C795BA140EA30492F5168B5B"
THUMBNAIL = pathlib.Path(
    r"C:\Users\amind\Downloads\dfa48e75f82fbb0fedc022d07a5d8a021a02ee8de95914fc84c1ee3066f656ba.jpg"
)
DESCRIPTION = """♫Origins of this track: Star Fox Remake Switch 2
♫Original Composer: Unknown

♫Extended loop version rendered from the highest available source.
♫Runtime: 14:29.24"""


class Cdp:
    def __init__(self, ws):
        self.ws = ws
        self.next_id = 1

    async def send(self, method, params=None, timeout=30):
        call_id = self.next_id
        self.next_id += 1
        await self.ws.send(json.dumps({"id": call_id, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(await asyncio.wait_for(self.ws.recv(), timeout=timeout))
            if msg.get("id") == call_id:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    async def click(self, x, y, wait=1.0):
        await self.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y, "button": "left"}, 10)
        await self.send(
            "Input.dispatchMouseEvent",
            {"type": "mousePressed", "x": x, "y": y, "button": "left", "buttons": 1, "clickCount": 1},
            10,
        )
        await asyncio.sleep(0.12)
        await self.send(
            "Input.dispatchMouseEvent",
            {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1},
            10,
        )
        await asyncio.sleep(wait)

    async def body_text(self):
        result = await self.send(
            "Runtime.evaluate",
            {"expression": "document.body.innerText", "returnByValue": True},
            10,
        )
        return result["result"].get("value", "")

    async def wait_for_text(self, needle, timeout=60):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if needle in await self.body_text():
                return
            await asyncio.sleep(1)
        raise TimeoutError(f"Timed out waiting for text: {needle}")

    async def wait_until_dialog_closed(self, timeout=90):
        deadline = time.time() + timeout
        while time.time() < deadline:
            dialogs = await self.visible_dialog_texts()
            if any("Video processing" in dialog for dialog in dialogs):
                await self.click_visible_text("Close", prefer_bottom=True, timeout=3)
                await asyncio.sleep(1)
                continue
            upload_visible = any(
                "Upload videos" in dialog or "Save or publish" in dialog or "Details\nMonetization" in dialog
                for dialog in dialogs
            )
            text = await self.body_text()
            if "Channel content" in text and not upload_visible:
                return
            await asyncio.sleep(1)
        raise TimeoutError("Upload dialog did not close")

    async def get_monetization_value(self):
        result = await self.send(
            "Runtime.evaluate",
            {
                "expression": "document.querySelector('ytcp-video-monetization')?.innerText || ''",
                "returnByValue": True,
            },
            10,
        )
        return result["result"].get("value", "")

    async def eval_value(self, expression, timeout=10):
        result = await self.send(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True},
            timeout,
        )
        return result["result"].get("value")

    async def visible_dialog_texts(self):
        return await self.eval_value(
            r"""
(() => [...document.querySelectorAll('tp-yt-paper-dialog')]
  .map(el => {
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    return {text: (el.innerText || el.textContent || ''), x: r.x, y: r.y, width: r.width, height: r.height, display: cs.display, visibility: cs.visibility};
  })
  .filter(item => item.width > 0 && item.height > 0 && item.display !== 'none' && item.visibility !== 'hidden')
  .map(item => item.text))()
""",
            10,
        ) or []

    async def click_visible_text(self, text, prefer_bottom=False, timeout=10):
        expression = f"""
(() => {{
  const target = {json.dumps(text)};
  const out = [];
  const seen = new Set();
  function walk(root) {{
    for (const el of root.querySelectorAll('*')) {{
      if (seen.has(el)) continue;
      seen.add(el);
      if (el.shadowRoot) walk(el.shadowRoot);
      const label = (el.innerText || el.textContent || '').trim().replace(/\\s+/g, ' ');
      if (label !== target) continue;
      const r = el.getBoundingClientRect();
      const cs = getComputedStyle(el);
      if (r.width <= 0 || r.height <= 0 || cs.display === 'none' || cs.visibility === 'hidden') continue;
      if (r.x < 0 || r.y < 0 || r.x > innerWidth || r.y > innerHeight) continue;
      out.push({{
        tag: el.tagName.toLowerCase(),
        aria: el.getAttribute('aria-label') || '',
        x: r.x,
        y: r.y,
        width: r.width,
        height: r.height
      }});
    }}
  }}
  walk(document);
  return out;
}})()
"""
        candidates = await self.eval_value(expression, timeout) or []
        if not candidates:
            raise RuntimeError(f"Visible text not found: {text}")
        if prefer_bottom:
            chosen = max(candidates, key=lambda item: item["y"])
        else:
            chosen = min(candidates, key=lambda item: item["width"] * item["height"])
        await self.click(chosen["x"] + chosen["width"] / 2, chosen["y"] + chosen["height"] / 2, 1.0)


async def connect(target_id):
    pages = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list"))
    target = next((p for p in pages if p.get("id") == target_id), None)
    if target is None:
        target = next(p for p in pages if "studio.youtube.com" in p.get("url", ""))
    ws = await websockets.connect(target["webSocketDebuggerUrl"], max_size=None)
    return Cdp(ws)


async def open_upload_dialog(cdp):
    await cdp.send("Page.bringToFront")
    text = await cdp.body_text()
    if "Drag and drop video files to upload" in text:
        return
    await cdp.click(1300, 33, 0.8)
    await cdp.click(1290, 77, 2.0)
    await cdp.wait_for_text("Drag and drop video files to upload", 30)


async def drop_video(cdp, video_path):
    size = await cdp.send("Runtime.evaluate", {"expression": "({w: innerWidth, h: innerHeight})", "returnByValue": True}, 10)
    viewport = size["result"]["value"]
    data = {"items": [], "files": [str(video_path)], "dragOperationsMask": 1}
    x = viewport["w"] / 2
    y = viewport["h"] * 0.45
    for event_type in ("dragEnter", "dragOver", "drop"):
        await cdp.send("Input.dispatchDragEvent", {"type": event_type, "x": x, "y": y, "data": data}, 10)
        await asyncio.sleep(0.7)
    await cdp.wait_for_text("Title (required)", 60)


async def set_metadata(cdp, title, thumbnail_path):
    expression = f"""
(() => {{
  const title = {json.dumps(title)};
  const desc = {json.dumps(DESCRIPTION)};
  function setBox(el, text) {{
    el.focus();
    const sel = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(el);
    sel.removeAllRanges();
    sel.addRange(range);
    document.execCommand('insertText', false, text);
    el.dispatchEvent(new InputEvent('input', {{bubbles: true, inputType: 'insertText', data: text}}));
    el.dispatchEvent(new Event('change', {{bubbles: true}}));
  }}
  const boxes = [...document.querySelectorAll('#textbox')];
  if (boxes.length < 2) throw new Error('title/description boxes not found');
  setBox(boxes[0], title);
  setBox(boxes[1], desc);
  return boxes.map(el => (el.innerText || el.textContent || '').slice(0, 120));
}})()
"""
    await cdp.send("Runtime.evaluate", {"expression": expression, "returnByValue": True}, 20)
    result = await cdp.send(
        "Runtime.evaluate",
        {"expression": "document.querySelector('input[type=file][accept*=image]')", "returnByValue": False},
        10,
    )
    object_id = result.get("result", {}).get("objectId")
    if not object_id:
        raise RuntimeError("thumbnail file input not found")
    await cdp.send("DOM.setFileInputFiles", {"objectId": object_id, "files": [str(thumbnail_path)]}, 20)
    await asyncio.sleep(3)


async def set_monetization_off(cdp):
    for _ in range(4):
        if "Off" in await cdp.get_monetization_value():
            return
        rect = await cdp.eval_value(
            """
(() => {
  const el = document.querySelector('#m10n-container') || document.querySelector('ytcp-video-monetization');
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return {x: r.x, y: r.y, width: r.width, height: r.height};
})()
"""
        )
        if not rect:
            raise RuntimeError("monetization field not found")
        # YouTube Studio shifts this control slightly between uploads. Anchor clicks
        # to the field itself instead of the whole viewport.
        await cdp.click(rect["x"] + rect["width"] / 2, rect["y"] + min(rect["height"] - 20, 44), 1.0)
        await cdp.click(rect["x"] + 60, rect["y"] + 73, 0.8)
        await cdp.click(rect["x"] + rect["width"] - 44, rect["y"] + 131, 2.0)
        if "Off" in await cdp.get_monetization_value():
            return
    raise RuntimeError("Could not set monetization to Off")


async def save_private(cdp):
    await cdp.click(1138, 704, 2.0)
    await cdp.wait_for_text("Monetization", 30)
    await set_monetization_off(cdp)
    await cdp.click(1138, 704, 1.5)
    await cdp.wait_for_text("Video elements", 30)
    await cdp.click(1138, 704, 1.5)
    await cdp.wait_for_text("Checks", 30)
    await cdp.click(1138, 704, 2.0)
    await cdp.wait_for_text("Save or publish", 30)
    await cdp.click(344, 351, 0.8)
    await cdp.click(1138, 704, 6.0)
    await cdp.wait_until_dialog_closed()


async def upload_one(args):
    video = pathlib.Path(args.video).resolve()
    if not video.exists():
        raise FileNotFoundError(video)
    if not THUMBNAIL.exists():
        raise FileNotFoundError(THUMBNAIL)
    cdp = await connect(args.target_id)
    try:
        print(f"Opening upload dialog for {args.title}", flush=True)
        await open_upload_dialog(cdp)
        print(f"Dropping file: {video.name}", flush=True)
        await drop_video(cdp, video)
        print("Setting metadata and thumbnail", flush=True)
        await set_metadata(cdp, args.title, THUMBNAIL)
        print("Saving as private with monetization off", flush=True)
        await save_private(cdp)
        print(f"Saved: {args.title}", flush=True)
    finally:
        await cdp.ws.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--target-id", default=DEFAULT_TARGET_ID)
    args = parser.parse_args()
    asyncio.run(upload_one(args))


if __name__ == "__main__":
    main()
