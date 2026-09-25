.PHONY: up down schema api worker test test-unit logs ps deploy ship

# --- prod deploy (run from an SSH-allowlisted IP). Override host/key via env. ---
EC2_HOST ?= 54.147.91.20
SSH_KEY  ?= $(HOME)/.ssh/zynd-deploy.pem
SSHCMD   := ssh -i $(SSH_KEY) -o StrictHostKeyChecking=no

deploy:             ## rsync app+sql to prod, apply schema (idempotent), rebuild, health-check
	rsync -az -e "$(SSHCMD)" --exclude .git --exclude __pycache__ --exclude .venv --exclude .env \
		app/ ubuntu@$(EC2_HOST):/home/ubuntu/zynd/app/
	rsync -az -e "$(SSHCMD)" sql/ ubuntu@$(EC2_HOST):/home/ubuntu/zynd/sql/
	$(SSHCMD) ubuntu@$(EC2_HOST) 'cd ~/zynd && \
		sudo docker compose -f docker-compose.prod.yml exec -T postgres psql -U zynd -d zynd -v ON_ERROR_STOP=1 < sql/schema.sql && \
		sudo docker compose -f docker-compose.prod.yml up -d --build api worker mcp'
	@echo "deployed — health:" && sleep 6 && curl -fsS https://api.zynd.ai/health && echo

ship:               ## git push + deploy
	git push origin main && $(MAKE) deploy

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
