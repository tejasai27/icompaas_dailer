# Architecture (Scalable V2)

## 1) Goal
Build a dialer that works for 3 SDRs now, but can scale to 300+ concurrent agents and high outbound volume without redesigning core flows.

## 2) Architecture Style
Use an **event-driven modular platform**:
- Synchronous APIs for command/query UX (`HTTP`/`WebSocket`)
- Asynchronous event pipeline for call lifecycle, AMD outcomes, retries, and CRM sync
- Isolate provider adapters (Exotel, Plivo) behind a stable internal contract

## 3) Service Topology
### Edge Layer
- `api-gateway` (Nginx/Envoy): TLS termination, routing, rate limits
- `frontend-web` (React): SDR UI + browser SDK session

### Application Layer
- `orchestrator-api` (Django REST): campaigns, agents, lead allocation, dial commands
- `telephony-adapter` (Django/FastAPI worker): provider API requests + webhook normalization
- `realtime-gateway` (Django Channels/FastAPI WS): push screen-pop + state transitions to agents
- `crm-sync-worker` (Celery): HubSpot write-behind with retries/DLQ
- `scheduler-worker` (Celery beat + workers): lead pacing, retry windows, wrap-up timer expiry

### Data and Messaging Layer
- `postgres-primary` (+ read replicas): source of truth
- `redis-cluster`: presence, distributed locks, short-lived session state
- `kafka/redpanda`: durable event bus (`call.*`, `agent.*`, `crm.*`)
- `object-storage` (S3/MinIO): recordings/transcripts metadata targets
- `analytics-store` (ClickHouse, optional): high-volume reporting without loading OLTP DB

### Observability and Ops
- `prometheus` + `grafana`: metrics
- `loki`/`elasticsearch`: logs
- `opentelemetry-collector` + tracing backend: distributed traces
- `alertmanager`: operational alerts

## 4) Event-Driven Core Contract
Every provider webhook is transformed into normalized events.

### Canonical Events
- `call.created`
- `call.ringing`
- `call.amd.machine`
- `call.amd.human`
- `call.bridged`
- `call.completed`
- `agent.status.changed`
- `disposition.submitted`
- `crm.sync.requested`
- `crm.sync.completed`
- `crm.sync.failed`

### Why this matters
- Provider migration (Exotel -> Plivo) impacts only adapter logic
- UI and downstream services consume stable internal events
- Reprocessing is possible from event log on failures

## 5) Scalable Call Flow
1. `orchestrator-api` selects an eligible lead using DB + Redis lock.
2. It emits `call.created` and enqueues outbound request.
3. `telephony-adapter` calls provider API.
4. Provider webhooks hit `/webhooks/{provider}` and are normalized.
5. On `amd.machine`: publish event, mark call terminal, auto-hangup.
6. On `amd.human`: reserve available agent atomically, emit `call.bridged`.
7. `realtime-gateway` pushes screen-pop payload to that agent session.
8. On hangup: wrap-up timer starts (15s), then disposition required.
9. Disposition triggers `crm.sync.requested`; worker syncs to HubSpot with retry policy.

## 6) Data Model (Production-Oriented)
### OLTP Core (PostgreSQL)
- `agents`
- `agent_sessions`
- `leads`
- `lead_lists`
- `campaigns`
- `campaign_members`
- `call_sessions`
- `call_events` (append-only, indexed by `call_id`, `event_ts`)
- `dispositions`
- `provider_webhook_receipts` (idempotency key, raw payload)
- `crm_sync_jobs`
- `crm_sync_attempts`

### Key Patterns
- `idempotency_key` unique indexes for webhook de-duplication
- `SELECT ... FOR UPDATE SKIP LOCKED` for lead allocation at scale
- Time partitioning for `call_events` and `provider_webhook_receipts`
- Read replicas for reporting queries

## 7) State Management Strategy
### Agent State
- Source of truth: PostgreSQL (`agents.status`)
- Fast path: Redis (`agent:{id}:presence`, TTL heartbeat)
- Conflict resolution: DB wins; Redis is cache + routing accelerator

### Call State
- Source of truth: `call_sessions`
- Transition log: `call_events` (audit + replay)
- Realtime projection cache for UI: Redis hash keyed by `call_id`

## 8) Concurrency and Throughput Controls
- Per-provider CPS throttlers in `telephony-adapter`
- Global rate limiter per campaign
- Circuit breaker for provider API errors
- Back-pressure: pause dial scheduling when available agents fall below threshold
- Bulkhead queues: separate `dial`, `webhook`, `crm-sync` workers

## 9) Reliability and Recovery
- Webhook endpoints are idempotent and ack quickly
- Heavy processing is async via queue consumers
- DLQ for failed CRM sync and malformed provider events
- Replay jobs from `provider_webhook_receipts` and event topics
- Outage mode: continue call processing, defer CRM sync

## 10) Security and Compliance
- Verify provider webhook signatures
- Encrypt secrets with KMS/Vault
- PII encryption-at-rest for phone/email fields
- Field-level audit for disposition edits
- Enforce India calling windows and DNC suppression
- Recording disclosure workflow and policy-based retention

## 11) Deployment Topology (Recommended)
- Kubernetes (EKS/GKE/AKS)
- `Deployment` per service, `HPA` on CPU/RPS/queue lag
- Managed Postgres + Redis + Kafka/Redpanda where possible
- Blue/green or canary for telephony adapter rollouts

## 12) Scale Path
### Stage A (0-20 agents)
- Django modular monolith + Celery + Redis + Postgres
- Redpanda optional

### Stage B (20-100 agents)
- Separate `telephony-adapter` and `realtime-gateway`
- Add event bus and read replica

### Stage C (100-300+ agents)
- Full event pipeline, partitioned tables, dedicated analytics store
- Multi-region DR and provider failover strategy

## 13) Provider Strategy (Your Current Need)
- Implement Exotel adapter first for immediate testing
- Keep canonical internal events and call state unchanged
- Add Plivo adapter as production target
- Flip provider by env/config, not by rewriting business logic
