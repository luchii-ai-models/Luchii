"""Frasberg engine implementations (diffusers). One model is resident at a time.

frasberg-motion-fast   LTX-Video 0.9.7 distilled + spatial latent upscaler (2-stage, guidance-distilled)
frasberg-motion-pro    Wan 2.2 TI2V-5B (text- and image-to-video, 720p/24fps)
frasberg-motion-ultra  HunyuanVideo 13B (T2V) / HunyuanVideo-I2V
frasberg-image         FLUX.1-schnell (4 steps)
frasberg-image-xl      Juggernaut XL v9 (SDXL, fp16, DPM++ 2M Karras 30 steps) - fits a free 16GB T4
frasberg-motion-free   LTX-Video 2B (T2V + I2V) - fits a free 16GB T4 (Kaggle / Colab)
frasberg-dev-test      procedural test pattern (CPU, protocol self-test only)
"""
import gc
import io
import os
import tempfile
import threading

MIN_VRAM = {"frasberg-motion-fast": 24, "frasberg-motion-pro": 24, "frasberg-motion-ultra": 80,
            "frasberg-image": 16, "frasberg-image-xl": 10, "frasberg-motion-free": 14, "frasberg-dev-test": 0}

REPOS = {
    "frasberg-motion-fast": ("Lightricks/LTX-Video-0.9.7-distilled", "Lightricks/ltxv-spatial-upscaler-0.9.7"),
    "frasberg-motion-pro": ("Wan-AI/Wan2.2-TI2V-5B-Diffusers",),
    "frasberg-motion-ultra": ("hunyuanvideo-community/HunyuanVideo", "hunyuanvideo-community/HunyuanVideo-I2V"),
    "frasberg-image": ("black-forest-labs/FLUX.1-schnell",),
    "frasberg-image-xl": ("RunDiffusion/Juggernaut-XL-v9",),
    "frasberg-motion-free": ("Lightricks/LTX-Video",),
}
XL_VAE = "madebyollin/sdxl-vae-fp16-fix"   # the stock SDXL VAE overflows (black images) in fp16
REPO_VARIANT = {"frasberg-image-xl": "fp16"}
XL_NEGATIVE = ("lowres, worst quality, low quality, blurry, jpeg artifacts, deformed, disfigured, bad anatomy, extra limbs, "
               "extra fingers, mutated hands, cropped, watermark, signature, text, logo")
NEGATIVE = "worst quality, inconsistent motion, blurry, jittery, distorted, watermark, text, deformed"

_lock = threading.RLock()
_loaded = {"model": None, "pipes": None}


def gpu_info():
    try:
        import torch
        if torch.cuda.is_available():
            p = torch.cuda.get_device_properties(0)
            return p.name, round(p.total_memory / 1024 ** 3, 1)
    except Exception:  # noqa: BLE001
        pass
    return None, 0.0


def loaded_model():
    return _loaded["model"]


def _dtype():
    """bf16 on Ampere+; T4/V100 (sm < 8) have no native bf16, so they run fp16 unless FRASBERG_DTYPE says otherwise."""
    import torch
    want = os.environ.get("FRASBERG_DTYPE", "auto").lower()
    if want in ("bf16", "bfloat16"):
        return torch.bfloat16
    if want in ("fp16", "float16", "half"):
        return torch.float16
    if torch.cuda.is_available() and torch.cuda.get_device_capability(0)[0] < 8:
        return torch.float16
    return torch.bfloat16


def preload(model):
    """Load an engine before the first job arrives (warm start), so the first render skips the load."""
    with _lock:
        _pipes(model)


def unload():
    with _lock:
        _loaded.update(model=None, pipes=None)
        gc.collect()
        try:
            import torch
            torch.cuda.empty_cache()
        except Exception:  # noqa: BLE001
            pass


def _place(pipe, model):
    """Fully on GPU when VRAM allows, otherwise model-level CPU offload."""
    vram = gpu_info()[1]
    if vram >= MIN_VRAM[model] * 1.5:
        return pipe.to("cuda")
    pipe.enable_model_cpu_offload()
    return pipe


