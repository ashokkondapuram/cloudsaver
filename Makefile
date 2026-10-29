.PHONY: build up status logs down test test-postgres scan platform-up platform-down platform-status
build:
	docker compose build scanner-service web-dashboard postgres
platform-up:
	docker compose --project-directory platform -f platform/compose.yaml up --build -d
platform-down:
	docker compose --project-directory platform -f platform/compose.yaml down
platform-status:
	docker compose --project-directory platform -f platform/compose.yaml ps
up:
	./start.sh
status: platform-status
	docker compose ps
logs:
	docker compose logs -f --tail=100
down:
	docker compose down
test:
	python test_platform.py
test-postgres:
	python test_platform.py --postgres
scan:
	python scripts/scan.py
