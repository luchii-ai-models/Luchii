# Luchii AI Clone — PRD

## Original problem
Import and clone an exact copy of luchii-ai.com (tools, files, database, features, models, stack) and wire it with the user's own Frasberg keys. No Emergent universal key. Production uses the live MongoDB `luchii-tools`.

## Architecture
- Frontend: the original React source, recovered from the live site's public source map (`main.65f24d02.js.map`). Same pages, styles, starfield, mock content.
- Backend: FastAPI rewritten to match the live API contract. Every AI call goes through Frasberg (`FRASBERG_BASE_URL=https://frasberg.com/api`). It rotates through 8 `frb_live_*` keys, retrying on permission and server errors.
- DB: MongoDB collections `users`, `generations`, `jobs`, `login_attempts`. Preview uses local Mongo because Atlas blocks this pod's IP. Production uses MONGO_URL/DB_NAME from the deployment secrets.

## Implemented (2026-06)
- Pages: Home, /create (text-to-image, image-to-image, upscale, share, download), /gallery, /s/:id, /models, /tts, /developers, /legal/:doc. New: /video (Video Creator) and /audio (Audio Studio).
- JWT auth (register/login/me), lockout after 5 bad attempts per email.
- Frasberg wiring: /generate/image (generate/edit/upscale), /voice/speak (TTS), /generate/video and /generate/music, polled via /jobs/{id}, with a music WAV proxy.

## Upstream status (Frasberg, at build time)
- Image: HTTP 502 upstream. TTS: 503 "voice engine warming up". Only key #5 has music permission, and none of the keys have text_to_speech permission.
- Video jobs complete, but they return sample MDN clips.

## Backlog
- P0: Get Frasberg image and voice endpoints healthy. Grant text_to_speech permission to the keys.
- P1: Speech to Speech, 3D Studio, Spaces Builder (still "Soon").
- P2: (dropped by the user) in-app chat assistant.

## Update (2026-10)
- In-house Luchii engines are used when a Frasberg-keyed call fails: Piper voices (TTS/STS), faster-whisper base (STT), SD-Turbo on CPU (generate/edit/upscale). Models are stored in LUCHII_MODELS_DIR and preloaded at startup.
- Voice Cloning page (/voice-clone): samples are stored in a GridFS voice_samples bucket. Speaking in the cloned voice is Frasberg-only.
- Per-feature key routing via FRASBERG_KEY_ROUTES.
- The /status page and /api/engines/status are admin-only (ADMIN_EMAILS) and the Status link is no longer in the public nav.
- The homepage showcase only shows generations with featured=true and otherwise falls back to the curated graphics.

## Update (2026-10, import)
- Restored from GitHub frasberg-code/luchii-tools into a new pod. Backend .env restored, frontend uses this pod URL. Deps installed (emergentintegrations/litellm skipped, not used). Smoke tests passed (iteration_5).
- 2026-10: Image queue (429 + Retry-After when the local image engine is busy; /create shows a queue notice and auto-retries). /login and /signup routes open the auth modal (?next= supported). STS studio upgraded: editable transcript, re-speak in any voice, takes history with download. Tests: iteration_6 all pass.
- 2026-10: Rebrand to "Luchii" with the new logo/favicon and "Powered by Frasberg" copy. 3D Studio (/3d) uses Shap-E on CPU (DPM++ 10 steps, ~3 min), with jobs queued in db.models3d and GLBs stored in GridFS. Model files are in LUCHII_SCRATCH_MODELS_DIR and re-download after a restart. Voice clone uses a vendored OpenVoice V2 converter (backend/vendor/openvoice) as a fallback in /voice/clone/speak and in /sts voice=clone. Saved voice takes are in db.voice_takes plus GridFS, shown in the /gallery tabs. Tests: iteration_7 passes.

## Update (2026-06, fork — stability fix + feature validation)
- **FIXED critical pod-restart loop**: boot-time `warm_up()` preloaded SD-Turbo + OpenVoice into RAM AND `snapshot_download`-ed ~6GB of Shap-E/music weights to `/tmp` (wiped every restart). This flooded the 8GB cgroup → kubelet evicted the whole pod mid-download → infinite loop every ~3-5 min, killing every long-running job with "Interrupted by a server restart". 
  - Changes: `LUCHII_SCRATCH_MODELS_DIR` → `/var/luchii-models/scratch` (persistent, backend/.env). `warm_up()` now only pre-caches the small Piper voice; all heavy engines (SD, Shap-E, MusicGen, OpenVoice) load lazily on first request. Removed the auto `prefetch_scratch_models` call from startup (kept the fn for optional use). Backend now stable for 6+ min idle, pid unchanged.
- **Validated REAL generation end-to-end** (all produce real files, pod stable, peak mem ~5GB of 8GB):
  - Image: SD-Turbo local (proven earlier).
  - Music: MusicGen → 321KB WAV 16-bit mono 32kHz.
  - Video: SD-Turbo frames → 252KB MP4 (glTF... no, ISO MP4 v1).
  - 3D: Shap-E → 4.3MB GLB (glTF binary v2). Text-to-3D has no thumbnail by design (frontend renders GLB in a viewer).
  - Speech-to-Speech (/sts): faster-whisper transcribe + Piper re-voice → 117KB WAV, accurate transcript.
- 3D Studio (/3d) and Speech-to-Speech (/sts) pages confirmed fully built and loading; both usable without login.

