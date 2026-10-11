from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

import asyncio
import hashlib
import json
import os
import random
import re
import time
import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import bcrypt
import httpx
import jwt
from fastapi import FastAPI, APIRouter, HTTPException, Request, Depends, UploadFile, File, Form
import base64
from fastapi.responses import Response, StreamingResponse
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorGridFSBucket
from pydantic import BaseModel, EmailStr, Field
from starlette.middleware.cors import CORSMiddleware

import local_engines
import frasberg_gpu
import kaggle_gpu
import aws_gpu
import engine_rules
import engine_runtime
import engine_systems

client = AsyncIOMotorClient(os.environ["MONGO_URL"])
db = client[os.environ["DB_NAME"]]
fs = AsyncIOMotorGridFSBucket(db, bucket_name="voice_samples")
takes_fs = AsyncIOMotorGridFSBucket(db, bucket_name="voice_takes")
models_fs = AsyncIOMotorGridFSBucket(db, bucket_name="models3d")
media_fs = AsyncIOMotorGridFSBucket(db, bucket_name="media")
frasberg_gpu.init(db)
kaggle_gpu.init(db)
aws_gpu.init(db)
engine_systems.init(db)
if kaggle_gpu.enabled():
    frasberg_gpu.ON_DEMAND.add("frasberg-motion-free")
if aws_gpu.enabled():
    frasberg_gpu.ON_DEMAND.update(aws_gpu.models())

JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALG = "HS256"
FRASBERG_BASE = os.environ["FRASBERG_BASE_URL"].rstrip("/")
FRASBERG_KEYS = [k.strip() for k in os.environ["FRASBERG_API_KEYS"].split(",") if k.strip()]
KEY_ROUTES = {f: p.split("|") for f, p in (r.split(":") for r in os.environ["FRASBERG_KEY_ROUTES"].split(","))}


def key_order(feature: Optional[str]) -> list:
    prefs = KEY_ROUTES.get(feature or "", [])
    first = [i for p in prefs for i, k in enumerate(FRASBERG_KEYS) if k.startswith(f"frb_live_{p}")]
    return first + [i for i in range(len(FRASBERG_KEYS)) if i not in first]

# Short hints: SD/CLIP reads only ~77 tokens, so long hints used to be cut off and the style was lost.
STYLE_HINTS = {
    "cinematic": "cinematic film still, dramatic lighting, rich color grade, shallow depth of field",
    "photorealistic": "photorealistic photo, natural light, 85mm lens, sharp focus, fine detail",
    "3d": "3D render, octane render, glossy materials, studio lighting",
    "anime": "anime key visual, cel shading, clean line art, vibrant colors",
    "digital-art": "digital art illustration, vivid colors, glowing highlights, artstation",
    "product": "product photography, studio backdrop, softbox lighting, crisp reflections",
}
LUCHII_IMAGE_MODELS = {
    "Luchii Nova-Muse": "RAW photo, ultra realistic, sharp focus",
    "Luchii Dreamline": "painterly, vivid color",
    "Luchii Vision": "concept art, dramatic composition",
}
# Built-in model routing: the style (and the words in the prompt) choose the Luchii model, no picker needed.
STYLE_MODEL = {"photorealistic": "Luchii Nova-Muse", "cinematic": "Luchii Nova-Muse", "product": "Luchii Nova-Muse",
               "anime": "Luchii Dreamline", "digital-art": "Luchii Dreamline", "3d": "Luchii Vision"}
ART_WORDS = re.compile(r"\b(anime|manga|cartoon|illustration|painting|painterly|watercolou?r|sketch|pixel art|vector|logo|icon|comic)\b", re.I)
RENDER_WORDS = re.compile(r"\b(3d|render|octane|concept art|isometric|low poly|sculpture|claymation)\b", re.I)
# Painter-X: the chosen style becomes part of the edit instruction, so style chips work for remixes too.
EDIT_STYLE = {
    "cinematic": "make it look like a cinematic film still", "photorealistic": "make it photorealistic",
    "3d": "turn it into a 3D render", "anime": "turn it into an anime illustration",
    "digital-art": "turn it into vivid digital art", "product": "make it a clean studio product photo",
}


def auto_model(prompt: str, style: Optional[str]) -> str:
    if ART_WORDS.search(prompt):
        return "Luchii Dreamline"
    if RENDER_WORDS.search(prompt) and style != "photorealistic":
        return "Luchii Vision"
    return STYLE_MODEL.get(style or "", "Luchii Nova-Muse")


# ---------- prompt understanding: make results match what the user described ----------
FILLER = re.compile(r"^\s*(?:please\s+)?(?:(?:can|could|would) you\s+)?(?:please\s+)?(?:i want\s+|i need\s+|i'd like\s+)?"
                    r"(?:(?:create|generate|make|draw|render|design|produce|give me|show me)\s+(?:me\s+)?)?"
                    r"(?:an?\s+)?(?:(?:image|picture|pic|photo|photograph|drawing|render)\s+(?:of|showing|with)\s+)", re.I)
CLOTHING_WORDS = re.compile(r"\b(wearing|wears|dressed|dress|gown|shirt|t-shirt|blouse|suit|tuxedo|jacket|coat|hoodie|sweater|"
                            r"jeans|pants|trousers|skirt|shorts|uniform|armou?r|kimono|saree|sari|outfit|clothes|clothing|"
                            r"bikini|swimsuit|robe|cloak|cape|vest|overalls|scarf|leather|denim)\b", re.I)


def clean_prompt(p: str) -> str:
    """Drop chat filler ("can you create an image of...") so the 77-token model budget is spent on the subject."""
    p = re.sub(r"\s+", " ", (p or "").strip())
    out = FILLER.sub("", p, count=1).strip(" .,")
    out = re.sub(r"[\s,.]*\bplease\b[\s.!]*$", "", out, flags=re.I).strip(" .,")
    return out or p


LEAD_SPLIT = re.compile(r",|\.|;|\b(?:wearing|sitting|standing|lying|holding|walking|running|flying|swimming|on|in|inside|beside|"
                        r"near|next to|under|over|with|at|by|against|surrounded|while|who|that)\b", re.I)


def emphasize_subject(p: str) -> str:
    """Long descriptions bury the main subject, and the model then paints only the scene. Lead with the subject
    once more (e.g. "a small red fox, a small red fox wearing a scarf on a rock by a lake...")."""
    if len(p.split()) < 14:
        return p
    lead = LEAD_SPLIT.split(p, maxsplit=1)[0].strip()
    return f"{lead}, {p}" if 1 <= len(lead.split()) <= 6 else p


EDIT_VERBS = re.compile(r"\b(make|turn|change|give|add|remove|replace|swap|dye|colou?r|recolou?r|convert|transform|put|"
                        r"erase|delete|switch|paint|dress)\b", re.I)
WHO = r"(?:her|him|them|his|their|it|the (?:person|girl|boy|man|woman|guy|lady|model|subject))"


NEW_OUTFITS = ["a black leather jacket", "a white linen shirt", "a red knit sweater", "a denim jacket", "a beige trench coat",
               "a green hoodie", "a navy blazer", "a yellow summer dress", "a striped t-shirt", "a grey wool coat"]


def normalize_instruction(text: str) -> str:
    """Rewrite casual edit requests into the clear commands Painter-X follows best.
    e.g. "give a blue hair and change clothes" -> "make the hair blue and change the clothes to a denim jacket"."""
    t = re.sub(r"\s+", " ", (text or "").strip().rstrip(".!"))
    t = re.sub(r"^(?:please\s+)?(?:(?:can|could|would) you\s+)?(?:please\s+)?", "", t, flags=re.I)
    # "give (her) (a) blue hair" / "give her blonde hair" -> "make the hair blue"
    t = re.sub(rf"\bgive\s+(?:{WHO}\s+)?(?:an?\s+)?([a-z]+(?:[- ][a-z]+)?)\s+hair\b", r"make the hair \1", t, flags=re.I)
    # "(make|turn|dye|colo(u)r) (her) hair X" -> "make the hair X"
    t = re.sub(rf"\b(?:make|turn|dye|colou?r)\s+(?:{WHO}\s+)?hair\s+(?:to\s+|into\s+)?", "make the hair ", t, flags=re.I)
    # "give her sunglasses" -> "add sunglasses"
    t = re.sub(rf"\bgive\s+(?:{WHO}\s+)?(?:an?\s+)?", "add ", t, flags=re.I)
    # "change (her) clothes" with no target -> pick a clear new outfit
    t = re.sub(rf"\bchange\s+(?:{WHO}\s+|the\s+)?(clothes|clothing|outfit|dress)\b(?!\s+(?:to|into|for|with|in)\b)",
               lambda m: f"change the {m.group(1)} to {random.choice(NEW_OUTFITS)}", t, flags=re.I)
    t = re.sub(rf"\bchange\s+(?:{WHO}\s+)?(clothes|clothing|outfit)\s+(?:to|into|for)\s+", r"dress them in ", t, flags=re.I)
    return t.strip() or text


def is_edit_command(text: str) -> bool:
    return bool(EDIT_VERBS.search(text or ""))


PHOTO_MODELS = {"Luchii Nova-Muse", "Luchii Dreamline", "Luchii Vision"}  # rendered by the photoreal engine (local_engines.generate_photo)
PERSON_WORDS = re.compile(r"\b(portrait|woman|women|man|men|girl|boy|person|people|model|face|selfie|lady|guy)s?\b", re.I)
UPSCALE_PRESET = "Enhance and upscale this image to crisp 4K detail, preserving the original composition and colors"

app = FastAPI()
api = APIRouter(prefix="/api")
logger = logging.getLogger("luchii")
logging.basicConfig(level=logging.INFO)


# ---------- helpers ----------
def now_iso():
    return datetime.now(timezone.utc).isoformat()


def hash_password(p: str) -> str:
    return bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode()


def verify_password(p: str, h: str) -> bool:
    try:
        return bcrypt.checkpw(p.encode(), h.encode())
    except ValueError:
        return False


def make_token(user_id: str, email: str) -> str:
    payload = {"sub": user_id, "email": email, "type": "access",
               "exp": datetime.now(timezone.utc) + timedelta(days=7)}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def public_user(u: dict) -> dict:
    return {"id": u["id"], "name": u.get("name", ""), "email": u["email"]}


