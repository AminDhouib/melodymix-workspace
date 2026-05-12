import argparse
import asyncio
import base64
import json
import pathlib
import sys
import time
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import websockets

from youtube_upload_metadata import TITLE_PREFIX, YOUTUBE_TAG_LIMIT, display_title, item_tags, tags_cost


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "Zelda Spirit Tracks Metadata" / "upload_manifest.json"
DEFAULT_STATE = ROOT / "Zelda Spirit Tracks Metadata" / "upload_state.json"
DEFAULT_PLAYLIST_TITLE = "Zelda - Spirit Tracks - Music Extended!"
DEFAULT_STUDIO_URL = "https://studio.youtube.com/"
MONTHS = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
]


class UserActionRequired(RuntimeError):
    pass


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

    async def eval_value(self, expression, timeout=10):
        result = await self.send(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
            timeout,
        )
        return result.get("result", {}).get("value")

    async def click(self, x, y, wait=0.8):
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

    async def key_combo(self, *keys, wait=0.2):
        modifiers = 0
        down = []
        for key in keys:
            if key.lower() in {"control", "ctrl"}:
                modifiers |= 2
            elif key.lower() == "alt":
                modifiers |= 1
            elif key.lower() == "shift":
                modifiers |= 8
            elif key.lower() in {"meta", "cmd", "command"}:
                modifiers |= 4
            else:
                down.append(key)
        for key in keys:
            if key.lower() in {"control", "ctrl", "alt", "shift", "meta", "cmd", "command"}:
                await self.send("Input.dispatchKeyEvent", {"type": "keyDown", "key": key, "modifiers": modifiers}, 10)
        for key in down:
            await self.send("Input.dispatchKeyEvent", {"type": "keyDown", "key": key, "modifiers": modifiers}, 10)
            await self.send("Input.dispatchKeyEvent", {"type": "keyUp", "key": key, "modifiers": modifiers}, 10)
        for key in reversed(keys):
            if key.lower() in {"control", "ctrl", "alt", "shift", "meta", "cmd", "command"}:
                await self.send("Input.dispatchKeyEvent", {"type": "keyUp", "key": key, "modifiers": 0}, 10)
        await asyncio.sleep(wait)

    async def insert_text(self, text, wait=0.2):
        await self.send("Input.insertText", {"text": text}, 10)
        await asyncio.sleep(wait)

    async def screenshot(self, path):
        result = await self.send("Page.captureScreenshot", {"format": "png", "fromSurface": True}, 30)
        pathlib.Path(path).write_bytes(base64.b64decode(result["data"]))

    async def page_text(self):
        return await self.eval_value(
            r"""
(() => {
  const seen = new Set();
  const chunks = [];
  function walk(root) {
    for (const el of root.querySelectorAll('*')) {
      if (seen.has(el)) continue;
      seen.add(el);
      const text = (el.innerText || el.textContent || '').trim();
      if (text) chunks.push(text);
      if (el.shadowRoot) walk(el.shadowRoot);
    }
  }
  chunks.push(document.body?.innerText || '');
  walk(document);
  return [...new Set(chunks)].join('\n');
})()
""",
            20,
        ) or ""

    async def wait_for_text(self, needles, timeout=60):
        if isinstance(needles, str):
            needles = [needles]
        deadline = time.time() + timeout
        while time.time() < deadline:
            text = await self.page_text()
            for needle in needles:
                if needle in text:
                    return needle
            await asyncio.sleep(1)
        raise TimeoutError(f"Timed out waiting for text: {needles}")

    async def assert_not_login_blocked(self):
        text = await self.page_text()
        if "Verify it's you" in text or "Please sign in again" in text:
            raise UserActionRequired("Google verification is required in the browser window.")
        if "Sign in" in text and "YouTube Studio" not in text and "Studio" not in text:
            raise UserActionRequired("YouTube Studio is asking for sign-in in the browser window.")

    async def visible_dialog_texts(self):
        return await self.eval_value(
            r"""
(() => {
  const out = [];
  const seen = new Set();
  function walk(root) {
    for (const el of root.querySelectorAll('*')) {
      if (seen.has(el)) continue;
      seen.add(el);
      if (el.shadowRoot) walk(el.shadowRoot);
      const tag = el.tagName.toLowerCase();
      if (!tag.includes('dialog') && el.getAttribute('role') !== 'dialog') continue;
      const r = el.getBoundingClientRect();
      const cs = getComputedStyle(el);
      if (r.width <= 0 || r.height <= 0 || cs.display === 'none' || cs.visibility === 'hidden') continue;
      out.push((el.innerText || el.textContent || '').trim());
    }
  }
  walk(document);
  return out;
})()
""",
            10,
        ) or []

    async def wait_until_upload_dialog_closed(self, timeout=180):
        deadline = time.time() + timeout
        while time.time() < deadline:
            dialogs = await self.visible_dialog_texts()
            if any("Video processing" in d for d in dialogs):
                await self.click_text("Close", prefer_bottom=True, timeout=4, required=False)
                await asyncio.sleep(1)
                continue
            text = await self.page_text()
            upload_visible = any(
                marker in text
                for marker in (
                    "Drag and drop video files to upload",
                    "Save or publish",
                    "Upload videos",
                    "Video elements",
                    "Checks",
                )
            )
            if "Channel content" in text and not upload_visible:
                return
            if "Studio" in text and not upload_visible and not dialogs:
                return
            await asyncio.sleep(1)
        raise TimeoutError("Upload dialog did not close.")

    async def click_text(self, text, contains=False, prefer_bottom=False, timeout=10, required=True):
        deadline = time.time() + timeout
        last_candidates = []
        while time.time() < deadline:
            candidates = await self.eval_value(
                f"""
(() => {{
  const target = {json.dumps(text)};
  const contains = {json.dumps(bool(contains))};
  const out = [];
  const seen = new Set();
  function norm(value) {{
    return (value || '').trim().replace(/\\s+/g, ' ');
  }}
  function visible(el) {{
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && cs.display !== 'none' && cs.visibility !== 'hidden' &&
      r.x < innerWidth && r.y < innerHeight && r.x + r.width > 0 && r.y + r.height > 0;
  }}
  function walk(root) {{
    for (const el of root.querySelectorAll('*')) {{
      if (seen.has(el)) continue;
      seen.add(el);
      if (el.shadowRoot) walk(el.shadowRoot);
      if (!visible(el)) continue;
      const label = norm(el.innerText || el.textContent || el.getAttribute('aria-label') || '');
      if (!label) continue;
      const match = contains ? label.includes(target) : label === target;
      if (!match) continue;
      const r = el.getBoundingClientRect();
      out.push({{
        tag: el.tagName.toLowerCase(),
        role: el.getAttribute('role') || '',
        aria: el.getAttribute('aria-label') || '',
        text: label,
        x: r.x,
        y: r.y,
        width: r.width,
        height: r.height,
        area: r.width * r.height
      }});
    }}
  }}
  walk(document);
  return out;
}})()
""",
                10,
            ) or []
            last_candidates = candidates
            if candidates:
                if prefer_bottom:
                    chosen = max(candidates, key=lambda item: (item["y"], -item["area"]))
                else:
                    chosen = min(candidates, key=lambda item: (item["area"], item["y"]))
                await self.click(chosen["x"] + chosen["width"] / 2, chosen["y"] + chosen["height"] / 2)
                return True
            await asyncio.sleep(0.5)
        if required:
            raise RuntimeError(f"Visible text not found: {text}; candidates={last_candidates}")
        return False

    async def click_text_near(self, text, near_text, timeout=10, required=True):
        deadline = time.time() + timeout
        while time.time() < deadline:
            chosen = await self.eval_value(
                f"""
(() => {{
  const target = {json.dumps(text)};
  const nearText = {json.dumps(near_text)};
  const seen = new Set();
  const els = [];
  function norm(value) {{
    return (value || '').trim().replace(/\\s+/g, ' ');
  }}
  function visible(el) {{
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && cs.display !== 'none' && cs.visibility !== 'hidden' &&
      r.x < innerWidth && r.y < innerHeight && r.x + r.width > 0 && r.y + r.height > 0;
  }}
  function walk(root) {{
    for (const el of root.querySelectorAll('*')) {{
      if (seen.has(el)) continue;
      seen.add(el);
      if (el.shadowRoot) walk(el.shadowRoot);
      if (!visible(el)) continue;
      const r = el.getBoundingClientRect();
      els.push({{el, text: norm(el.innerText || el.textContent || el.getAttribute('aria-label') || ''), r}});
    }}
  }}
  walk(document);
  const near = els.filter(item => item.text === nearText || item.text.includes(nearText))
    .sort((a, b) => a.r.y - b.r.y)[0];
  if (!near) return null;
  const candidates = els
    .filter(item => item.text === target)
    .filter(item => item.r.y >= near.r.y - 20)
    .map(item => {{
      const dy = Math.abs(item.r.y - near.r.y);
      const dx = Math.abs(item.r.x - near.r.x);
      return {{x: item.r.x, y: item.r.y, width: item.r.width, height: item.r.height, score: dy * 3 + dx}};
    }})
    .sort((a, b) => a.score - b.score);
  return candidates[0] || null;
}})()
""",
                10,
            )
            if chosen:
                await self.click(chosen["x"] + chosen["width"] / 2, chosen["y"] + chosen["height"] / 2)
                return True
            await asyncio.sleep(0.5)
        if required:
            raise RuntimeError(f"Visible text not found near {near_text}: {text}")
        return False

    async def scroll_to_text(self, text, timeout=10):
        deadline = time.time() + timeout
        while time.time() < deadline:
            ok = await self.eval_value(
                f"""
(() => {{
  const target = {json.dumps(text)};
  const seen = new Set();
  function norm(value) {{
    return (value || '').trim().replace(/\\s+/g, ' ');
  }}
  function walk(root) {{
    for (const el of root.querySelectorAll('*')) {{
      if (seen.has(el)) continue;
      seen.add(el);
      if (el.shadowRoot) walk(el.shadowRoot);
      const label = norm(el.innerText || el.textContent || '');
      if (label === target || label.includes(target)) {{
        el.scrollIntoView({{block: 'center', inline: 'nearest'}});
        return true;
      }}
    }}
    return false;
  }}
  return walk(document);
}})()
""",
                10,
            )
            if ok:
                await asyncio.sleep(0.7)
                return True
            await asyncio.sleep(0.5)
        return False

    async def wait_for_upload_progress_done(self, timeout=900):
        deadline = time.time() + timeout
        while time.time() < deadline:
            text = await self.page_text()
            if "Upload complete" in text or "Processing will begin shortly" in text or "Checks complete" in text:
                return
            if "Processing" in text and "Upload" not in text:
                return
            await asyncio.sleep(3)


