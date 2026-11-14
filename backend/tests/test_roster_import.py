"""Roster parsing tests use synthetic contacts, never private board data."""

import pytest

from app.services.roster_import import parse_roster

HEADER = "\tGirlHacks Title\tEboard Position\tMajor\tGraduation Date\t\t\t\t\n"


def test_roster_blocks_preserve_missing_contacts_and_role_notes(tmp_path):
    path = tmp_path / "roster.tsv"
    path.write_text(HEADER + (
        "Alice Example\tFinance Chair\tTreasurer\tData Science\tMay 2029"
        "\t(202) 555-0123\tAlice@Example.com\tThe Role: Manage finances.\tTasks:\n"
        "\tTasks:\n Draft budgets.\n\n"
        "Bob Example\tTech Operations Chair\tTechnical Director\tComputer Science"
        "\tMay 2027\t\t\tThe Role: Recruit members.\n Lead recruitment.\n"
    ), encoding="utf-8")
    rows, warnings = parse_roster(path)
    assert len(rows) == 2
    assert rows[0]["email"] == "alice@example.com"
    assert rows[0]["phone_number"] == "(202) 555-0123"
    assert rows[0]["contact_consent"] is True
    assert rows[0]["role_responsibilities"] == ["Draft budgets."]
    assert rows[0]["graduation_year"] == 2029
    assert rows[1]["email"] is None
    assert rows[1]["phone_number"] is None
    assert rows[1]["contact_consent"] is False
    assert rows[1]["delegation_context_verified"] is True
    assert "technical development" in rows[1]["role_description"]
    assert len(rows[1]["role_responsibilities"]) == 5
    assert "Lead recruitment." not in rows[1]["role_responsibilities"]
    assert warnings == []
    assert rows == parse_roster(path)[0]  # Stable codes make repeat imports update members.


def test_duplicate_contact_email_rejects_entire_file(tmp_path):
    path = tmp_path / "roster.tsv"
    path.write_text(HEADER + (
        "Alice\tDirector\tPresident\tCS\tMay 2027\t\tuser@example.com\n"
        "Bob\tVice Director\tVice President\tCS\tMay 2027\t\tUSER@example.com\n"
    ), encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate invitation email"):
        parse_roster(path)


def test_malformed_member_row_is_not_treated_as_responsibility(tmp_path):
    path = tmp_path / "roster.tsv"
    path.write_text(HEADER + "Alice\tDirector\tPresident\tCS\tunknown\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unrecognized roster row"):
        parse_roster(path)


@pytest.mark.parametrize("role,count,expected", [
    ("Membership Chair", 10, "Lead recruitment efforts during Involvement Fairs and orientation events."),
    ("Technical Director", 5, "Design and develop the GirlHacks website and landing pages."),
])
def test_user_verified_definitions_replace_swapped_export_blocks(tmp_path, role, count, expected):
    path = tmp_path / "roster.tsv"
    source = HEADER + (
        f"Demo Person\tDemo Title\t{role}\tCS\tMay 2027"
        "\t\t\tThe Role: Incorrect export description.\n Incorrect responsibility.\n"
    )
    path.write_text(source, encoding="utf-8")
    rows, warnings = parse_roster(path)
    assert warnings == []
    assert rows[0]["delegation_context_verified"] is True
    assert len(rows[0]["role_responsibilities"]) == count
    assert expected in rows[0]["role_responsibilities"]
    assert "Incorrect" not in rows[0]["role_description"]
    assert path.read_text(encoding="utf-8") == source