async def optional_user(request: Request) -> Optional[dict]:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    try:
        payload = jwt.decode(auth[7:], JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.InvalidTokenError:
        return None
    return await db.users.find_one({"id": payload.get("sub")}, {"_id": 0, "password_hash": 0})


async def current_user(user: Optional[dict] = Depends(optional_user)) -> dict:
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def as_data_url(b64: str, mime: str = "image/png") -> str:
    return b64 if b64.startswith("data:") else f"data:{mime};base64,{b64}"


def strip_data_url(s: str) -> str:
    return s.split(",", 1)[1] if s.startswith("data:") else s


def upstream_detail(r: httpx.Response) -> str:
    try:
        d = r.json()
    except ValueError:
        return f"Frasberg server returned HTTP {r.status_code} (Bad Gateway)" if r.status_code == 502 else f"Frasberg returned HTTP {r.status_code}"
    det = d.get("detail") if isinstance(d, dict) else None
    if isinstance(det, dict):
        return det.get("message") or str(det)
    if isinstance(det, str):
        return det
    err = d.get("error") if isinstance(d, dict) else None
    if isinstance(err, dict):
        return err.get("message") or str(err)
    return f"Frasberg returned HTTP {r.status_code}"


async def frasberg(method: str, path: str, json: Optional[dict] = None, key_index: Optional[int] = None,
                   feature: Optional[str] = None):
    """Call Frasberg, rotating through keys on permission / server errors. Returns (response, key_index)."""
    order = [key_index] if key_index is not None else key_order(feature)
    last, best = "Frasberg is unavailable", None
    async with httpx.AsyncClient(timeout=180) as hc:
        for i in order:
            try:
                r = await hc.request(method, f"{FRASBERG_BASE}{path}", json=json,
                                     headers={"Authorization": f"Bearer {FRASBERG_KEYS[i]}"})
            except httpx.HTTPError as e:
                last = f"Frasberg connection error: {e.__class__.__name__}"
                continue
            if r.status_code < 400:
                return r, i
            last = upstream_detail(r)
            if r.status_code != 403:
                best = last
            logger.warning("Frasberg %s %s key#%s -> %s %s", method, path, i, r.status_code, last)
            if r.status_code in (400, 404, 422) or r.status_code >= 500:
                break
    raise HTTPException(status_code=424, detail=f"Frasberg: {best or last}")


async def frasberg_image(payload: dict) -> str:
    r, _ = await frasberg("POST", "/generate/image", payload, feature="image")
    d = r.json()
    b64 = d.get("image_base64") or d.get("image") or (d.get("data") or [{}])[0].get("b64_json")
    if not b64:
        raise HTTPException(status_code=424, detail="Frasberg returned no image")
    return as_data_url(b64, d.get("mime") or "image/png")


async def gpu_image(prompt: str, aspect: Optional[str]) -> Optional[str]:
    if not await frasberg_gpu.is_online("frasberg-image"):
        return None
    try:
        g = await frasberg_gpu.submit("image", "frasberg-image", prompt, aspect_ratio=aspect or "1:1")
        for _ in range(240):
            await asyncio.sleep(0.5)
            cur = await frasberg_gpu.get_job(g["id"])
            if cur["status"] == "completed":
                return as_data_url(base64.b64encode(await frasberg_gpu.output_bytes(cur)).decode(), cur.get("mime") or "image/png")
            if cur["status"] == "failed":
                break
        else:
            await db.gpu_jobs.update_one({"id": g["id"], "status": "queued"},
                                         {"$set": {"status": "failed", "error": "Timed out waiting for a GPU worker"}})
    except HTTPException as e:
        logger.warning("Frasberg Image GPU failed: %s", e.detail)
    return None


FRASBERG_IMAGE_RETRY_S = 600
_frasberg_image_down_until = 0.0


async def image_with_fallback(frasberg_payload: dict, local_fn, *args) -> tuple:
    global _frasberg_image_down_until
    # When Frasberg's image API is down, every request used to wait for it to fail first. Skip it for 10 min.
    if time.time() >= _frasberg_image_down_until:
        try:
            return await frasberg_image(frasberg_payload), "frasberg"
        except HTTPException as e:
            _frasberg_image_down_until = time.time() + FRASBERG_IMAGE_RETRY_S
            logger.warning("Frasberg image failed (%s); using Luchii in-house image engine", e.detail)
    if local_engines.image_busy():
        raise HTTPException(status_code=429, detail="Frasberg Creator is finishing another image. Yours is in the queue.",
                            headers={"Retry-After": "8"})
    try:
        return await asyncio.to_thread(local_fn, *args), "luchii-local"
    except local_engines.UnsafeImage:
        raise HTTPException(status_code=422, detail="The Luchii safety filter blocked this result. Please try a different prompt.")
    except Exception as e:  # noqa: BLE001
        logger.exception("Local image engine failed")
        raise HTTPException(status_code=424, detail=f"Luchii image engine error: {e.__class__.__name__}")


async def speak_with_fallback(text: str, voice: Optional[str]) -> dict:
    try:
        return {**(await speak(text, voice)), "engine": "frasberg"}
    except HTTPException as e:
        logger.warning("Frasberg voice failed (%s); using Luchii in-house voice engine", e.detail)
    try:
        return {**(await asyncio.to_thread(local_engines.synthesize, text, voice or "nova")), "engine": "luchii-local"}
    except Exception as e:  # noqa: BLE001
        logger.exception("Local voice engine failed")
        raise HTTPException(status_code=424, detail=f"Luchii voice engine error: {e.__class__.__name__}")


def wants_publish(user: Optional[dict], publish: Optional[bool]) -> bool:
    """There is no public community gallery: every image stays private to its creator."""
    return False


async def resolve_parent(parent_id: Optional[str], src_image: str, session_id: Optional[str],
                         user: Optional[dict]) -> dict:
    """Remix history: link a new edit to the image it was made from. A fresh upload becomes a hidden step-0
    'source' doc, so the chain always starts at the original photo."""
    if parent_id:
        p = await db.generations.find_one({"id": parent_id}, {"_id": 0, "id": 1, "root_id": 1, "step": 1})
        if p:
            return {"parent_id": p["id"], "root_id": p.get("root_id") or p["id"], "step": (p.get("step") or 0) + 1}
    src = {"id": str(uuid.uuid4()), "kind": "source", "hidden": True, "prompt": "Original photo",
           "image_base64": src_image, "session_id": session_id, "user_id": user["id"] if user else None,
           "author": user.get("name") if user else None, "step": 0, "created_at": now_iso()}
    src["root_id"] = src["id"]
    if len(src_image) > LIST_THUMB_OVER:
        try:
            src["thumb_base64"] = await asyncio.to_thread(local_engines.preview, src_image)
        except Exception:  # noqa: BLE001
            logger.exception("Preview for source failed")
    await db.generations.insert_one(src.copy())
    return {"parent_id": src["id"], "root_id": src["id"], "step": 1}


async def save_generation(kind: str, prompt: str, image: str, session_id: Optional[str],
                          user: Optional[dict], style: Optional[str] = None, aspect: Optional[str] = None,
                          model: Optional[str] = None, publish: Optional[bool] = None,
                          lineage: Optional[dict] = None, extra: Optional[dict] = None) -> dict:
    doc = {
        "id": str(uuid.uuid4()), "kind": kind, "prompt": prompt, "style": style,
        "aspect_ratio": aspect, "model": model, "image_base64": image, "session_id": session_id,
        "user_id": user["id"] if user else None, "author": user.get("name") if user else None,
        "created_at": now_iso(), **(lineage or {}), **(extra or {}),
    }
    if wants_publish(user, publish):
        doc.update(public=True, published_at=doc["created_at"])
    if image and len(image) > LIST_THUMB_OVER:
        try:  # 4K / HD images: lists send a light preview, the full file loads on open/download
            doc["thumb_base64"] = await asyncio.to_thread(local_engines.preview, image)
        except Exception:  # noqa: BLE001
            logger.exception("Preview for generation failed")
    await db.generations.insert_one(doc.copy())
    return doc


LIST_THUMB_OVER = 900_000  # base64 chars


def _listed(doc: dict) -> dict:
    thumb = doc.pop("thumb_base64", None)
    if thumb:
        doc["image_base64"], doc["has_full"] = thumb, True
    return doc


# ---------- models ----------
class RegisterIn(BaseModel):
    name: str = Field(min_length=1)
    email: EmailStr
    password: str = Field(min_length=6)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class GenerateIn(BaseModel):
    prompt: str = Field(min_length=1)
    style: Optional[str] = "cinematic"
    aspect_ratio: Optional[str] = "1:1"
    session_id: Optional[str] = None
    model: Optional[str] = None
    quality: Optional[str] = None  # "draft" (Nova-Muse quick preview) or "full"
    seed: Optional[int] = None
    publish: Optional[bool] = None  # None = follow the user's auto-publish setting


class EditIn(BaseModel):
    prompt: str = Field(min_length=1)
    image_base64: str
    session_id: Optional[str] = None
    style: Optional[str] = None
    parent_id: Optional[str] = None  # generation this remix was made from (remix history)
    publish: Optional[bool] = None


class CutoutIn(BaseModel):
    image_base64: str
    session_id: Optional[str] = None
    parent_id: Optional[str] = None
    publish: Optional[bool] = None


class UpscaleIn(BaseModel):
    image_base64: str
    prompt: Optional[str] = "Upscaled"
    session_id: Optional[str] = None
    parent_id: Optional[str] = None
    publish: Optional[bool] = None


class TTSIn(BaseModel):
    text: str = Field(min_length=1, max_length=4096)
    voice: str = "nova"
    hd: bool = False


# ---------- routes ----------
@api.get("/")
async def root():
    return {"message": "Frasberg Creator API is running"}


@api.post("/auth/register")
async def register(body: RegisterIn):
    email = body.email.lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="Email already registered")
    user = {"id": str(uuid.uuid4()), "name": body.name.strip(), "email": email,
            "password_hash": hash_password(body.password), "created_at": now_iso()}
    await db.users.insert_one(user.copy())
    return {"token": make_token(user["id"], email), "user": public_user(user)}


@api.post("/auth/login")
async def login(body: LoginIn):
    email = body.email.lower()
    ident = email
    att = await db.login_attempts.find_one({"identifier": ident})
    if att and att.get("count", 0) >= 5 and att.get("locked_until", "") > now_iso():
        raise HTTPException(status_code=429, detail="Too many attempts. Try again in 15 minutes.")
    user = await db.users.find_one({"email": email})
    if not user or not verify_password(body.password, user.get("password_hash", "")):
        await db.login_attempts.update_one(
            {"identifier": ident},
            {"$inc": {"count": 1},
             "$set": {"locked_until": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()}},
            upsert=True)
        raise HTTPException(status_code=401, detail="Invalid email or password")
    await db.login_attempts.delete_one({"identifier": ident})
    return {"token": make_token(user["id"], email), "user": public_user(user)}


@api.get("/auth/me")
async def me(user: dict = Depends(current_user)):
    return public_user(user)


@api.post("/generate")
async def generate(body: GenerateIn, user: Optional[dict] = Depends(optional_user)):
    subject = clean_prompt(body.prompt)
    model = body.model if body.model in LUCHII_IMAGE_MODELS else auto_model(subject, body.style)
    draft = body.quality == "draft" and model in PHOTO_MODELS
    seed = body.seed if body.seed is not None else random.randint(0, 2**31 - 1)
    # The photo hint ("RAW photo") fights 3D/illustration styles, so the style hint wins there.
    model_hint = "" if model in PHOTO_MODELS and body.style in ("3d", "digital-art", "anime") else LUCHII_IMAGE_MODELS.get(model or "")
    hint = ", ".join(h for h in (model_hint, STYLE_HINTS.get(body.style or "", "")) if h)
    full = f"{subject}. {hint}. Aspect ratio {body.aspect_ratio}." if hint else subject
    img, engine = await gpu_image(full, body.aspect_ratio), "frasberg-image"
    if not img:
        focus = emphasize_subject(subject)
        local_prompt = f"{focus}, {hint}" if hint else focus
        if model in PHOTO_MODELS:
            # cfg 1.0 ignores negative prompts, so steer people toward clothing, but never override clothes the user described.
            if PERSON_WORDS.search(subject) and not CLOTHING_WORDS.search(subject):
                local_prompt = f"{focus}, fully clothed, wearing a stylish outfit, {hint}"
            elif PERSON_WORDS.search(subject):
                local_prompt = f"{focus}, fully clothed, {hint}"
            local_fn, args = local_engines.generate_photo, (local_prompt, body.aspect_ratio, draft, seed)
        else:
            local_fn, args = local_engines.generate_image, (local_prompt, body.aspect_ratio)
        img, engine = await image_with_fallback({"prompt": full, "style": body.style, "aspect_ratio": body.aspect_ratio},
                                                local_fn, *args)
    doc = await save_generation("generate", body.prompt, img, body.session_id, user, body.style, body.aspect_ratio, model,
                                publish=body.publish)
    return {"id": doc["id"], "kind": "generate", "image_base64": img, "prompt": body.prompt, "style": body.style,
            "model": model, "engine": engine, "quality": "draft" if draft else "full", "seed": seed,
            "aspect_ratio": body.aspect_ratio, "public": bool(doc.get("public"))}


@api.post("/edit")
async def edit(body: EditIn, user: Optional[dict] = Depends(optional_user)):
    raw = body.prompt.strip().rstrip(".")
    if is_edit_command(raw):
        # A command ("make the hair blue", "change the clothes") is mapped to the regions it names and edited
        # in one fast masked pass on the warm photo engine (~30-60s); the rest of the photo is kept.
        instruction = normalize_instruction(raw)
        if body.style in ("anime", "3d", "digital-art"):
            instruction = f"{instruction}, {EDIT_STYLE[body.style]}"
        local_fn, args, mode = local_engines.fast_edit, (instruction, body.image_base64), "instruct"
    else:
        # A description ("a woman in a red dress on a beach") re-renders the photo toward that description.
        instruction = f"{raw}, {EDIT_STYLE[body.style]}" if EDIT_STYLE.get(body.style or "") else raw
        local_fn, args, mode = local_engines.fast_edit, (instruction, body.image_base64), "describe"
    img, engine = await image_with_fallback({"prompt": instruction, "image_base64": strip_data_url(body.image_base64)},
                                            local_fn, *args)
    lineage = await resolve_parent(body.parent_id, body.image_base64, body.session_id, user)
    doc = await save_generation("edit", body.prompt, img, body.session_id, user, "Remix", model="Luchii Painter-X",
                                publish=body.publish, lineage=lineage, extra={"instruction": instruction, "edit_mode": mode})
    return {"id": doc["id"], "kind": "edit", "model": "Luchii Painter-X", "image_base64": img, "prompt": body.prompt,
            "engine": engine, "style": body.style, "instruction": instruction, "edit_mode": mode,
            "public": bool(doc.get("public")), **lineage}


