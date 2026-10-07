"""Checking an answer before a reader sees it.

The model is told to use only what its tools return. These are the checks that
hold it to that, because instructions alone did not: asked what share of Cabo
Rojo is protected, it answered "22.1%" without running the calculation; asked
about building in a flood zone, it answered from its own knowledge without
searching a single document.
"""

from api import assistant
from api.tools import Session


def session(results=(), passages=0, measured=False) -> Session:
    s = Session()
    s.results = [*results]
    s.passages = [object()] * passages  # only their count matters here
    s.measured = measured
    return s


class TestEvidence:
    def test_an_answer_with_nothing_behind_it_is_sent_back(self):
        assert "search_documents" in assistant._check("You can build there.", session())

    def test_searched_documents_count_as_evidence(self):
        assert assistant._check("You can build there with a permit.", session(passages=3)) is None

    def test_a_measurement_counts_as_evidence(self):
        s = session(results=['{"count": 5}'], measured=True)
        assert assistant._check("There are 5 schools.", s) is None


class TestFigures:
    def test_a_number_no_tool_returned_is_sent_back(self):
        s = session(
            results=['{"place_km2": 186.8, "covered_km2": 24.8, "share_percent": 13.3}'],
            measured=True,
        )
        problem = assistant._check("22.1% of Cabo Rojo is protected.", s)
        assert problem and "22.1" in problem

    def test_numbers_compare_by_value(self):
        s = session(results=['{"share_percent": 44.0, "total": 1234}'], measured=True)
        assert assistant._check("44% of 1,234 schools.", s) is None

    def test_citation_numbers_and_road_names_are_not_figures(self):
        s = session(results=['{"count": 5}'], measured=True)
        assert assistant._check("There are 5 schools near PR-52 [2, 3].", s) is None

    def test_an_unsupported_figure_is_removed_with_its_sentence(self):
        s = session(results=['{"count": 5}'], measured=True)
        out = assistant._drop_unsupported("There are 5 schools. About 40 more are planned.", s)
        assert out == "There are 5 schools."


class TestCleaning:
    def test_passage_numbers_are_found_and_removed(self):
        text = "Building is regulated [2]. Permits apply [1, 3-4]."
        assert assistant.cited_numbers(text) == [2, 1, 3, 4]
        assert assistant.clean(text) == "Building is regulated. Permits apply."

    def test_links_never_reach_the_reader(self):
        out = assistant.clean("See [the plan](https://example.org/plan.pdf) or www.jp.pr.gov.")
        assert "http" not in out and "www" not in out and "the plan" in out

    def test_bullets_are_plain(self):
        assert assistant.clean("- one\n* two") == "• one\n• two"


class TestClickContext:
    def test_a_clicked_point_is_described_as_one_point(self):
        """Unlabelled, 'flood zone: no' at one spot in Mayagüez became 'Mayagüez is
        not in a flood zone' - when 41% of it is."""
        note = assistant.Context(
            clicked={
                "municipio": "Mayagüez",
                "hazards": [{"name_en": "FEMA flood zones 2009", "inside": False}],
            }
        ).note("en")
        assert "exact point" in note and "not the whole municipio" in note
