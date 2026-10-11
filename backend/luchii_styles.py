"""Luchii Painter-X art styles: instant, identity-preserving art filters (oil, watercolor, sketch, comic, pixel...).

The photoreal engine cannot turn a photo into a painting (it pulls everything back to a photo and changes the
face), so whole-image art styles are rendered here in ~1-3s on the CPU. The person, pose and layout stay exactly
as in the photo; only the medium changes.
"""
import re
from typing import Optional

import numpy as np

STYLES = [
    ("van-gogh", r"van gogh|starry night|post-?impressionis"),
    ("oil", r"oil paint|oil-paint|\boil\b|impasto|acrylic|painting\b(?!.*water)"),
    ("watercolor", r"watercolou?r|aquarelle|gouache"),
    ("charcoal", r"charcoal"),
    ("color-pencil", r"colou?red pencil|crayon"),
    ("sketch", r"pencil|sketch|drawing|graphite|line art"),
    ("comic", r"comic|cartoon(?!.*3d)|anime|manga|cel[- ]shad|cartoonish|toon"),
    ("pop-art", r"pop art|warhol|posteri[sz]ed?"),
    ("pixel", r"pixel art|8-?bit|16-?bit|pixelated|retro game"),
    ("mosaic", r"stained glass|mosaic|tiles?\b"),
    ("ukiyo-e", r"ukiyo-?e|woodblock|japanese print"),
    ("vintage", r"vintage|1970s|70s|retro photo|old photo|film photo|polaroid|sepia"),
    ("bw", r"black and white|black-and-white|monochrome|b&w|grayscale|greyscale"),
    ("neon", r"neon sign|neon outline|glowing outline"),
    ("marble", r"marble statue|statue|sculpture of marble"),
]
_COMPILED = [(n, re.compile(p, re.I)) for n, p in STYLES]


def detect_style(text: str) -> Optional[str]:
    if re.search(r"\b(3d|clay|claymation|lego|pixar|render|plush|gold|golden|ice|frozen)\b", text or "", re.I):
        return None  # these are material/render looks the diffusion engine handles
    for name, rx in _COMPILED:
        if rx.search(text or ""):
            return name
    return None


def _cv(img):
    import cv2
    return cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2BGR)


def _pil(arr):
    import cv2
    from PIL import Image
    if arr.ndim == 2:
        return Image.fromarray(arr).convert("RGB")
    return Image.fromarray(cv2.cvtColor(arr, cv2.COLOR_BGR2RGB))


def _saturate(bgr, s=1.25, v=1.0):
    import cv2
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[..., 1] = np.clip(hsv[..., 1] * s, 0, 255)
    hsv[..., 2] = np.clip(hsv[..., 2] * v, 0, 255)
    return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)


def _quantize(bgr, k=10):
    import cv2
    data = bgr.reshape(-1, 3).astype(np.float32)
    small = data[:: max(1, len(data) // 40000)]
    _, _, centers = cv2.kmeans(small, k, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 12, 1.0), 2,
                               cv2.KMEANS_PP_CENTERS)
    centers = centers.astype(np.float32)
    d = ((data[:, None, :] - centers[None, :, :]) ** 2).sum(-1)
    return centers[d.argmin(1)].reshape(bgr.shape).astype(np.uint8)


def _edges(bgr, block=9, c=5):
    import cv2
    gray = cv2.medianBlur(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY), 7)
    return cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, block, c)


def _paper(bgr, strength=12, seed=7):
    rng = np.random.default_rng(seed)
    import cv2
    noise = rng.normal(0, 1, bgr.shape[:2]).astype(np.float32)
    noise = cv2.GaussianBlur(noise, (0, 0), 1.2) * strength
    return np.clip(bgr.astype(np.float32) + noise[..., None], 0, 255).astype(np.uint8)