@api.post("/remove-bg")
async def remove_bg(body: CutoutIn, user: Optional[dict] = Depends(optional_user)):
    if local_engines.image_busy():
        raise HTTPException(status_code=429, detail="Frasberg Creator is finishing another image. Yours is in the queue.",
                            headers={"Retry-After": "8"})
    try:
        img = await asyncio.to_thread(local_engines.remove_background, body.image_base64)
    except Exception as e:  # noqa: BLE001
        logger.exception("Background removal failed")
        raise HTTPException(status_code=424, detail=f"Luchii cutout engine error: {e.__class__.__name__}")
    lineage = await resolve_parent(body.parent_id, body.image_base64, body.session_id, user)
    doc = await save_generation("cutout", "Background removed", img, body.session_id, user, "Cutout", model="Luchii Prime",
                                publish=body.publish, lineage=lineage)
    return {"id": doc["id"], "kind": "cutout", "model": "Luchii Prime", "image_base64": img, "prompt": "Background removed",
            "engine": "luchii-local", "public": bool(doc.get("public")), **lineage}


@api.post("/upscale")
async def upscale(body: UpscaleIn, user: Optional[dict] = Depends(optional_user)):
    img, engine = await image_with_fallback({"prompt": UPSCALE_PRESET, "image_base64": strip_data_url(body.image_base64)},
                                            local_engines.upscale_image, body.image_base64)
    lineage = await resolve_parent(body.parent_id, body.image_base64, body.session_id, user)
    doc = await save_generation("upscale", body.prompt or "Upscaled", img, body.session_id, user, "Upscale 4K",
                                publish=body.publish, lineage=lineage)
    return {"id": doc["id"], "kind": "upscale", "model": "Luchii Prime", "image_base64": img, "prompt": body.prompt,
            "engine": engine, "public": bool(doc.get("public")), **lineage}


# ---------- image jobs (async; photoreal renders take ~2 min, longer than the ingress timeout) ----------
IMAGE_JOB_STALE_S = 20 * 60


async def _run_image_job(jid: str, fn, body, user: Optional[dict]):
    for attempt in range(150):
        try:
            await db.image_jobs.update_one({"id": jid}, {"$set": {"status": "running", "updated_at": now_iso()}})
            res = await fn(body, user)
            break
        except HTTPException as e:
            if e.status_code == 429 and attempt < 149:
                await db.image_jobs.update_one({"id": jid}, {"$set": {"status": "queued", "updated_at": now_iso()}})
                await asyncio.sleep(8)
                continue
            await db.image_jobs.update_one({"id": jid}, {"$set": {"status": "failed", "error": str(e.detail), "updated_at": now_iso()}})
            return
        except Exception as e:  # noqa: BLE001
            logger.exception("Image job %s failed", jid)
            await db.image_jobs.update_one({"id": jid}, {"$set": {"status": "failed", "error": e.__class__.__name__, "updated_at": now_iso()}})
            return
    res.pop("image_base64", None)
    await db.image_jobs.update_one({"id": jid}, {"$set": {"status": "completed", "result": res, "updated_at": now_iso()}})


async def _start_image_job(kind: str, fn, body, user: Optional[dict]) -> dict:
    job = {"id": str(uuid.uuid4()), "kind": kind, "status": "queued", "result": None, "error": None,
           "model": getattr(body, "model", None), "user_id": user["id"] if user else None,
           "created_at": now_iso(), "updated_at": now_iso()}
    await db.image_jobs.insert_one(job.copy())
    asyncio.create_task(_run_image_job(job["id"], fn, body, user))
    return {"job_id": job["id"], "status": "queued", "kind": kind}


@api.post("/generate/jobs")
async def generate_job(body: GenerateIn, user: Optional[dict] = Depends(optional_user)):
    return await _start_image_job("generate", generate, body, user)


@api.post("/edit/jobs")
async def edit_job(body: EditIn, user: Optional[dict] = Depends(optional_user)):
    return await _start_image_job("edit", edit, body, user)


@api.post("/remove-bg/jobs")
async def remove_bg_job(body: CutoutIn, user: Optional[dict] = Depends(optional_user)):
    return await _start_image_job("cutout", remove_bg, body, user)


@api.post("/upscale/jobs")
async def upscale_job(body: UpscaleIn, user: Optional[dict] = Depends(optional_user)):
    return await _start_image_job("upscale", upscale, body, user)


@api.get("/image-jobs/{job_id}")
async def image_job_status(job_id: str):
    job = await db.image_jobs.find_one({"id": job_id}, {"_id": 0})
    if not job:
        raise HTTPException(status_code=404, detail="Image job not found")
    if job["status"] in ("queued", "running"):
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(job["updated_at"])).total_seconds()
        if age > IMAGE_JOB_STALE_S:
            job["status"], job["error"] = "failed", "Interrupted by a server restart. Please try again."
            await db.image_jobs.update_one({"id": job_id}, {"$set": {"status": "failed", "error": job["error"]}})
    out = {"job_id": job["id"], "kind": job["kind"], "status": job["status"], "error": job.get("error"), "model": job.get("model")}
    if job["status"] == "completed" and job.get("result"):
        gen = await db.generations.find_one({"id": job["result"]["id"]}, {"_id": 0, "image_base64": 1})
        out["result"] = {**job["result"], "image_base64": (gen or {}).get("image_base64")}
    return out


@api.post("/tts")
async def tts(body: TTSIn):
    return {**(await speak_with_fallback(body.text, body.voice)), "voice": body.voice}


@api.get("/generations")
async def generations(session_id: str, limit: int = 8):
    cur = db.generations.find({"session_id": session_id, "image_base64": {"$ne": None}, "hidden": {"$ne": True}}, {"_id": 0})
    return [_listed(d) for d in await cur.sort("created_at", -1).limit(min(limit, 60)).to_list(None)]


@api.get("/my/generations")
async def my_generations(limit: int = 60, user: dict = Depends(current_user)):
    cur = db.generations.find({"user_id": user["id"], "image_base64": {"$ne": None}, "hidden": {"$ne": True}}, {"_id": 0})
    return [_listed(d) for d in await cur.sort("created_at", -1).limit(min(limit, 200)).to_list(None)]


@api.get("/showcase")
async def showcase(limit: int = 8):
    cur = db.generations.find({"kind": "generate", "featured": True, "image_base64": {"$ne": None}},
                              {"_id": 0, "id": 1, "prompt": 1, "style": 1, "image_base64": 1})
    return await cur.sort("created_at", -1).limit(min(limit, 24)).to_list(None)


class BulkDeleteIn(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=200)


@api.post("/generations/bulk-delete")
async def bulk_delete_generations(body: BulkDeleteIn, user: dict = Depends(current_user)):
    res = await db.generations.delete_many({"id": {"$in": body.ids}, "user_id": user["id"]})
    return {"deleted": res.deleted_count}


@api.delete("/generations/{gen_id}")
async def delete_generation(gen_id: str, user: dict = Depends(current_user)):
    res = await db.generations.delete_one({"id": gen_id, "user_id": user["id"]})
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail="Not found")
    return {"deleted": gen_id}


HISTORY_FIELDS = {"_id": 0, "id": 1, "parent_id": 1, "root_id": 1, "step": 1, "kind": 1, "prompt": 1, "instruction": 1,
                  "model": 1, "style": 1, "created_at": 1, "public": 1, "mini_base64": 1, "thumb_base64": 1}


@api.get("/generations/{gen_id}/history")
async def remix_history(gen_id: str):
    """Every version in this photo's Painter-X chain (original upload, each remix, upscales, cut-outs), oldest first,
    with small previews. parent_id links let the client draw the path to any version and branch from it."""
    g = await db.generations.find_one({"id": gen_id}, {"_id": 0, "id": 1, "root_id": 1})
    if not g:
        raise HTTPException(status_code=404, detail="Not found")
    root = g.get("root_id") or g["id"]
    docs = await db.generations.find({"$or": [{"id": root}, {"root_id": root}], "image_base64": {"$ne": None}},
                                     HISTORY_FIELDS).sort("created_at", 1).limit(80).to_list(80)
    for d in docs:
        if not d.get("mini_base64"):
            full = await db.generations.find_one({"id": d["id"]}, {"_id": 0, "image_base64": 1})
            try:
                d["mini_base64"] = await asyncio.to_thread(local_engines.preview, d.pop("thumb_base64", None) or full["image_base64"], 320)
                await db.generations.update_one({"id": d["id"]}, {"$set": {"mini_base64": d["mini_base64"]}})
            except Exception:  # noqa: BLE001
                logger.exception("History preview failed for %s", d["id"])
                d["mini_base64"] = None
        d.pop("thumb_base64", None)
        d["public"] = bool(d.get("public"))
        d.setdefault("step", 0 if d["id"] == root else None)
    return {"root_id": root, "current_id": gen_id, "items": docs}


@api.get("/share/{gen_id}")
async def share(gen_id: str):
    doc = await db.generations.find_one({"id": gen_id},
                                        {"_id": 0, "id": 1, "kind": 1, "model": 1, "prompt": 1, "style": 1, "image_base64": 1, "author": 1,
                                         "parent_id": 1, "root_id": 1, "step": 1, "public": 1, "instruction": 1})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    doc["public"] = bool(doc.get("public"))
    return doc


async def frasberg_upload(path: str, filename: str, data: bytes, ctype: str, feature: str) -> dict:
    last, best = "Frasberg is unavailable", None
    async with httpx.AsyncClient(timeout=120) as hc:
        for i in key_order(feature):
            try:
                r = await hc.post(f"{FRASBERG_BASE}{path}", headers={"Authorization": f"Bearer {FRASBERG_KEYS[i]}"},
                                  files={"file": (filename, data, ctype)})
            except httpx.HTTPError as e:
                last = f"Frasberg connection error: {e.__class__.__name__}"
                continue
            if r.status_code < 400:
                return r.json()
            last = upstream_detail(r)
            if r.status_code != 403:
                best = last
            logger.warning("Frasberg upload %s key#%s -> %s %s", path, i, r.status_code, last)
            if r.status_code in (400, 413, 422) or r.status_code >= 500:
                break
    raise HTTPException(status_code=424, detail=f"Frasberg: {best or last}")


async def speak(text: str, voice: Optional[str] = None) -> dict:
    payload = {"text": text, **({"voice": voice} if voice else {})}
    r, _ = await frasberg("POST", "/voice/speak", payload, feature="tts")
    d = r.json()
    if not d.get("audio_base64"):
        raise HTTPException(status_code=424, detail="Frasberg returned no audio")
    return {"audio_base64": strip_data_url(d["audio_base64"]), "mime": d.get("mime", "audio/mp3")}


@api.post("/sts")
async def speech_to_speech(file: UploadFile = File(...), voice: str = Form("nova"),
                           user: Optional[dict] = Depends(optional_user)):
    audio = await file.read()
    if not audio:
        raise HTTPException(status_code=400, detail="Empty audio file")
    if voice == "clone" and not (user and user.get("voice_clone")):
        raise HTTPException(status_code=400, detail="Log in and save a voice sample on the Voice Cloning page first")
    try:
        d = await frasberg_upload("/voice/transcribe", file.filename or "voice.webm", audio,
                                  file.content_type or "audio/webm", "stt")
        text = (d.get("text") or "").strip()
    except HTTPException as e:
        logger.warning("Frasberg transcribe failed (%s); using Luchii in-house transcription", e.detail)
        try:
            text = await asyncio.to_thread(local_engines.transcribe, audio)
        except Exception as le:  # noqa: BLE001
            logger.exception("Local transcribe failed")
            raise HTTPException(status_code=400,
                                detail=f"Could not transcribe audio: {le.__class__.__name__}")
    if not text:
        raise HTTPException(status_code=400, detail="No speech detected in the recording")
    speech = await speak_in_clone(text, user["voice_clone"]) if voice == "clone" else await speak_with_fallback(text, voice)
    return {"text": text, "voice": voice, **speech}


