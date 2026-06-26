.PHONY: up down schema api worker test test-unit logs ps

up:                 ## start Postgres + Redis
	docker compose up -d

down:               ## stop containers (keeps data volume)
	docker compose down

schema:             ## (re)apply sql/schema.sql to the running DB
	./scripts/apply_schema.sh

reset-demo:         ## clear all derived data AND the job queue for a clean live demo
	docker compose exec -T postgres psql -U zynd -d zynd -c "TRUNCATE assertion_history, assertions, user_embeddings, entities, trace_chunks RESTART IDENTITY CASCADE;"
	docker compose exec -T redis redis-cli FLUSHALL >/dev/null && echo "queue cleared"

check:              ## verify live embedding+extraction APIs (needs keys, MOCK_LLM=false)
	uv run python -m app.check_live

api:                ## run the API (reload)
	uv run uvicorn app.main:app --reload --port 8000

worker:             ## run the async worker (includes decay/orphan cron)
	uv run arq app.worker.WorkerSettings

mcp:                ## run the MCP server (stdio)
	uv run python -m app.mcp_server

decay:              ## run the decay job once (manual)
	uv run python -m app.jobs decay

orphan:             ## run orphan cleanup once (manual)
	uv run python -m app.jobs orphan

test:               ## run all tests (needs docker up for integration)
	uv run pytest -q

test-unit:          ## run only fast unit tests (no docker needed)
	uv run pytest -q -m "not integration"

logs:               ## tail container logs
	docker compose logs -f

ps:                 ## container status
	docker compose ps