def load_json(path):
    with pathlib.Path(path).open("r", encoding="utf-8") as fh:
        return json.load(fh)


def save_json(path, value):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(value, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    tmp.replace(path)


def load_state(path):
    path = pathlib.Path(path)
    if not path.exists():
        return {"items": {}}
    return load_json(path)


def has_completed_items(state):
    return any(item.get("status") == "completed" for item in state.get("items", {}).values())


def manifest_key(item):
    return f"{int(item['upload_order']):03d}-{int(item['source_track_number']):03d}"


def yt_date(dt):
    return f"{MONTHS[dt.month - 1]} {dt.day}, {dt.year}"


def yt_time(dt):
    hour = dt.hour % 12 or 12
    minute = f"{dt.minute:02d}"
    suffix = "AM" if dt.hour < 12 else "PM"
    return f"{hour}:{minute} {suffix}"


def schedule_time(base_dt, item):
    return base_dt + timedelta(hours=int(item.get("schedule_offset_hours", 0)))


def parse_base_time(value, timezone):
    tz = ZoneInfo(timezone)
    if value:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=tz)
        return parsed.astimezone(tz)
    now = datetime.now(tz)
    return now.replace(second=0, microsecond=0)


def video_id_from_link(link):
    if not link:
        return None
    if "youtu.be/" in link:
        return link.rsplit("/", 1)[-1].split("?", 1)[0]
    if "watch?v=" in link:
        return link.split("watch?v=", 1)[1].split("&", 1)[0]
    return None