# ---------- voice cloning ----------
clone_lock = asyncio.Lock()


class CloneSpeakIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


async def read_sample(clone: dict) -> bytes:
    stream = await fs.open_download_stream(clone["file_id"])
    return await stream.read()


@api.post("/voice/clone")
async def voice_clone(file: UploadFile = File(...), user: dict = Depends(current_user)):
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty audio file")
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 8 MB)")
    name, ctype = file.filename or "sample.webm", file.content_type or "audio/webm"
    try:
        async with clone_lock:
            d = await frasberg_upload("/voice/clone", name, data, ctype, "clone")
    except HTTPException as e:
        logger.warning("Frasberg clone upload failed (%s); keeping sample for in-house cloning", e.detail)
        try:
            d = {"duration_sec": await asyncio.to_thread(local_engines.audio_duration, data), "cloning_status": "ready"}
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=400, detail="Could not read that audio file")
    file_id = await fs.upload_from_stream(f"voice-samples/{user['id']}/{uuid.uuid4()}", data,
                                          metadata={"user_id": user["id"], "content_type": ctype})
    clone = {"file_id": file_id, "filename": name, "content_type": ctype,
             "duration_sec": d.get("duration_sec"), "created_at": now_iso()}
    await db.users.update_one({"id": user["id"]}, {"$set": {"voice_clone": clone}})
    return {"has_sample": True, "duration_sec": clone["duration_sec"], "cloning_status": d.get("cloning_status"),
            "created_at": clone["created_at"]}


@api.get("/voice/clone")
async def voice_clone_info(user: dict = Depends(current_user)):
    c = user.get("voice_clone")
    if not c:
        return {"has_sample": False}
    return {"has_sample": True, "duration_sec": c.get("duration_sec"), "created_at": c.get("created_at")}


@api.get("/voice/clone/sample")
async def voice_clone_sample(user: dict = Depends(current_user)):
    c = user.get("voice_clone")
    if not c:
        raise HTTPException(status_code=404, detail="No voice sample yet")
    return Response(content=await read_sample(c), media_type=c["content_type"])


@api.post("/voice/clone/speak")
async def voice_clone_speak(body: CloneSpeakIn, user: dict = Depends(current_user)):
    c = user.get("voice_clone")
    if not c:
        raise HTTPException(status_code=400, detail="Record your voice sample first")
    return {"text": body.text, **(await speak_in_clone(body.text, c))}


async def speak_in_clone(text: str, clone: dict) -> dict:
    sample = await read_sample(clone)
    try:
        async with clone_lock:
            await frasberg_upload("/voice/clone", clone["filename"], sample, clone["content_type"], "clone")
            return {**(await speak(text)), "engine": "frasberg"}
    except HTTPException as e:
        logger.warning("Frasberg cloned speech failed (%s); using in-house voice converter", e.detail)
    try:
        return {**(await asyncio.to_thread(local_engines.speak_cloned, text, sample)), "engine": "luchii-local"}
    except Exception as e:  # noqa: BLE001
        logger.exception("Local voice conversion failed")
        raise HTTPException(status_code=424, detail=f"Voice clone engine error: {e.__class__.__name__}")


# ---------- video & music jobs (Frasberg Edge) ----------
VIDEO_STYLES = {
    "cinematic": "cinematic film still, anamorphic lens, dramatic lighting, rich color grade",
    "photoreal": "photorealistic, natural light, ultra detailed, 35mm photography",
    "anime": "anime key visual, vibrant cel shading, clean line art",
    "3d": "3D animated film still, pixar style, soft global illumination",
    "noir": "black and white film noir, high contrast, moody shadows",
    "fantasy": "epic fantasy concept art, magical glow, painterly detail",
}
MUSIC_STYLES = {
    "lofi": "lo-fi hip hop, mellow, vinyl crackle", "cinematic": "epic cinematic orchestral score",
    "electronic": "electronic dance music, synths, punchy beat", "ambient": "ambient, atmospheric pads, calm",
    "rock": "rock, electric guitars, live drums", "jazz": "smooth jazz, saxophone, upright bass",
    "hiphop": "hip hop beat, boom bap drums, deep bass", "acoustic": "acoustic folk, guitar, warm",
}
MEDIA_LIMITS = {"video": (3, 15), "music": (5, 30)}
media_queues = {"video": asyncio.Lock(), "music": asyncio.Lock()}


class JobIn(BaseModel):
    prompt: str = Field(min_length=1, max_length=500)
    duration: Optional[int] = None       # None = the engine's short default (engine rules: video 5s, music 15s)
    style: Optional[str] = None
    model: Optional[str] = None          # Frasberg GPU engine id (video only)
    aspect_ratio: Optional[str] = "16:9"
    image_base64: Optional[str] = None   # start frame for image-to-video
    luchii_model: Optional[str] = None


LUCHII_MEDIA_MODELS = {"video": ("Luchii Cinematica", "Luchii Animus"), "music": ("Luchii Harmonia",)}


def luchii_media_model(kind: str, requested: Optional[str], has_image: bool) -> str:
    if requested in LUCHII_MEDIA_MODELS.get(kind, ()):
        return requested
    return ("Luchii Animus" if has_image else "Luchii Cinematica") if kind == "video" else "Luchii Harmonia"


async def job_out(job: dict) -> dict:
    out = {"job_id": job["id"], "kind": job["kind"], "status": job["status"], "prompt": job.get("prompt"),
           "style": job.get("style"), "duration": job.get("duration"), "error": job.get("error"),
           "engine": ENGINE_LABELS.get(job.get("render_engine") or "", job.get("render_engine")), "model": job.get("model"),
           "mode": "image-to-video" if job.get("has_image") else None,
           "luchii_model": job.get("luchii_model"), "progress": job.get("progress"),
           "phase": job.get("phase"), "phase_detail": job.get("phase_detail"),
           "url": f"/api/media/{job['id']}" if job["status"] == "completed" else None}
    if job["status"] == "queued":
        out["queue_position"] = await db.jobs.count_documents(
            {"kind": job["kind"], "engine": "local", "status": {"$in": ["queued", "running"]},
             "created_at": {"$lt": job["created_at"]}}) + 1
    return out


def is_sample_url(url: str) -> bool:
    return not url or any(h in url.lower() for h in SAMPLE_HOSTS)


async def frasberg_video(prompt: str, duration: int) -> Optional[bytes]:
    """Ask the Frasberg Video Engine for a render. Returns MP4 bytes only for a genuine, prompt-specific render;
    returns None when Frasberg hands back a public stock sample or fails, so the caller falls back."""
    try:
        r, ki = await frasberg("POST", "/generate/video", {"prompt": prompt, "duration": duration,
                                                           "output_format": "mp4"}, feature="video")
        task = r.json().get("task_id")
        if not task:
            return None
        for _ in range(60):  # up to ~5 min
            await asyncio.sleep(5)
            jr, _ = await frasberg("GET", f"/jobs/{task}", key_index=ki)
            d = jr.json()
            if d.get("status") == "failed":
                logger.warning("Frasberg video job failed: %s", d.get("error"))
                return None
            if d.get("status") == "completed":
                url = d.get("video_url") or (d.get("result") or {}).get("url") or ""
                if is_sample_url(url):
                    logger.warning("Frasberg video returned a stock sample (%s); rejecting", url)
                    return None
                if url.startswith("/"):
                    url = FRASBERG_BASE.rsplit("/api", 1)[0] + url
                async with httpx.AsyncClient(timeout=120, follow_redirects=True) as hc:
                    vr = await hc.get(url, headers={"Authorization": f"Bearer {FRASBERG_KEYS[ki]}"})
                if vr.status_code != 200 or len(vr.content) <= 1000:
                    return None
                # Content fingerprint: identical bytes already served for a different prompt = canned clip.
                digest = hashlib.sha256(vr.content).hexdigest()
                seen = await db.frasberg_video_hashes.find_one({"sha256": digest}, {"_id": 0})
                if seen and seen.get("prompt") != prompt:
                    logger.warning("Frasberg video bytes repeat a previous render (%s); rejecting as canned", digest[:12])
                    return None
                await db.frasberg_video_hashes.update_one({"sha256": digest}, {"$setOnInsert": {
                    "sha256": digest, "prompt": prompt, "url": url, "at": now_iso()}}, upsert=True)
                return vr.content
    except HTTPException as e:
        logger.warning("Frasberg video unavailable (%s)", e.detail)
    except Exception:  # noqa: BLE001
        logger.exception("Frasberg video error")
    return None


GPU_VIDEO_DEFAULT = "frasberg-motion-fast"
GPU_VIDEO_ORDER = ["frasberg-motion-fast", "frasberg-motion-pro", "frasberg-motion-ultra", "frasberg-motion-free"]


FREE_GPU_MODEL = "frasberg-motion-free"


def public_gateway(request: Request) -> str:
    """This server's public /api/gpu URL, as the browser reached it (what a Kaggle worker must call back to)."""
    base = os.environ.get("FRASBERG_PUBLIC_URL", "").rstrip("/")
    if not base:
        host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "").split(",")[0].strip()
        base = f"https://{host}" if host else ""
    return f"{base}/api/gpu" if base else ""


async def _set_phase(job_id: str, phase: str, detail: str):
    await db.jobs.update_one({"id": job_id}, {"$set": {"phase": phase, "phase_detail": detail}})


async def gpu_render_video(job: dict, prompt: str):
    """Frasberg Serverless GPU first: the chosen engine if a worker is online, else any online Frasberg motion engine,
    else a free Kaggle T4 started on demand (Frasberg Motion Free). Returns (None, None) to fall back to Lite."""
    wanted = job.get("model") or GPU_VIDEO_DEFAULT
    order = [wanted] + [m for m in GPU_VIDEO_ORDER if m != wanted]
    model = None
    for m in order:
        if m in frasberg_gpu.MODELS and await frasberg_gpu.is_online(m):
            model = m
            break
    gateway = job.get("gateway") or ""
    cold = None  # "aws" | "kaggle": which cold-starting GPU host this job is waiting for
    if not model and aws_gpu.enabled() and gateway:
        await _set_phase(job["id"], "gpu-boot", "Starting the Frasberg GPU")
        res = await aws_gpu.ensure(gateway, os.environ["FRASBERG_WORKER_SECRET"], reason=f"video {job['id'][:8]}")
        if res.get("ok") and await aws_gpu.booting(gateway):
            aws_models = aws_gpu.models()
            model, cold = (wanted if wanted in aws_models else aws_models[0]), "aws"
        elif not res.get("ok"):
            logger.warning("AWS GPU not available: %s", res.get("reason"))
    if not model and kaggle_gpu.enabled() and gateway:
        await _set_phase(job["id"], "gpu-boot", "Starting a free Frasberg GPU")
        res = await kaggle_gpu.launch(gateway, os.environ["FRASBERG_WORKER_SECRET"], reason=f"video {job['id'][:8]}")
        if res.get("launched") or await kaggle_gpu.booting(gateway):
            model, cold = FREE_GPU_MODEL, "kaggle"
        else:
            logger.warning("Free GPU not available: %s", res.get("reason"))
    if not model:
        return None, None
    try:
        g = await frasberg_gpu.submit("video", model, prompt, duration=job["duration"],
                                      aspect_ratio=job.get("aspect_ratio") or "16:9",
                                      image_base64=job.get("image_base64"), owner="luchii")
        await db.jobs.update_one({"id": job["id"]}, {"$set": {"gpu_task": g["id"], "model": model}})
        last_phase = None
        for i in range(720):  # up to 60 min (cold start + ultra on a busy queue)
            await asyncio.sleep(5)
            cur = await frasberg_gpu.get_job(g["id"])
            await db.jobs.update_one({"id": job["id"]}, {"$set": {"progress": cur.get("progress")}})
            if cur["status"] == "completed":
                return await frasberg_gpu.output_bytes(cur), frasberg_gpu.MODELS[model]["name"]
            if cur["status"] == "failed":
                logger.warning("Frasberg GPU %s failed: %s", model, cur.get("error"))
                return None, None
            phase = "gpu-render" if cur["status"] == "running" else "gpu-queued"
            if cur["status"] == "queued" and not await frasberg_gpu.is_online(model):
                if cold == "aws" or (not cold and aws_gpu.enabled()):
                    boot = await aws_gpu.booting(gateway)
                else:
                    boot = None
                if not boot and (cold == "kaggle" or kaggle_gpu.enabled()):
                    boot = await kaggle_gpu.booting(gateway)
                if not boot:
                    logger.warning("Frasberg GPU %s went offline; falling back", model)
                    await frasberg_gpu.db.gpu_jobs.update_one({"id": g["id"], "status": "queued"},
                                                              {"$set": {"status": "failed", "error": "No GPU workers online"}})
                    return None, None
                phase = "gpu-boot"
                detail = (boot.get("boot") or {}).get("label") or (
                    "Waiting for a free Kaggle GPU" if boot.get("kaggle_status") == "queued" else
                    "Starting the Frasberg GPU" if boot.get("instance") else "Starting a free Frasberg GPU")
            else:
                detail = "Rendering on the Frasberg GPU" if phase == "gpu-render" else "Queued on the Frasberg GPU"
            if (phase, detail) != last_phase:
                await _set_phase(job["id"], phase, detail)
                last_phase = (phase, detail)
    except HTTPException as e:
        logger.warning("Frasberg GPU submit failed: %s", e.detail)
    except Exception:  # noqa: BLE001
        logger.exception("Frasberg GPU path error; falling back")
    return None, None


