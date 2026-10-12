"""Luchii in-house engines: Piper (voice), faster-whisper (STT), SD-Turbo (images), Shap-E (3D), OpenVoice (voice conversion). CPU only."""
import base64
import io
import logging
import os
import re
import threading
import time
import wave
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger("luchii.local")
MODELS_DIR = Path(os.environ["LUCHII_MODELS_DIR"])
MODELS_DIR.mkdir(parents=True, exist_ok=True)
SCRATCH_MODELS_DIR = Path(os.environ["LUCHII_SCRATCH_MODELS_DIR"])
SCRATCH_MODELS_DIR.mkdir(parents=True, exist_ok=True)
OPENVOICE_REPO = "myshell-ai/OpenVoiceV2"
SHAPE_MODEL = "openai/shap-e"
SHAPE_STEPS = 10


def cpu_threads() -> int:
    try:
        quota, period = open("/sys/fs/cgroup/cpu.max").read().split()
        if quota != "max":
            return max(1, int(int(quota) / int(period)))
    except (OSError, ValueError):
        pass
    return max(1, (os.cpu_count() or 4) - 2)

PIPER_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main"
PIPER_VOICES = {
    "nova": "en_US-amy-medium", "alloy": "en_US-lessac-medium", "echo": "en_US-ryan-medium",
    "fable": "en_GB-alan-medium", "onyx": "en_US-joe-medium", "shimmer": "en_US-kristin-medium",
    "sage": "en_US-hfc_female-medium", "coral": "en_GB-jenny_dioco-medium", "ash": "en_US-hfc_male-medium",
}
IMAGE_MODEL = "stabilityai/sd-turbo"
# Photoreal engine (Luchii Nova-Muse): Realistic Vision V6 + LCM-LoRA, 4 steps. Weights live on the
# persistent volume (LUCHII_PHOTO_MODELS_DIR) so they survive pod restarts.
PHOTO_MODELS_DIR = Path(os.environ["LUCHII_PHOTO_MODELS_DIR"])
PHOTO_REPO = "SG161222/Realistic_Vision_V6.0_B1_noVAE"
PHOTO_FILE = "Realistic_Vision_V6.0_NV_B1_fp16.safetensors"
PHOTO_VAE = "stabilityai/sd-vae-ft-mse"
PHOTO_LCM = "latent-consistency/lcm-lora-sdv1-5"
PHOTO_STEPS = 4
PHOTO_DRAFT_STEPS = 3
PHOTO_NEGATIVE = ("nsfw, nude, naked, topless, deformed face, distorted, disfigured, blurry, cartoon, painting, lowres, "
                  "bad anatomy, extra fingers, watermark, text")
DETAILED_TOKENS = 30   # prompts this long describe several things; turn guidance on so none of them get dropped
DETAIL_GUIDANCE = 1.0  # >1 doubles render time on this CPU; prompt chunking + subject emphasis carry accuracy instead
PHOTO_ASPECTS = {"1:1": (512, 512), "16:9": (704, 384), "9:16": (384, 704), "4:3": (576, 448), "3:4": (512, 640)}
ASPECTS = {"1:1": (512, 512), "16:9": (640, 384), "9:16": (384, 640), "4:3": (576, 448), "3:4": (448, 576)}

_voices: dict = {}
_whisper = None
_t2i = None
_i2i = None
_photo = None
_ip2p = None
_voice_lock = threading.Lock()
_image_lock = threading.Lock()
_stt_lock = threading.Lock()
_shape = None
_converter = None
_shape_lock = threading.Lock()
_convert_lock = threading.Lock()
# Only ONE heavy engine (SD image/video, Shap-E 3D, MusicGen, OpenVoice) may be
# resident at a time on this 8GB/2-core CPU pod. _heavy_lock serializes heavy work
# and _claim() frees the others before a different engine loads, preventing the
# two-models-resident memory collision that evicts the pod.
_heavy_lock = threading.RLock()


def _claim(keep: str):
    global _t2i, _i2i, _shape, _shape_i2m, _music, _photo, _ip2p
    freed = []
    if keep != "image" and _t2i is not None:
        _t2i = _i2i = None
        freed.append("image")
    if keep != "photo" and _photo is not None:
        _photo = None
        freed.append("photo")
    if keep != "edit" and _ip2p is not None:
        _ip2p = None
        freed.append("edit")
    if keep != "shape" and (_shape is not None or _shape_i2m is not None):
        _shape = _shape_i2m = None
        freed.append("shape")
    if keep != "music" and _music is not None:
        _music = None
        freed.append("music")
    if freed:
        import gc
        gc.collect()
        _release_memory()
        logger.info("Freed heavy engine(s) %s to make room for %s", freed, keep)


def _release_memory():
    """Return freed heap back to the OS. Python/glibc keep freed arenas by
    default, so after unloading a multi-GB model the RSS stays high and the next
    model load spikes past the pod memory limit. malloc_trim forces the release."""
    try:
        import ctypes
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:  # noqa: BLE001
        pass


