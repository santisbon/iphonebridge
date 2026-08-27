"""models.py — identifier-to-marketing-name mapping."""
from iphonebridge.models import MODEL_NAMES, marketing_name


def test_known_identifiers():
    assert marketing_name("iPhone18,1") == "iPhone 17 Pro"
    assert marketing_name("iPhone14,7") == "iPhone 14"


def test_unknown_passes_through():
    # A model newer than the table must display as itself, never blank.
    assert marketing_name("iPhone99,9") == "iPhone99,9"
    assert marketing_name("") == ""
    assert marketing_name(None) == ""
    assert marketing_name("  iPhone18,1  ") == "iPhone 17 Pro"


def test_table_shape():
    assert len(MODEL_NAMES) > 50
    for ident, name in MODEL_NAMES.items():
        assert ident.startswith("iPhone") and "," in ident
        assert name and not name.startswith("iPhone,"), (ident, name)