## Update (2026-06, fork — generation speed + memory optimization)
Hardware reality of this pod: **2 CPU cores, no AVX2/bf16 hardware, ~6GB effective memory** (the 8GB cgroup is never the killer — oom_kill stays 0; the pod is evicted at the node/pod level around 6GB). So bf16/fp16 are useless (emulated → slower) and only ~1 big model fits at a time.
- **Images 2.4x faster (38s → 10–16s):** swapped SD-Turbo's heavy VAE for the TAESD tiny VAE (`madebyollin/taesd`) + `channels_last`. Quality verified unchanged (photorealistic, no artifacts). Same SD pipeline powers **video**, so video keyframes are faster too.
- **One-heavy-model-resident policy (`_claim` in local_engines.py):** SD (image/video), Shap-E (3D) and MusicGen (music) are mutually exclusive — before a different big engine loads, the others are freed + `gc.collect()` + `libc malloc_trim(0)` to return RSS to the OS. This prevents the two-models-resident spike that was evicting the pod. OpenVoice/Whisper/Piper are small and stay resident.
- **3D weight caching (the explicit ask):** Shap-E weights persist on disk (`/var/luchii-models/scratch`, no re-download) and the loaded pipeline stays resident across requests, so **repeat 3D requests skip the load and complete reliably** (verified: warm repeat 3D ran with a stable pid). Added `low_cpu_mem_usage=True` to the Shap-E load.
- **Self-healing first load:** the first Shap-E/MusicGen load has a transient spike that can trip a pod restart on this tight budget. `_resume_interrupted_jobs()` now re-queues interrupted media/3D jobs (bounded to MAX_JOB_ATTEMPTS=3, text-source only for 3D) instead of hard-failing — on retry the model file is warm in cache, the spike is smaller, and the job completes. Verified: a cold 3D job self-healed across a restart and finished (3MB GLB).
- **Validated end-to-end after changes:** image 10–16s, video MP4, 3D 3MB GLB, music WAV, S2S WAV — all real files, services stable.
- Note for future: 3D's first cold load remains the only fragile step on this 2-core/~6GB pod. A larger pod (or a dedicated 3D worker) would make it instant and bulletproof.

## Update (2026-06, fork — Prompt Presets + video reality check)
- **Prompt Presets shipped (all 4 studios), tested 100% (iteration_8):** one-tap chips that fill a ready-to-go prompt (and matching style). Data in `/app/frontend/src/presets.js`, reusable `PresetRow` in `/app/frontend/src/components/PresetRow.jsx`. Image: Portrait/Landscape/Product/Anime/Logo/Sci-fi. Video: Cinematic/Nature/Anime/Product ad/Fantasy/Vlog. Music (user-requested genres): Reggae, Reggae Fusion, Reggae Dancehall, Amapiano, Jazz. 3D: Game asset/Character/Vehicle/Furniture/Food/Sci-fi prop.
- **CONFIRMED: Frasberg/Luchii video API is FAKE.** POST https://frasberg.com/api/generate/video returns a job that "completes" with `video_url = https://filesamples.com/samples/video/mp4/sample_640x360.mp4` — a public stock sample clip, unrelated to the prompt (gpu_class/region fields are cosmetic). So the Frasberg keys cannot produce real video. The current `/video` endpoint uses the **local SD-Turbo keyframe + Ken Burns slideshow** (local_engines.generate_video) — which is why users see drifting slideshows with warped faces. Real AI video is GPU-only and cannot run on this 2-core CPU pod.
- **BLOCKED — real AI video needs fal.ai (or similar) + the user's API key.** Plan once key provided: integrate fal.ai text-to-video + image-to-video (image-to-video = TikTok-style animate-a-photo), with a per-generation model/quality selector (fast LTX-Video ↔ high-quality Kling/Veo). Route `/video` to fal.ai, keep local slideshow only as a last-ditch fallback, and update the video studio copy (currently claims "Powered by Frasberg renders keyframes").

## Update (2026-10, re-import + Frasberg key audit)
- Re-imported luchii-ai-models/frasberg-secure-runtime (HEAD 8cae905). Recreated backend/.env + frontend/.env (they were missing), created /var/luchii-models/scratch. Services up.
- All 9 user keys wired (FRASBERG_API_KEYS) with per-feature routing (FRASBERG_KEY_ROUTES): image→be3354f2, video→a1872bf2|be3354f2, music→a0e8a8fb|722a8e9e, clone→eac278f3, audio→0257e1a1, stt→b439ef0d, tts→57d798ce. Key 9b4aa1f2 kept but returns 401 key_not_found.
- Key audit (live, 2026-10-09): /generate/image = 502 on every key; /voice/speak = 403/503; /generate/video "completes" with rotating stock clips (filesamples, test-videos.co.uk Big Buck Bunny, MDN flower.mp4), `model` field ignored; /generate/music returns a synthesized fixed chord drone ("mood":"major"), not prompt-specific music. Frasberg's own site bundle references no real video model.
- /video is now Frasberg-first: `frasberg_video()` submits to the Video Engine key, polls, accepts only non-sample renders, otherwise falls back to the local engine. Job status exposes `engine` (frasberg | luchii-local).
- Frasberg server is NOT in this repo — it must be fixed on the Frasberg side (real GPU models) for real renders.