def get_pages(port):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=5) as resp:
        return json.load(resp)


async def connect(port, target_id=None):
    pages = get_pages(port)
    target = None
    if target_id:
        target = next((p for p in pages if p.get("id") == target_id), None)
    if target is None:
        target = next((p for p in pages if "studio.youtube.com" in p.get("url", "")), None)
    if target is None:
        target = next((p for p in pages if "accounts.google.com" in p.get("url", "")), None)
    if target is None:
        target = next((p for p in pages if p.get("type") == "page"), None)
    if target is None:
        raise RuntimeError(f"No browser page targets found on CDP port {port}.")
    ws = await websockets.connect(target["webSocketDebuggerUrl"], max_size=None)
    cdp = Cdp(ws)
    await cdp.send("Page.enable", timeout=10)
    await cdp.send("Runtime.enable", timeout=10)
    return cdp


async def navigate_to_studio(cdp):
    await cdp.send("Page.bringToFront")
    await cdp.send("Page.navigate", {"url": DEFAULT_STUDIO_URL}, timeout=10)
    await asyncio.sleep(3)
    await cdp.assert_not_login_blocked()
    await cdp.wait_for_text(["Studio", "Channel content"], timeout=60)


async def open_upload_dialog(cdp):
    await cdp.assert_not_login_blocked()
    text = await cdp.page_text()
    if "Drag and drop video files to upload" in text:
        return
    if not await cdp.click_text("Create", timeout=8, required=False):
        await cdp.click(1275, 78, wait=0.8)
    if not await cdp.click_text("Upload videos", timeout=8, required=False):
        await cdp.click(1210, 145, wait=1.5)
    await cdp.wait_for_text("Drag and drop video files to upload", timeout=45)