async def _render_video(job: dict) -> tuple:
    style = VIDEO_STYLES.get(job.get("style") or "", "")
    full = f"{job['prompt']}. {style}" if style else job["prompt"]
    # The GPU path (which may wait minutes for a free GPU to boot) runs outside the local CPU queue, so other
    # clips are not blocked behind a cold start.
    await db.jobs.update_one({"id": job["id"]}, {"$set": {"status": "running", "started_at": now_iso()}})
    data, engine = await gpu_render_video(job, full)
    if data is None:
        data = await frasberg_video(full, job["duration"])
        engine = "frasberg"
    if data is None:
        await db.jobs.update_one({"id": job["id"]}, {"$set": {"status": "queued"}})
        async with media_queues["video"]:
            await db.jobs.update_one({"id": job["id"]}, {"$set": {"status": "running", "phase": "lite",
                                                                  "phase_detail": "Rendering a preview on Frasberg Lite"}})
            data = await asyncio.to_thread(local_engines.generate_video, job["prompt"], job["duration"], style)
        engine = "Frasberg Lite (CPU)"
        await db.jobs.update_one({"id": job["id"]}, {"$set": {"has_image": False}})
    await db.jobs.update_one({"id": job["id"]}, {"$set": {"render_engine": engine}})
    return data, "video/mp4"


async def run_media(job: dict):
    kind = job["kind"]
    try:
        if kind == "video":
            data, mime = await _render_video(job)
        else:
            async with media_queues[kind]:
                await db.jobs.update_one({"id": job["id"]}, {"$set": {"status": "running", "started_at": now_iso()}})
                style = MUSIC_STYLES.get(job.get("style") or "", "")
                data = await asyncio.to_thread(local_engines.generate_music,
                                               f"{job['prompt']}. {style}" if style else job["prompt"], job["duration"])
            mime = "audio/wav"
        file_id = await media_fs.upload_from_stream(f"{kind}/{job['id']}", data, metadata={"mime": mime})
        update = {"status": "completed", "file_id": file_id, "mime": mime}
    except Exception as e:  # noqa: BLE001
        logger.exception("%s generation failed", kind)
        update = {"status": "failed", "error": f"{kind.title()} engine error: {e.__class__.__name__}"}
    await db.jobs.update_one({"id": job["id"]}, {"$set": {**update, "finished_at": now_iso()}})


async def create_media_job(kind: str, body: JobIn, user: Optional[dict], gateway: str = ""):
    lo, hi = MEDIA_LIMITS[kind]
    job = {"id": str(uuid.uuid4()), "kind": kind, "engine": "local", "status": "queued", "prompt": body.prompt.strip(),
           "style": body.style, "duration": max(lo, min(hi, engine_rules.default_duration(kind, body.duration))), "error": None,
           "model": body.model if kind == "video" else None, "aspect_ratio": body.aspect_ratio or "16:9",
           "has_image": bool(body.image_base64 and kind == "video"),
           "luchii_model": luchii_media_model(kind, body.luchii_model, bool(body.image_base64 and kind == "video")),
           "user_id": user["id"] if user else None, "created_at": now_iso()}
    await db.jobs.insert_one(job.copy())
    asyncio.create_task(run_media({**job, "gateway": gateway, "image_base64": body.image_base64 if kind == "video" else None}))
    return await job_out(job)


@api.post("/video")
async def video(body: JobIn, request: Request, user: Optional[dict] = Depends(optional_user)):
    return await create_media_job("video", body, user, public_gateway(request))


@api.post("/music")
async def music(body: JobIn, user: Optional[dict] = Depends(optional_user)):
    return await create_media_job("music", body, user)


ENGINE_LABELS = {"luchii-local": "Frasberg Lite (CPU)", "frasberg": "Frasberg Edge"}


def video_card(j: dict) -> dict:
    return {"id": j["id"], "prompt": j.get("prompt"), "style": j.get("style"), "duration": j.get("duration"),
            "engine": ENGINE_LABELS.get(j.get("render_engine") or "", j.get("render_engine")) or "Frasberg Lite (CPU)",
            "model": j.get("model"), "luchii_model": j.get("luchii_model"),
            "mode": "image-to-video" if j.get("has_image") else "text-to-video",
            "aspect_ratio": j.get("aspect_ratio") or "16:9", "url": f"/api/media/{j['id']}",
            "author": j.get("author"), "created_at": j.get("created_at"), "finished_at": j.get("finished_at")}


@api.get("/videos")
async def my_videos(limit: int = 60, user: dict = Depends(current_user)):
    rows = await db.jobs.find({"kind": "video", "status": "completed", "user_id": user["id"]}, {"_id": 0}) \
        .sort("created_at", -1).limit(max(1, min(limit, 200))).to_list(200)
    return [video_card(j) for j in rows]


@api.get("/videos/{video_id}")
async def get_video(video_id: str):
    j = await db.jobs.find_one({"id": video_id, "kind": "video", "status": "completed"}, {"_id": 0})
    if not j:
        raise HTTPException(status_code=404, detail="Video not found")
    if j.get("user_id") and not j.get("author"):
        u = await db.users.find_one({"id": j["user_id"]}, {"_id": 0, "name": 1})
        j["author"] = (u or {}).get("name")
    return video_card(j)


@api.get("/media/{job_id}")
async def media_file(job_id: str):
    job = await db.jobs.find_one({"id": job_id, "status": "completed", "engine": "local"}, {"_id": 0})
    if not job:
        raise HTTPException(status_code=404, detail="Not ready")
    stream = await media_fs.open_download_stream(job["file_id"])
    return Response(content=await stream.read(), media_type=job["mime"], headers={"Accept-Ranges": "none"})


LUCHII_MARK = Path(__file__).parent / "assets" / "luchii-logo.png"


def _watermark_video(data: bytes) -> bytes:
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        src, out = Path(d) / "in.mp4", Path(d) / "out.mp4"
        src.write_bytes(data)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-i", str(LUCHII_MARK), "-filter_complex",
                        "[1:v][0:v]scale2ref=w=oh*mdar:h=ih*0.14[mk][base];[mk]format=rgba,colorchannelmixer=aa=0.85[m];"
                        "[base][m]overlay=W-w-W*0.03:H-h-H*0.04",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", "-c:a", "copy",
                        "-movflags", "+faststart", str(out)], check=True, timeout=180)
        return out.read_bytes()


@api.get("/media/{job_id}/download")
async def media_download(job_id: str):
    job = await db.jobs.find_one({"id": job_id, "status": "completed", "engine": "local"}, {"_id": 0})
    if not job:
        raise HTTPException(status_code=404, detail="Not ready")
    name = f"luchii-{job['kind']}-{job_id[:8]}.{'mp4' if job['kind'] == 'video' else 'wav'}"
    headers = {"Content-Disposition": f'attachment; filename="{name}"'}
    if job["kind"] != "video":
        stream = await media_fs.open_download_stream(job["file_id"])
        return Response(content=await stream.read(), media_type=job["mime"], headers=headers)
    if not job.get("marked_file_id"):
        raw = await (await media_fs.open_download_stream(job["file_id"])).read()
        marked = await asyncio.to_thread(_watermark_video, raw)
        fid = await media_fs.upload_from_stream(name, marked, metadata={"job_id": job_id, "luchii_mark": True})
        await db.jobs.update_one({"id": job_id}, {"$set": {"marked_file_id": fid}})
        job["marked_file_id"] = fid
    stream = await media_fs.open_download_stream(job["marked_file_id"])
    return Response(content=await stream.read(), media_type="video/mp4", headers=headers)


@api.get("/jobs/{job_id}")
async def job_status(job_id: str):
    job = await db.jobs.find_one({"id": job_id}, {"_id": 0})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.get("engine") == "local":
        return await job_out(job)
    r, _ = await frasberg("GET", f"/jobs/{job_id}", key_index=job["key_index"])
    d = r.json()
    status = d.get("status", "queued")
    await db.jobs.update_one({"id": job_id}, {"$set": {"status": status}})
    url = None
    if status == "completed":
        url = f"/api/music/{job_id}/audio" if job["kind"] == "music" else (
            d.get("video_url") or (d.get("result") or {}).get("url"))
    return {"job_id": job_id, "kind": job["kind"], "status": status, "url": url, "error": d.get("error")}


@api.get("/music/{job_id}/audio")
async def music_audio(job_id: str):
    job = await db.jobs.find_one({"id": job_id, "kind": "music"}, {"_id": 0})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    r, _ = await frasberg("GET", f"/generate/music/task/{job_id}/audio", key_index=job["key_index"])
    return Response(content=r.content, media_type=r.headers.get("content-type", "audio/wav"))


# ---------- saved voice takes ----------
class TakeIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    voice: str
    mime: str = "audio/wav"
    audio_base64: str = Field(min_length=1)


def take_out(t: dict) -> dict:
    return {"id": t["id"], "text": t["text"], "voice": t["voice"], "mime": t["mime"],
            "audio_url": f"/api/voice/takes/{t['id']}/audio", "created_at": t["created_at"]}


@api.post("/voice/takes")
async def save_take(body: TakeIn, user: dict = Depends(current_user)):
    data = base64.b64decode(strip_data_url(body.audio_base64))
    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Take too large")
    take = {"id": str(uuid.uuid4()), "user_id": user["id"], "text": body.text, "voice": body.voice,
            "mime": body.mime, "created_at": now_iso()}
    take["file_id"] = await takes_fs.upload_from_stream(f"takes/{user['id']}/{take['id']}", data,
                                                        metadata={"user_id": user["id"]})
    await db.voice_takes.insert_one(take.copy())
    return take_out(take)


@api.get("/voice/takes")
async def list_takes(limit: int = 50, user: dict = Depends(current_user)):
    cur = db.voice_takes.find({"user_id": user["id"]}, {"_id": 0})
    return [take_out(t) for t in await cur.sort("created_at", -1).limit(min(limit, 200)).to_list(None)]


@api.get("/voice/takes/{take_id}/audio")
async def take_audio(take_id: str):
    t = await db.voice_takes.find_one({"id": take_id}, {"_id": 0})
    if not t:
        raise HTTPException(status_code=404, detail="Take not found")
    stream = await takes_fs.open_download_stream(t["file_id"])
    return Response(content=await stream.read(), media_type=t["mime"])


@api.delete("/voice/takes/{take_id}")
async def delete_take(take_id: str, user: dict = Depends(current_user)):
    t = await db.voice_takes.find_one({"id": take_id, "user_id": user["id"]}, {"_id": 0})
    if not t:
        raise HTTPException(status_code=404, detail="Take not found")
    await takes_fs.delete(t["file_id"])
    await db.voice_takes.delete_one({"id": take_id})
    return {"deleted": True}


