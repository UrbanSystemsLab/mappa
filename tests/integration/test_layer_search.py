"""A question's topic finds a layer that is about it.

Several layers can be right for one topic - there are two tsunami evacuation
layers and many flood layers - so each case lists the acceptable ones. These are
our own checks of search behaviour, not La Maraña's questions.
"""

import pytest

from api.repositories import layers

CASES = {
    "escuelas": {"layer_dotacional_educacion_escuelas_2021"},
    "schools": {"layer_dotacional_educacion_escuelas_2021"},
    "hospitales": {"layer_hospitales"},
    "zona inundable": {
        "layer_g23_riesgo_inundacion_fema_firms_2009",
        "layer_inundacion_fema_firms_2009",
        "layer_g23_riesgo_inundacion_floodzone_0_2pct_seamless_2018",
        "layer_inundacion_flood_zone_0_2pct_seamless_2018",
    },
    "ríos": {"layer_mapa_base_crim_ogp_hidrografia_2006", "layer_hidrografia_lineal_2006"},
    "rivers": {"layer_mapa_base_crim_ogp_hidrografia_2006", "layer_hidrografia_lineal_2006"},
    "humedales": {"layer_g23_humedales_prvi_wetlands_fws_2010", "layer_humedales"},
    "landslide": {"layer_landsl_monroe_plus_slop50pct", "layer_deslizamiento"},
    "tsunami": {
        "layer_zonas_desalojo_all_project",
        "layer_areas_desalojo_tsunami_2003_2014",
        "layer_g15_riesgo_geol_areas_desalojo_tsunami_2003_2014",
    },
    "refugios": {"layer_refugios_2023"},
    "protected areas": {
        "layer_pacat_2018_areas_protegidas_terrestres",
        "layer_areas_naturales_protegidas",
        "layer_areas_protegidas_pr_diciembre2016_clcc_pacat",
    },
}


@pytest.mark.parametrize("topic", sorted(CASES))
def test_topic_finds_a_layer_about_it(topic):
    found = [layer.table for layer, _ in layers.search(topic)][:3]
    assert CASES[topic] & set(found), f"{topic!r} found {found}"
