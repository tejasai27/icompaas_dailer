# Database Scaling Plan

## PostgreSQL Baseline
- Primary for writes + 1..N read replicas
- Connection pooling via PgBouncer
- Strict migration discipline (online-safe changes)

## Core Tables and Load Expectations
- `call_sessions`: hot writes during live calls
- `call_events`: very high write volume (append-only)
- `provider_webhook_receipts`: bursty writes from callbacks
- `crm_sync_jobs` and `crm_sync_attempts`: queue-like writes

## Partitioning
Use monthly range partitions for:
- `call_events(event_ts)`
- `provider_webhook_receipts(received_at)`

Benefits:
- Faster retention cleanup
- Better index locality
- Predictable query performance on recent data

## Indexing Strategy
- `call_sessions(provider, provider_call_uuid)` unique where provider_call_uuid is present
- `call_sessions(status, created_at)` for dialer dashboards
- `call_events(call_id, event_ts)` for replay timelines
- `crm_sync_jobs(status, next_retry_at)` for worker polling
- `leads(phone_e164)` and campaign-scoped queue indexes

## Concurrency Controls
- Lead allocation with `FOR UPDATE SKIP LOCKED`
- Agent reservation in transaction with conditional status update
- Idempotent webhook upsert on `(provider, webhook_idempotency_key)`

## Retention
- Keep transactional entities long-term
- Keep raw webhook payloads for 30-90 days (policy-based)
- Archive old `call_events` partitions to object storage if needed

## Backup and Recovery
- Daily base backup + WAL archiving
- Point-in-time recovery tested quarterly
- Replica lag alerting and failover runbook