async def drop_video(cdp, video_path):
    viewport = await cdp.eval_value("({w: innerWidth, h: innerHeight})", timeout=10)
    data = {"items": [], "files": [str(video_path)], "dragOperationsMask": 1}
    x = viewport["w"] / 2
    y = viewport["h"] * 0.45
    for event_type in ("dragEnter", "dragOver", "drop"):
        await cdp.send("Input.dispatchDragEvent", {"type": event_type, "x": x, "y": y, "data": data}, timeout=20)
        await asyncio.sleep(0.8)
    await cdp.wait_for_text("Title (required)", timeout=90)


async def set_metadata(cdp, title, description, thumbnail_path):
    result = await cdp.eval_value(
        f"""
(() => {{
  const title = {json.dumps(title)};
  const desc = {json.dumps(description)};
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
  const boxes = [...document.querySelectorAll('#textbox')]
    .filter(el => {{
      const r = el.getBoundingClientRect();
      const cs = getComputedStyle(el);
      return r.width > 0 && r.height > 0 && cs.display !== 'none' && cs.visibility !== 'hidden';
    }});
  if (boxes.length < 2) return {{ok: false, count: boxes.length}};
  setBox(boxes[0], title);
  setBox(boxes[1], desc);
  return {{ok: true, count: boxes.length, values: boxes.slice(0, 2).map(el => (el.innerText || '').slice(0, 120))}};
}})()
""",
        timeout=20,
    )
    if not result or not result.get("ok"):
        raise RuntimeError(f"Title/description boxes not found: {result}")

    if thumbnail_path:
        result = await cdp.send(
            "Runtime.evaluate",
            {"expression": "document.querySelector('input[type=file][accept*=image]')", "returnByValue": False},
            timeout=10,
        )
        object_id = result.get("result", {}).get("objectId")
        if not object_id:
            raise RuntimeError("Thumbnail file input not found.")
        await cdp.send("DOM.setFileInputFiles", {"objectId": object_id, "files": [str(thumbnail_path)]}, timeout=30)
        await asyncio.sleep(3)