def _load(model):
    import torch
    bf16 = _dtype()
    if model == "frasberg-motion-fast":
        from diffusers import LTXConditionPipeline, LTXLatentUpsamplePipeline
        base = LTXConditionPipeline.from_pretrained(REPOS[model][0], torch_dtype=bf16)
        up = LTXLatentUpsamplePipeline.from_pretrained(REPOS[model][1], vae=base.vae, torch_dtype=bf16)
        base.vae.enable_tiling()
        return {"base": _place(base, model), "up": _place(up, model)}
    if model == "frasberg-motion-pro":
        from diffusers import AutoencoderKLWan, WanPipeline
        vae = AutoencoderKLWan.from_pretrained(REPOS[model][0], subfolder="vae", torch_dtype=torch.float32)
        return {"pipe": _place(WanPipeline.from_pretrained(REPOS[model][0], vae=vae, torch_dtype=bf16), model)}
    if model == "frasberg-motion-ultra":
        from diffusers import HunyuanVideoPipeline
        t2v = HunyuanVideoPipeline.from_pretrained(REPOS[model][0], torch_dtype=bf16)
        t2v.vae.enable_tiling()
        return {"t2v": _place(t2v, model), "i2v": None}
    if model == "frasberg-image":
        from diffusers import FluxPipeline
        return {"pipe": _place(FluxPipeline.from_pretrained(REPOS[model][0], torch_dtype=bf16), model)}
    if model == "frasberg-image-xl":
        from diffusers import AutoencoderKL, DPMSolverMultistepScheduler, StableDiffusionXLPipeline
        vae = AutoencoderKL.from_pretrained(XL_VAE, torch_dtype=torch.float16)
        pipe = StableDiffusionXLPipeline.from_pretrained(REPOS[model][0], vae=vae, torch_dtype=torch.float16, variant="fp16")
        pipe.scheduler = DPMSolverMultistepScheduler.from_config(pipe.scheduler.config, use_karras_sigmas=True,
                                                                 algorithm_type="dpmsolver++")
        pipe.enable_vae_slicing()
        return {"pipe": _place(pipe, model)}
    if model == "frasberg-motion-free":
        from diffusers import LTXImageToVideoPipeline, LTXPipeline
        t2v = LTXPipeline.from_pretrained(REPOS[model][0], torch_dtype=bf16)
        t2v.vae.enable_tiling()
        # Both pipelines share the same modules; CPU offload (16GB T4) is attached to whichever one runs next.
        return {"t2v": t2v, "i2v": LTXImageToVideoPipeline(**t2v.components), "active": None}
    if model == "frasberg-dev-test":
        return {}
    raise ValueError(f"Unknown Frasberg engine {model}")


def _pipes(model):
    if _loaded["model"] != model:
        unload()
        _loaded.update(model=model, pipes=_load(model))
    return _loaded["pipes"]


def _size(aspect, long_side, short_side, mult):
    h, w = {"16:9": (short_side, long_side), "9:16": (long_side, short_side)}.get(aspect, (short_side, short_side))
    return h - h % mult, w - w % mult


