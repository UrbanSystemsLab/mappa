"""Rules about what may appear in an answer. Each was violated in production."""

from api import llm


class TestNoUrls:
    """An answer about La Maraña's documents must never point at a website.

    A citation once carried the document's original URL, so an answer about their
    planning documents linked to a government site.
    """

    def test_strips_a_bare_url(self):
        out = llm._strip_urls("See https://docs.pr.gov/file.pdf for detail.")
        assert "http" not in out

    def test_strips_a_markdown_link(self):
        out = llm._strip_urls("See [the plan](https://example.gov/a.pdf).")
        assert "example.gov" not in out


class TestMapMarker:
    """The model cites the computed-facts block the way it cites a document.

    Readers saw '[1, MAP FACTS]' in answers. The first fix only caught the marker
    standing alone, not folded into a citation list.
    """

    def test_strips_marker_alone(self):
        assert "MAP FACTS" not in llm._strip_map_markers("Not in a flood zone [MAP FACTS].")

    def test_keeps_the_real_citation(self):
        out = llm._strip_map_markers("8 of 25 schools [1, MAP FACTS].")
        assert "MAP FACTS" not in out and "[1]" in out

    def test_strips_the_spanish_form(self):
        out = llm._strip_map_markers("Tres de siete [1, 2, Dato del mapa] intersecan.")
        assert "Dato del mapa" not in out and "[1, 2]" in out

    def test_leaves_ordinary_citations(self):
        assert llm._strip_map_markers("normal [1, 2] text.") == "normal [1, 2] text."


class TestCitationIds:
    """A citation shows La Maraña's inventory ID, or nothing.

    Documents they supplied that are not on their sheet get an internal LM- slug,
    which is a key rather than a reference anyone can look up.
    """

    def test_accepts_their_ids(self):
        from api.retrieval import citation_id

        for good in ("HMP-045", "DOC-128", "POT-007", "GIS-609", "WCRP-014"):
            assert citation_id(good) == good

    def test_hides_internal_slugs(self):
        from api.retrieval import citation_id

        assert citation_id("LM-REGLAMENTO-ZONIFICACIO-N-ESPECIAL-DE-SANTURCE") == ""


class TestWhatCountsAsDeclining:
    """An answer only loses its sources when it says nothing but 'I don't know'."""

    def test_a_plain_refusal_is_a_decline(self):
        from api.llm import _is_decline

        assert _is_decline(
            "There is not enough information in the available documents to answer this."
        )
        assert _is_decline("No encontré información sobre esto en los documentos disponibles.")

    def test_a_hedge_followed_by_an_answer_is_not(self):
        """The case that removed every source from an answer quoting the
        Reglamento Conjunto."""
        from api.llm import _is_decline

        answer = (
            "There is not enough information in the available documents to definitively answer "
            "whether you can build in a flood zone in Ponce. However, the FEMA flood zones in Ponce "
            "were last updated in 2009. A 'Zona Susceptible a Inundaciones' is defined as land with a "
            "1% probability of being flooded in any given year. Projects to mitigate flooding in "
            "Ponce include the construction of a gabion wall and channel improvements."
        )
        assert not _is_decline(answer)


def test_one_long_document_cannot_fill_every_slot():
    """Ponce's mitigation plan took all six places, and the Reglamento never got one."""
    from api.retrieval import PER_DOCUMENT, _spread

    plan = [(0.66 - i * 0.01, {"id": "HMP-ponce"}) for i in range(6)]
    rule = [(0.60, {"id": "DOC-reglamento"})]
    got = _spread(plan + rule, top_k=6)
    assert sum(1 for _, d in got if d["id"] == "HMP-ponce") == PER_DOCUMENT
    assert any(d["id"] == "DOC-reglamento" for _, d in got)