## Update (2026-10, Frasberg Serverless GPU)
- `backend/frasberg_gpu.py` is the Frasberg Serverless GPU Gateway, mounted at `/api/gpu` and tested 21/21 in iteration_9.
  - Client API in the frasberg.com style: `/v1/engines`, `/generate/video`, `/generate/image`, `/jobs/{id}`, `/files/{id}`. Auth is the exact frb_live keys from FRASBERG_API_KEYS; a bad key returns FK-001.
  - Worker pull API at `/worker/*`, using the FRASBERG_WORKER_SECRET header. Includes heartbeat, an atomic claim that prefers the warm model, chunked upload, a 180s lease with re-queue (3 attempts max), and re-queue on OOM.
  - Mongo collections: gpu_jobs, gpu_workers, gpu_chunks. GridFS bucket: gpu_outputs.
- `/app/frasberg_gpu_worker/` is a standalone worker (Dockerfile, requirements-gpu.txt, prefetch.py, NOTICE.md). Its engines are frasberg-motion-fast (LTX-Video 0.9.7 distilled, two-stage), frasberg-motion-pro (Wan 2.2 TI2V-5B), frasberg-motion-ultra (HunyuanVideo T2V and I2V) and frasberg-image (FLUX.1-schnell). The hidden frasberg-dev-test engine is only for protocol testing. Unloads after an idle timeout (scale-to-zero).
  - NEVER pip install requirements-gpu.txt into the backend venv. It upgrades diffusers and transformers and breaks the local engines (backend pins diffusers 0.31.0 and transformers 4.46.3).
- Luchii `/api/video` accepts model, aspect_ratio and image_base64. Routing order: an online GPU worker for the chosen engine, then any online motion engine, then frasberg.com, then Frasberg Lite (local CPU).
  - frasberg.com clips are rejected if the URL is a known sample or the bytes repeat a render made for a different prompt (db.frasberg_video_hashes).
- `/api/generate` (text-to-image) tries the Frasberg Image GPU first when a worker is online.
- `/video` UI has an engine picker with live status, format chips, a start-image upload (image-to-video), and the engine label and progress percentage. The Models page lists Motion Fast, Pro and Ultra.
- BLOCKER for real renders: at least one NVIDIA GPU machine (24GB+, or 80GB for Ultra) must run the worker. This pod has no GPU.

