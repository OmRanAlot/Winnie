"""Prompt catalogue tests: every planning stage has a prompt and keeps the safety preamble."""

import pytest

from app.agents.prompts import (
    PLANNER_SYSTEM_PROMPT,
    STAGE_NAMES,
    STAGE_RULES,
    stage_prompt,
)


def test_stage_names_are_the_five_specialists():
    assert STAGE_NAMES == ("classify", "classify_history", "tasks", "dependencies", "timeline")


@pytest.mark.parametrize("stage", STAGE_NAMES)
def test_every_stage_prompt_starts_with_the_shared_rules(stage):
    prompt = stage_prompt(stage)
    assert prompt.startswith(STAGE_RULES)
    assert len(prompt) > len(STAGE_RULES)


def test_shared_rules_treat_input_as_untrusted_and_forbid_writes():
    assert "untrusted data" in STAGE_RULES
    assert "Never write live tasks or contact anyone" in STAGE_RULES


def test_single_shot_planner_prompt_treats_input_as_untrusted_and_forbids_commitments():
    assert "untrusted DATA" in PLANNER_SYSTEM_PROMPT
    assert "No live tasks, messages, purchases" in PLANNER_SYSTEM_PROMPT


def test_unknown_stage_is_rejected_with_the_valid_names():
    with pytest.raises(ValueError, match="Unknown planning stage 'nope'") as error:
        stage_prompt("nope")
    assert "classify_history" in str(error.value)