def _frames(duration, fps, step, cap):
    n = min(int(duration * fps), cap)
    return (n // step) * step + 1


def _gen(seed):
    import torch
    return torch.Generator("cpu").manual_seed(int(seed)) if seed is not None else None


def _cb(progress, total, offset=0.0, span=1.0):
    def cb(pipe, step, t, kw):
        progress(offset + span * (step + 1) / max(total, 1))
        return kw
    return cb


def _mp4(frames, fps):
    from diffusers.utils import export_to_video
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        path = f.name
    try:
        export_to_video(frames, path, fps=fps)
        with open(path, "rb") as fh:
            return fh.read()
    finally:
        os.unlink(path)


def _fit(image, h, w):
    from PIL import ImageOps
    return ImageOps.fit(image, (w, h)) if image is not None else None


def render(model, *, prompt, negative_prompt=None, duration=5, aspect_ratio="16:9", seed=None, image=None,
           progress=lambda p: None):
    with _lock:
        pipes = _pipes(model)
        neg = negative_prompt or NEGATIVE
        if model == "frasberg-motion-fast":
            return _ltx(pipes, prompt, neg, duration, aspect_ratio, seed, image, progress), "video/mp4"
        if model == "frasberg-motion-pro":
            h, w = _size(aspect_ratio, 1280, 704, 32)
            n = _frames(duration, 24, 4, 120)
            p = pipes["pipe"]
            kw = {"image": _fit(image, h, w)} if image is not None else {}
            frames = p(prompt=prompt, negative_prompt=neg, height=h, width=w, num_frames=n, num_inference_steps=40,
                       guidance_scale=5.0, generator=_gen(seed), callback_on_step_end=_cb(progress, 40), **kw).frames[0]
            return _mp4(frames, 24), "video/mp4"
        if model == "frasberg-motion-ultra":
            h, w = _size(aspect_ratio, 1280, 720, 16)
            n = _frames(duration, 24, 4, 128)
            if image is not None:
                if pipes["i2v"] is None:
                    import torch
                    from diffusers import HunyuanVideoImageToVideoPipeline
                    pipes["t2v"] = None
                    gc.collect()
                    torch.cuda.empty_cache()
                    i2v = HunyuanVideoImageToVideoPipeline.from_pretrained(REPOS[model][1], torch_dtype=torch.bfloat16)
                    i2v.vae.enable_tiling()
                    pipes["i2v"] = _place(i2v, model)
                frames = pipes["i2v"](image=_fit(image, h, w), prompt=prompt, height=h, width=w, num_frames=n,
                                      num_inference_steps=50, generator=_gen(seed),
                                      callback_on_step_end=_cb(progress, 50)).frames[0]
            else:
                if pipes["t2v"] is None:
                    unload()
                    pipes = _pipes(model)
                frames = pipes["t2v"](prompt=prompt, height=h, width=w, num_frames=n, num_inference_steps=50,
                                      guidance_scale=6.0, generator=_gen(seed),
                                      callback_on_step_end=_cb(progress, 50)).frames[0]
            return _mp4(frames, 24), "video/mp4"
        if model == "frasberg-image":
            h, w = _size(aspect_ratio, 1344, 768, 64) if aspect_ratio in ("16:9", "9:16") else (1024, 1024)
            img = pipes["pipe"](prompt=prompt, height=h, width=w, num_inference_steps=4, guidance_scale=0.0,
                                max_sequence_length=256, generator=_gen(seed),
                                callback_on_step_end=_cb(progress, 4)).images[0]
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue(), "image/png"
        if model == "frasberg-image-xl":
            h, w = {"16:9": (768, 1344), "9:16": (1344, 768)}.get(aspect_ratio, (1024, 1024))
            img = pipes["pipe"](prompt=prompt, negative_prompt=negative_prompt or XL_NEGATIVE, height=h, width=w,
                                num_inference_steps=30, guidance_scale=6.0, generator=_gen(seed),
                                callback_on_step_end=_cb(progress, 30)).images[0]
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue(), "image/png"
        if model == "frasberg-motion-free":
            return _ltx_free(pipes, prompt, neg, duration, aspect_ratio, seed, image, progress), "video/mp4"
        if model == "frasberg-dev-test":
            return _dev_test(prompt, duration, image, progress), "video/mp4"
    raise ValueError(f"Unknown Frasberg engine {model}")


FREE_SEGMENT_MAX = 97   # frames per LTX pass that fit a 16GB T4 (4s at 24fps)
SEAM_TRIM = 8           # LTX softens the last frames of a pass; the next part starts before them
SEAM_BLEND = 24         # frames over which the colour match at the seam fades out


def _ltx_pass(pipes, key, h, w, n, prompt, neg, seed, image, progress, offset, span):
    if pipes["active"] != key:
        import torch
        if torch.cuda.is_available():
            pipes[key].enable_model_cpu_offload()
        pipes["active"] = key
    extra = {"image": _fit(image, h, w)} if image is not None else {}
    return pipes[key](prompt=prompt, negative_prompt=neg, height=h, width=w, num_frames=n, num_inference_steps=30,
                      decode_timestep=0.03, decode_noise_scale=0.025, generator=_gen(seed),
                      callback_on_step_end=_cb(progress, 30, offset, span), **extra).frames[0]


def _seam_match(head, tail_ref):
    """Colour-match the start of the next part to the frame it continues from, fading back to its own look, so the
    stitch is invisible even when image-to-video drifts the grade a little."""
    import numpy as np
    ref = np.asarray(tail_ref, dtype=np.float32)
    first = np.asarray(head[0], dtype=np.float32)
    mu_r, sd_r = ref.reshape(-1, 3).mean(0), ref.reshape(-1, 3).std(0) + 1e-3
    mu_f, sd_f = first.reshape(-1, 3).mean(0), first.reshape(-1, 3).std(0) + 1e-3
    out = []
    for i, fr in enumerate(head):
        a = np.asarray(fr, dtype=np.float32)
        k = max(0.0, 1.0 - i / SEAM_BLEND)
        if k > 0:
            matched = (a - mu_f) / sd_f * sd_r + mu_r
            a = a * (1 - k) + matched * k
        out.append(np.clip(a, 0, 255).astype(np.uint8))
    return out


def _ltx_free(pipes, prompt, neg, duration, aspect, seed, image, progress):
    """Frasberg Motion Free. Up to 4s is one LTX pass; 6-8s clips are two passes stitched seamlessly: part B is
    image-to-video from a clean frame near the end of part A (same prompt), the duplicate frame is dropped and the
    colour is matched across the seam."""
    import numpy as np
    from PIL import Image
    h, w = _size(aspect, 704, 480, 32) if aspect in ("16:9", "9:16") else (512, 512)
    total = int(duration * 24)
    if total <= FREE_SEGMENT_MAX:
        n = _frames(duration, 24, 8, FREE_SEGMENT_MAX)
        frames = _ltx_pass(pipes, "i2v" if image is not None else "t2v", h, w, n, prompt, neg, seed, image, progress, 0, 1)
        return _mp4(frames, 24)
    # two parts of equal length; part A keeps SEAM_TRIM extra frames that are cut at the seam
    seg = min(FREE_SEGMENT_MAX, ((total // 2 + SEAM_TRIM) // 8) * 8 + 1)
    a = _ltx_pass(pipes, "i2v" if image is not None else "t2v", h, w, seg, prompt, neg, seed, image, progress, 0, 0.5)
    cut = len(a) - SEAM_TRIM
    seam = a[cut - 1]
    seam_img = seam if isinstance(seam, Image.Image) else Image.fromarray(np.asarray(seam))
    b = _ltx_pass(pipes, "i2v", h, w, seg, prompt, neg, None if seed is None else int(seed) + 1, seam_img,
                  progress, 0.5, 0.5)
    frames = list(a[:cut]) + [Image.fromarray(x) for x in _seam_match(b[1:], seam)]
    return _mp4(frames, 24)


def _ltx(pipes, prompt, neg, duration, aspect, seed, image, progress):
    """LTX 0.9.7 distilled recipe: low-res pass -> 2x latent upscale -> short refine pass."""
    base, up = pipes["base"], pipes["up"]
    eh, ew = _size(aspect, 1152, 640, 32)
    n = _frames(duration, 24, 8, 256)
    dh, dw = int(eh * 2 / 3), int(ew * 2 / 3)
    r = base.vae_spatial_compression_ratio
    dh, dw = dh - dh % r, dw - dw % r
    cond = {}
    if image is not None:
        from diffusers.pipelines.ltx.pipeline_ltx_condition import LTXVideoCondition
        cond = {"conditions": [LTXVideoCondition(image=_fit(image, dh, dw), frame_index=0)]}
    common = dict(prompt=prompt, negative_prompt=neg, num_frames=n, decode_timestep=0.05, decode_noise_scale=0.025,
                  image_cond_noise_scale=0.0, guidance_scale=1.0, guidance_rescale=0.7, **cond)
    latents = base(width=dw, height=dh, timesteps=[1000, 993, 987, 981, 975, 909, 725, 0.03], generator=_gen(seed),
                   output_type="latent", callback_on_step_end=_cb(progress, 8, 0.0, 0.6), **common).frames
    latents = up(latents=latents, adain_factor=1.0, output_type="latent").frames
    progress(0.7)
    frames = base(width=dw * 2, height=dh * 2, denoise_strength=0.999, timesteps=[1000, 909, 725, 421, 0],
                  latents=latents, generator=_gen(seed), output_type="pil",
                  callback_on_step_end=_cb(progress, 5, 0.7, 0.3), **common).frames[0]
    frames = [f.resize((ew, eh)) for f in frames]
    return _mp4(frames, 24)


def _dev_test(prompt, duration, image, progress):
    """Protocol self-test only: a moving test pattern. Never served for a product engine."""
    import numpy as np
    from PIL import Image, ImageDraw
    frames = []
    total = max(1, int(duration)) * 12
    base = image.resize((256, 256)) if image is not None else None
    for i in range(total):
        im = base.copy() if base is not None else Image.new("RGB", (256, 256), (5, 6, 10))
        d = ImageDraw.Draw(im)
        x = int(20 + 200 * i / total)
        d.ellipse([x, 110, x + 36, 146], fill=(0, 240, 255))
        d.text((8, 8), f"FRASBERG DEV TEST {i}", fill=(255, 255, 255))
        frames.append(np.asarray(im).astype("float32") / 255.0)
        progress((i + 1) / total)
    return _mp4(frames, 12)
