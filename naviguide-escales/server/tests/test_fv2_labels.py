"""FV2 — libellés d'escale, FR et EN. L'identité des escales ne change pas."""
from film_script import display_stop_name, norm_stop


def test_acores_sans_suffixe_corse():
    assert display_stop_name("Açores (Corse)", "fr") == "Açores"
    assert display_stop_name("Açores (Corse)", "en") == "Azores (Portugal)"
    assert "Corse" not in display_stop_name("Açores (Corse)", "fr")
    assert "Corsica" not in display_stop_name("Açores (Corse)", "en")
    assert display_stop_name("Ajaccio (Corse)", "fr") == "Ajaccio (Corse)"
    assert display_stop_name("Ajaccio (Corse)", "en") == "Ajaccio (Corse)"
    assert norm_stop("Açores (Corse)") == norm_stop("Açores")
    assert norm_stop("Ajaccio (Corse)") == "ajaccio"


def test_saint_maur_indre():
    for lang in ("fr", "en"):
        assert display_stop_name("Saint-Maur (Berry)", lang) == "Saint-Maur (Indre)"
        assert display_stop_name("Saint-Maur (Berry, Indre)", lang) == "Saint-Maur (Indre)"
        assert display_stop_name("Saint-Maur", lang) == "Saint-Maur (Indre)"
        assert "Berry" not in display_stop_name("Saint-Maur (Berry)", lang)
    assert display_stop_name("Europa (TAAF)", "fr") == "Europa (TAAF)"
    assert display_stop_name("La Rochelle", "en") == "La Rochelle"
