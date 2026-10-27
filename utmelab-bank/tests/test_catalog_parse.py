"""The layout helpers that turn one printed line into one subtopic heading."""

from utmelab_bank.catalog.parse import _stop_subtopic_name
from utmelab_bank.catalog.profiles import profile_for


def test_a_commerce_heading_stops_before_its_list() -> None:
    profile = profile_for("commerce", "Commerce")

    assert _stop_subtopic_name("Retail trade: Functions of retailer", profile) == "Retail trade"
    assert (
        _stop_subtopic_name(
            "Small scale and large scale retailing – Types of Retail Outlets",
            profile,
        )
        == "Small scale and large scale retailing"
    )
    assert (
        _stop_subtopic_name("Wholesale trade - Functions of Wholesalers", profile)
        == "Wholesale trade"
    )


def test_a_commerce_e_commerce_term_is_not_cut_at_its_hyphen() -> None:
    profile = profile_for("commerce", "Commerce")

    name = "Definition of Commerce and E - Commerce"
    assert _stop_subtopic_name(name, profile) == name
    assert _stop_subtopic_name("Types of Insurance a. life Insurance", profile) == (
        "Types of Insurance"
    )
    assert _stop_subtopic_name("And manifest (i) Meaning", profile) == "And manifest"