def stylize(img, style: str):
    """Apply a Luchii art style to a PIL image and return a PIL image."""
    import cv2
    bgr = _cv(img)
    h, w = bgr.shape[:2]
    if style in ("oil", "van-gogh"):
        size = 9 if style == "van-gogh" else 6
        base = cv2.edgePreservingFilter(bgr, flags=1, sigma_s=40, sigma_r=0.35)
        out = cv2.xphoto.oilPainting(base, size, 1)
        out = _saturate(out, 1.5 if style == "van-gogh" else 1.2, 1.03)
        # canvas relief so it reads as paint, not a blur
        gray = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY).astype(np.float32)
        relief = cv2.filter2D(gray, -1, np.array([[-1, -1, 0], [-1, 0, 1], [0, 1, 1]], np.float32))
        out = np.clip(out.astype(np.float32) + relief[..., None] * 0.18, 0, 255).astype(np.uint8)
        return _pil(_paper(out, 6))
    if style == "watercolor":
        out = cv2.stylization(bgr, sigma_s=70, sigma_r=0.45)
        out = _saturate(out, 1.1, 1.06)
        soft = cv2.GaussianBlur(out, (0, 0), 1.5)
        lines = cv2.cvtColor(_edges(bgr, 11, 7), cv2.COLOR_GRAY2BGR)
        out = cv2.addWeighted(soft, 0.85, cv2.min(soft, lines), 0.15, 0)
        paper = np.full_like(out, (232, 240, 246))
        return _pil(_paper(cv2.addWeighted(out, 0.9, paper, 0.1, 0), 8))
    if style in ("sketch", "charcoal", "color-pencil"):
        gray, color = cv2.pencilSketch(bgr, sigma_s=60, sigma_r=0.08, shade_factor=0.04 if style != "charcoal" else 0.09)
        if style == "color-pencil":
            return _pil(_paper(_saturate(color, 1.2), 6))
        if style == "charcoal":
            g = cv2.equalizeHist(gray)
            g = cv2.addWeighted(g, 0.8, cv2.GaussianBlur(g, (0, 0), 2), 0.2, -25)
            return _pil(_paper(cv2.cvtColor(g, cv2.COLOR_GRAY2BGR), 14))
        return _pil(_paper(cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR), 7))
    if style == "comic":
        smooth = bgr
        for _ in range(4):
            smooth = cv2.bilateralFilter(smooth, 9, 60, 60)
        flat = _saturate(_quantize(smooth, 12), 1.3, 1.05)
        edges = _edges(bgr, 9, 4)
        return _pil(cv2.bitwise_and(flat, flat, mask=edges))
    if style == "pop-art":
        flat = _quantize(cv2.bilateralFilter(bgr, 9, 80, 80), 5)
        flat = _saturate(flat, 2.0, 1.1)
        edges = _edges(bgr, 9, 3)
        return _pil(cv2.bitwise_and(flat, flat, mask=edges))
    if style == "pixel":
        px = max(64, min(128, max(w, h) // 10))
        s = px / max(w, h)
        small = cv2.resize(bgr, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA)
        small = _saturate(_quantize(small, 24), 1.2)
        return _pil(cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST))
    if style == "mosaic":
        lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
        slic = cv2.ximgproc.createSuperpixelSLIC(lab, algorithm=cv2.ximgproc.SLICO, region_size=max(14, max(w, h) // 45))
        slic.iterate(8)
        labels = slic.getLabels()
        flat_l = labels.ravel()
        n = int(flat_l.max()) + 1
        cnt = np.maximum(np.bincount(flat_l, minlength=n), 1)
        means = np.stack([np.bincount(flat_l, bgr[..., c].ravel().astype(np.float64), n) / cnt for c in range(3)], 1)
        out = means[labels].astype(np.uint8)
        out = _saturate(out, 1.45, 1.08)
        border = slic.getLabelContourMask(True)
        border = cv2.dilate(border, np.ones((3, 3), np.uint8))
        out[border > 0] = (25, 25, 25)
        return _pil(out)
    if style == "ukiyo-e":
        flat = _quantize(cv2.bilateralFilter(bgr, 9, 70, 70), 7)
        flat = _saturate(flat, 0.85)
        paper = np.full_like(flat, (190, 215, 235))
        flat = cv2.addWeighted(flat, 0.8, paper, 0.2, 0)
        edges = _edges(bgr, 11, 5)
        return _pil(_paper(cv2.bitwise_and(flat, flat, mask=edges), 9))
    if style == "vintage":
        f = bgr.astype(np.float32) / 255
        f = 0.08 + f * 0.86  # faded blacks and whites
        f[..., 2] *= 1.08
        f[..., 1] *= 1.02
        f[..., 0] *= 0.86
        yy, xx = np.mgrid[0:h, 0:w]
        vig = 1 - 0.35 * (((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2)
        f *= np.clip(vig, 0.55, 1)[..., None]
        out = np.clip(f * 255, 0, 255).astype(np.uint8)
        return _pil(_paper(_saturate(out, 0.8), 10))
    if style == "bw":
        g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        g = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(g)
        return _pil(_paper(cv2.cvtColor(g, cv2.COLOR_GRAY2BGR), 6))
    if style == "neon":
        gray = cv2.GaussianBlur(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY), (5, 5), 0)
        e = cv2.Canny(gray, 40, 110)
        e = cv2.dilate(e, np.ones((2, 2), np.uint8))
        hue = (np.linspace(150, 90, w)[None, :].repeat(h, 0)).astype(np.uint8)
        hsv = np.dstack([hue, np.full_like(hue, 255), e])
        line = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
        glow = cv2.GaussianBlur(line, (0, 0), 6) * 2.2
        dark = (bgr * 0.12).astype(np.float32)
        return _pil(np.clip(dark + glow + line, 0, 255).astype(np.uint8))
    if style == "marble":
        g = cv2.cvtColor(cv2.bilateralFilter(bgr, 9, 60, 60), cv2.COLOR_BGR2GRAY)
        g = cv2.normalize(g, None, 70, 245, cv2.NORM_MINMAX)
        tint = cv2.merge([g, (g * 0.98).astype(np.uint8), (g * 0.96).astype(np.uint8)])
        return _pil(_paper(tint, 5))
    return img