# ---------- voice ----------
def _piper_file(name: str, ext: str) -> Path:
    lang, speaker, quality = name.split("-")
    path = MODELS_DIR / "piper" / f"{name}.{ext}"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        url = f"{PIPER_BASE}/{lang.split('_')[0]}/{lang}/{speaker}/{quality}/{name}.{ext}"
        logger.info("Downloading Piper voice %s", url)
        with httpx.stream("GET", url, follow_redirects=True, timeout=300) as r:
            r.raise_for_status()
            tmp = path.with_suffix(path.suffix + ".part")
            with open(tmp, "wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
            tmp.rename(path)
    return path


def _voice(voice: str):
    from piper import PiperVoice
    name = PIPER_VOICES.get(voice, PIPER_VOICES["nova"])
    if name not in _voices:
        _piper_file(name, "onnx.json")
        _voices[name] = PiperVoice.load(str(_piper_file(name, "onnx")))
    return _voices[name]


def synthesize(text: str, voice: str = "nova") -> dict:
    with _voice_lock:
        v = _voice(voice)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            if hasattr(v, "synthesize_wav"):
                v.synthesize_wav(text, wf)
            else:
                v.synthesize(text, wf)
    return {"audio_base64": base64.b64encode(buf.getvalue()).decode(), "mime": "audio/wav"}


# ---------- transcription ----------
def transcribe(data: bytes) -> str:
    global _whisper
    with _stt_lock:
        if _whisper is None:
            from faster_whisper import WhisperModel
            _whisper = WhisperModel("base", device="cpu", compute_type="int8", download_root=str(MODELS_DIR / "whisper"))
        segments, _ = _whisper.transcribe(io.BytesIO(data), vad_filter=True)
        return " ".join(s.text.strip() for s in segments).strip()


# ---------- images ----------
def _pipes():
    global _t2i, _i2i
    if _t2i is None:
        import torch
        from diffusers import AutoPipelineForText2Image, AutoPipelineForImage2Image, AutoencoderTiny
        torch.set_num_threads(cpu_threads())
        # fp16 weights (half the download/disk) on the persistent volume, upcast to fp32 for CPU.
        _t2i = AutoPipelineForText2Image.from_pretrained(IMAGE_MODEL, variant="fp16", torch_dtype=torch.float32,
                                                         cache_dir=str(PHOTO_MODELS_DIR))
        # TAESD tiny VAE: ~2x faster decode on CPU vs the full VAE, negligible quality loss.
        _t2i.vae = AutoencoderTiny.from_pretrained("madebyollin/taesd", torch_dtype=torch.float32,
                                                   cache_dir=str(PHOTO_MODELS_DIR))
        _t2i.unet = _t2i.unet.to(memory_format=torch.channels_last)
        _t2i.set_progress_bar_config(disable=True)
        _i2i = AutoPipelineForImage2Image.from_pipe(_t2i)
        _i2i.set_progress_bar_config(disable=True)
    return _t2i, _i2i


PHOTO_WARM_MIN_GB = 4.0


def _mem_headroom_gb() -> float:
    try:
        limit = open("/sys/fs/cgroup/memory.max").read().strip()
        if limit == "max":
            return float("inf")
        used = int(open("/sys/fs/cgroup/memory.current").read())
        stat = dict(line.split() for line in open("/sys/fs/cgroup/memory.stat"))
        return (int(limit) - used + int(stat.get("inactive_file", 0))) / 1e9
    except OSError:
        return float("inf")


def _wait_for_platform_engines(timeout: int = 300):
    # Measure headroom only after the platform voice engines finish loading.
    try:
        import voice_engine
    except ImportError:
        return
    for _ in range(timeout // 5):
        st = voice_engine.status()
        if all(st[k]["status"] not in ("idle", "loading") for k in ("stt", "tts", "cloning")):
            return
        time.sleep(5)


def warm_up():
    """Lightweight boot: pre-cache only the small Piper voice. Heavy engines
    (SD-Turbo, Shap-E, MusicGen, OpenVoice) load lazily on first use and only one
    big model stays resident at a time (see _claim). Pre-loading SD at boot was
    removed: it permanently held ~2.5GB, leaving too little headroom for Shap-E's
    ~4GB load on this ~6GB-effective pod and causing evictions."""
    try:
        _voice("nova")
        logger.info("Luchii voice engine ready; image/3D/music/clone load on first use")
    except Exception:  # noqa: BLE001
        logger.exception("Luchii in-house engine warm-up failed")
    # Images and remixes are the main use, so the photo engine (~3GB) and the small region parser are kept warm.
    # _claim() still frees the photo engine before 3D/music load, so the one-heavy-model rule holds.
    _wait_for_platform_engines()
    headroom = _mem_headroom_gb()
    if headroom < PHOTO_WARM_MIN_GB:
        logger.warning("Only %.1fGB memory headroom: photo engine stays internal but loads on first use", headroom)
        return
    try:
        with _heavy_lock:
            _claim("photo")
            try:
                _photo_pipe()
            except (ImportError, RuntimeError):
                # transformers can be mid-import on another engine thread at boot; retry once it settles
                time.sleep(20)
                _photo_pipe()
        _parse_pipe()
        import luchii_face
        luchii_face.warm()
        from PIL import Image
        is_nsfw(Image.new("RGB", (64, 64)))
        logger.info("Luchii photo engine, region parser, Face Fix and safety filter warm")
    except Exception:  # noqa: BLE001
        logger.exception("Luchii photo engine warm-up failed")


def prefetch_scratch_models():
    """One-time background download of 3D/music weights to persistent disk."""
    try:
        from huggingface_hub import snapshot_download
        for repo in (SHAPE_MODEL, SHAPE_IMG_MODEL, MUSIC_MODEL):
            snapshot_download(repo, cache_dir=str(SCRATCH_MODELS_DIR / "hf"))
        logger.info("Scratch models (3D, music) cached on persistent disk")
    except Exception:  # noqa: BLE001
        logger.exception("Scratch model prefetch failed")


def _to_data_url(img) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _to_jpeg_url(img, quality: int = 93) -> str:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=quality, subsampling=0, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


HD_SCALE = 4  # every 512px render is super-resolved (Luchii Prime compact, ~7s) to a crisp ~2K image
SR_BLEND = 0.8  # keep 20% of the Lanczos image so skin and fabric keep natural texture
PHOTO_SR_BLEND = 0.5  # photos: ESRGAN alone paints skin like wax, so keep half the natural upscale
GRAIN = 2.2  # fine luminance grain, like a real camera sensor; stops skin looking airbrushed


def _grain(img):
    import numpy as np
    from PIL import Image
    a = np.asarray(img.convert("RGB")).astype(np.float32)
    noise = np.random.default_rng().normal(0, GRAIN, a.shape[:2])[..., None]
    return Image.fromarray(np.clip(a + noise, 0, 255).astype(np.uint8))


def _hd(img, longest: Optional[int] = None, kind: str = "compact", faces: bool = False) -> str:
    """Luchii Prime finishing pass: real-ESRGAN super-resolution, blended with Lanczos for natural texture.
    faces=True also runs Luchii Face Fix (sharp, natural eyes) on the finished image."""
    from PIL import Image
    import luchii_sr
    target = longest or max(img.size) * HD_SCALE
    try:
        t0 = time.time()
        sr = luchii_sr.enhance(img, target, kind)
        soft = img.convert("RGB").resize(sr.size, Image.LANCZOS)
        out = Image.blend(soft, sr, PHOTO_SR_BLEND if faces else SR_BLEND)
        logger.info("Luchii Prime finish %.1fs -> %dx%d", time.time() - t0, *out.size)
        if faces:
            import luchii_face
            t0 = time.time()
            out = _grain(luchii_face.restore_faces(out))
            logger.info("Luchii Face Fix %.1fs", time.time() - t0)
        return _to_jpeg_url(out)
    except Exception:  # noqa: BLE001
        logger.exception("Luchii Prime finishing pass failed; returning the base render")
        return _to_data_url(img)


def _open_image(b64: str, mode: str = "RGB"):
    """Decode an uploaded image and apply its EXIF orientation, so phone photos are never processed sideways."""
    from PIL import Image, ImageOps
    raw = base64.b64decode(b64.split(",", 1)[1] if b64.startswith("data:") else b64)
    img = Image.open(io.BytesIO(raw))
    try:
        img = ImageOps.exif_transpose(img)
    except Exception:  # noqa: BLE001
        pass
    return img.convert(mode)


def _chunk_ids(tok, text: str) -> list:
    ids = tok(text, truncation=False, add_special_tokens=False).input_ids
    size = tok.model_max_length - 2
    return [ids[i:i + size] for i in range(0, min(len(ids), size * 3), size)] or [[]]


def _encode_chunks(pipe, chunks: list):
    import torch
    tok = pipe.tokenizer
    pad = tok.pad_token_id if tok.pad_token_id is not None else tok.eos_token_id
    embs = []
    with torch.no_grad():
        for c in chunks:
            row = [tok.bos_token_id] + c + [tok.eos_token_id]
            row += [pad] * (tok.model_max_length - len(row))
            embs.append(pipe.text_encoder(torch.tensor([row], device=pipe.text_encoder.device))[0])
    return torch.cat(embs, dim=1)


def _prompt_args(pipe, prompt: str, negative: Optional[str] = None) -> dict:
    """CLIP reads only 77 tokens, so long descriptions used to be cut off mid-sentence. Long prompts are encoded
    in 75-token chunks (up to 3) and joined, so every detail the user wrote reaches the model. When a negative
    prompt is given (guidance on), it is chunked to the same length."""
    chunks = _chunk_ids(pipe.tokenizer, prompt)
    if len(chunks) == 1:
        return {"prompt": prompt, **({"negative_prompt": negative} if negative else {})}
    out = {"prompt_embeds": _encode_chunks(pipe, chunks)}
    if negative:
        neg = _chunk_ids(pipe.tokenizer, negative)[:len(chunks)]
        out["negative_prompt_embeds"] = _encode_chunks(pipe, neg + [[]] * (len(chunks) - len(neg)))
    return out


def prompt_tokens(pipe_tok_text: str) -> int:
    return len(re.findall(r"\w+|[^\w\s]", pipe_tok_text))


def _load_image(b64: str, longest: int):
    from PIL import Image
    img = _open_image(b64)
    scale = longest / max(img.size)
    w, h = (max(64, int(d * scale) // 64 * 64) for d in img.size)
    return img.resize((w, h), Image.LANCZOS)


def preview(b64: str, longest: int = 768) -> str:
    """Light JPEG preview of a large (HD/4K) image for gallery and history lists."""
    from PIL import Image
    img = _open_image(b64)
    img.thumbnail((longest, longest), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def thumbnail(b64: str) -> str:
    img = _load_image(b64, 256)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def generate_image(prompt: str, aspect: Optional[str] = "1:1") -> str:
    w, h = ASPECTS.get(aspect or "1:1", ASPECTS["1:1"])
    with _heavy_lock, _image_lock:
        _claim("image")
        t2i, _ = _pipes()
        img = t2i(**_prompt_args(t2i, prompt), num_inference_steps=2, guidance_scale=0.0, width=w, height=h).images[0]
        return _hd(img)


def edit_image(prompt: str, image_b64: str, strength: float = 0.6, longest: int = 512) -> str:
    src = _load_image(image_b64, longest)
    steps = max(2, int(round(1 / strength)) + 1)
    with _heavy_lock, _image_lock:
        _claim("image")
        _, i2i = _pipes()
        img = i2i(prompt=prompt, image=src, num_inference_steps=steps, strength=strength, guidance_scale=0.0).images[0]
    return _to_data_url(img)


# ---------- Painter-X: instruction-based editing (InstructPix2Pix) ----------
EDIT_MODEL = "timbrooks/instruct-pix2pix"
EDIT_STEPS = 10
EDIT_IMAGE_GUIDANCE = 1.7  # a little higher than the 1.5 default so faces and layout stay closer to the photo


def _ip2p_pipe():
    global _ip2p
    if _ip2p is None:
        import torch
        from huggingface_hub import snapshot_download
        from diffusers import EulerAncestralDiscreteScheduler, StableDiffusionInstructPix2PixPipeline
        torch.set_num_threads(cpu_threads())
        path = snapshot_download(EDIT_MODEL, cache_dir=str(SCRATCH_MODELS_DIR / "hf"), allow_patterns=[
            "model_index.json", "scheduler/*", "tokenizer/*", "feature_extractor/*", "text_encoder/config.json",
            "text_encoder/model.fp16.safetensors", "unet/config.json", "unet/diffusion_pytorch_model.fp16.safetensors",
            "vae/config.json", "vae/diffusion_pytorch_model.fp16.safetensors"])
        pipe = StableDiffusionInstructPix2PixPipeline.from_pretrained(path, variant="fp16", torch_dtype=torch.float32,
                                                                      safety_checker=None, requires_safety_checker=False)
        pipe.scheduler = EulerAncestralDiscreteScheduler.from_config(pipe.scheduler.config)
        pipe.unet = pipe.unet.to(memory_format=torch.channels_last)
        pipe.set_progress_bar_config(disable=True)
        _ip2p = pipe
        logger.info("Luchii Painter-X edit engine loaded")
    return _ip2p


# ---------- Luchii region masks: keep an edit inside the part the user named ----------
PARSE_MODEL = "mattmdjaga/segformer_b2_clothes"
REGION_LABELS = {"hair": [2], "clothes": [4, 5, 6, 7, 8, 17], "hat": [1, 2], "face": [3, 11], "shoes": [9, 10], "bag": [16],
                 "background": [0]}
REGION_WORDS = [
    ("background", re.compile(r"\b(background|backdrop|behind (?:her|him|them))\b", re.I)),
    ("face", re.compile(r"\b(sunglasses|glasses|spectacles|makeup|make-up|lipstick|eyeshadow|beard|mustache|moustache|freckles|"
                        r"smile|smiling|eyes?|face paint|face mask)\b", re.I)),
    ("hat", re.compile(r"\b(crown|tiara|flower crown|halo|headband|hat|cap|beanie|helmet)\b", re.I)),
    ("hair", re.compile(r"\b(hair|hairstyle|haircut|ponytail|braids?|curls)\b", re.I)),
    ("clothes", re.compile(r"\b(clothes|clothing|outfit|shirt|t-shirt|dress(?:ed)?|jacket|sweater|hoodie|coat|suit|blazer|"
                           r"top|blouse|jeans|pants|skirt|wear(?:ing)?|uniform|costume|armou?r|kimono)\b", re.I)),
    ("shoes", re.compile(r"\b(shoes|sneakers|boots|heels)\b", re.I)),
]
_parser = None
_parse_lock = threading.Lock()


def _parse_pipe():
    global _parser
    if _parser is None:
        import torch
        from huggingface_hub import snapshot_download
        from transformers import SegformerForSemanticSegmentation, SegformerImageProcessor
        path = snapshot_download(PARSE_MODEL, cache_dir=str(PHOTO_MODELS_DIR),
                                 allow_patterns=["config.json", "preprocessor_config.json", "model.safetensors"])
        model = SegformerForSemanticSegmentation.from_pretrained(path, torch_dtype=torch.float32).eval()
        _parser = (SegformerImageProcessor.from_pretrained(path), model)
        logger.info("Luchii region parser loaded")
    return _parser


def region_for(step: str) -> Optional[str]:
    if re.search(r"\b(it|everything|the (?:image|photo|picture|scene|whole))\b", step, re.I) and not re.search(r"background", step, re.I):
        return None  # whole-picture change ("make it rainy", "turn it into an oil painting")
    for name, rx in REGION_WORDS:
        if rx.search(step):
            return name
    return None


def _segment(img):
    """Per-pixel labels (hair, face, clothes, background...) from the Luchii region parser."""
    import torch
    with _parse_lock:
        proc, model = _parse_pipe()
        with torch.no_grad():
            logits = model(**proc(images=img, return_tensors="pt")).logits
        return torch.nn.functional.interpolate(logits, size=img.size[::-1], mode="bilinear", align_corners=False).argmax(1)[0].numpy()


def _region_mask(img, region: str, seg=None):
    """Soft mask of the named region (hair, clothes...) or None when that region is not in the photo."""
    import numpy as np
    from PIL import Image, ImageFilter
    seg = _segment(img) if seg is None else seg
    mask = np.isin(seg, REGION_LABELS[region])
    if mask.mean() < 0.004:
        return None
    m = Image.fromarray((mask * 255).astype("uint8"), "L")
    grow = max(5, (max(img.size) // 90) | 1)
    return m.filter(ImageFilter.MaxFilter(grow)).filter(ImageFilter.GaussianBlur(grow / 2))


def instruct_edit(instruction: str, image_b64: str, longest: int = 512,
                  image_guidance: float = EDIT_IMAGE_GUIDANCE) -> str:
    """Follows plain-language edit commands ("make it snowy", "turn day into night") while keeping the
    original layout. ~2.5 min on this 2-core CPU, so callers run it as a job."""
    src = _load_image(image_b64, longest)
    # "make the hair blue and change the clothes" in one pass bleeds the colour over the whole picture,
    # so multi-part requests are applied one step at a time (max 3 steps).
    steps = [p.strip(" ,") for p in re.split(r"\s*(?:,\s*and\s+|\s+and then\s+|\s+and\s+(?=(?:make|turn|change|add|remove|replace|dress|put|give|swap)\b)|;\s*)",
                                             instruction) if p.strip(" ,")][:3] or [instruction]
    with _heavy_lock, _image_lock:
        _claim("edit")
        pipe = _ip2p_pipe()
        from PIL import Image
        img = src
        for step in steps:
            region = region_for(step)
            # A targeted edit may change its region freely (lower image guidance); the mask keeps everything else.
            out = pipe(step, image=img, num_inference_steps=EDIT_STEPS, guidance_scale=7.5,
                       image_guidance_scale=1.4 if region else image_guidance).images[0]
            if out.size != img.size:
                out = out.resize(img.size, Image.LANCZOS)
            mask = None
            if region:
                try:
                    mask = _region_mask(img, region)
                except Exception:  # noqa: BLE001
                    logger.exception("Region mask failed; applying the edit to the whole image")
            img = Image.composite(out, img, mask) if mask is not None else out
        return _hd(img)


REGION_STRENGTH = {"hair": 0.72, "clothes": 0.8, "hat": 0.75, "face": 0.55, "shoes": 0.8, "bag": 0.8, "background": 0.85}
GLOBAL_STRENGTH = 0.6
ART_STRENGTH = 0.7


def describe_edit(step: str) -> str:
    """Turn an edit command into the words the picture should contain ("make the hair blue" -> "blue hair")."""
    s = step.strip().rstrip(".!")
    rules = [
        (r"make the hair (.+)", lambda m: f"{m[1]} hair"),
        (r"(?:change|turn|switch) the (?:clothes|clothing|outfit|dress) (?:to|into|for) (.+)", lambda m: f"wearing {m[1]}"),
        (r"dress (?:them|her|him|it) (?:in|up in|up as) (.+)", lambda m: f"wearing {m[1]}"),
        (r"(?:put|place) (.+?) on (?:them|her|him|it)", lambda m: f"wearing {m[1]}"),
        (r"(?:replace|change|swap) the background (?:with|to|for|into) (.+)", lambda m: f"{m[1]} in the background"),
        (r"add (.+)", lambda m: f"with {m[1]}"),
        (r"remove (?:the )?(.+)", lambda m: f"without {m[1]}, clean"),
        (r"(?:make|turn) (?:it|this|everything|the (?:image|photo|picture|scene))\s+(?:into |look like |like |a |an )?(.+)", lambda m: m[1]),
        (r"turn (?:.+?) into (.+)", lambda m: m[1]),
        (r"make (?:the )?(.+?) (\w+)$", lambda m: f"{m[2]} {m[1]}"),
    ]
    for pat, fn in rules:
        m = re.fullmatch(pat, s, re.I)
        if m:
            return fn(m)
    return s


def split_steps(instruction: str) -> list:
    parts = re.split(r"\s*(?:,\s*and\s+|\s+and then\s+|\s+and\s+(?=(?:make|turn|change|add|remove|replace|dress|put|give|swap)\b)|;\s*)",
                     instruction)
    return [p.strip(" ,") for p in parts if p.strip(" ,")][:3] or [instruction]


def fast_edit(instruction: str, image_b64: str, longest: int = 576) -> str:
    """Painter-X edit in ~30-60s.
    - Region edits (hair, clothes, face, background...): one masked img2img pass on the warm photo engine
      (RV6 + LCM, 4 steps); new pixels are kept only inside the named regions, so face, skin and the rest stay put.
    - Art styles (oil, watercolor, sketch, comic, pixel, mosaic, vintage...): instant Luchii art filters that keep
      the person and layout exactly (the photo engine cannot paint and would change the face).
    - Other whole-picture changes (weather, time of day, materials): a light-guidance pass with the safety prompt."""
    import math
    import numpy as np
    import luchii_styles
    from PIL import Image, ImageChops
    from diffusers import StableDiffusionImg2ImgPipeline
    plan = [(region_for(st), describe_edit(st)) for st in split_steps(instruction)]
    style = next((luchii_styles.detect_style(d) for r, d in plan if r is None and luchii_styles.detect_style(d)), None)
    plan = [(r, d) for r, d in plan if not (r is None and luchii_styles.detect_style(d))]
    if not plan:  # pure art style: instant, on the full-resolution upload
        big = _open_image(image_b64)
        big.thumbnail((1600, 1600), Image.LANCZOS)
        t0 = time.time()
        if is_nsfw(big):
            raise UnsafeImage()
        with _image_lock:
            out = luchii_styles.stylize(big, style)
        logger.info("Painter-X art style %s in %.1fs", style, time.time() - t0)
        return _to_jpeg_url(out, 92)

    t_start = time.time()
    src = _load_image(image_b64, longest)
    words = ", ".join(d for _, d in plan)
    art = bool(REMIX_ART.search(words))
    regional = all(r for r, _ in plan)
    strength = ART_STRENGTH if art else max(REGION_STRENGTH.get(r, GLOBAL_STRENGTH) if r else GLOBAL_STRENGTH for r, _ in plan)
    mask, seg = None, None
    try:
        seg = _segment(src)
    except Exception:  # noqa: BLE001
        logger.exception("Region parser failed; editing the whole image")
    person = seg is not None and np.isin(seg, [4, 5, 6, 7, 11]).mean() > 0.02
    if regional and seg is not None:
        for r, _ in plan:
            m = _region_mask(src, r, seg)
            if m is not None:
                mask = m if mask is None else ImageChops.lighter(mask, m)
    if regional and mask is None:  # named region not found (e.g. no person): gentle whole-image edit
        strength = GLOBAL_STRENGTH
    whole = mask is None
    # Whole-picture edits of a person get light guidance so the negative prompt (nsfw, nude...) is enforced;
    # they run at 512px to stay inside a minute. Masked edits need no guidance (only the region changes).
    guided = whole and (person or art)
    work = src
    if guided and max(src.size) > 512:
        sc = 512 / max(src.size)
        work = src.resize((max(64, int(src.width * sc) // 64 * 64), max(64, int(src.height * sc) // 64 * 64)), Image.LANCZOS)
    keep = ", the same person, fully clothed" if person and whole else ""
    with _heavy_lock, _image_lock:
        _claim("photo")
        pipe = StableDiffusionImg2ImgPipeline(**_photo_pipe().components)
        pipe.set_progress_bar_config(disable=True)
        full = f"{words}{keep}, {ART_HINT if art else REMIX_HINT}"
        args = _prompt_args(pipe, full, (ART_NEGATIVE if art else PHOTO_NEGATIVE) if guided else None)
        t0 = time.time()
        out = pipe(**args, image=work, strength=strength, num_inference_steps=math.ceil(PHOTO_STEPS / strength),
                   guidance_scale=EDIT_GUIDANCE if guided else 1.0).images[0]
        logger.info("Painter-X %s pass %.1fs (%dx%d, strength %.2f, steps %s)", "masked" if mask is not None else "whole",
                    time.time() - t0, work.size[0], work.size[1], strength, plan)
        def merge(o):
            if mask is None:
                return o
            return Image.composite(o.resize(src.size, Image.LANCZOS) if o.size != src.size else o, src, mask)
        result = merge(out)
        if is_nsfw(result):  # one guided retry with the safety prompt, then block
            out = pipe(**_prompt_args(pipe, full + SAFE_PROMPT, ART_NEGATIVE if art else PHOTO_NEGATIVE), image=work,
                       strength=strength, num_inference_steps=math.ceil(PHOTO_STEPS / strength),
                       guidance_scale=EDIT_GUIDANCE).images[0]
            result = merge(out)
            if is_nsfw(result):
                raise UnsafeImage()
    out = result
    logger.info("Painter-X before finish %.1fs", time.time() - t_start)
    url = _hd(out, longest=2048, faces=not art)
    if style:  # e.g. "make the hair blue and turn it into an oil painting"
        img = Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))).convert("RGB")
        img.thumbnail((1600, 1600), Image.LANCZOS)
        url = _to_jpeg_url(luchii_styles.stylize(img, style), 92)
    return url


REMIX_STRENGTH = 0.5
REMIX_HINT = "RAW photo, ultra realistic, sharp focus, detailed face, natural skin texture, high detail"
ART_HINT = "artwork, visible brush strokes and texture, highly detailed, masterpiece"
ART_NEGATIVE = "nsfw, nude, naked, topless, photo, photograph, photorealistic, deformed, blurry, lowres, watermark, text"
EDIT_GUIDANCE = 1.7
REMIX_ART = re.compile(r"\b(anime|manga|cartoon|comic|illustration|painting|painted|watercolou?r|sketch|drawing|pixel art|"
                       r"pop art|stained glass|claymation|clay|3d|render|van gogh|oil|lego|origami|mosaic|ukiyo-e)\b", re.I)


def photo_remix(prompt: str, image_b64: str, strength: float = REMIX_STRENGTH, longest: int = 576) -> str:
    """Painter-X remix: photoreal img2img on the Nova-Muse engine (RV6 + LCM) keeps the layout and faces sharp.
    Art-style remixes (oil painting, anime, sketch...) skip the photo hint, which would pull them back to a photo,
    and get a stronger change so the new look actually shows."""
    import math
    from diffusers import StableDiffusionImg2ImgPipeline
    src = _load_image(image_b64, longest)
    art = bool(REMIX_ART.search(prompt))
    strength = max(strength, 0.68) if art else strength
    with _heavy_lock, _image_lock:
        _claim("photo")
        pipe = StableDiffusionImg2ImgPipeline(**_photo_pipe().components)
        pipe.set_progress_bar_config(disable=True)
        full = f"{prompt}, {ART_HINT if art else REMIX_HINT}"
        img = pipe(**_prompt_args(pipe, full), image=src, strength=strength,
                   num_inference_steps=math.ceil(PHOTO_STEPS / strength), guidance_scale=1.0).images[0]
        return _hd(img)


UPSCALE_BASE = 640     # Prime (RRDB x4) input size: 640 -> 2560 in ~2.5 min on this 2-core CPU
UPSCALE_LONGEST = 3840  # true 4K UHD long edge


def upscale_image(image_b64: str) -> str:
    """Luchii Prime 4K: Real-ESRGAN x4plus super-resolution, then resampled to a 3840px long edge."""
    from PIL import Image
    img = _open_image(image_b64)
    if max(img.size) > UPSCALE_BASE:
        s = UPSCALE_BASE / max(img.size)
        img = img.resize((round(img.width * s), round(img.height * s)), Image.LANCZOS)
    import luchii_sr
    with _image_lock:
        big = luchii_sr.enhance(img, UPSCALE_LONGEST, "prime")
        soft = img.resize(big.size, Image.LANCZOS)
        out = Image.blend(soft, big, 0.85)
    return _to_jpeg_url(out, 90)


PHOTO_TINY_VAE = "madebyollin/taesd"

# ---------- Luchii safety filter ----------
NSFW_MODEL = "Falconsai/nsfw_image_detection"
NSFW_THRESHOLD = 0.6
SAFE_PROMPT = ", fully clothed, wearing a shirt, modest, safe for work"
_nsfw = None
_nsfw_lock = threading.Lock()


class UnsafeImage(Exception):
    pass


def is_nsfw(img) -> bool:
    """~0.3s ViT check on every finished render; a flagged image is re-rendered with the safety prompt or blocked."""
    global _nsfw
    try:
        import torch
        with _nsfw_lock:
            if _nsfw is None:
                from huggingface_hub import snapshot_download
                from transformers import AutoImageProcessor, AutoModelForImageClassification
                p = snapshot_download(NSFW_MODEL, cache_dir=str(PHOTO_MODELS_DIR),
                                      allow_patterns=["config.json", "preprocessor_config.json", "model.safetensors"])
                _nsfw = (AutoImageProcessor.from_pretrained(p), AutoModelForImageClassification.from_pretrained(p).eval())
            proc, model = _nsfw
            with torch.no_grad():
                prob = model(**proc(images=img.convert("RGB"), return_tensors="pt")).logits.softmax(-1)[0]
        score = float(prob[[i for i, n in model.config.id2label.items() if n.lower() == "nsfw"][0]])
        if score >= NSFW_THRESHOLD:
            logger.warning("Luchii safety filter flagged a render (nsfw %.2f)", score)
        return score >= NSFW_THRESHOLD
    except Exception:  # noqa: BLE001
        logger.exception("Safety filter failed")
        return False


def _bf16_linears(module) -> int:
    import torch

    class _BF16Linear(torch.nn.Module):
        def __init__(self, lin):
            super().__init__()
            self.lin = lin.to(torch.bfloat16)

        def forward(self, x):
            return self.lin(x.to(torch.bfloat16)).to(x.dtype)

    n = 0
    for name, child in module.named_children():
        if isinstance(child, torch.nn.Linear):
            setattr(module, name, _BF16Linear(child))
            n += 1
        else:
            n += _bf16_linears(child)
    return n


def _photo_pipe():
    global _photo
    if _photo is None:
        import torch
        from huggingface_hub import snapshot_download
        from diffusers import AutoencoderKL, LCMScheduler, StableDiffusionPipeline
        torch.set_num_threads(cpu_threads())
        cache = str(PHOTO_MODELS_DIR)
        rv = snapshot_download(PHOTO_REPO, cache_dir=cache, allow_patterns=[
            PHOTO_FILE, "model_index.json", "scheduler/*", "tokenizer/*", "text_encoder/config.json",
            "unet/config.json", "vae/config.json", "feature_extractor/*"])
        vae = AutoencoderKL.from_pretrained(snapshot_download(PHOTO_VAE, cache_dir=cache, allow_patterns=[
            "config.json", "diffusion_pytorch_model.safetensors"]), torch_dtype=torch.float32)
        pipe = StableDiffusionPipeline.from_single_file(f"{rv}/{PHOTO_FILE}", config=rv, vae=vae, torch_dtype=torch.float32,
                                                        safety_checker=None, requires_safety_checker=False)
        pipe.scheduler = LCMScheduler.from_config(pipe.scheduler.config)
        pipe.load_lora_weights(snapshot_download(PHOTO_LCM, cache_dir=cache))
        pipe.fuse_lora()
        pipe.unload_lora_weights()
        # Pipelines decode with TAESD (~1s, edits stay fast). generate_photo decodes finals with the full VAE
        # (_full_vae), which keeps pores, freckles and hair that TAESD smears into a plastic look.
        global _full_vae
        _full_vae = vae.to(memory_format=torch.channels_last)
        pipe.vae = _tiny()
        _bf16_linears(pipe.unet)
        pipe.unet = pipe.unet.to(memory_format=torch.channels_last)
        pipe.set_progress_bar_config(disable=True)
        _photo = pipe
        logger.info("Luchii photoreal engine (Nova-Muse) loaded")
    return _photo


def generate_photo(prompt: str, aspect: Optional[str] = "1:1", draft: bool = False, seed: Optional[int] = None) -> str:
    """Photoreal render (Luchii Nova-Muse). Full: 4 steps, ~40s on this 2-core CPU. Quick draft: 3 steps, ~30s.
    The same seed keeps the draft and full render close in composition."""
    import torch
    w, h = PHOTO_ASPECTS.get(aspect or "1:1", PHOTO_ASPECTS["1:1"])
    # Draft keeps the full size (3/4 size distorted wide shots) and saves time with one step less.
    with _heavy_lock, _image_lock:
        _claim("photo")
        pipe = _photo_pipe()
        gen = torch.Generator().manual_seed(int(seed)) if seed is not None else None
        detailed = prompt_tokens(prompt) >= DETAILED_TOKENS
        lat = pipe(**_prompt_args(pipe, prompt, PHOTO_NEGATIVE if detailed else None),
                   num_inference_steps=PHOTO_DRAFT_STEPS if draft else PHOTO_STEPS, output_type="latent",
                   guidance_scale=DETAIL_GUIDANCE if detailed else 1.0, width=w, height=h, generator=gen).images
        img = _decode(pipe, lat, full=False)
        if is_nsfw(img):  # re-render once with guidance, so the negative prompt (nude, topless...) really applies
            lat = pipe(**_prompt_args(pipe, prompt + SAFE_PROMPT, PHOTO_NEGATIVE), num_inference_steps=PHOTO_STEPS,
                       guidance_scale=EDIT_GUIDANCE, width=w, height=h, generator=gen, output_type="latent").images
            img = _decode(pipe, lat, full=False)
            if is_nsfw(img):
                raise UnsafeImage()
        if not draft:
            import luchii_face
            if luchii_face.largest_face(img) >= HIRES_MIN_FACE:
                img = _hires_pass(pipe, prompt, img, gen)
            else:
                img = _decode(pipe, lat, full=True)
        return _hd(img, longest=2048, faces=True)


_full_vae = None


def _decode(pipe, lat, full: bool):
    """Latents -> PIL. full=True uses the full SD VAE (fine skin and hair detail, ~20s at 512); else TAESD (~1s)."""
    import torch
    t0 = time.time()
    with torch.no_grad():
        if full:
            x = _full_vae.decode(lat / _full_vae.config.scaling_factor).sample
        else:
            x = pipe.vae.decode(lat).sample
    out = pipe.image_processor.postprocess(x, output_type="pil")[0]
    logger.info("Luchii decode (%s) %.1fs", "full VAE" if full else "TAESD", time.time() - t0)
    return out


HIRES_SCALE = 1.25  # 512 -> 640: the photo engine paints real pores, lashes and hair at the larger size
HIRES_STRENGTH = 0.35
HIRES_STEPS = 6  # x strength -> 2 real denoise steps
HIRES_FULL_DECODE = False  # full VAE at 768 costs ~65s on this CPU; TAESD at 768 keeps the new detail
HIRES_MIN_FACE = 40  # px in the 512 render; people shots get the pass, landscapes and products skip it
_tiny_vae = None


def _tiny():
    global _tiny_vae
    if _tiny_vae is None:
        import torch
        from huggingface_hub import snapshot_download
        from diffusers import AutoencoderTiny
        _tiny_vae = AutoencoderTiny.from_pretrained(snapshot_download(PHOTO_TINY_VAE, cache_dir=str(PHOTO_MODELS_DIR), allow_patterns=[
            "config.json", "diffusion_pytorch_model.safetensors"]), torch_dtype=torch.float32)
    return _tiny_vae


def _hires_pass(pipe, prompt: str, img, gen):
    """Hi-res fix: re-render the upscaled image lightly so detail is generated, not smeared in by the upscaler."""
    from PIL import Image
    from diffusers import StableDiffusionImg2ImgPipeline
    t0 = time.time()
    big = img.resize((int(img.width * HIRES_SCALE) // 8 * 8, int(img.height * HIRES_SCALE) // 8 * 8), Image.LANCZOS)
    import numpy as np
    import torch
    x = torch.from_numpy(np.asarray(big.convert("RGB"), dtype=np.float32) / 127.5 - 1).permute(2, 0, 1)[None]
    with torch.no_grad():  # fast TAESD encode (same latent space); the full VAE still does the final decode
        latents = _tiny().encode(x).latents  # TAESD latents are already in the scaled SD space
    i2i = StableDiffusionImg2ImgPipeline(**pipe.components)
    i2i.set_progress_bar_config(disable=True)
    t1 = time.time()
    lat = i2i(**_prompt_args(i2i, prompt + ", detailed skin texture, sharp eyes", None), image=latents,
              strength=HIRES_STRENGTH, num_inference_steps=HIRES_STEPS, guidance_scale=1.0, generator=gen,
              output_type="latent").images
    logger.info("Luchii hi-res denoise %.1fs", time.time() - t1)
    out = _decode(pipe, lat, full=HIRES_FULL_DECODE)
    logger.info("Luchii hi-res pass %.1fs -> %dx%d", time.time() - t0, *out.size)
    return out


_cutout = None


def remove_background(image_b64: str) -> str:
    """Luchii cutout: IS-Net (rembg) background removal -> transparent PNG at the original size (max 2048px)."""
    global _cutout
    from PIL import Image
    from rembg import new_session, remove
    img = _open_image(image_b64)
    img.thumbnail((2048, 2048), Image.LANCZOS)
    with _image_lock:
        if _cutout is None:
            _cutout = new_session("isnet-general-use")
        out = remove(img, session=_cutout, post_process_mask=True)
    return _to_data_url(out)


def image_busy() -> bool:
    return _image_lock.locked()


def status() -> dict:
    voice_ready = any((MODELS_DIR / "piper").glob("*.onnx")) if (MODELS_DIR / "piper").exists() else False
    image_ready = any(PHOTO_MODELS_DIR.glob("models--stabilityai--sd-turbo/snapshots/*/unet/*.safetensors"))
    shape_ready = (SCRATCH_MODELS_DIR / "hf").exists() and any((SCRATCH_MODELS_DIR / "hf").rglob("*.bin"))
    return {"voice_downloaded": voice_ready, "image_downloaded": image_ready, "image_loaded": _t2i is not None,
            "shape_downloaded": shape_ready, "shape_loaded": _shape is not None, "converter_loaded": _converter is not None}


# ---------- 3D ----------
_shape_i2m = None
SHAPE_IMG_MODEL = "openai/shap-e-img2img"


def _fast_scheduler(pipe):
    from diffusers import DPMSolverMultistepScheduler
    pipe.scheduler = DPMSolverMultistepScheduler(
        num_train_timesteps=1024, trained_betas=pipe.scheduler.betas.numpy(), prediction_type="sample",
        algorithm_type="dpmsolver++", use_karras_sigmas=True)
    pipe.set_progress_bar_config(disable=True)
    return pipe


def _shape_pipe(from_image: bool = False):
    global _shape, _shape_i2m
    import torch
    torch.set_num_threads(cpu_threads())
    cache = str(SCRATCH_MODELS_DIR / "hf")
    if from_image:
        if _shape_i2m is None:
            from diffusers import ShapEImg2ImgPipeline
            _shape_i2m = _fast_scheduler(ShapEImg2ImgPipeline.from_pretrained(SHAPE_IMG_MODEL, torch_dtype=torch.float32, low_cpu_mem_usage=True, cache_dir=cache))
        return _shape_i2m
    if _shape is None:
        from diffusers import ShapEPipeline
        _shape = _fast_scheduler(ShapEPipeline.from_pretrained(SHAPE_MODEL, torch_dtype=torch.float32, low_cpu_mem_usage=True, cache_dir=cache))
    return _shape


def generate_3d(prompt: str, image_b64: Optional[str] = None) -> bytes:
    import numpy as np
    import trimesh
    with _heavy_lock, _shape_lock:
        _claim("shape")
        pipe = _shape_pipe(from_image=bool(image_b64))
        source = _load_image(image_b64, 256) if image_b64 else prompt
        guidance = 3.0 if image_b64 else 15.0
        latents = pipe(source, guidance_scale=guidance, num_inference_steps=SHAPE_STEPS, output_type="latent").images
        mesh = pipe.shap_e_renderer.decode_to_mesh(latents[0, None], "cpu")
    verts = mesh.verts.cpu().numpy()[:, [0, 2, 1]] * [1, 1, -1]
    colors = np.stack([mesh.vertex_channels[k].cpu().numpy() for k in "RGB"], 1)
    tm = trimesh.Trimesh(vertices=verts, faces=mesh.faces.cpu().numpy(),
                         vertex_colors=(colors * 255).clip(0, 255).astype("uint8"))
    return tm.export(file_type="glb")


# ---------- voice conversion ----------
def _openvoice():
    global _converter
    if _converter is None:
        import sys
        from huggingface_hub import hf_hub_download
        sys.path.insert(0, str(Path(__file__).parent / "vendor"))
        from openvoice.api import ToneColorConverter
        root = MODELS_DIR / "openvoice"
        cfg = hf_hub_download(OPENVOICE_REPO, "converter/config.json", local_dir=str(root))
        ckpt = hf_hub_download(OPENVOICE_REPO, "converter/checkpoint.pth", local_dir=str(root))
        conv = ToneColorConverter(cfg, device="cpu")
        conv.load_ckpt(ckpt)
        _converter = conv
    return _converter


def _to_wav_file(data: bytes, path: Path, rate: int = 22050) -> float:
    import av
    import numpy as np
    import soundfile
    chunks = []
    with av.open(io.BytesIO(data)) as container:
        resampler = av.AudioResampler(format="flt", layout="mono", rate=rate)
        for frame in container.decode(audio=0):
            for f in resampler.resample(frame):
                chunks.append(f.to_ndarray().reshape(-1))
        for f in resampler.resample(None):
            chunks.append(f.to_ndarray().reshape(-1))
    audio = np.concatenate(chunks) if chunks else np.zeros(0, dtype="float32")
    soundfile.write(str(path), audio, rate)
    return len(audio) / rate


def audio_duration(data: bytes) -> float:
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        return round(_to_wav_file(data, Path(tmp) / "a.wav"), 1)


def speak_cloned(text: str, reference: bytes, base_voice: str = "nova") -> dict:
    import tempfile
    base = base64.b64decode(synthesize(text, base_voice)["audio_base64"])
    with _convert_lock, tempfile.TemporaryDirectory() as tmp:
        conv = _openvoice()
        src, ref, out = Path(tmp) / "src.wav", Path(tmp) / "ref.wav", Path(tmp) / "out.wav"
        src.write_bytes(base)
        _to_wav_file(reference, ref, conv.hps.data.sampling_rate)
        src_se = conv.extract_se([str(src)])
        tgt_se = conv.extract_se([str(ref)])
        conv.convert(audio_src_path=str(src), src_se=src_se, tgt_se=tgt_se, output_path=str(out))
        return {"audio_base64": base64.b64encode(out.read_bytes()).decode(), "mime": "audio/wav"}


def busy_3d() -> bool:
    return _shape_lock.locked()


# ---------- video (keyframes + motion) ----------
VIDEO_FPS = 24
VIDEO_BEATS = ["establishing wide shot", "medium shot", "close-up detail shot", "dynamic low angle",
               "sweeping side view", "final hero shot"]


def _ken_burns(img, t: float, k: int, size):
    from PIL import Image
    w, h = size
    zoom = 1.0 + 0.10 * t if k % 2 == 0 else 1.10 - 0.10 * t
    cw, ch = w / zoom, h / zoom
    dx = (w - cw) * (0.5 + 0.4 * (t - 0.5) * (1 if k % 3 else -1))
    dy = (h - ch) * 0.5
    return img.crop((dx, dy, dx + cw, dy + ch)).resize(size, Image.BICUBIC)


def generate_video(prompt: str, duration: int, style: str = "") -> bytes:
    import tempfile
    import av
    import numpy as np
    from PIL import Image
    size = ASPECTS["16:9"]
    n = max(2, round(duration / 2.5))
    keys = []
    with _heavy_lock, _image_lock:
        _claim("image")
        t2i, i2i = _pipes()
        full = lambda b: f"{prompt}, {b}, {style}".strip(", ")  # noqa: E731
        img = t2i(prompt=full(VIDEO_BEATS[0]), num_inference_steps=1, guidance_scale=0.0,
                  width=size[0], height=size[1]).images[0]
        keys.append(img)
        for k in range(1, n):
            img = i2i(prompt=full(VIDEO_BEATS[k % len(VIDEO_BEATS)]), image=img, num_inference_steps=2,
                      strength=0.55, guidance_scale=0.0).images[0].resize(size)
            keys.append(img)
    total, fade = duration * VIDEO_FPS, VIDEO_FPS // 2
    seg = total / n
    with tempfile.NamedTemporaryFile(suffix=".mp4") as tmp:
        with av.open(tmp.name, "w") as out:
            st = out.add_stream("libx264", rate=VIDEO_FPS, options={"crf": "22", "preset": "veryfast"})
            st.width, st.height, st.pix_fmt = size[0], size[1], "yuv420p"
            for f in range(total):
                k = min(n - 1, int(f / seg))
                t = (f - k * seg) / seg
                frame = _ken_burns(keys[k], t, k, size)
                remaining = (k + 1) * seg - f
                if k < n - 1 and remaining < fade:
                    nxt = _ken_burns(keys[k + 1], 0.0, k + 1, size)
                    frame = Image.blend(frame, nxt, 1 - remaining / fade)
                vf = av.VideoFrame.from_ndarray(np.asarray(frame.convert("RGB")), format="rgb24")
                for p in st.encode(vf):
                    out.mux(p)
            for p in st.encode():
                out.mux(p)
        return Path(tmp.name).read_bytes()


# ---------- music ----------
_music = None
_music_lock = threading.Lock()
MUSIC_MODEL = "facebook/musicgen-small"


def generate_music(prompt: str, duration: int) -> bytes:
    global _music
    import numpy as np
    with _heavy_lock, _music_lock:
        _claim("music")
        if _music is None:
            import torch
            from transformers import AutoProcessor, MusicgenForConditionalGeneration
            torch.set_num_threads(cpu_threads())
            cache = str(SCRATCH_MODELS_DIR / "hf")
            _music = (AutoProcessor.from_pretrained(MUSIC_MODEL, cache_dir=cache),
                      MusicgenForConditionalGeneration.from_pretrained(MUSIC_MODEL, cache_dir=cache))
        proc, model = _music
        inputs = proc(text=[prompt], padding=True, return_tensors="pt")
        audio = model.generate(**inputs, max_new_tokens=int(duration * 50) + 4, do_sample=True, guidance_scale=3.0)
        rate = model.config.audio_encoder.sampling_rate
    pcm = (np.clip(audio[0, 0].numpy(), -1, 1) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()
