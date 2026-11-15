.PHONY: triage-eval triage-prevalence candidates fact-sheets install lint typecheck test check data-facts h2-gold-patches held-out-facts task oracle-check sample label history-reads rules-dev judge-dev red-team-trial red-team-pilot replay-export replay-results rq3 figures rq1 label-agreement label-page exploit-review

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

# Writes data/label_view/index.html: a browser page for labeling the dev items.
label-page:
	uv run python -m grader_proof.label_view

# Writes labels/fact_sheets/test/: one page of facts per test item and index.html (issue #9).
# The pages hold no label. Needs the data that data-facts downloads.
fact-sheets:
	uv run python -m grader_proof.fact_sheet

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

# Coverage and precision of the triage rules on the 30 dev labels; writes results/rules_dev.json.
# Needs labels/human.jsonl (the maintainer's dev labels) and the data from `make data-facts`.
rules-dev:
	uv run python -m grader_proof.rules_eval

# Kappa of every judge prompt version on the 30 dev labels; writes results/judge_dev.json.
# Needs labels/human.jsonl, the data from `make data-facts` and, for calls not in cache/llm/,
# TINKER_API_KEY. Prints each batch's cost estimate and asks before calling the model.
judge-dev:
	uv run python -m grader_proof.judge_eval

# Scores the frozen triager on the 70 test labels; writes results/triage_test.json (issue #14).
# Refuses to run until every test item has a label. Needs the label file, the data from
# `make data-facts` and, for calls not in cache/llm/, TINKER_API_KEY. Asks before calling the model.
# Usage: make triage-eval [LABELS=labels/opus_test.jsonl] [LABELER="Claude Opus 5.5 labeler session"]
LABELS ?= labels/opus_test.jsonl
LABELER ?= Claude Opus 5.5 labeler session
triage-eval:
	uv run python -m grader_proof.triage_eval --labels "$(LABELS)" --labeler "$(LABELER)"

# Class shares from the frozen triager on 1,000 trajectories outside the labeling sample; writes
# results/triage_prevalence.json and .md (issue #15). Same needs and cost prompt as triage-eval.
triage-prevalence:
	uv run python -m grader_proof.prevalence

# Red-team pilot (issue #28). `make red-team-trial` adds one trial to runs/red-team-pilot: terminus-2
# through Harbor's Tinker backend, with RED_TEAM_INSTRUCTION appended to the task instruction.
# It needs TINKER_API_KEY in the environment (set -a && source .env && set +a). On the 9B model a
# trial cost $0.08 in the pilot, at most about $0.92 (40 turns, each a full 64K prompt, no cache).
# `make red-team-pilot` rebuilds results/red_team_pilot.json from the saved trials at no cost.
# Usage: make red-team-trial [RED_TEAM_TASK=<task folder>] [RED_TEAM_INSTRUCTION=<file>] [RED_TEAM_MODEL=<model>]
RED_TEAM_TASK ?= python-versioneer__python-versioneer-222__baseline
RED_TEAM_INSTRUCTION ?= prompts/red-team-v1.md
RED_TEAM_MODEL ?= Qwen/Qwen3.5-9B-Base
RED_TEAM_JOB ?= runs/red-team-pilot
red-team-trial:
	HARBOR_TELEMETRY=0 uvx --from 'harbor[tinker]==0.26.0' harbor run \
		-p tasks/$(RED_TEAM_TASK) -a terminus-2 -m $(RED_TEAM_MODEL) \
		--ak llm_backend=tinker --ak max_turns=40 --ak temperature=0.7 \
		--ak 'llm_kwargs={"context_limit": 65536, "max_tokens": 4096, "renderer_name": "qwen3_5_disable_thinking"}' \
		--extra-instruction-path $(RED_TEAM_INSTRUCTION) --artifact /testbed \
		-o $(RED_TEAM_JOB) -n 1 -y -q

red-team-pilot:
	uv run python -m grader_proof.red_team $(RED_TEAM_JOB)/*/ \
		--notes results/red_team_pilot_notes.json --out results/red_team_pilot.json

# Replay (issue #32). A replay set is results/replay/$(REPLAY_SET): the saved Baseline red-team
# patches, regraded under every condition by the replay workflow on Actions.
# `make replay-export JOBS="runs/<job> ..." [SUMMARY=results/red_team.json]` copies each Baseline
# trial's patch.diff into the set; with SUMMARY, exactly the Baseline trials that file lists.
# Commit the set, push, then run: gh workflow run replay.yml --ref <branch> -f set=$(REPLAY_SET)
# `make replay-results` downloads the latest replay run (or RUN=<run id>) into the set.
REPLAY_SET ?= red-team
replay-export:
	@test -n "$(JOBS)" || { echo "usage: make replay-export JOBS=<job dirs> [REPLAY_SET=<set>]"; exit 2; }
	uv run python -m grader_proof.replay export $(JOBS) --set results/replay/$(REPLAY_SET) \
		$(if $(SUMMARY),--summary $(SUMMARY))

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

# Figures for the write-up (issue #34), as SVG and PNG in figures/, from the table `make rq3` writes.
# Pilot check, never committed: make figures RQ3_TABLE=results/replay/pilot/rq3.csv FIGURES=figures/pilot LABEL=pilot
RQ3_TABLE ?= results/rq3.csv
FIGURES ?= figures
figures:
	uv run python -m grader_proof.plotting --table $(RQ3_TABLE) --out $(FIGURES) $(if $(LABEL),--label $(LABEL))

# RQ1 table (issue #16): why self-checks were fooled, from labels only. Writes $(RQ1_OUT).csv and
# .md: each fooled_reason with its count and share of the labeled self-check false positives.
LABELS ?= labels/opus_test.jsonl
RQ1_OUT ?= results/rq1
rq1:
	uv run python -m grader_proof.rq1 --labels $(LABELS) --out $(RQ1_OUT)

# Agreement between two label files (issue #10 and ADR 0015), over the trajectories in both:
# failure-class agreement with a Wilson 95% interval and Cohen's kappa with a 95% bootstrap
# interval (`unclear` left out and counted, ADR 0003), the class pairs they disagree on, and
# fooled-reason agreement. Writes results/agreement_$(NAME).json and .md.
# Self-agreement: make label-agreement A=labels/opus_test.jsonl B=labels/relabel.jsonl NAME=<name>
A ?= labels/human.jsonl
B ?= labels/opus_dev.jsonl
NAME ?= dev_opus_vs_maintainer
label-agreement:
	uv run python -m grader_proof.label_agreement --a $(A) --b $(B) --name $(NAME)

# Agreement between automatic flags and the maintainer's verdicts (issue #31, ADR 0006).
# Writes results/exploit_review.json and results/exploit_review.md from committed files at no cost.
VERDICTS ?= labels/exploit_verdicts.jsonl
FLAGS ?= results/exploit_flags.jsonl
EXPLOIT_REVIEW_OUT ?= results
exploit-review:
	uv run python -m grader_proof.exploit_review summary --verdicts $(VERDICTS) --flags $(FLAGS) --out-dir $(EXPLOIT_REVIEW_OUT)
