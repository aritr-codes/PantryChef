from pantrychef.ingredients.units import parse_quantity, parse_unit, replace_unicode_fractions


def test_replace_unicode_fractions() -> None:
    assert replace_unicode_fractions("½ cup").strip().startswith("1/2")


def test_parse_quantity_integer_decimal_fraction() -> None:
    assert parse_quantity("2 cups flour")[0] == 2.0
    assert parse_quantity("1.5 cups flour")[0] == 1.5
    assert parse_quantity("1/2 cup milk")[0] == 0.5
    assert parse_quantity("1 1/2 cups sugar")[0] == 1.5


def test_parse_quantity_unicode_and_range() -> None:
    assert parse_quantity("½ cup milk")[0] == 0.5
    assert parse_quantity("1 to 2 cups water")[0] == 1.0
    assert parse_quantity("1-2 cups water")[0] == 1.0


def test_parse_quantity_none_when_absent() -> None:
    qty, rest = parse_quantity("pinch of salt")
    assert qty is None
    assert "salt" in rest


def test_parse_unit_known_and_unknown() -> None:
    assert parse_unit("cups flour") == ("cup", "flour")
    assert parse_unit("tbsp sugar") == ("tbsp", "sugar")
    assert parse_unit("flour") == (None, "flour")


def test_parse_quantity_fraction_slash_and_range_with_fraction() -> None:
    assert (
        parse_quantity("1 \u20442 cups milk")[0] == 1.5
        or parse_quantity("1\u20442 cup milk")[0] == 0.5
    )
    assert parse_quantity("1 1\u20442 cups milk") == (1.5, "cups milk")
    qty, rest = parse_quantity("\u00bd-1 tsp salt")
    assert qty == 0.5 and rest == "tsp salt"


def test_parse_unit_skips_size_parenthetical() -> None:
    assert parse_unit("(14 oz) can tomatoes") == ("can", "tomatoes")
    assert parse_unit("(optional) parsley") == (None, "(optional) parsley")
