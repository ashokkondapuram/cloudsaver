.PHONY: build up status logs down test test-postgres scan
build:
	docker compose build
up:
	docker compose up -d
status:
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
