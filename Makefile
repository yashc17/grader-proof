.PHONY: install lint typecheck test check data-facts task

install:
	uv sync
	uv run pre-commit install

lint:
	uv run ruff check .
	uv run ruff format --check .

typecheck:
	uv run pyright

# pytest exits with 5 when it collects no tests; allowed until the first tests land in M1.
test:
	uv run pytest; status=$$?; [ $$status -eq 0 ] || [ $$status -eq 5 ]

check: lint typecheck test

data-facts:
	uv run python -m grader_proof.data_facts

# Usage: make task ID=12rambau__sepal_ui-411
task:
	@test -n "$(ID)" || { echo "usage: make task ID=<instance_id>"; exit 2; }
	uv run python -m grader_proof.task_builder $(ID)
