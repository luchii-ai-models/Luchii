"""Re-create every Models page image through the live job API, signed in as the platform admin.

Each image is a real generation saved in the admin's gallery; manifest.json records the proof (generation id,
engine, seed, time). Resumable: names already in the manifest are skipped.
"""
import base64
import io
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

from PIL import Image

sys.path.insert(0, "/app/scripts")
from gen_model_prompts import PROMPTS  # noqa: E402
from gen_model_samples_prompts import EXTRA  # noqa: E402

API = "http://localhost:8001/api"
OUT = Path("/app/frontend/public/models")
MANIFEST = OUT / "manifest.json"
EMAIL, PASSWORD = os.environ["ADMIN_EMAIL"], os.environ["ADMIN_PASSWORD"]
REMIX_SRC = {"luchii-painter-x": ["frasberg-apex-sphere", "luchii-cinematica"], "luchii-prime": ["luchii-nova-muse", "frasberg-ex-prime"]}
token = None


def call(path, body=None):
    headers = {"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})}
    req = urllib.request.Request(f"{API}{path}", data=json.dumps(body).encode() if body else None, headers=headers)
    return json.load(urllib.request.urlopen(req, timeout=60))


def run(path, body):
    job = call(path, body)["job_id"]
    while True:
        time.sleep(6)
        d = call(f"/image-jobs/{job}")
        if d["status"] == "completed":
            return d["result"]
        if d["status"] == "failed":
            raise RuntimeError(d.get("error"))


def as_b64(name):
    return "data:image/jpeg;base64," + base64.b64encode((OUT / f"{name}.jpg").read_bytes()).decode()


def save(name, result, manifest, prompt, model):
    img = Image.open(io.BytesIO(base64.b64decode(result["image_base64"].split(",", 1)[1]))).convert("RGB")
    img.thumbnail((1280, 1280), Image.LANCZOS)
    img.save(OUT / f"{name}.jpg", quality=90)
    manifest[name] = {"generation_id": result.get("id"), "engine": result.get("engine"), "model": result.get("model") or model,
                      "seed": result.get("seed"), "prompt": prompt, "account": EMAIL,
                      "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    MANIFEST.write_text(json.dumps(manifest, indent=1))
    print("saved", name, result.get("engine"), flush=True)


def tasks():
    for name, (prompt, model, style) in PROMPTS.items():
        yield name, "/generate/jobs", {"prompt": prompt, "model": model, "style": style, "aspect_ratio": "4:3", "quality": "full"}, None
    yield "luchii-painter-x", "/edit/jobs", {"prompt": "change the background to a snowy winter forest and give her a red wool coat"}, "luchii-nova-muse"
    yield "luchii-prime", "/upscale/jobs", {"prompt": "Upscaled"}, "frasberg-titan-core"
    for slug, items in EXTRA.items():
        for n, (prompt, model, style) in enumerate(items, start=2):
            if slug in REMIX_SRC:
                path = "/edit/jobs" if slug == "luchii-painter-x" else "/upscale/jobs"
                yield f"{slug}-{n}", path, {"prompt": prompt}, REMIX_SRC[slug][n - 2]
            else:
                yield f"{slug}-{n}", "/generate/jobs", {"prompt": prompt, "model": model, "style": style,
                                                         "aspect_ratio": "4:3", "quality": "full"}, None


def main():
    global token
    token = call("/auth/login", {"email": EMAIL, "password": PASSWORD})["token"]
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    for name, path, body, src in tasks():
        if name in manifest:
            continue
        if src:
            body = {**body, "image_base64": as_b64(src)}
        for attempt in range(3):
            try:
                token = call("/auth/login", {"email": EMAIL, "password": PASSWORD})["token"]
                save(name, run(path, body), manifest, body["prompt"], body.get("model"))
                break
            except Exception as e:  # noqa: BLE001
                print("retry", name, attempt, e, flush=True)
                time.sleep(30)
    print("ALL DONE", len(manifest), flush=True)


if __name__ == "__main__":
    main()