async def set_tags(cdp, tags):
    tags = [tag for tag in tags if tag]
    if not tags:
        return False

    await cdp.click_text("Show more", contains=True, timeout=6, required=False)
    await cdp.scroll_to_text("Tags", timeout=10)
    tag_text = ", ".join(tags)
    rect = await cdp.eval_value(
        f"""
(() => {{
  const seen = new Set();
  const els = [];
  function norm(value) {{
    return (value || '').trim().replace(/\\s+/g, ' ');
  }}
  function visible(el) {{
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && cs.display !== 'none' && cs.visibility !== 'hidden' &&
      r.x < innerWidth && r.y < innerHeight && r.x + r.width > 0 && r.y + r.height > 0;
  }}
  function walk(root) {{
    for (const el of root.querySelectorAll('*')) {{
      if (seen.has(el)) continue;
      seen.add(el);
      if (el.shadowRoot) walk(el.shadowRoot);
      if (!visible(el)) continue;
      const r = el.getBoundingClientRect();
      els.push({{el, text: norm(el.innerText || el.textContent || el.getAttribute('aria-label') || ''), r}});
    }}
  }}
  walk(document);
  const labels = els
    .filter(item => item.text === 'Tags' || item.text.includes('Tags can be useful'))
    .sort((a, b) => a.r.y - b.r.y);
  const label = labels[0];
  if (!label) return null;
  const inputs = els
    .filter(item => {{
      const tag = item.el.tagName.toLowerCase();
      const editable = item.el.isContentEditable || item.el.getAttribute('contenteditable') === 'true';
      const textbox = item.el.id === 'textbox';
      return tag === 'input' || tag === 'textarea' || editable || textbox;
    }})
    .filter(item => item.r.y >= label.r.y - 10 && item.r.y <= label.r.y + 280 && item.r.width > 80)
    .sort((a, b) => a.r.y - b.r.y || a.r.x - b.r.x);
  const target = inputs[0];
  if (!target) return null;
  return {{x: target.r.x, y: target.r.y, width: target.r.width, height: target.r.height}};
}})()
""",
        timeout=20,
    )
    if not rect:
        return False
    await cdp.click(rect["x"] + rect["width"] / 2, rect["y"] + rect["height"] / 2, wait=0.4)
    await cdp.key_combo("Control", "A", wait=0.1)
    await cdp.insert_text(tag_text, wait=0.3)
    await cdp.key_combo("Enter", wait=1.0)
    text = await cdp.page_text()
    return any(tag in text for tag in tags[:4])


async def add_to_playlist(cdp, playlist_title):
    if not playlist_title:
        return False
    await cdp.scroll_to_text("Playlists", timeout=8)
    clicked = await cdp.click_text_near("Select", "Playlists", timeout=8, required=False)
    if not clicked:
        return False
    await asyncio.sleep(1.5)
    text = await cdp.page_text()
    if playlist_title not in text:
        # The selector sometimes opens below the fold with a search box.
        await cdp.click_text("Search playlists", contains=True, timeout=3, required=False)
        await cdp.insert_text(playlist_title)
        await asyncio.sleep(1)
    if not await cdp.click_text(playlist_title, contains=True, timeout=10, required=False):
        await cdp.click_text("Cancel", timeout=3, required=False)
        return False
    await asyncio.sleep(0.6)
    await cdp.click_text("Done", prefer_bottom=True, timeout=10, required=False)
    await asyncio.sleep(1)
    return True


async def get_monetization_value(cdp):
    return await cdp.eval_value(
        r"""
(() => {
  const el = document.querySelector('#m10n-container') || document.querySelector('ytcp-video-monetization');
  return (el?.innerText || el?.textContent || '').trim();
})()
""",
        timeout=10,
    ) or ""


async def set_monetization_on(cdp):
    await cdp.wait_for_text("Monetization", timeout=60)
    for _ in range(4):
        if "On" in await get_monetization_value(cdp):
            return
        rect = await cdp.eval_value(
            r"""
(() => {
  const el = document.querySelector('#m10n-container') || document.querySelector('ytcp-video-monetization');
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return {x: r.x, y: r.y, width: r.width, height: r.height};
})()
""",
            timeout=10,
        )
        if not rect:
            raise RuntimeError("Monetization field not found.")
        await cdp.click(rect["x"] + rect["width"] / 2, rect["y"] + min(rect["height"] - 20, 44), wait=0.8)
        await cdp.click_text("On", timeout=8, required=False)
        await asyncio.sleep(0.4)
        await cdp.click_text("Done", prefer_bottom=True, timeout=8, required=False)
        await asyncio.sleep(2)
        if "On" in await get_monetization_value(cdp):
            return
    raise RuntimeError("Could not set monetization to On.")


