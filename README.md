# iCompaas Dialer - Automated WebRTC Power Dialer

Monorepo setup for a React + Django power dialer with PostgreSQL and Redis, designed to evolve from starter mode to high-scale event-driven deployment.

## Stack
- Frontend: React (Vite)
- Backend: Django + Django REST Framework
- DB: PostgreSQL
- Cache/Queue: Redis
- Event Bus (scalable profile): Redpanda/Kafka
- Telephony adapters: Exotel (active), Plivo (target)

## Local Run (Starter)
1. Copy `.env.example` to `.env` and fill credentials.
2. Start services (single-port mode, recommended):
   ```bash
   docker compose up --build -d
   ```
3. Frontend (website): `http://localhost` (default `PUBLIC_HTTP_PORT=80`)
4. API/media use the same host via proxy paths:
   - `http://localhost/api/...`
   - `http://localhost/media/...`
5. Open only one public port in firewall/security group: `PUBLIC_HTTP_PORT` (default `80`).

## Optional Direct Service Ports (Debug / Local Tooling)
By default only `PUBLIC_HTTP_PORT` is exposed.
If you need direct host access to backend/Postgres/Redis, uncomment the `ports:` lines in `docker-compose.yml`.

Default host ports from `.env` when those lines are enabled:
- Backend API: `8000` (`BACKEND_HOST_PORT`)
- PostgreSQL: `5433` (`POSTGRES_HOST_PORT`)
- Redis: `6380` (`REDIS_HOST_PORT`)

## Backend API (Current)
- `GET /api/v1/dialer/health/`
- `GET /api/v1/dialer/agents/`
- `POST /api/v1/dialer/agents/<agent_id>/status/`
- `GET /api/v1/dialer/leads/next/`
- `POST /api/v1/dialer/leads/upload/`
- `POST /api/v1/dialer/leads/manual/`
- `GET /api/v1/dialer/call-logs/`
- `POST /api/v1/dialer/call-logs/sync/exotel/`
- `GET /api/v1/dialer/recordings/`
- `POST /api/v1/dialer/recordings/upload/`
- `GET /api/v1/dialer/recordings/<recording_public_id>/`
- `POST /api/v1/dialer/recordings/<recording_public_id>/transcribe/`
- `POST /api/v1/dialer/calls/start/exotel/`
- `POST /api/v1/dialer/webhooks/exotel/`
- `GET/POST /api/v1/dialer/integrations/hubspot/settings/`
- `POST /api/v1/dialer/integrations/hubspot/test/`
- `POST /api/v1/dialer/integrations/hubspot/sync-call/<call_public_id>/`

## Exotel Setup
In `.env` set:
- `TELEPHONY_PROVIDER=exotel`
- `EXOTEL_SID=...`
- `EXOTEL_API_KEY=...`
- `EXOTEL_API_TOKEN=...`
- `EXOTEL_SUBDOMAIN=api.in.exotel.com`
- `EXOTEL_CALLER_ID=<your_exophone_or_verified_cli>`
- `EXOTEL_MAX_CALL_DURATION_SECONDS=0` (0 = no provider time limit)
- `EXOTEL_WAIT_URL=<public_audio_url_or_exotel_voice_url>`
- `EXOTEL_START_PLAYBACK_VALUE=<public_audio_url_or_provider_value>`
- `EXOTEL_START_PLAYBACK_TO=both` (or `callee`)
- `PUBLIC_WEBHOOK_BASE_URL=https://<your-ngrok-domain>`

Direct upload option:
- Open Settings page -> `Exotel Wait Audio`
- Upload `mp3/wav/ogg/m4a`
- Backend hosts it under `/media/...` and uses it as Exotel `WaitUrl`

## HubSpot Integration Setup
You can configure HubSpot from UI: `Integrations -> HubSpot`.

Optional env defaults:
- `HUBSPOT_ENABLED=1`
- `HUBSPOT_ACCESS_TOKEN=<hubspot_private_app_token>`
- `HUBSPOT_TIMEOUT_SECONDS=12`

Call sync behavior:
- Call details are synced to HubSpot Call activities.
- Sync runs automatically on terminal call state and on disposition save (configurable in Integrations page).
- Deal association supports Deal ID or Deal Name.

## Whisper Transcription Setup
In `.env` set:
- `TRANSCRIPTION_BACKEND=local_whisper`
- `WHISPER_MODEL=small` (or `base`, `medium`, `large-v3`)
- `WHISPER_DEVICE=cpu` (or `cuda`)
- `WHISPER_COMPUTE_TYPE=int8` (or `float16` on GPU)
- `WHISPER_LANGUAGE=` (optional, e.g. `en`)
- `WHISPER_VAD_FILTER=0` (set `1` only if you want VAD segmentation)
- `AUTO_TRANSCRIBE_RECORDINGS=1` (auto-run transcript when recording appears)

Optional OpenAI fallback:
- set `TRANSCRIPTION_BACKEND=openai`
- then configure `OPENAI_API_KEY`, `OPENAI_WHISPER_MODEL`, `OPENAI_WHISPER_LANGUAGE`, `OPENAI_WHISPER_TIMEOUT_SECONDS`

## Make a Test Call
```bash
curl -X POST http://localhost/api/v1/dialer/calls/start/exotel/ \
  -H "Content-Type: application/json" \
  -d '{
    "lead_id": 1,
    "agent_id": 1,
    "agent_phone": "+919999999999"
  }'
```

## Architecture Docs
- Architecture blueprint: `docs/ARCHITECTURE.md`
- Database scaling guide: `docs/DATABASE_SCALING.md`

The target architecture separates API, telephony workers, realtime gateway, scheduler, CRM sync workers, and adds durable event streaming + observability.
