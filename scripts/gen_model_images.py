import base64
import io
import json
import sys
import time
import urllib.request
from pathlib import Path

from PIL import Image

sys.path.insert(0, "/app/scripts")
API = "http://localhost:8001/api"
OUT = Path("/app/frontend/public/models")
OUT.mkdir(parents=True, exist_ok=True)
from gen_model_prompts import PROMPTS  # noqa: E402


def call(path, body=None):
    req = urllib.request.Request(f"{API}{path}", data=json.dumps(body).encode() if body else None,
                                 headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=60))


def run(path, body):
    job = call(path, body)["job_id"]
    while True:
        time.sleep(8)
        d = call(f"/image-jobs/{job}")
        if d["status"] == "completed":
            return d["result"]["image_base64"]
        if d["status"] == "failed":
            raise RuntimeError(d.get("error"))


def save(name, data_url):
    img = Image.open(io.BytesIO(base64.b64decode(data_url.split(",", 1)[1]))).convert("RGB")
    img.thumbnail((1280, 1280), Image.LANCZOS)
    img.save(OUT / f"{name}.jpg", quality=88)
    print("saved", name, img.size, flush=True)


def as_b64(name):
    return "data:image/jpeg;base64," + base64.b64encode((OUT / f"{name}.jpg").read_bytes()).decode()


def main():
    for name, (prompt, model, style) in PROMPTS.items():
        if (OUT / f"{name}.jpg").exists():
            continue
        save(name, run("/generate/jobs", {"prompt": prompt, "model": model, "style": style, "aspect_ratio": "4:3", "quality": "full"}))
    if not (OUT / "luchii-painter-x.jpg").exists():
        save("luchii-painter-x", run("/edit/jobs", {"prompt": "same woman in a snowy winter forest, wearing a red wool coat",
                                                    "image_base64": as_b64("luchii-nova-muse")}))
    if not (OUT / "luchii-prime.jpg").exists():
        save("luchii-prime", run("/upscale/jobs", {"prompt": "Upscaled", "image_base64": as_b64("frasberg-titan-core")}))
    print("ALL DONE", flush=True)


if __name__ == "__main__":
    main()
