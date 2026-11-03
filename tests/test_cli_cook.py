from pathlib import Path

from pantrychef.cli import cook_command

FIXTURE = str(Path(__file__).parent / "fixtures" / "pack")


def test_cook_shows_groups_and_unlocks(capsys) -> None:
    rc = cook_command(have="flour,eggs,milk", k=3, pack_dir=FIXTURE)
    out = capsys.readouterr().out
    assert rc == 0
    assert "MAKE NOW" in out and "ONE ITEM AWAY" in out
    assert "Top unlocks:" in out and "to move" in out
    assert "(you have" in out


def test_cook_reports_unrecognised_names(capsys) -> None:
    rc = cook_command(have="flour,xylophone", k=3, pack_dir=FIXTURE)
    assert rc == 0
    assert "Not recognised (not used): xylophone" in capsys.readouterr().out


def test_cook_missing_pack_errors(tmp_path, capsys) -> None:
    rc = cook_command(have="flour", k=3, pack_dir=str(tmp_path / "nope"))
    out = capsys.readouterr().out
    assert rc == 1
    assert "not found" in out.lower()


def test_cook_says_so_when_nothing_matches(capsys) -> None:
    rc = cook_command(have="xylophone", k=3, pack_dir=FIXTURE)
    out = capsys.readouterr().out
    assert rc == 0
    assert "No matching recipes." in out
