from pipelines.layer_dictionaries import limit_for, resolve


def row(field, description="d", include="1", reason=""):
    return {"field": field, "description": description, "include": include, "reason": reason}


def test_field_matches_its_column_case_and_accent_blind():
    fields = resolve([row("JanBASEAvg"), row("Técnico")], ["janbaseavg", "tecnico", "geom"])
    assert [f.column for f in fields] == ["janbaseavg", "tecnico"]


def test_shapefile_ten_character_names_match():
    fields = resolve([row("DESCRIPPUT_LONG")], ["descripput"])
    assert fields[0].column == "descripput"


def test_one_cell_naming_two_columns_covers_both():
    fields = resolve([row("DECIMAL_X / DECIMAL_Y", "Coordinates")], ["decimal_x", "decimal_y"])
    assert [f.column for f in fields] == ["decimal_x", "decimal_y"]


def test_field_without_a_column_is_left_out():
    assert resolve([row("PL_WET")], ["pi_wet"]) == []


def test_include_flag_and_blank():
    fields = resolve([row("a", include="0"), row("b", include="")], ["a", "b"])
    assert [f.include for f in fields] == [False, None]


def test_monthly_series_are_not_cut_to_ten():
    assert limit_for("Data Dictionary_Wind") is None
    assert limit_for("Data Dictionary - Temperature") is None
    assert limit_for("Data Dictionary_Geology") == 10


def test_owner_names_are_never_shown_even_when_included():
    owner = resolve([row("nombre", "Property owner name or owner entity name.")], ["nombre"])[0]
    school = resolve([row("escuela", "Name of the school.")], ["escuela"])[0]
    assert owner.include and not owner.shown
    assert school.shown


def test_a_parcels_address_is_hidden_but_a_schools_is_not():
    parcel = resolve([row("t_fisdir1", "Physical property address (line 1).")], ["t_fisdir1"])[0]
    school = resolve([row("direccion", "Physical address of the school.")], ["direccion"])[0]
    assert not parcel.shown and school.shown