async def complete_self_certification(cdp):
    text = await cdp.page_text()
    if "Tell us what's in your video" not in text and "Ad suitability" not in text:
        return False
    await cdp.click_text("Dismiss", timeout=4, required=False)
    found = False
    for _ in range(10):
        text = await cdp.page_text()
        if "None of the above" in text:
            found = await cdp.click_text("None of the above", contains=True, timeout=4, required=False)
            break
        await cdp.send("Input.dispatchMouseEvent", {"type": "mouseWheel", "x": 900, "y": 650, "deltaY": 900}, timeout=10)
        await asyncio.sleep(0.5)
    if not found:
        raise RuntimeError("Could not find the self-certification 'None of the above' option.")
    await asyncio.sleep(1)
    await cdp.click_text("Submit", prefer_bottom=True, timeout=10)
    await asyncio.sleep(2)
    return True


async def next_from_step(cdp, expected_text=None, timeout=90):
    await cdp.click_text("Next", prefer_bottom=True, timeout=20)
    if expected_text:
        await cdp.wait_for_text(expected_text, timeout=timeout)


async def extract_video_link(cdp):
    links = await cdp.eval_value(
        r"""
(() => {
  const out = [];
  const seen = new Set();
  function walk(root) {
    for (const el of root.querySelectorAll('a')) {
      if (!seen.has(el)) {
        seen.add(el);
        const href = el.href || '';
        if (href.includes('youtu.be/') || href.includes('youtube.com/watch')) out.push(href);
      }
    }
    for (const el of root.querySelectorAll('*')) {
      if (el.shadowRoot) walk(el.shadowRoot);
    }
  }
  walk(document);
  return out;
})()
""",
        timeout=10,
    ) or []
    return links[0] if links else None


async def choose_public_now(cdp):
    await cdp.wait_for_text("Save or publish", timeout=90)
    await cdp.click_text("Public", timeout=10, required=False)
    await asyncio.sleep(1)
    link = await extract_video_link(cdp)
    if not await cdp.click_text("Publish", prefer_bottom=True, timeout=8, required=False):
        await cdp.click_text("Save", prefer_bottom=True, timeout=8)
    await cdp.wait_until_upload_dialog_closed(timeout=240)
    return link


async def set_schedule_inputs(cdp, date_text, time_text):
    result = await cdp.eval_value(
        f"""
(() => {{
  const dateValue = {json.dumps(date_text)};
  const timeValue = {json.dumps(time_text)};
  const seen = new Set();
  const els = [];
  function norm(value) {{
    return (value || '').trim().replace(/\\s+/g, ' ');
  }}
  function visible(el) {{
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && cs.display !== 'none' && cs.visibility !== 'hidden' &&
      r.x < innerWidth && r.y < innerHeight && r.x + r.width > 0 && r.y + r.height > 0;
  }}
  function walk(root) {{
    for (const el of root.querySelectorAll('*')) {{
      if (seen.has(el)) continue;
      seen.add(el);
      if (el.shadowRoot) walk(el.shadowRoot);
      if (!visible(el)) continue;
      const r = el.getBoundingClientRect();
      els.push({{el, text: norm(el.innerText || el.textContent || el.getAttribute('aria-label') || ''), r}});
    }}
  }}
  walk(document);
  const heading = els.filter(item => item.text.includes('Schedule as public') || item.text === 'Schedule')
    .sort((a, b) => b.r.y - a.r.y)[0];
  const minY = heading ? heading.r.y - 10 : 0;
  const inputs = els
    .map(item => item.el)
    .filter(el => el.tagName.toLowerCase() === 'input')
    .map(el => {{ const r = el.getBoundingClientRect(); return {{el, r}}; }})
    .filter(item => item.r.y >= minY && item.r.y < innerHeight - 60 && item.r.width > 60)
    .sort((a, b) => a.r.y - b.r.y || a.r.x - b.r.x);
  if (inputs.length < 2) return {{ok: false, count: inputs.length, minY}};
  function setInput(el, value) {{
    el.focus();
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
    setter.call(el, value);
    el.dispatchEvent(new InputEvent('input', {{bubbles: true, inputType: 'insertText', data: value}}));
    el.dispatchEvent(new Event('change', {{bubbles: true}}));
    el.blur();
  }}
  setInput(inputs[0].el, dateValue);
  setInput(inputs[1].el, timeValue);
  return {{ok: true, count: inputs.length, values: inputs.slice(0, 2).map(item => item.el.value)}};
}})()
""",
        timeout=20,
    )
    if not result or not result.get("ok"):
        raise RuntimeError(f"Could not set schedule date/time inputs: {result}")
    await asyncio.sleep(1)


