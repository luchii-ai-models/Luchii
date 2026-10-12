import sys

sys.path.insert(0, "/app/scripts")
from gen_model_images import OUT, as_b64, run, save  # noqa: E402
from gen_model_samples_prompts import EXTRA  # noqa: E402

REMIX_SRC = {"luchii-painter-x": ["frasberg-apex-sphere", "luchii-cinematica"], "luchii-prime": ["luchii-nova-muse", "frasberg-ex-prime"]}

for slug, items in EXTRA.items():
    for n, (prompt, model, style) in enumerate(items, start=2):
        name = f"{slug}-{n}"
        if (OUT / f"{name}.jpg").exists():
            continue
        try:
            if slug in REMIX_SRC:
                src = as_b64(REMIX_SRC[slug][n - 2])
                path = "/edit/jobs" if slug == "luchii-painter-x" else "/upscale/jobs"
                save(name, run(path, {"prompt": prompt, "image_base64": src}))
            else:
                save(name, run("/generate/jobs", {"prompt": prompt, "model": model, "style": style,
                                                  "aspect_ratio": "4:3", "quality": "full"}))
        except Exception as e:  # noqa: BLE001
            print("fail", name, e, flush=True)
print("ALL DONE", flush=True)