## Update (2026-10, video presets + gallery)
- The /video page has "Trending" TikTok-style presets: Surprise me (a random idea from SURPRISE_VIDEO_IDEAS), POV, Glow-up transition, Satisfying loop, Pet reaction, Street dance, Food ASMR and Outfit check. Picking one sets the format to 9:16.
- Once a start image is attached, a "Photo motion" row replaces those presets: Zoom in, Orbit 360, Hair in wind, Come alive, Dolly out, 3D parallax, Slow-mo, Rain & neon. Data is in presets.js.
- New `GET /api/videos` (signed-in user's finished clips) and public `GET /api/videos/{id}`. Legacy engine labels are mapped to Frasberg names.
- The gallery has a Videos tab: each clip card has a player, a badge, replay, share, download and open.
- Public share page at `/v/:id`. Shared clips use the native share sheet when available, otherwise the link is copied. Studio results also get a Share button.
- Tests: iteration_10 passed 100% (backend tests in backend/tests/test_videos_api.py).

## Update (2026-10, zero-cost real video)
- Checked github.com/frasberg-code/frasberg-secure-runtime (now public). Its /api/video only forwards to frasberg.com, and cinematicRenderV2 is an ffmpeg placeholder. It contains no video model or GPU code.
- Emergent has no GPU hosting. The Sora 2 API was shut down on 2026-09-24. Veo needs a paid Google key, which the user declined (zero cost).
- New engine **frasberg-motion-free** (LTX-Video 2B, 480p, text-to-video and image-to-video) for free 16GB T4s (Kaggle/Colab). Its calls were checked against diffusers 0.39 with tiny random weights.
- Worker package moved to /app/backend/frasberg_gpu_worker. The gateway serves its files at /api/gpu/worker/files/{name} (worker secret required).
- Admin endpoints: /api/gpu-admin/overview and /api/gpu-admin/notebook. The notebook comes pre-filled with the gateway URL and secret, and the gateway must be this server's own host.
- /status now has a GPU panel: workers, job counts, a free-notebook download and Kaggle steps.
- Queued GPU jobs expire after 30 minutes (QUEUE_TTL).
- Honest UI: a "Preview mode" banner shows when no GPU is online, and Lite clips are labelled "Preview · animated stills" (studio, gallery, share page). The engine defaults to Motion Free and auto-selects an online engine.
- Tests: iteration_11 passed 37/37 backend plus all frontend checks.
- Preview-only admin test account: admin.tester@luchiiapp.com is in ADMIN_EMAILS in backend/.env.

## Update (2026-06, re-import)
- Re-imported luchii-ai-models/frasberg-secure-runtime. Recreated backend/.env with the 8 user frb_live keys + FRASBERG_KEY_ROUTES, installed deps + ffmpeg, re-created admin.tester / motion.tester accounts. Smoke tests passed (iteration_12).
- /status GPU panel polling now pauses when the tab is hidden.
- P2 in-app chat assistant was built, then REMOVED at the user's request (it is not wanted in the app). Do not re-add it.
- 2026-06: Rebranded the platform from "Luchii" to "Frasberg Creator" (nav, hero, footer, auth, legal, studios, share pages, title, toasts) with the FA Frasberg emblem as logo + favicon. "Luchii" now only names the Frasberg AI models and intelligence (Luchii Models, Luchii Prime, Vision, etc.). Internal storage keys (luchii_token) unchanged.
- 2026-06: Luchii logo restored for Luchii Models (Models page family header + each Luchii model card, API docs note). "Made with Luchii" restored (home featured, share page, 3D share). Footer copyright: "© 2003-2026, Frasberg, Inc. or its affiliates". Legal states Frasberg.com / Frasberg, Inc. own and operate Luchii AI Models and all Luchii products and systems. luchii-ai.com stays.
- 2026-06: Luchii badge (components/LuchiiBadge.jsx) on all creations: create result, gallery image + video cards, image share /s/:id, video share /v/:id, video & music studio results. New /about-luchii page (logo, 5 pillars, model family, CTAs), linked from footer "About Luchii". Tests: iteration_13 100%.
- 2026-06: "About Luchii" nav link with Luchii logo (desktop + mobile). Badges now name the model: Nova-Muse (default), Dreamline (anime/digital-art), Vision (3d), Painter-X (remix), Prime (upscale), Luchii Video, Luchii Audio (components/LuchiiBadge.jsx luchiiModelFor). Downloads carry the Luchii mark: images via canvas (lib/luchiiMark.js), videos via GET /api/media/{id}/download (ffmpeg overlay, cached in GridFS marked_file_id). /api/share/{id} returns kind. Tests: iteration_14 100%.
- 2026-06: Named Luchii video/music models: Luchii Cinematica (text-to-video), Luchii Animus (photo-to-video), Luchii Harmonia (music) — shown on all badges and as cards on /models. Gallery Images and Videos tabs have a Luchii model filter (chips, only shown when 2+ models present). Tests: iteration_15 100%.
- 2026-06: Nav/footer "About Luchii" renamed "Luchii Code" (still /about-luchii).
- 2026-06: Luchii Chat BACKEND ONLY (for other Frasberg platforms — no chat UI on this creator site, user explicit): GET /api/chat/models (proxy Frasberg /v1/models, chat-capable), GET/DELETE /api/chat/conversations[/id], POST /api/chat/send (SSE stream proxy to Frasberg /v1/chat, model switch, session continuity, db.chat_conversations), POST/GET /api/chat/agents/tasks (agents dispatch image/video/music creator jobs, db.agent_tasks). Auth: user JWT or X-Frasberg-Key (frb_live key). Upstream luchii chat currently replies "turbulence".
- 2026-06: Luchii model picker on /create (Nova-Muse / Dreamline / Vision for text, Painter-X for remix); model sent to /api/generate (prompt hint, stored on generation), shown on badges; /models "Try" preselects. Tests: iteration_16 100%.

## Update (2026-10, conflict branch merged)
- Re-imported luchii-ai-models/frasberg-secure-runtime. Branch `conflict_091026_2226` had unrelated history (squashed re-import of main@00fd644 + assistant). Grafted it onto main@00fd644 and 3-way merged: clean, no file conflicts. Result = main + all conflict-branch work (Agent bundle /api/chat/agents/bundle, Luchii Cinematica/Animus/Harmonia model selection, 429 retry, VideoModelPicker, ChatDocs, LuchiiAgent page, Luchii Code/Chat backend, badges/marks). Temp PR template removed.
- Recreated backend/.env (8 frb_live keys + FRASBERG_KEY_ROUTES) and frontend/.env, installed deps + ffmpeg, seeded test accounts.

## Update (2026-10, photoreal engine + async image jobs + real showcase)
- Frasberg has no image model: /v1/models + docs list only chat/embed/music/audio, and /api/generate/image returns a Cloudflare 502 on every key. So images come from the in-house Luchii engines (zero cost, no third-party keys).
- NEW photoreal engine for **Luchii Nova-Muse**: Realistic Vision V6 (fp16 single file) + sd-vae-ft-mse + LCM-LoRA, 4 steps, cfg 1.0, ~2 min on the 2-core CPU (local_engines.generate_photo). Dreamline/Vision stay on SD-Turbo (~15-20s).
- All image weights (RV6, LCM, VAE, SD-Turbo fp16 variant, TAESD) are in LUCHII_PHOTO_MODELS_DIR=/root/luchii-models/hf on the PERSISTENT volume. /var and /tmp are wiped on pod restart. HF_HUB_DISABLE_XET=1 is needed, because xet downloads hang or crash here.
- Async image jobs: POST /api/generate/jobs, /api/edit/jobs, /api/upscale/jobs -> {job_id}; GET /api/image-jobs/{id} -> {status queued|running|completed|failed, result{...image_base64}}. Jobs go stale after 20 min. /create uses them now (no more ingress 502 on long renders). The sync /api/generate etc. are kept for the API and agents.
- Homepage showcase: the 8 Unsplash/Pexels stock photos were replaced with images generated by this system from the same 8 prompts (frontend/public/showcase/*.jpg, mock.js).
- Known limits: Painter-X (SD-Turbo img2img) barely follows edit instructions. cfg 1.0 means the negative prompt is ignored.

## Update (2026-10, Painter-X real edits, Quick draft, colour fix)
- Painter-X (/api/edit and /api/edit/jobs) now uses InstructPix2Pix (timbrooks/instruct-pix2pix fp16, Euler-A 8 steps, cfg 7, image cfg 1.5) via local_engines.instruct_edit. It follows commands like "make it a snowy winter night". ~2.5–4 min. Weights are in SCRATCH (ephemeral /var) and re-download (~2GB) after a pod restart, because the persistent volume has only ~1.7GB free.
- Nova-Muse Quick draft: GenerateIn.quality="draft" renders at 3/4 size with 3 steps (~30–55s). The response returns seed, quality and aspect_ratio. The /create "Render full quality" button re-runs the same prompt and seed with quality="full". UI testids: draft-toggle, draft-toggle-input (default ON for Nova-Muse), draft-badge, render-full-btn, painterx-hint.
- Colour fix: STYLE_HINTS no longer force "teal/cyan/violet" brand palettes (cinematic, 3d, digital-art), which had made every image the same colours. Showcase regenerated. The Golden Hour card was retaken with a warm amber dusk prompt (mock.js prompt updated).
- Nova-Muse prompts that mention people get "wearing a stylish outfit" added (cfg 1.0 ignores the negative prompt).

## Update (2026-10, re-import + showcase restore + public gallery)
- Re-imported luchii-ai-models/frasberg-secure-runtime into /app/backend + /app/frontend; recreated .env files (8 frb_live keys + FRASBERG_KEY_ROUTES), admin.tester account.
- Homepage showcase always shows the 8 curated images (no longer replaced by /api/showcase). Images in frontend/public/showcase were rebuilt from the user's screenshot (labels removed, 2x upscaled, ~770px wide); source crops in /root/showcase_src.
- Public gallery: GET /api/gallery/public (public), POST /api/admin/gallery/publish-recent?hours=2 (admin) sets public:true on recent generations. Homepage "Public gallery" section (PublicGallery.jsx) shows when items exist.
- This pod's DB was empty, so publish-recent published 0. The last-2h images live in the previous pod/production DB; run the endpoint there.
- Tests: iteration_1 100%.
## Backlog
- P1: auto-publish toggle for new generations; higher-res originals of the 8 showcase images

## Update (2026-10, remix quality + gallery delete + model images)
- Painter-X remix now uses photoreal img2img on the Nova-Muse engine (RV6 + LCM, strength 0.5, local_engines.photo_remix) instead of InstructPix2Pix: sharp faces, keeps layout. Dreamline + Vision text-to-image also moved from SD-Turbo 2-step to the RV6 engine (PHOTO_MODELS) — no more warped/blurry people.
- Gallery: delete button per image (gallery-delete-{id}, always visible on mobile) + DELETE /api/generations/{id} (owner only).
- Models page: all 19 stock photos replaced with images generated by our own engines through the app's job API (frontend/public/models/*.jpg; scripts/gen_model_images.py + gen_model_prompts.py, skips existing files).
- User asked to "show all nudity" — not implemented; existing clothing steering kept.
- NOTE: never run a separate engine process alongside the backend (two RV6 copies -> pod OOM restart). Use the job API.
- Tests: iteration_2 100%.

## Update (2026-10-11, re-import + conflict_101026_1646 app changes)
- github.com/luchii-ai-models/frasberg-secure-runtime is identical to /app (only the preview URL defaults in tests differ), so nothing new had to be imported.
- The requested branch conflict_051026_0213 does not exist on origin. The only open conflict branches are conflict_091026_2226 (merged earlier) and conflict_101026_1646.
- conflict_101026_1646 has unrelated history and about 5000 files. Its app changes (backend/, frontend/src, frontend/public showcase and model samples, memory/) were applied to the working tree as a patch, with no git commits or merges. These cover remix via Nova-Muse, gallery delete, the public gallery and model samples. Its large imports/, packages/, apps/, studio/ and workers/ trees were NOT brought in.
- Recreated backend/.env (8 frb_live keys with the routes image/video/music/clone/audio/stt/tts) and frontend/.env, installed ffmpeg and the dependencies, and seeded the test accounts. Branch tests test_public_gallery and test_remix_delete_iter2 passed 11/11.
- 2026-10-11 (follow-up): the FULL contents of conflict_101026_1646 (SHA 03938aed, no newer pushes) are now in main's working tree, including all 4,895 added files (imports/, packages/, apps/, studio/, workers/, infra/, root package.json and so on). Every branch file exists locally. For the 14 files changed on both sides, main's version was kept: .emergent/emergent.yml, .gitignore, tests with the current preview URL, and the merged PRD. Nothing was deleted from main. The app was verified running.
- 2026-10-11: Luchii credit wording. Models cards say "Made with Luchii" (Luchii family) or "Created by Luchii" (Frasberg family), testid model-credit-{slug}. Studio and 3D progress text says "Created by Luchii". Share pages (video, 3D) dropped "Powered by Frasberg". The gallery subtitle now credits Luchii models. Gallery 3D cards show a Luchii Sculpt 3D badge.
- 2026-10-11: Surprise me and prompt accuracy.
  - Surprise me (lib/promptKit.js) is now a prompt grammar instead of a fixed list. Text ideas combine subject, action, place, time or light, mood, palette and look, with coherence rules for living/object subjects, indoor/outdoor places and water scenes. Product and remix ideas are built the same way, and 3D uses surprise3D(). Seen prompts are kept in localStorage (luchii_surprise_seen_v2): the last 300, plus a subject window. Video Surprise uses the freshFromList deck. 200 of 200 were unique in tests, with no repeat after a reload.
  - Accuracy fixes:
    - Uploads are opened through _open_image, which applies the EXIF orientation. Phone photos were being remixed sideways.
    - CLIP long-prompt chunking (_prompt_args, up to 225 tokens).
    - Detailed prompts (30+ tokens) on Nova-Muse/Dreamline/Vision use guidance 1.6 plus the negative prompt.
    - clean_prompt strips filler. emphasize_subject repeats the lead subject.
    - "Fully clothed" is no longer added when the user described clothing.
  - Painter-X routing: a command (make/change/give/add...) goes to InstructPix2Pix via normalize_instruction. Multi-part commands are applied step by step, and hair/clothes/hat/shoe edits are kept inside a SegFormer region mask (mattmdjaga/segformer_b2_clothes in PHOTO_MODELS_DIR). A description goes to photo_remix, and art-style remixes drop the photo hint and use strength 0.68. The /edit response includes instruction and edit_mode, and the UI shows a toast with the instruction it applied. The remix ETA is now 200s.
  - Verified: "give a blue hair and change clothes" on an EXIF-rotated photo gives an upright image with blue hair and a new shirt, with the face and background kept (about 4 min). A long fox prompt now renders the fox (131s).
- 2026-10-11: Speed, faces and safety.
  - Speed:
    - The photo engine now decodes with TAESD instead of the full VAE (saves about 20s) and runs its Linear layers in bf16. The pod is Neoverse-V2 ARM, 2 CPUs and 8GB. Convolutions and attention stay fp32, because bf16 is very slow for them here.
    - Detailed-prompt guidance is off. The draft keeps full size with 3 steps.
    - At boot the photo engine, region parser, Face Fix and safety filter are kept warm (backend RSS about 5.5GB).
    - Frasberg image calls are skipped for 10 min after a failure.
    - Timings: text-to-image about 43s, quick draft about 30s.
  - Painter-X fast_edit:
    - Region edits (hair, clothes, face, hat, background) are a single masked img2img pass on the photo engine, about 50s.
    - Other whole-image edits run guided at 512px, about 50s.
    - Art styles (oil, watercolor, sketch, charcoal, comic/anime, pop art, pixel, mosaic/stained glass, ukiyo-e, vintage, b&w, neon, marble) use OpenCV filters in luchii_styles.py, 1–4s. The opencv-contrib-python-headless package was added.
    - Descriptive remixes also go through fast_edit. IP2P is no longer used.
  - luchii_face.py (Face Fix): YuNet detection, FFHQ alignment and GFPGAN 1.4 ONNX, blended at 0.85. It runs on every photo render and edit (not on art styles), about 3.5s. Weights are in /root/luchii-models/face.
  - Safety filter: Falconsai/nsfw_image_detection checks each render (threshold 0.6). If flagged, it does one guided retry with SAFE_PROMPT and the negative prompt; if still flagged it raises UnsafeImage, returned as 422 "The Luchii safety filter blocked this result…".

## Update (2026-10-11, re-import into new pod)
- origin/main of luchii-ai-models/frasberg-secure-runtime is identical to /app HEAD (nothing new to pull).
- Recreated backend/.env (8 frb_live keys + FRASBERG_KEY_ROUTES, new JWT/worker secrets, ADMIN_EMAILS) and frontend/.env. Created model dirs, installed backend deps (emergentintegrations/litellm skipped) + ffmpeg, restarted.
- Seeded admin.tester@luchiiapp.com / AdminTest123! and test@luchii.ai / Test1234! (memory/test_credentials.md).
- Smoke: auth/me, engines status, public gallery OK. Nova-Muse draft render completed in ~36s (luchii-local). Home + /create render on desktop and mobile.

## Update (2026-10-11, auto-publish + remix history + free Kaggle GPU video)
- Auto-publish: users.auto_publish (GET/PUT /api/me/settings, also in /auth/me). save_generation sets public=true when on; body.publish overrides; guests never publish. POST /api/generations/{id}/publish {public} (owner). UI: composer switch `auto-publish-toggle`, result `result-publish-btn`, gallery `gallery-publish-{id}` + Public badge.
- Remix history: edit/upscale/remove-bg take parent_id; a fresh upload becomes a hidden kind=source doc (step 0, excluded from every list). Docs carry parent_id/root_id/step(+instruction). GET /api/generations/{id}/history -> chain with mini_base64 (cached). UI: components/RemixHistory.jsx strip on /create (path lit, branches dimmed), /create?gen=<id> deep link, gallery History button.
- Free Kaggle GPU (REAL, verified): backend/kaggle_gpu.py uses kagglesdk with KAGGLE_API_TOKEN + KAGGLE_USERNAME=frasberg (backend/.env). A video whose engine is not online pushes a private notebook (slug frasberg-gpu-worker-<host hash>, NvidiaTeslaT4, internet on) that bootstraps the worker from /api/gpu/worker/files. Boot beacons POST /api/gpu/worker/boot -> job.phase gpu-boot/gpu-queued/gpu-render + phase_detail. Worker preloads, exits after 20 idle min (FRASBERG_WORKER_MAX_IDLE_S), honours admin stop (heartbeat stop flag) and /worker/offline. GPU wait runs outside the local video lock; Lite is the fallback.
- T4 has no native bf16: engines._dtype() uses fp16 on sm<8 (render 94s vs 540s bf16 for 3s 704x480). Cold start ~6-9 min (session + 150s weights + 90s load), warm ~2-3 min. Verified clip: fox in snow, 4s 97 frames, engine "Frasberg Motion Free".
- Admin /status: Kaggle panel (status, boot stage, Start GPU now, Stop, notebook link). /api/gpu/v1/engines marks motion-free on_demand/status "on-demand".
- Tests: iteration_21 (backend 11/12, the share.public gap fixed; frontend 100%).
- Production needs KAGGLE_API_TOKEN/KAGGLE_USERNAME in its env too; the kernel slug is per host, so preview and prod each get their own worker.

## Update (2026-10-11, re-import into pod 781d0ae5)
- /app was empty. Cloned luchii-ai-models/frasberg-secure-runtime main@cdee73d (includes merged PR #2) and copied it into /app without .git. Recreated backend/.env (8 frb_live keys + FRASBERG_KEY_ROUTES, KAGGLE_API_TOKEN, KAGGLE_USERNAME=frasberg, new JWT/worker secrets) and frontend/.env. Deps and ffmpeg installed. Seeded the test accounts.
- GitHub state: 0 open PRs. PR #2 is merged and PR #1 is closed unmerged. Stale remote branches: merge/frasberg-branches-into-main (only MERGE_NOTES.md + .gitignore), merged-frasberg-branches and merged-frasberg-branches-update-to-main (older snapshots, all their content is already in main). They can be deleted on GitHub. The agent cannot do git writes.
- Verified: home page matches frasberg-preview.preview.emergentagent.com, auth works, Kaggle API auth works (lists frasberg/* kernels), and a Nova-Muse draft render completed on luchii-local. Frasberg upstream is the same as before: image 502, voice "warming up", video returns sample clips.

## Update (2026-10-11, AWS GPU host)
- New backend/aws_gpu.py: dedicated EC2 GPU (g5.xlarge A10G 24GB, us-east-1, account 303004020510, IAM user frasberg-gpu) runs the same Frasberg GPU worker as the Kaggle notebook via user-data (DLAMI PyTorch Ubuntu 24.04, /opt/pytorch python, pip deps, worker files from /api/gpu/worker/files, prefetch, systemd frasberg-worker). Security group frasberg-gpu-worker has no inbound rules. IMDSv2, encrypted 200GB gp3. One instance per gateway host (tag Name=frasberg-gpu-<hosthash>).
- Env: AWS_ACCESS_KEY_ID/SECRET, AWS_REGION, AWS_GPU_MODE (always_on|on_demand|off), AWS_GPU_INSTANCE_TYPE, AWS_GPU_MODELS (frasberg-motion-fast,frasberg-motion-free). always_on: a startup reconcile loop (every 5 min) keeps it running. Admin Stop pauses it (state in db.aws_gpu).
- Video routing: online worker -> AWS (ensure + wait while booting) -> Kaggle -> frasberg.com -> Lite.
- Admin API: GET /api/gpu-admin/aws, POST /api/gpu-admin/aws/start|stop, POST /api/gpu-admin/aws/terminate?confirm=true. UI: AwsPanel on /status (testids aws-panel, aws-status, aws-quota, aws-start-btn, aws-stop-btn).
- BLOCKER: the G/VT On-Demand vCPU quota is 0. An increase to 8 was requested (request 0b95f43a..., support case 179173096600295, CASE_OPENED). A run_instances dry run succeeds. The instance auto-launches once AWS approves.
- Kaggle T4 session for this host stayed "queued" for 35+ min (Kaggle capacity), so the test videos fell back to Lite.
- PROD NOTE: production must set FRASBERG_PUBLIC_URL to its own URL (not the preview one), plus the AWS and Kaggle env vars. Keep always_on in only one environment to avoid paying for two GPUs.
- 2026-10-11: Cost Saver Mode. Admins switch the AWS GPU between Always on and Cost saver (on_demand) on /status (testids aws-mode, aws-mode-always_on, aws-mode-on_demand, aws-idle-{10|20|30|60|120}, aws-idle). PUT /api/gpu-admin/aws/settings {mode?, idle_min?} is stored in db.aws_gpu_settings and overrides the AWS_GPU_MODE env default. AWS_GPU_MODE=off still disables it. Switching to always_on clears an admin pause and starts the box.
  - The worker is now mode-agnostic (Restart=always, never idles out). The backend loop runs every 60s: in cost saver it stops the instance (stop, not terminate, so the weights are kept) once it has been idle for idle_min, but never during a cold boot or while GPU jobs are queued or running. Monthly and hourly estimates come from HOURLY_USD.
  - Preview is set to always_on with a 20 min idle default.
- 2026-10-11: GPU Spend Tracker. The aws_gpu loop calls record_usage every 60s. It writes run sessions to db.aws_gpu_usage {id, name, instance_id, type, start, last_seen, end}; a gap while the same instance keeps running counts as running time. db.aws_gpu.volume_since tracks the EBS disk. GET /api/gpu-admin/aws/usage?month=YYYY-MM -> hours, compute_usd, storage_usd (200GB x $0.08/GB-mo), total_usd, projected_usd (always_on = 24/7 for the rest of the month; cost saver = pace so far), daily[], sessions[]. UI: AwsSpend inside AwsPanel (testids aws-spend, aws-spend-{hours|compute|storage|total}, aws-spend-chart, aws-spend-month-{current|previous}).
- 2026-10-11: The engines on branch merged-frasberg-branches-update-to-main (apps/engine-server/*-execute.ts, packages/*-engine, config/emergent/engines/*.prompt.md) are already in /app, byte-identical. They are TypeScript stubs (Math.random scores, echoed output) and are not wired into the Python app. Waiting for the user to decide how to wire them.

## Update (2026-06, re-import + GitHub merge + full engine wiring)
- Re-imported luchii-ai-models/frasberg-secure-runtime main (550455d, newer than merged-frasberg-branches-update-to-main). backend/.env: 8 frb_live keys + routes, Kaggle token, AWS key pair (IAM user frasberg-gpu verified), AWS_GPU_MODE=on_demand (G/VT quota still 0, so no instance can launch yet).
- GitHub: branch merged-frasberg-branches-update-to-main (unrelated history, older snapshot) merged into main with main's content kept + its monorepo README. Stale branches deleted, no open PRs.
- Engines are internal only: /engines page removed (redirects to /status), footer + Developers links removed. All /api/engines/* runtime endpoints need an admin JWT or X-Frasberg-Key.
- New backend/engine_systems.py ports the 6 non-runtime engines (Mongo instead of Supabase): governance (db.engine_governance, global "*" + owner), policy (db.engine_policy), diagnostics (db.engine_diagnostics gateway/router/engine), worldgraph (db.engine_continuity + identity graph), engine-flow (identity→…→structure), unified-enforce (runs on every execute/chain/flow; blocked → 403). 44 runtime + 6 system = 50 engines.
- New endpoints: GET /engines/systems, POST /engines/flow, GET/PUT /engines/governance (scope owner|global), GET/PUT /engines/policy, GET /engines/diagnostics[?component], GET /engines/identity, GET/DELETE /engines/continuity/{cid}. execute/chain accept `continuity`.
- /status (admin) shows Engine Runtime + System engines panel (EngineSystems.jsx) + Engine rules.
- 2026-06: GPU Quota Alert. aws_gpu.check_quota() runs every 5 min in reconcile_loop until approved; the first time the G/VT quota reaches the instance's vCPUs it stamps db.aws_gpu.quota_approved_at. Overview returns quota_approved_at + quota_alert (approved, not dismissed, mode != always_on). POST /api/gpu-admin/aws/quota/check, /quota/dismiss. UI: QuotaBanner.jsx on top of /status (testids quota-banner, quota-banner-always-on, quota-banner-dismiss) + "Check now" link in the AWS panel (aws-quota-check).
- 2026-06: Engines in Creation. Every image (generate/edit/remove-bg/upscale, sync + jobs + agent), video and music creation runs creation_check(): Unified Enforce on action create:<kind> for owner user:<id>|guest (policy + global/owner governance; blocked → 403 "Blocked by Frasberg engine rules: …"), then the Engine Flow (identity→structure) over the prompt. The record (requestId, flow_id, score, coverage, stages) is stored as engine_flow on generations/jobs and returned by the APIs. GET /api/engines/creations (admins) → counts + recent; UI panel engine-creations on /status. Tests: iteration_62 100%.
- 2026-06: Per-User Blocks. GET/PUT /api/engines/user-blocks (admins) block create:image|video|music for one user (stored in that user's engine_policy, other actions kept; empty kinds = unblock). UI: UserBlocks.jsx in the System engines panel on /status. Creations log shows user emails (owner_label). Tests: iteration_63 100%.
- 2026-06: Timed Blocks. PUT /engines/user-blocks takes duration 24h|7d|null(permanent)|keep; stored as engine_policy.creation_block_until; load_policy auto-lifts expired create:* blocks (lazy, on every check/list). Blocked users see "…blocked by policy until <date> UTC". UI: duration select + "Lifts in …" per row. Tests: iteration_64 100%.

## Update (2026-10-12, re-import into pod luchii-media)
- Cloned luchii-ai-models/frasberg-secure-runtime main@5958691 (PR #6 timed blocks) and copied it into /app without .git. Recreated backend/.env with the 8 frb_live keys + FRASBERG_KEY_ROUTES, Kaggle token, the AWS pair, and new JWT/worker secrets. frontend/.env kept. ffmpeg installed, model dirs created, test accounts seeded.
- AWS key AKIAUNDDSN4P... is REJECTED by AWS (sts InvalidClientTokenId / ec2 AuthFailure). It has been deleted or rotated. AWS GPU and S3 are blocked until a valid key is provided.
- Fix: aws_gpu.py now pauses all AWS calls for 15 min after an auth error (AUTH_ERRORS, AUTH_BACKOFF_S). Before, it called AWS and logged a warning every 60s. ensure() and _short() now return a clear "AWS rejected the access key" reason.
- Verified: Frasberg keys auth OK (/v1/models 200), Kaggle enabled, Nova-Muse draft ~60s cold. Tests: iteration_65 100%.
- Backlog: S3 media storage (needs a valid AWS key). GridFS is still the media store.

- 2026-10-12: Header wordmark changed from "Frasberg Creator" to "Frasberg" (Navbar plus the Gallery, Share, Generator and AuthModal headers). Page copy, hero and title unchanged.