async def choose_scheduled(cdp, publish_at):
    await cdp.wait_for_text("Save or publish", timeout=90)
    await cdp.click_text("Schedule", timeout=10, required=False)
    await asyncio.sleep(1)
    date_text = yt_date(publish_at)
    time_text = yt_time(publish_at)
    await set_schedule_inputs(cdp, date_text, time_text)
    link = await extract_video_link(cdp)
    await cdp.click_text("Schedule", prefer_bottom=True, timeout=20)
    await cdp.wait_until_upload_dialog_closed(timeout=240)
    return link


async def upload_one(cdp, item, publish_at, args):
    video_path = pathlib.Path(item["file"])
    thumbnail_path = pathlib.Path(item.get("thumbnail", ""))
    title = display_title(item, args.title_prefix)
    tags = item_tags(item, extra_tags=args.extra_tag, include_defaults=not args.no_default_tags)
    if not video_path.exists():
        raise FileNotFoundError(video_path)
    if thumbnail_path and not thumbnail_path.exists():
        raise FileNotFoundError(thumbnail_path)

    print(f"Opening upload dialog: {title}", flush=True)
    await open_upload_dialog(cdp)
    if args.screenshot_dir:
        await cdp.screenshot(pathlib.Path(args.screenshot_dir) / f"{manifest_key(item)}-upload-dialog.png")

    print(f"Dropping file: {video_path.name}", flush=True)
    await drop_video(cdp, video_path)
    print("Setting title, description, thumbnail", flush=True)
    await set_metadata(cdp, title, item["description"], thumbnail_path)

    tags_set = False
    if not args.no_tags:
        print(f"Setting tags: {len(tags)} tags, {tags_cost(tags)}/{YOUTUBE_TAG_LIMIT} chars", flush=True)
        tags_set = await set_tags(cdp, tags)
        print(f"Tags set: {tags_set}", flush=True)
        if not tags_set and not args.allow_missing_tags:
            raise RuntimeError("Could not confirm tags were set.")

    playlist_added = await add_to_playlist(cdp, args.playlist_title)
    print(f"Playlist selected: {playlist_added}", flush=True)
    if not playlist_added and not args.allow_missing_playlist:
        raise RuntimeError(f"Could not confirm playlist selection: {args.playlist_title}")

    print("Moving to monetization", flush=True)
    await next_from_step(cdp, "Monetization", timeout=90)
    print("Setting monetization on", flush=True)
    await set_monetization_on(cdp)
    monetization_text = await get_monetization_value(cdp)
    monetization_on = "On" in monetization_text
    if not monetization_on and not args.allow_monetization_off:
        raise RuntimeError(f"Could not confirm monetization is On: {monetization_text!r}")
    await complete_self_certification(cdp)

    print("Moving through video elements", flush=True)
    await next_from_step(cdp, "Video elements", timeout=90)
    await next_from_step(cdp, "Checks", timeout=90)
    await next_from_step(cdp, "Save or publish", timeout=240)

    await cdp.wait_for_upload_progress_done(timeout=900)
    if int(item["upload_order"]) == 1:
        print("Publishing immediately", flush=True)
        link = await choose_public_now(cdp)
        visibility = "public"
    else:
        print(f"Scheduling for {publish_at.isoformat()} ({yt_date(publish_at)} {yt_time(publish_at)})", flush=True)
        link = await choose_scheduled(cdp, publish_at)
        visibility = "scheduled"
    return {
        "title": title,
        "tags": tags,
        "tags_set": tags_set,
        "source_track_number": item["source_track_number"],
        "upload_order": item["upload_order"],
        "visibility": visibility,
        "scheduled_for": None if visibility == "public" else publish_at.isoformat(),
        "video_link": link,
        "video_id": video_id_from_link(link),
        "playlist_selected": playlist_added,
        "monetization_on": monetization_on,
        "completed_at": datetime.now(ZoneInfo("America/Toronto")).isoformat(),
    }


