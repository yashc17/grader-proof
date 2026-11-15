.PHONY: candidates install lint typecheck test check data-facts h2-gold-patches held-out-facts task oracle-check replay-export replay-results rq3 sample label history-reads

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

# Counts the gold patches H2 would reject (ADR 0009). Needs the data that data-facts downloads.
h2-gold-patches:
	uv run python -m grader_proof.h2_gold_patches

# Measures how many instances H3 can hold tests out of, and checks its patches (ADR 0010).
# Needs the parquet files that `make data-facts` downloads.
held-out-facts:
	uv run python -m grader_proof.held_out_facts

# Usage: make task ID=12rambau__sepal_ui-411 [CONDITION=h1|h2|h3|h4|all]
CONDITION ?= baseline
task:
	@test -n "$(ID)" || { echo "usage: make task ID=<instance_id> [CONDITION=<condition>]"; exit 2; }
	uv run python -m grader_proof.task_builder $(ID) --condition $(CONDITION)

# Downloads the results of the latest oracle-check run (or RUN=<run id>) into results/oracle-check
# and writes results/oracle_check.csv: per task and condition, the runs in which the oracle got
# reward 1, out of 3. Exits non-zero if any run rejected the oracle (a false negative) or a task
# folder has no result.
oracle-check:
	rm -rf results/oracle-check
	gh run download $${RUN:-$$(gh run list --workflow oracle-check.yml --limit 1 --json databaseId --jq '.[0].databaseId')} --pattern 'oracle-check-*' --dir results/oracle-check
	uv run python -m grader_proof.oracle_check summarize results/oracle-check

# Draws labels/sample.jsonl (100 unresolved trajectories, 30 dev and 70 test). Keeps an existing file.
sample:
	uv run python -m grader_proof.label_cli sample

# Labels the next unlabeled trajectory. Usage: make label SPLIT=dev (or test, or all)
label:
	uv run python -m grader_proof.label_cli label --split $(or $(SPLIT),dev)

# Ranks about 20 candidate instances for the 12 tasks (needs data/, labels/human.jsonl and Docker Hub access for image sizes).
candidates:
	uv run python -m grader_proof.candidates

# Counts trajectories whose commands read git history beyond HEAD (issue #56, ADR 0011).
# Needs the data that data-facts downloads.
history-reads:
	uv run python -m grader_proof.history_reads

# Replay (issue #32). A replay set is results/replay/$(REPLAY_SET): the saved Baseline red-team
# patches, regraded under every condition by the replay workflow on Actions.
# `make replay-export JOBS="runs/<job> ..."` copies each Baseline trial's patch.diff into the set.
# Commit the set, push, then run: gh workflow run replay.yml --ref <branch> -f set=$(REPLAY_SET)
# `make replay-results` downloads the latest replay run (or RUN=<run id>) into the set.
REPLAY_SET ?= red-team
replay-export:
	@test -n "$(JOBS)" || { echo "usage: make replay-export JOBS=<job dirs> [REPLAY_SET=<set>]"; exit 2; }
	uv run python -m grader_proof.replay export $(JOBS) --set results/replay/$(REPLAY_SET)

replay-results:
	@test -n "$(REPLAY_SET)" || { echo "REPLAY_SET is empty"; exit 2; }
	rm -rf results/replay/$(REPLAY_SET)/results
	gh run download $${RUN:-$$(gh run list --workflow replay.yml --limit 1 --json databaseId --jq '.[0].databaseId')} --pattern 'replay-*' --dir results/replay/$(REPLAY_SET)/results

# RQ3 table (results/rq3.csv and .md): exploit rates, effects with 95% task-clustered intervals,
# exploit categories and oracle acceptance, for all tasks and per task. Reads the replay set, the
# adaptive red-team summary (ADAPTIVE=, empty to leave it out), labels/exploit_verdicts.jsonl
# and results/oracle-check. Fails if an accepted patch has no verdict yet.
ADAPTIVE ?= results/red_team.json
RQ3_OUT ?= results/rq3
rq3:
	uv run python -m grader_proof.rq3 --replay results/replay/$(REPLAY_SET)/results \
		$(if $(ADAPTIVE),--adaptive $(ADAPTIVE)) --out $(RQ3_OUT)
