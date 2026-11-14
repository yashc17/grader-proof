.PHONY: install lint typecheck test check task oracle-results

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

# Usage: make task ID=12rambau__sepal_ui-411
task:
	@test -n "$(ID)" || { echo "usage: make task ID=<instance_id>"; exit 2; }
	uv run python -m grader_proof.task_builder $(ID)

# Downloads the results of the latest oracle-check run (or RUN=<run id>) into results/oracle-check.
# Exits non-zero unless every task's oracle got reward 1 in all 3 runs.
oracle-results:
	rm -rf results/oracle-check
	gh run download $${RUN:-$$(gh run list --workflow oracle-check.yml --limit 1 --json databaseId --jq '.[0].databaseId')} --pattern 'oracle-check-*' --dir results/oracle-check
	uv run python -m grader_proof.oracle_check summarize results/oracle-check