# ---------- 3D studio ----------
shape_queue = asyncio.Lock()


class ModelIn(BaseModel):
    prompt: Optional[str] = Field(default=None, max_length=300)
    image_base64: Optional[str] = None
    session_id: Optional[str] = None


async def model_out(m: dict) -> dict:
    out = {k: m.get(k) for k in ("id", "prompt", "status", "error", "created_at", "finished_at", "source", "thumbnail")}
    out["model_url"] = f"/api/3d/{m['id']}/model.glb" if m["status"] == "completed" else None
    if m["status"] == "queued":
        out["queue_position"] = await db.models3d.count_documents(
            {"status": {"$in": ["queued", "running"]}, "created_at": {"$lt": m["created_at"]}}) + 1
    return out


async def run_3d(model_id: str, prompt: str, image_b64: Optional[str] = None):
    async with shape_queue:
        await db.models3d.update_one({"id": model_id}, {"$set": {"status": "running", "started_at": now_iso()}})
        try:
            glb = await asyncio.to_thread(local_engines.generate_3d, prompt, image_b64)
            file_id = await models_fs.upload_from_stream(f"models3d/{model_id}.glb", glb)
            update = {"status": "completed", "file_id": file_id}
        except Exception as e:  # noqa: BLE001
            logger.exception("3D generation failed")
            update = {"status": "failed", "error": f"3D engine error: {e.__class__.__name__}"}
        await db.models3d.update_one({"id": model_id}, {"$set": {**update, "finished_at": now_iso()}})


@api.post("/3d")
async def create_3d(body: ModelIn, user: Optional[dict] = Depends(optional_user)):
    prompt = (body.prompt or "").strip()
    if not prompt and not body.image_base64:
        raise HTTPException(status_code=400, detail="Describe an object or upload a photo")
    thumb = None
    if body.image_base64:
        try:
            thumb = await asyncio.to_thread(local_engines.thumbnail, body.image_base64)
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=400, detail="That file isn't a readable image")
    m = {"id": str(uuid.uuid4()), "prompt": prompt or "Photo to 3D", "status": "queued", "error": None,
         "source": "image" if body.image_base64 else "text", "thumbnail": thumb,
         "session_id": body.session_id, "user_id": user["id"] if user else None, "created_at": now_iso()}
    await db.models3d.insert_one(m.copy())
    asyncio.create_task(run_3d(m["id"], m["prompt"], body.image_base64))
    return await model_out(m)


@api.get("/3d")
async def list_3d(session_id: Optional[str] = None, limit: int = 12, user: Optional[dict] = Depends(optional_user)):
    if not user and not session_id:
        return []
    q = {"user_id": user["id"]} if user else {"session_id": session_id}
    cur = db.models3d.find(q, {"_id": 0})
    return [await model_out(m) for m in await cur.sort("created_at", -1).limit(min(limit, 60)).to_list(None)]


@api.get("/3d/{model_id}")
async def get_3d(model_id: str):
    m = await db.models3d.find_one({"id": model_id}, {"_id": 0})
    if not m:
        raise HTTPException(status_code=404, detail="Model not found")
    return await model_out(m)


@api.get("/3d/{model_id}/model.glb")
async def get_3d_file(model_id: str):
    m = await db.models3d.find_one({"id": model_id, "status": "completed"}, {"_id": 0})
    if not m:
        raise HTTPException(status_code=404, detail="Model not ready")
    stream = await models_fs.open_download_stream(m["file_id"])
    return Response(content=await stream.read(), media_type="model/gltf-binary",
                    headers={"Cache-Control": "public, max-age=86400"})


# ---------- spaces builder ----------
class SpaceItem(BaseModel):
    uid: str = Field(min_length=1, max_length=64)
    model_id: str
    position: list[float] = Field(min_length=3, max_length=3)
    rotation: list[float] = Field(min_length=3, max_length=3)
    scale: float = Field(gt=0, le=50)


class SpaceIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    ground: str = Field(default="#1b2a30", pattern=r"^#[0-9a-fA-F]{6}$")
    items: list[SpaceItem] = Field(default_factory=list, max_length=60)


def space_out(sp: dict) -> dict:
    return {k: sp.get(k) for k in ("id", "name", "ground", "items", "author", "created_at", "updated_at")}


async def check_models(items: list[SpaceItem]):
    ids = {i.model_id for i in items}
    found = await db.models3d.count_documents({"id": {"$in": list(ids)}, "status": "completed"})
    if found != len(ids):
        raise HTTPException(status_code=400, detail="Some objects are missing or not finished")


@api.post("/spaces")
async def create_space(body: SpaceIn, user: dict = Depends(current_user)):
    await check_models(body.items)
    sp = {"id": str(uuid.uuid4()), "user_id": user["id"], "author": user.get("name"), **body.model_dump(),
          "created_at": now_iso(), "updated_at": now_iso()}
    await db.spaces.insert_one(sp.copy())
    return space_out(sp)


@api.get("/spaces")
async def list_spaces(user: dict = Depends(current_user)):
    cur = db.spaces.find({"user_id": user["id"]}, {"_id": 0})
    return [space_out(sp) for sp in await cur.sort("updated_at", -1).limit(100).to_list(None)]


@api.get("/spaces/{space_id}")
async def get_space(space_id: str):
    sp = await db.spaces.find_one({"id": space_id}, {"_id": 0})
    if not sp:
        raise HTTPException(status_code=404, detail="Space not found")
    return space_out(sp)


@api.put("/spaces/{space_id}")
async def update_space(space_id: str, body: SpaceIn, user: dict = Depends(current_user)):
    await check_models(body.items)
    res = await db.spaces.update_one({"id": space_id, "user_id": user["id"]},
                                     {"$set": {**body.model_dump(), "updated_at": now_iso()}})
    if not res.matched_count:
        raise HTTPException(status_code=404, detail="Space not found")
    return space_out(await db.spaces.find_one({"id": space_id}, {"_id": 0}))


@api.delete("/spaces/{space_id}")
async def delete_space(space_id: str, user: dict = Depends(current_user)):
    res = await db.spaces.delete_one({"id": space_id, "user_id": user["id"]})
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail="Space not found")
    return {"deleted": True}


# ---------- engine status ----------
SAMPLE_HOSTS = ("mozilla.net", "mozilla.org", "filesamples", "sample", "example", "w3schools", "commondatastorage.googleapis.com",
                "test-videos", "pexels.com", "pixabay.com", "archive.org", "bigbuckbunny")
_status_cache: dict = {}


async def _timed(coro):
    t = time.monotonic()
    try:
        status, detail = await coro
    except HTTPException as e:
        status, detail = "offline", str(e.detail)
    except Exception as e:  # noqa: BLE001
        status, detail = "offline", f"{e.__class__.__name__}"
    return status, detail, int((time.monotonic() - t) * 1000)


async def probe_image():
    await frasberg_image({"prompt": "status check: a small red circle"})
    return "online", "Generating images"


async def probe_voice():
    await frasberg("POST", "/voice/speak", {"text": "Status check", "voice": "nova"}, feature="tts")
    return "online", "Speaking"


async def probe_job(path: str, payload: dict, kind: str):
    r, ki = await frasberg("POST", path, payload, feature=kind)
    task = r.json().get("task_id")
    for _ in range(12):
        await asyncio.sleep(3)
        jr, _ = await frasberg("GET", f"/jobs/{task}", key_index=ki)
        d = jr.json()
        if d.get("status") == "completed":
            url = d.get("video_url") or (d.get("result") or {}).get("url") or ""
            if kind == "video" and is_sample_url(url):
                return "degraded", f"Returns public sample file instead of a render ({url.split('/')[2] if '//' in url else 'no url'})"
            return "online", "Jobs completing"
        if d.get("status") == "failed":
            return "offline", d.get("error") or "Job failed"
    return "degraded", "Job did not finish within 36s"


async def probe_chat():
    text = ""
    async with httpx.AsyncClient(timeout=60) as hc:
        r = await hc.post(f"{FRASBERG_BASE}/v1/chat", json={"message": "Reply with OK", "model": "luchii-6-plus"},
                          headers={"Authorization": f"Bearer {FRASBERG_KEYS[0]}"})
    if r.status_code >= 400:
        return "offline", upstream_detail(r)
    for m in re.finditer(r'"delta":\s*"([^"]*)"', r.text):
        text += m.group(1)
    if not text or "turbulence" in text.lower():
        return "degraded", "Replies with turbulence error"
    return "online", "Replying"


async def probe_local_voice():
    await asyncio.to_thread(local_engines.synthesize, "Status check", "nova")
    return "online", "Piper voices running on Frasberg edge"


async def probe_local_image():
    st = local_engines.status()
    if st["image_loaded"]:
        return "online", "SD-Turbo loaded on Frasberg edge (CPU)"
    if st["image_downloaded"]:
        return "online", "SD-Turbo ready, loads on first image"
    return "degraded", "SD-Turbo downloads on first image (~2.5 GB)"


async def probe_local_3d():
    st = local_engines.status()
    if local_engines.busy_3d():
        return "online", "Building a 3D model now"
    if st["shape_loaded"]:
        return "online", "Shap-E loaded on Frasberg edge (CPU)"
    if st["shape_downloaded"]:
        return "online", "Shap-E ready, loads on first model"
    return "degraded", "Shap-E downloads on first model (~4 GB)"


async def probe_local_clone():
    st = local_engines.status()
    return ("online", "OpenVoice converter loaded") if st["converter_loaded"] else ("degraded", "OpenVoice loads on first use")


ENGINES = [
    ("image", "Image Engine", "Generate, edit, upscale", probe_image),
    ("voice", "Voice Engine", "Text to Speech", probe_voice),
    ("video", "Astral Video Engine", "Video Creator",
     lambda: probe_job("/generate/video", {"prompt": "status check", "duration": 5, "model": "frasberg-engine",
                                           "ratio": "16:9", "output_format": "mp4"}, "video")),
    ("music", "Music Engine", "Audio Studio",
     lambda: probe_job("/generate/music", {"prompt": "status check", "duration": 15, "model": "frasberg-music"}, "music")),
    ("chat", "Luchii Chat (luchii-6-plus)", "Language model", probe_chat),
    ("local_voice", "Frasberg Edge Voice", "Text to Speech & Speech to Speech fallback", probe_local_voice),
    ("local_image", "Frasberg Edge Image", "Generate, edit, upscale fallback", probe_local_image),
    ("local_3d", "Frasberg Edge 3D", "3D Studio", probe_local_3d),
    ("local_clone", "Frasberg Edge Voice Clone", "Cloned voice in Voice Cloning & Speech to Speech", probe_local_clone),
]


ADMIN_EMAILS = {e.strip().lower() for e in os.environ["ADMIN_EMAILS"].split(",") if e.strip()}


async def admin_user(user: dict = Depends(current_user)) -> dict:
    if user["email"].lower() not in ADMIN_EMAILS:
        raise HTTPException(status_code=403, detail="Admins only")
    return user


@api.get("/engines/status")
async def engines_status(refresh: bool = False, _: dict = Depends(admin_user)):
    cached = _status_cache.get("data")
    if cached and not refresh and time.monotonic() - _status_cache["t"] < 120:
        return cached
    results = await asyncio.gather(*[_timed(fn()) for _, _, _, fn in ENGINES])
    engines = [{"id": i, "name": n, "powers": p, "status": s, "detail": d, "latency_ms": ms}
               for (i, n, p, _), (s, d, ms) in zip(ENGINES, results)]
    data = {"checked_at": now_iso(), "engines": engines}
    _status_cache.update(data=data, t=time.monotonic())
    return data


@api.get("/gpu-admin/overview")
async def gpu_admin_overview(_: dict = Depends(admin_user)):
    return {"workers": await frasberg_gpu.recent_workers(), "jobs": await frasberg_gpu.job_stats(),
            "engines": (await frasberg_gpu.engines())["data"], "boot": await frasberg_gpu.latest_boot()}


@api.get("/gpu-admin/kaggle")
async def gpu_admin_kaggle(request: Request, _: dict = Depends(admin_user)):
    return await kaggle_gpu.overview(public_gateway(request))


