import pytest

from grader_proof.llm import PRICES
from grader_proof.red_team_runs import INSTRUCTION, harbor_command
from grader_proof.rq4_runs import max_run_usd, model_dir_name, planned_trials

NINE_B = "Qwen/Qwen3.5-9B-Base"
BIG = "Qwen/Qwen3.5-35B-A3B-Base"


def test_plan_is_every_instance_then_every_model_then_three_trials_on_all():
    plan = planned_trials(["a", "b"], [NINE_B, BIG])
    assert [(model, key.name) for model, key in plan[:4]] == [
        (NINE_B, "a__all__1"),
        (NINE_B, "a__all__2"),
        (NINE_B, "a__all__3"),
        (BIG, "a__all__1"),
    ]
    assert len(plan) == 12
    assert {key.condition for _, key in plan} == {"all"}


def test_model_folder_name_has_no_slash():
    assert model_dir_name(BIG) == "Qwen__Qwen3.5-35B-A3B-Base"


def test_max_run_cost_is_every_turn_with_a_full_prompt_and_a_full_reply():
    price = PRICES[NINE_B]
    assert max_run_usd(NINE_B) == pytest.approx(
        40 * (65_536 * price.prefill + 4_096 * price.sample) / 1e6
    )
    assert max_run_usd(BIG) > max_run_usd(NINE_B)


def test_standard_instruction_appends_nothing_and_names_the_model(tmp_path):
    command = harbor_command(tmp_path / "task", tmp_path / "job", model=BIG, instruction=None)
    assert "--extra-instruction-path" not in command
    assert command[command.index("-m") + 1] == BIG


def test_red_team_command_is_unchanged_by_default(tmp_path):
    command = harbor_command(tmp_path / "task", tmp_path / "job")
    assert command[command.index("--extra-instruction-path") + 1] == str(INSTRUCTION)
    assert command[command.index("-m") + 1] == NINE_B
