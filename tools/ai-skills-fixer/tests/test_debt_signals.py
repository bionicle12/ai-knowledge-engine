"""Tests for deterministic prompt-debt signal detectors (spec §11.2, §17).

Detectors produce evidence with hints for the agent — never verdicts.
"""
from __future__ import annotations

from ai_skills_fixer.linting import cross_skill_duplicates, debt_signals


def signals_of(text, kind=None):
    found = debt_signals(text)
    return [s for s in found if kind is None or s.signal == kind]


def test_absolute_rule_lines_are_flagged():
    text = "You MUST always do this.\nNever skip validation.\nMaybe consider tests.\n"
    found = signals_of(text, "absolute-rule")
    assert len(found) == 2
    assert found[0].line == 1
    assert "conditional-rule" in found[0].hint


def test_model_references_are_flagged():
    text = "Optimized for GPT-4 and Claude 3 Opus.\nWorks with o1-mini too.\n"
    found = signals_of(text, "model-reference")
    assert len(found) == 2
    assert "model-specific" in found[0].hint


def test_generic_prompting_phrases_are_flagged():
    text = (
        "Think step by step about the problem.\n"
        "You are an expert developer.\n"
        "Do not hallucinate APIs.\n"
    )
    found = signals_of(text, "generic-prompting")
    assert len(found) == 3
    assert "trained-default" in found[0].hint


def test_duplicate_paragraphs_within_a_skill_are_flagged():
    para = (
        "This exact same long paragraph appears twice in the body and is "
        "clearly redundant content that wastes tokens every invocation."
    )
    text = f"{para}\n\nSome other text in between.\n\n{para}\n"
    found = signals_of(text, "duplicate-paragraph")
    assert len(found) == 1
    assert "duplicate" in found[0].hint


def test_short_or_clean_text_produces_no_signals():
    assert debt_signals("A short, specific instruction about our API.\n") == []


def test_cross_skill_duplicates_find_shared_boilerplate():
    boilerplate = (
        "Always follow the standard operating procedure described here in "
        "great detail because it applies to every single skill equally."
    )
    skills = {
        "skill-a": f"Intro A.\n\n{boilerplate}\n",
        "skill-b": f"Intro B.\n\n{boilerplate}\n",
        "skill-c": "Unique content only.\n",
    }
    shared = cross_skill_duplicates(skills)
    assert len(shared) == 1
    assert sorted(shared[0]["skills"]) == ["skill-a", "skill-b"]
    assert shared[0]["excerpt"].startswith("Always follow")