@api.post("/gpu-admin/kaggle/launch")
async def gpu_admin_kaggle_launch(request: Request, force: bool = False, admin: dict = Depends(admin_user)):
    if not kaggle_gpu.enabled():
        raise HTTPException(status_code=400, detail="Add KAGGLE_API_TOKEN and KAGGLE_USERNAME to the backend first")
    gateway = public_gateway(request)
    if not gateway:
        raise HTTPException(status_code=400, detail="Could not work out this server's public URL")
    return await kaggle_gpu.launch(gateway, os.environ["FRASBERG_WORKER_SECRET"], reason=f"admin {admin['email']}", force=force)


@api.get("/gpu-admin/aws")
async def gpu_admin_aws(request: Request, _: dict = Depends(admin_user)):
    return await aws_gpu.overview(public_gateway(request))


@api.post("/gpu-admin/aws/start")
async def gpu_admin_aws_start(request: Request, _: dict = Depends(admin_user)):
    if not aws_gpu.enabled():
        raise HTTPException(status_code=400, detail="Add AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY to the backend first")
    gateway = public_gateway(request)
    if not gateway:
        raise HTTPException(status_code=400, detail="Could not work out this server's public URL")
    return await aws_gpu.resume(gateway, os.environ["FRASBERG_WORKER_SECRET"])


class AwsSettingsIn(BaseModel):
    mode: Optional[str] = None       # always_on | on_demand (cost saver)
    idle_min: Optional[int] = None   # on_demand: stop after this many idle minutes


@api.put("/gpu-admin/aws/settings")
async def gpu_admin_aws_settings(body: AwsSettingsIn, request: Request, admin: dict = Depends(admin_user)):
    if not aws_gpu.enabled():
        raise HTTPException(status_code=400, detail="AWS GPU is not configured")
    try:
        res = await aws_gpu.set_settings(body.mode, body.idle_min, by=admin["email"])
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    gateway = public_gateway(request)
    if body.mode == "always_on" and gateway:
        # Always on means "keep it running": clear an earlier admin pause and start it right away.
        res["start"] = await aws_gpu.resume(gateway, os.environ["FRASBERG_WORKER_SECRET"])
    return res


@api.get("/gpu-admin/aws/usage")
async def gpu_admin_aws_usage(request: Request, month: Optional[str] = None, _: dict = Depends(admin_user)):
    if month and not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", month):
        raise HTTPException(status_code=422, detail="month must look like 2026-10")
    if not aws_gpu.enabled():
        return {"configured": False}
    return {"configured": True, **await aws_gpu.usage(public_gateway(request), month)}


@api.post("/gpu-admin/aws/stop")
async def gpu_admin_aws_stop(request: Request, _: dict = Depends(admin_user)):
    return await aws_gpu.stop(public_gateway(request))


@api.post("/gpu-admin/aws/terminate")
async def gpu_admin_aws_terminate(request: Request, confirm: bool = False, _: dict = Depends(admin_user)):
    if not confirm:
        raise HTTPException(status_code=409, detail="Pass confirm=true to delete the AWS GPU server")
    return await aws_gpu.terminate(public_gateway(request))


@api.post("/gpu-admin/stop")
async def gpu_admin_stop(_: dict = Depends(admin_user)):
    return {"stop_requested": await frasberg_gpu.request_stop()}


@api.get("/gpu-admin/notebook")
async def gpu_admin_notebook(request: Request, gateway: str, models: str = "frasberg-motion-free",
                             _: dict = Depends(admin_user)):
    import json as _json
    from urllib.parse import urlparse
    if not re.match(r"^https://[^\s\"']+/api/gpu$", gateway):
        raise HTTPException(status_code=422, detail="gateway must be an https URL ending in /api/gpu")
    own_host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "").split(",")[0].split(":")[0]
    if urlparse(gateway).hostname != own_host:
        raise HTTPException(status_code=422, detail="gateway must point at this Frasberg Creator server")
    wanted = [m for m in models.split(",") if m in frasberg_gpu.MODELS]
    nb = frasberg_gpu.build_notebook(gateway, os.environ["FRASBERG_WORKER_SECRET"], ",".join(wanted) or "frasberg-motion-free")
    return Response(content=_json.dumps(nb, indent=1), media_type="application/x-ipynb+json",
                    headers={"Content-Disposition": 'attachment; filename="frasberg-free-gpu-worker.ipynb"'})


LUCHII_CHAT_FALLBACK = ["luchii-6-plus", "luchii-6-mini", "luchii-70b", "luchii-7b", "luchii-1b"]


async def chat_owner(request: Request, user: Optional[dict] = Depends(optional_user)) -> str:
    key = request.headers.get("X-Frasberg-Key", "")
    if user:
        return user["id"]
    if key and key in FRASBERG_KEYS:
        return f"platform:{key[9:17]}"
    raise HTTPException(status_code=401, detail="Sign in or send a valid X-Frasberg-Key")


