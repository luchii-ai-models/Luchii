# Local Run — Frasberg-com branch @ d0dbb7a859955618a15a263892771cda8bd77921 (2026-06)
## Status
- MongoDB local ✅ | FastAPI backend :8001 ✅ (NOT Flask) | React frontend :3000 ✅ | Redis ✅
- Node gateway (apps/gateway) ❌ — branch inconsistent: server.ts expects setApiKeyStore + plain middlewares; packages/luchii-api-keys exports older factory API. Own tests: 15/88 fail. Stopped in supervisor.
- Python ML installed (torch 2.13 CPU, coqui-tts, faster-whisper, transformers). No TensorFlow in branch. Voice engine won't warm up: only ~0.7GB free RAM in pod.
## Fixes applied
- backend/server.py: /generate/image now requires image_generation, /generate/video requires video_generation (previously ANY valid key passed).
- packages/luchii-model-router/index.ts: export alias LuchiiModelRouter.
## Install notes
- pip: `pip install --no-deps -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cpu` (resolver conflicts on protobuf/litellm otherwise)
- frontend: `yarn install --ignore-engines` (machina wants node>=22)
- supervisor gateway/redis conf copy: /app/scripts/supervisor-gateway.conf
## Backlog
- P0 reconcile apps/gateway with packages/luchii-api-keys (or decide gateway not needed)
- DONE remove hardcoded ADMIN_PASSWORD fallback (backend refuses to start without ADMIN_EMAIL + ADMIN_PASSWORD)
- P1 Deploy to frasberg.com (separate phase)
