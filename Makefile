.PHONY: install lint typecheck test check data-facts task oracle-results sample label label-page

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

# Downloads the results of the latest oracle-check run (or RUN=<run id>) into results/oracle-check.
# Exits non-zero unless every task's oracle got reward 1 in all 3 runs.
oracle-results:
	rm -rf results/oracle-check
	gh run download $${RUN:-$$(gh run list --workflow oracle-check.yml --limit 1 --json databaseId --jq '.[0].databaseId')} --pattern 'oracle-check-*' --dir results/oracle-check
	uv run python -m grader_proof.oracle_check summarize results/oracle-check

# Draws labels/sample.jsonl (100 unresolved trajectories, 30 dev and 70 test). Keeps an existing file.
sample:
	uv run python -m grader_proof.label_cli sample

# Writes data/label_view/index.html: a browser page for labeling the dev items.
label-page:
	uv run python -m grader_proof.label_view

# Labels the next unlabeled trajectory. Usage: make label SPLIT=dev (or test, or all)
label:
	uv run python -m grader_proof.label_cli label --split $(or $(SPLIT),dev)
