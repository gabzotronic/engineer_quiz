.PHONY: run install probe extract generate extract-smad generate-smad extract-exam test test-e2e format

run:
	poetry run uvicorn src.app:app --reload --host 0.0.0.0 --port 8000

install:
	poetry install

probe:
	poetry run python -m cli.extract probe --pdf books/fundamentals_of_space_systems.pdf

extract:
	poetry run python -m cli.extract extract --pdf books/fundamentals_of_space_systems.pdf

generate:
	poetry run python -m cli.generate generate --chunks-file chunks.json

extract-smad:
	poetry run python -m cli.extract extract \
		--pdf "books/Space Mission Analysis and Design (J. R. Wertz, W. J. Larson) (z-library.sk, 1lib.sk, z-lib.sk).pdf" \
		--output chunks_smad.json

generate-smad:
	poetry run python -m cli.generate generate --chunks-file chunks_smad.json

extract-exam:
	poetry run python -m cli.extract_exam extract \
		--pdf "books/E-Math - Sec 4 - Prelims Exam Paper - 2024 - ACS Barker.pdf"

test-e2e:
	poetry run playwright install chromium
	poetry run pytest tests/test_e2e_math.py -v -o "addopts="

test:
	poetry run pytest tests/ -v

format:
	poetry run black src/ cli/ tests/
	poetry run isort src/ cli/ tests/
