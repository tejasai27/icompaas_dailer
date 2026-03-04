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
2. Start services:
   ```bash
   docker compose up --build -d
   ```
3. Backend: `http://localhost:8002`
4. Frontend: `http://localhost:5173`

## Backend API (Current)
- `GET /api/v1/dialer/health/`
- `GET /api/v1/dialer/agents/`
- `POST /api/v1/dialer/agents/<agent_id>/status/`
- `GET /api/v1/dialer/leads/next/`
- `POST /api/v1/dialer/leads/upload/`
- `POST /api/v1/dialer/leads/manual/`
- `POST /api/v1/dialer/calls/start/exotel/`
- `POST /api/v1/dialer/webhooks/exotel/`

## Exotel Setup
In `.env` set:
- `TELEPHONY_PROVIDER=exotel`
- `EXOTEL_SID=...`
- `EXOTEL_API_KEY=...`
- `EXOTEL_API_TOKEN=...`
- `EXOTEL_SUBDOMAIN=api.in.exotel.com`
- `EXOTEL_CALLER_ID=<your_exophone_or_verified_cli>`
- `EXOTEL_MAX_CALL_DURATION_SECONDS=60`
- `PUBLIC_WEBHOOK_BASE_URL=https://<your-ngrok-domain>`

## Make a Test Call
```bash
curl -X POST http://localhost:8002/api/v1/dialer/calls/start/exotel/ \
  -H "Content-Type: application/json" \
  -d '{
    "lead_id": 1,
    "agent_id": 1,
    "agent_phone": "+919999999999"
  }'
```

## Scalable Profile (Recommended Architecture)
- Compose template: `docker-compose.scalable.yml`
- Architecture blueprint: `docs/ARCHITECTURE.md`
- Database scaling guide: `docs/DATABASE_SCALING.md`

This profile separates API, telephony workers, realtime gateway, scheduler, CRM sync workers, and adds durable event streaming + observability.