async def run(args):
    manifest = load_json(args.manifest)
    state = load_state(args.state)
    timezone = args.timezone
    state_has_resume_items = has_completed_items(state)
    if args.schedule_base:
        base_dt = parse_base_time(args.schedule_base, timezone)
    elif state.get("schedule_base") and state_has_resume_items:
        base_dt = parse_base_time(state["schedule_base"], timezone)
    else:
        base_dt = parse_base_time(None, timezone)

    items = [
        item
        for item in manifest["items"]
        if int(item["upload_order"]) >= args.start_order and int(item["source_track_number"]) >= args.min_track
    ]
    if args.only_track:
        wanted = {int(value) for value in args.only_track.split(",")}
        items = [item for item in items if int(item["source_track_number"]) in wanted]
    if args.limit:
        items = items[: args.limit]

    if args.dry_run:
        for item in items:
            publish_at = schedule_time(base_dt, item)
            title = display_title(item, args.title_prefix)
            tags = item_tags(item, extra_tags=args.extra_tag, include_defaults=not args.no_default_tags)
            print(
                f"{manifest_key(item)}\t{title}\t"
                f"{'now' if int(item['upload_order']) == 1 else publish_at.isoformat()}\t"
                f"tags={len(tags)}/{tags_cost(tags)}"
            )
        return

    cdp = await connect(args.port, args.target_id)
    try:
        await navigate_to_studio(cdp)
        state.setdefault("schedule_base", base_dt.isoformat())
        state.setdefault("timezone", timezone)
        state.setdefault("playlist_title", args.playlist_title)
        save_json(args.state, state)
        for item in items:
            key = manifest_key(item)
            title = display_title(item, args.title_prefix)
            if not args.force and state["items"].get(key, {}).get("status") == "completed":
                print(f"Skipping completed: {key} {title}", flush=True)
                continue
            publish_at = schedule_time(base_dt, item)
            record = {"status": "started", "title": title, "started_at": datetime.now().isoformat()}
            state["items"][key] = record
            save_json(args.state, state)
            try:
                result = await upload_one(cdp, item, publish_at, args)
                record.update({"status": "completed", **result})
                state["items"][key] = record
                save_json(args.state, state)
                print(f"Completed: {key} {title}", flush=True)
            except Exception as exc:
                record.update({"status": "failed", "error": str(exc), "failed_at": datetime.now().isoformat()})
                state["items"][key] = record
                save_json(args.state, state)
                if args.screenshot_dir:
                    await cdp.screenshot(pathlib.Path(args.screenshot_dir) / f"{key}-failure.png")
                raise
    finally:
        await cdp.ws.close()


def main():
    parser = argparse.ArgumentParser(description="Upload and schedule videos from a YouTube Studio manifest.")
    parser.add_argument("--manifest", type=pathlib.Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--state", type=pathlib.Path, default=DEFAULT_STATE)
    parser.add_argument("--port", type=int, required=True, help="Chrome remote debugging port.")
    parser.add_argument("--target-id", default=None)
    parser.add_argument("--playlist-title", default=DEFAULT_PLAYLIST_TITLE)
    parser.add_argument("--timezone", default="America/Toronto")
    parser.add_argument("--schedule-base", default=None, help="ISO datetime for upload_order 1; defaults to now.")
    parser.add_argument("--start-order", type=int, default=1)
    parser.add_argument("--min-track", type=int, default=0)
    parser.add_argument("--only-track", default=None, help="Comma-separated source track numbers.")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--title-prefix", default=TITLE_PREFIX)
    parser.add_argument("--extra-tag", action="append", default=[])
    parser.add_argument("--no-default-tags", action="store_true")
    parser.add_argument("--no-tags", action="store_true")
    parser.add_argument("--allow-missing-tags", action="store_true")
    parser.add_argument("--allow-missing-playlist", action="store_true")
    parser.add_argument("--allow-monetization-off", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--screenshot-dir", type=pathlib.Path, default=ROOT / "upload-screenshots")
    args = parser.parse_args()

    try:
        asyncio.run(run(args))
    except UserActionRequired as exc:
        print(f"USER_ACTION_REQUIRED: {exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
