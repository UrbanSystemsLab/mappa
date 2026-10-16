"""Which column names a layer's features, and that it is never a person.

An answer that says *which* schools are in a flood zone reads the layer's name
column. On some layers the only name is a person's - the farmers on the
farm-permit layers, private owners on others - and those must never be read out.
"""

from pipelines.profile_layers import looks_like_people


def test_farmers_names_read_as_people():
    assert looks_like_people(
        ["MIGUEL DOMINGUEZ", "CATALINA TORRES", "ANGEL ALICEA APONTE", "PABLO L. TORRES FLORES"]
    )


def test_institutions_and_places_do_not():
    assert not looks_like_people(
        [
            "HOSP DEL MAESTRO",
            "Bosque Estatal de Guajataca",
            "Balneario Crash Boat",
            "Centro Gobierno Juncos",
            "Naranjito WWTP",
            "Matadero 3",
        ]
    )


def test_a_few_owners_among_facilities_are_not_enough_to_flag():
    assert not looks_like_people(
        [
            "REXACH OFFICE BUILDING",
            "PRASA-BARBOSA",
            "COCO BEACH GOLF CLUB",
            "ANTONIO RIVERA",
            "HOSP SAN PABLO",
            "Aeropuerto de Ponce",
        ]
    )


def test_rivers_and_creeks_are_places():
    assert not looks_like_people(
        [
            "Río Grande de Loíza",
            "Quebrada Grande",
            "Río Piedras",
            "Laguna Tortuguero",
            "Caño Tiburones",
        ]
    )
