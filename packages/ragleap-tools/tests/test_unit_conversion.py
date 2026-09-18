from ragleap_tools.unit_conversion import convert_length, convert_weight, convert_temperature


def test_length_km_to_miles():
    r = convert_length(1, "km", "mi")
    assert r.success
    assert abs(r.result - 0.621371) < 0.001


def test_length_unknown_unit():
    r = convert_length(1, "km", "furlongs")
    assert not r.success


def test_weight_kg_to_lb():
    r = convert_weight(1, "kg", "lb")
    assert r.success
    assert abs(r.result - 2.20462) < 0.001


def test_temperature_c_to_f():
    r = convert_temperature(100, "c", "f")
    assert r.success
    assert r.result == 212.0


def test_temperature_f_to_c():
    r = convert_temperature(32, "f", "c")
    assert r.success
    assert r.result == 0.0


def test_temperature_below_absolute_zero_rejected():
    r = convert_temperature(-500, "c", "k")
    assert not r.success
