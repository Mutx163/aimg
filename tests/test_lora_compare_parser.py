import pytest

from src.ui.widgets.param_panel import parse_compare_weights_expression


def test_parse_compare_weights_list():
    values = parse_compare_weights_expression("0.7,0.75,0.8,0.85")
    assert values == [0.7, 0.75, 0.8, 0.85]


def test_parse_compare_weights_range():
    values = parse_compare_weights_expression("0.7:0.85:0.05")
    assert values == [0.7, 0.75, 0.8, 0.85]


def test_parse_compare_weights_mixed_dedup():
    values = parse_compare_weights_expression("0.7;0.75\n0.8,0.75,0.7:0.8:0.1")
    assert values == [0.7, 0.75, 0.8]


@pytest.mark.parametrize(
    "expr",
    [
        "",
        "0.7:0.9",
        "0.7:0.9:0",
        "abc",
        "0.9:0.7:0.05",
    ],
)
def test_parse_compare_weights_invalid(expr):
    with pytest.raises(ValueError):
        parse_compare_weights_expression(expr)
