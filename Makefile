.PHONY: run install probe extract generate test format

run:
	poetry run uvicorn src.app:app --reload --host 0.0.0.0 --port 8000

install:
	poetry install

probe:
	poetry run python -m cli.extract probe --pdf books/fundamentals_of_space_systems.pdf

extract:
	poetry run python -m cli.extract extract --pdf books/fundamentals_of_space_systems.pdf

generate:
	poetry run python -m cli.generate --book "Fundamentals of Space Systems"

test:
	poetry run pytest tests/ -v

format:
	poetry run black src/ cli/ tests/
	poetry run isort src/ cli/ tests/
