"""Luchii Face Fix: sharp, natural eyes and faces on every portrait.

512px CPU renders draw faces at ~150-250px, so eyes often come out blurry, uneven or melted. After each render
the faces are found (OpenCV YuNet, 5 landmarks), aligned to the FFHQ 512 template, restored with GFPGAN 1.4
(ONNX, CPU) and blended back with a soft mask. ~2-4s per face on this CPU.
Weights live in LUCHII_MODELS_DIR/face (persistent) and download on first use.
"""
import logging
import os
import threading
from pathlib import Path

import httpx
import numpy as np

logger = logging.getLogger("luchii.face")
FACE_DIR = Path(os.environ["LUCHII_MODELS_DIR"]) / "face"
GFPGAN_URL = "https://huggingface.co/facefusion/models-3.0.0/resolve/main/gfpgan_1.4.onnx"
YUNET_URL = "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
# FFHQ 512 alignment template (left eye, right eye, nose, left mouth corner, right mouth corner in image space)
TEMPLATE = np.array([[0.37691676, 0.46864664], [0.62285697, 0.46912813], [0.50123859, 0.61331904],
                     [0.39308822, 0.72541100], [0.61150205, 0.72490465]], np.float32) * 512
BLEND = 0.7  # small faces: GFPGAN fixes eyes and teeth the 512px render could not draw
MIN_BLEND = 0.25  # close-ups keep most of their own skin texture
_lock = threading.Lock()
_restorer = None


def _fetch(url: str, path: Path):
    if path.exists() and path.stat().st_size > 0:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    with httpx.stream("GET", url, follow_redirects=True, timeout=600) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
    tmp.rename(path)


def _load():
    global _restorer
    if _restorer is None:
        import onnxruntime as ort
        _fetch(GFPGAN_URL, FACE_DIR / "gfpgan_1.4.onnx")
        _fetch(YUNET_URL, FACE_DIR / "yunet_2023mar.onnx")
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 2
        _restorer = ort.InferenceSession(str(FACE_DIR / "gfpgan_1.4.onnx"), opts, providers=["CPUExecutionProvider"])
        logger.info("Luchii Face Fix loaded")
    return _restorer


def warm():
    try:
        with _lock:
            _load()
    except Exception:  # noqa: BLE001
        logger.exception("Luchii Face Fix warm-up failed")


def _detect(bgr):
    """YuNet works best on ~640px images, so detect on a small copy and scale boxes/landmarks back."""
    import cv2
    h, w = bgr.shape[:2]
    s = min(1.0, 640 / max(h, w))
    small = cv2.resize(bgr, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA) if s < 1 else bgr
    det = cv2.FaceDetectorYN.create(str(FACE_DIR / "yunet_2023mar.onnx"), "", (small.shape[1], small.shape[0]), 0.6, 0.3, 50)
    _, faces = det.detect(small)
    if faces is None:
        return []
    faces = faces.copy()
    faces[:, :14] /= s
    return list(faces)


def largest_face(img) -> int:
    """Size in px of the biggest face in a PIL image (0 when none)."""
    import cv2
    try:
        with _lock:
            _load()
            faces = _detect(cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2BGR))
        return int(max((max(f[2], f[3]) for f in faces), default=0))
    except Exception:  # noqa: BLE001
        logger.exception("Face detect failed")
        return 0


def _blend(face_px: float) -> float:
    """GFPGAN restores at 512px: on bigger faces a full blend swaps real skin for a smooth, fake-looking face."""
    if face_px <= 384:
        return BLEND
    return max(MIN_BLEND, BLEND * 384 / face_px)


def restore_faces(img):
    """PIL in, PIL out. Faces smaller than 48px or no faces: returned unchanged."""
    import cv2
    from PIL import Image
    try:
        with _lock:
            sess = _load()
            bgr = cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2BGR)
            h, w = bgr.shape[:2]
            out = bgr.astype(np.float32)
            faces = sorted(_detect(bgr), key=lambda f: -f[2] * f[3])[:4]
            for f in faces:
                if min(f[2], f[3]) < 48:
                    continue
                pts = f[4:14].reshape(5, 2).astype(np.float32)
                M, _ = cv2.estimateAffinePartial2D(pts, TEMPLATE, method=cv2.LMEDS)
                if M is None:
                    continue
                crop = cv2.warpAffine(bgr, M, (512, 512), borderMode=cv2.BORDER_REFLECT_101, flags=cv2.INTER_LINEAR)
                x = (crop[:, :, ::-1].astype(np.float32) / 255.0 - 0.5) / 0.5
                y = sess.run(None, {"input": x.transpose(2, 0, 1)[None]})[0][0]
                fixed = ((np.clip(y, -1, 1) + 1) / 2 * 255).transpose(1, 2, 0)[:, :, ::-1]
                # soft oval mask in face space, warped back to the image
                mask = np.zeros((512, 512), np.float32)
                cv2.ellipse(mask, (256, 270), (190, 235), 0, 0, 360, 1.0, -1)
                mask = cv2.GaussianBlur(mask, (0, 0), 22)
                inv = cv2.invertAffineTransform(M)
                back = cv2.warpAffine(fixed.astype(np.float32), inv, (w, h), flags=cv2.INTER_LANCZOS4,
                                      borderMode=cv2.BORDER_CONSTANT)
                m = cv2.warpAffine(mask, inv, (w, h), flags=cv2.INTER_LINEAR)[..., None] * _blend(max(f[2], f[3]))
                out = out * (1 - m) + back * m
            if not faces:
                return img
            return Image.fromarray(cv2.cvtColor(np.clip(out, 0, 255).astype(np.uint8), cv2.COLOR_BGR2RGB))
    except Exception:  # noqa: BLE001
        logger.exception("Luchii Face Fix failed; keeping the original face")
        return img
