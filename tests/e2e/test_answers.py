"""Questions with known answers, asked end to end through the model.

Each asserts the figure in the answer and the tool that produced it, so a change
to the instructions, the tools or the model that breaks a real answer fails the
release. These call the model, so they run in scripts/release.sh, not in CI.
"""

import os
import re

import pytest

from api.services.answering import Ask, answer

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="needs a database")

CASES = [
    ("How many schools are in Cataño?", "en", "count_features", r"\b5\b"),
    ("¿Cuántos pozos hay en Arecibo?", "es", "count_features", r"\b289\b"),
    (
        "How many public schools in Carolina are in a FEMA flood zone?",
        "en",
        "count_inside",
        r"\b8\b",
    ),
    ("What share of Cabo Rojo is a protected area?", "en", "area_share", r"13[.,]3"),
]


@pytest.mark.parametrize("question,lang,tool,figure", CASES)
def test_known_figures(question, lang, tool, figure):
    out = answer(Ask(question=question, lang=lang))
    assert re.search(figure, out["answer"]), out["answer"]
    assert tool in [s["tool"] for s in out["steps"]], out["steps"]


def test_a_rule_question_is_answered_from_documents():
    out = answer(Ask(question="Can I build in a flood zone in Ponce?"))
    assert "search_documents" in [s["tool"] for s in out["steps"]]
    assert out["citations"], "a rule question must cite the documents it used"


def test_an_unrelated_question_is_not_answered_from_general_knowledge():
    out = answer(Ask(question="What is the capital of France?"))
    assert "Paris" not in out["answer"]
    assert not out["citations"]