class ChatSendIn(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    model: str = "luchii-6-plus"
    conversation_id: Optional[str] = None


class AgentTaskIn(BaseModel):
    type: str = Field(pattern="^(image|video|music)$")
    prompt: str = Field(min_length=1, max_length=500)
    style: Optional[str] = None
    model: Optional[str] = None
    duration: Optional[int] = None
    conversation_id: Optional[str] = None


def enforce_engine_permission(owner: str, engine: str):
    """Engine rules: API-key callers need a key routed to the engine's feature; decline in one sentence."""
    if owner.startswith("platform:") and not engine_rules.key_allowed(engine, owner.split(":", 1)[1], KEY_ROUTES):
        raise HTTPException(status_code=403, detail=engine_rules.decline_sentence(engine))


@api.get("/chat/models")
async def chat_models():
    try:
        r, _ = await frasberg("GET", "/v1/models", feature="chat")
        ids = [m["id"] for m in r.json().get("data", []) if (m.get("capabilities") or {}).get("chat")]
    except HTTPException:
        ids = []
    return {"default": "luchii-6-plus", "models": [{"id": i, "owned_by": "frasberg"} for i in (ids or LUCHII_CHAT_FALLBACK)]}


@api.get("/chat/conversations")
async def chat_conversations(owner: str = Depends(chat_owner)):
    return await db.chat_conversations.find({"owner": owner}, {"_id": 0, "messages": 0}).sort("updated_at", -1).to_list(100)


@api.get("/chat/conversations/{cid}")
async def chat_conversation(cid: str, owner: str = Depends(chat_owner)):
    c = await db.chat_conversations.find_one({"id": cid, "owner": owner}, {"_id": 0})
    if not c:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return c


@api.delete("/chat/conversations/{cid}")
async def chat_delete(cid: str, owner: str = Depends(chat_owner)):
    await db.chat_conversations.delete_one({"id": cid, "owner": owner})
    return {"ok": True}


async def _luchii_stream(payload: dict):
    async with httpx.AsyncClient(timeout=120) as hc:
        for i in key_order("chat"):
            try:
                async with hc.stream("POST", f"{FRASBERG_BASE}/v1/chat", json=payload,
                                     headers={"Authorization": f"Bearer {FRASBERG_KEYS[i]}"}) as r:
                    if r.status_code >= 400:
                        continue
                    async for line in r.aiter_lines():
                        if line.startswith("data:"):
                            try:
                                yield json.loads(line[5:].strip())
                            except ValueError:
                                continue
                    return
            except httpx.HTTPError:
                continue
    yield {"error": "Luchii Chat is unavailable right now"}


@api.post("/chat/send")
async def chat_send(body: ChatSendIn, owner: str = Depends(chat_owner)):
    conv = await db.chat_conversations.find_one({"id": body.conversation_id, "owner": owner}, {"_id": 0}) if body.conversation_id else None
    if not conv:
        conv = {"id": str(uuid.uuid4()), "owner": owner, "title": body.message[:60], "model": body.model,
                "session_id": None, "messages": [], "created_at": now_iso(), "updated_at": now_iso()}
        await db.chat_conversations.insert_one(conv.copy())
    payload = {"message": body.message, "model": body.model}
    if conv.get("session_id"):
        payload["session_id"] = conv["session_id"]

    async def events():
        text, sid, err = "", conv.get("session_id"), None
        yield f"data: {json.dumps({'conversation_id': conv['id'], 'model': body.model})}\n\n"
        async for ev in _luchii_stream(payload):
            if ev.get("delta"):
                text += ev["delta"]
                yield f"data: {json.dumps({'delta': ev['delta']})}\n\n"
            sid = ev.get("session_id") or sid
            err = ev.get("error") or err
        if "turbulence" in text.lower():
            err = "Luchii Chat (Frasberg) replied with a turbulence error"
        now = now_iso()
        await db.chat_conversations.update_one({"id": conv["id"]}, {
            "$set": {"session_id": sid, "model": body.model, "updated_at": now},
            "$push": {"messages": {"$each": [{"role": "user", "content": body.message, "at": now},
                                             {"role": "assistant", "content": text.strip(), "model": body.model,
                                              "error": err, "at": now}]}}})
        yield f"data: {json.dumps({'done': True, 'error': err, 'conversation_id': conv['id']})}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


async def _run_agent_task(task: dict, user: Optional[dict]):
    try:
        if task["type"] == "image":
            body = GenerateIn(prompt=task["prompt"], style=task.get("style") or "cinematic", model=task.get("model"))
            for attempt in range(60):
                try:
                    res = await generate(body, user)
                    break
                except HTTPException as e:
                    if e.status_code != 429 or attempt == 59:
                        raise
                    await db.agent_tasks.update_one({"id": task["id"]}, {"$set": {"status": "waiting", "updated_at": now_iso()}})
                    await asyncio.sleep(10)
            result = {"generation_id": res["id"], "share_url": f"/s/{res['id']}"}
        else:
            res = await create_media_job(task["type"], JobIn(prompt=task["prompt"], style=task.get("style"),
                                                             duration=task.get("duration")), user)
            result = {"job_id": res["job_id"]}
        await db.agent_tasks.update_one({"id": task["id"]}, {"$set": {"status": "dispatched", "result": result, "updated_at": now_iso()}})
    except Exception as e:  # noqa: BLE001
        detail = e.detail if isinstance(e, HTTPException) else e.__class__.__name__
        await db.agent_tasks.update_one({"id": task["id"]}, {"$set": {"status": "failed", "error": str(detail), "updated_at": now_iso()}})


@api.post("/chat/agents/tasks")
async def agent_task(body: AgentTaskIn, owner: str = Depends(chat_owner), user: Optional[dict] = Depends(optional_user)):
    enforce_engine_permission(owner, body.type)
    task = {"id": str(uuid.uuid4()), "owner": owner, **body.model_dump(), "status": "queued",
            "result": None, "error": None, "created_at": now_iso(), "updated_at": now_iso()}
    await db.agent_tasks.insert_one(task.copy())
    asyncio.create_task(_run_agent_task(task, user))
    return task


class AgentBundleIn(BaseModel):
    idea: str = Field(min_length=1, max_length=400)
    image_model: Optional[str] = None
    style: Optional[str] = None
    include: list[str] = Field(default_factory=lambda: ["image", "video", "music"])  # engines to run (explicit)


async def _wait_job(job_id: str, timeout: int = 1800):
    for _ in range(timeout // 5):
        j = await db.jobs.find_one({"id": job_id}, {"_id": 0, "status": 1})
        if not j or j["status"] in ("completed", "failed"):
            return
        await asyncio.sleep(5)


async def _run_bundle(tasks: list, user: Optional[dict]):
    for t in tasks:
        await _run_agent_task(t, user)
        done = await db.agent_tasks.find_one({"id": t["id"]}, {"_id": 0})
        if done and (done.get("result") or {}).get("job_id"):
            await _wait_job(done["result"]["job_id"])


@api.post("/chat/agents/bundle")
async def agent_bundle(body: AgentBundleIn, owner: str = Depends(chat_owner), user: Optional[dict] = Depends(optional_user)):
    bundle_id, now = str(uuid.uuid4()), now_iso()
    idea = body.idea.strip()
    include = [k for k in ("image", "video", "music") if k in set(body.include)]
    if not include:
        raise HTTPException(status_code=422, detail="include must name at least one of image, video, music")
    for k in include:
        enforce_engine_permission(owner, k)
    specs = [s for s in [("image", idea, body.style or "cinematic", body.image_model, 0),
                         ("video", f"{idea}, cinematic camera movement", body.style or "cinematic", None, 5),
                         ("music", f"Soundtrack for: {idea}", None, None, 15)] if s[0] in include]
    tasks = [{"id": str(uuid.uuid4()), "bundle_id": bundle_id, "owner": owner, "type": ty, "prompt": pr[:500],
              "style": st, "model": mo, "duration": du, "conversation_id": None, "status": "queued",
              "result": None, "error": None, "created_at": now, "updated_at": now} for ty, pr, st, mo, du in specs]
    await db.agent_tasks.insert_many([t.copy() for t in tasks])
    asyncio.create_task(_run_bundle(tasks, user))
    return {"bundle_id": bundle_id, "idea": idea, "tasks": tasks}


@api.get("/chat/agents/bundle/{bid}")
async def agent_bundle_status(bid: str, owner: str = Depends(chat_owner)):
    tasks = await db.agent_tasks.find({"bundle_id": bid, "owner": owner}, {"_id": 0}).to_list(10)
    if not tasks:
        raise HTTPException(status_code=404, detail="Bundle not found")
    for t in tasks:
        res = t.get("result") or {}
        if res.get("job_id"):
            j = await db.jobs.find_one({"id": res["job_id"]}, {"_id": 0})
            t["job"] = await job_out(j) if j else None
    order = {"image": 0, "video": 1, "music": 2}
    return {"bundle_id": bid, "tasks": sorted(tasks, key=lambda t: order[t["type"]])}


@api.get("/chat/agents/tasks/{tid}")
async def agent_task_status(tid: str, owner: str = Depends(chat_owner)):
    t = await db.agent_tasks.find_one({"id": tid, "owner": owner}, {"_id": 0})
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")
    if t.get("result", {}) and t["result"].get("job_id"):
        j = await db.jobs.find_one({"id": t["result"]["job_id"]}, {"_id": 0})
        t["job"] = await job_out(j) if j else None
    return t


# ---------- Frasberg Engine Runtime (packages/*-engine, interpreted) + engine rules ----------
class EngineExecIn(BaseModel):
    input: str = Field(default="", max_length=2000)
    state: dict = Field(default_factory=dict)


    continuity: Optional[str] = Field(default=None, max_length=256)


class EngineChainIn(EngineExecIn):
    engines: list[str] = Field(min_length=1, max_length=12)


class EngineFlowIn(BaseModel):
    domain: str
    input: str = Field(default="", max_length=2000)
    awareness: Optional[dict] = None
    state: dict = Field(default_factory=dict)


class EngineBlockIn(BaseModel):
    actions: list[str] = Field(default_factory=list, max_length=200)
    scope: str = Field(default="owner", pattern="^(owner|global)$")


def _state_ok(state: dict):
    if len(json.dumps(state, default=str)) > 64_000:
        raise HTTPException(status_code=413, detail="state is too large (64 KB max)")


async def engine_owner(request: Request, user: Optional[dict] = Depends(optional_user)) -> str:
    """Engines are internal: admins (JWT) or platform frb_live keys only."""
    key = request.headers.get("X-Frasberg-Key", "")
    if user and user["email"].lower() in ADMIN_EMAILS:
        return f"admin:{user['email'].lower()}"
    if key and key in FRASBERG_KEYS:
        return f"platform:{key[9:17]}"
    if user:
        raise HTTPException(status_code=403, detail="Admins only")
    raise HTTPException(status_code=401, detail="Sign in as an admin or send a valid X-Frasberg-Key")


async def _enforce(engine: str, owner: str, cid: Optional[str], action: Optional[str] = None) -> dict:
    try:
        return await engine_systems.unified_enforce(engine, owner, {"continuity": cid, "action": action})
    except engine_systems.EnforceError as e:
        raise HTTPException(status_code=403, detail=str(e))


async def _with_continuity(owner: str, cid: Optional[str], state: dict) -> dict:
    if not cid:
        return state
    saved = (await engine_systems.load_continuity(owner, cid))["state"]
    return {**saved, **state}


def _run_state(model: dict) -> dict:
    return {k: v for k, v in model.items() if isinstance(v, dict)}


@api.get("/engines/runtime")
async def engines_runtime(_: str = Depends(engine_owner)):
    return {"count": len(engine_runtime.REGISTRY), "source": "packages/*-engine (TypeScript), run by the Frasberg Engine Runtime",
            "engines": engine_runtime.catalogue(), "systems": engine_systems.SYSTEMS,
            "total": len(engine_runtime.REGISTRY) + len(engine_systems.SYSTEMS)}


@api.get("/engines/runtime/{engine_id}")
async def engines_runtime_one(engine_id: str, _: str = Depends(engine_owner)):
    if engine_id not in engine_runtime.REGISTRY:
        raise HTTPException(status_code=404, detail="Unknown engine")
    return engine_runtime.describe(engine_id, full=True)


@api.post("/engines/chain")
async def engines_chain(body: EngineChainIn, owner: str = Depends(engine_owner)):
    unknown = [e for e in body.engines if e not in engine_runtime.REGISTRY]
    if unknown:
        raise HTTPException(status_code=404, detail=f"Unknown engine: {', '.join(unknown)}")
    _state_ok(body.state)
    for e in body.engines:
        enf = await _enforce(e, owner, body.continuity)
    try:
        res = engine_runtime.chain(body.engines, body.input, await _with_continuity(owner, body.continuity, body.state))
    except engine_runtime.EngineError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if body.continuity:
        st = {}
        for s in res["steps"]:
            st.update(_run_state(s["model"]))
        await engine_systems.update_continuity(owner, body.continuity, st, "chain")
    return {**res, "requestId": enf["requestId"], "continuity": body.continuity}


@api.post("/engines/flow")
async def engines_flow(body: EngineFlowIn, owner: str = Depends(engine_owner)):
    _state_ok(body.state)
    if body.domain not in engine_systems.FLOW_DOMAINS:
        raise HTTPException(status_code=404, detail=f"Unknown domain. Use one of: {', '.join(engine_systems.FLOW_DOMAINS)}")
    enf = await _enforce("engine-flow", owner, None, f"flow:{body.domain}")
    try:
        res = engine_systems.flow(body.domain, body.awareness or engine_systems.sample_awareness(), body.input, body.state)
    except (engine_runtime.EngineError, engine_systems.EnforceError) as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {**res, "requestId": enf["requestId"]}


@api.post("/engines/{engine_id}/execute")
async def engines_execute(engine_id: str, body: EngineExecIn, owner: str = Depends(engine_owner)):
    if engine_id not in engine_runtime.REGISTRY:
        raise HTTPException(status_code=404, detail="Unknown engine")
    _state_ok(body.state)
    enf = await _enforce(engine_id, owner, body.continuity)
    try:
        res = engine_runtime.execute(engine_id, body.input, await _with_continuity(owner, body.continuity, body.state))
    except engine_runtime.EngineError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if body.continuity:
        await engine_systems.update_continuity(owner, body.continuity, _run_state(res["model"]), engine_id)
    return {**res, "requestId": enf["requestId"], "continuity": body.continuity}


@api.get("/engines/systems")
async def engines_systems_list(owner: str = Depends(engine_owner)):
    return {"owner": owner, "systems": engine_systems.SYSTEMS, "flow_domains": engine_systems.FLOW_DOMAINS,
            "governance": await engine_systems.load_governance(owner), "policy": await engine_systems.load_policy(owner)}


@api.get("/engines/governance")
async def engines_governance(owner: str = Depends(engine_owner)):
    return await engine_systems.load_governance(owner)


@api.put("/engines/governance")
async def engines_governance_set(body: EngineBlockIn, owner: str = Depends(engine_owner)):
    if body.scope == "global" and not owner.startswith("admin:"):
        raise HTTPException(status_code=403, detail="Only admins can set global governance")
    target = "*" if body.scope == "global" else owner
    await engine_systems.save_governance(target, body.actions, owner)
    return await engine_systems.load_governance(owner)


@api.get("/engines/policy")
async def engines_policy(owner: str = Depends(engine_owner)):
    return await engine_systems.load_policy(owner)


@api.put("/engines/policy")
async def engines_policy_set(body: EngineBlockIn, owner: str = Depends(engine_owner)):
    return await engine_systems.save_policy(owner, body.actions, owner)


@api.get("/engines/diagnostics")
async def engines_diagnostics(component: Optional[str] = None, owner: str = Depends(engine_owner)):
    if component:
        if component not in engine_systems.DIAG_COMPONENTS:
            raise HTTPException(status_code=404, detail="Unknown component")
        return {"component": component, "events": await engine_systems.fetch_diagnostics(owner, component)}
    return await engine_systems.aggregate_diagnostics(owner)


@api.get("/engines/identity")
async def engines_identity(owner: str = Depends(engine_owner)):
    return await engine_systems.load_identity(owner)


@api.get("/engines/continuity/{cid}")
async def engines_continuity(cid: str, owner: str = Depends(engine_owner)):
    return await engine_systems.load_continuity(owner, cid)


@api.delete("/engines/continuity/{cid}")
async def engines_continuity_delete(cid: str, owner: str = Depends(engine_owner)):
    if not await engine_systems.delete_continuity(owner, cid):
        raise HTTPException(status_code=404, detail="Continuity not found")
    return {"deleted": cid}


@api.get("/engines/rules")
async def engines_rules(_: str = Depends(engine_owner)):
    return {"summary": engine_rules.summary(), "engines": engine_rules.RULES,
            "default_duration": engine_rules.DEFAULT_DURATION}


app.include_router(api)
app.include_router(frasberg_gpu.router)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


MAX_JOB_ATTEMPTS = 3


async def _resume_interrupted_jobs():
    """A heavy local engine can trip a transient memory spike while loading and
    get the pod restarted. Instead of hard-failing interrupted jobs, re-queue them
    (bounded) so they retry once the model file is warm in cache; give up after
    MAX_JOB_ATTEMPTS."""
    async for job in db.jobs.find({"engine": "local", "status": {"$in": ["queued", "running"]}}):
        attempts = job.get("attempts", 0) + 1
        if attempts <= MAX_JOB_ATTEMPTS:
            await db.jobs.update_one({"id": job["id"]}, {"$set": {"status": "queued", "attempts": attempts, "error": None}})
            job.update({"status": "queued", "attempts": attempts})
            asyncio.create_task(run_media(job))
        else:
            await db.jobs.update_one({"id": job["id"]},
                                     {"$set": {"status": "failed", "error": "Generation failed after several attempts. Please try again."}})
    async for m in db.models3d.find({"status": {"$in": ["queued", "running"]}}):
        attempts = m.get("attempts", 0) + 1
        if m.get("source") == "text" and m.get("prompt") and attempts <= MAX_JOB_ATTEMPTS:
            await db.models3d.update_one({"id": m["id"]}, {"$set": {"status": "queued", "attempts": attempts, "error": None}})
            asyncio.create_task(run_3d(m["id"], m["prompt"], None))
        else:
            await db.models3d.update_one({"id": m["id"]},
                                         {"$set": {"status": "failed", "error": "3D generation failed after several attempts. Please try again."}})


@app.on_event("startup")
async def startup():
    await db.users.create_index("email", unique=True)
    await db.users.create_index("id")
    await db.generations.create_index("id")
    await db.generations.create_index([("session_id", 1), ("created_at", -1)])
    await db.generations.create_index([("user_id", 1), ("created_at", -1)])
    await db.jobs.create_index("id")
    await db.login_attempts.create_index("identifier")
    await db.voice_takes.create_index([("user_id", 1), ("created_at", -1)])
    await db.models3d.create_index("id")
    await db.spaces.create_index("id")
    await db.spaces.create_index([("user_id", 1), ("updated_at", -1)])
    await frasberg_gpu.ensure_indexes()
    await _resume_interrupted_jobs()
    loop = asyncio.get_running_loop()
    loop.run_in_executor(None, local_engines.warm_up)
    await aws_gpu.load_settings()
    base = os.environ.get("FRASBERG_PUBLIC_URL", "").rstrip("/")
    if aws_gpu.enabled() and base:
        asyncio.create_task(aws_gpu.reconcile_loop(f"{base}/api/gpu", os.environ["FRASBERG_WORKER_SECRET"]))


@app.on_event("shutdown")
async def shutdown():
    client.close()
