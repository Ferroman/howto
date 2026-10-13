"""`howto probe` on a desktop storyboard, from the command to the report. These tests need Docker and the base image."""
import pytest
import yaml

from howto import cli

pytestmark = pytest.mark.desktop

STEPS = [
    {"do": [{"fill": {"label": "Name", "value": "sam"}}, {"select": {"label": "Role", "option": "Admin"}}]},
    {"do": [{"click": {"role": "button", "name": "Add"}}, {"wait_for": {"text": "Added sam"}}]},
    {"do": [{"click": {"role": "menu", "name": "File"}}, {"click": {"role": "menuitem", "name": "About"}}]},
    {"do": [{"click": {"role": "button", "name": "Close"}}]},
]


def write_board(tmp_path, desktop, steps, **extra):
    data = {
        "title": "Add a name",
        "app": {"image": desktop.image, "run": desktop.run},
        "viewport": "1280x720",
        "steps": steps,
        **extra,
    }
    path = tmp_path / "videos" / "add.yaml"
    path.parent.mkdir(exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def test_a_probe_of_a_correct_storyboard(desktop, sandbox, tmp_path, capsys):
    assert cli.main(["probe", str(write_board(tmp_path, desktop, STEPS))]) == 0
    out = capsys.readouterr().out
    assert "step 4 ok      click role=button name=\"Close\"" in out
    assert f'page: app {desktop.run}  "Fixture"' in out
    assert '- frame "Fixture" [active]:' in out
    assert '- label "sam, Admin"' in out and '- label "Added sam"' in out
    assert "note:" not in out


def test_a_probe_names_the_step_with_the_wrong_name_and_offers_the_right_one(desktop, sandbox, tmp_path, capsys, monkeypatch):
    # Three seconds for an element, and so nine for the app's first window.
    monkeypatch.setenv("HOWTO_ACTION_TIMEOUT", "3")
    steps = [STEPS[0], {"do": [{"click": {"role": "button", "name": "Addd"}}]}]
    assert cli.main(["probe", str(write_board(tmp_path, desktop, steps))]) == 1
    out = capsys.readouterr().out
    assert "step 1 ok" in out
    assert 'step 2 FAILED  click role=button name="Addd": not in the tree. The nearest names: "Add"' in out
    assert '- button "Add"' in out


def test_a_probe_stops_where_until_says_and_shows_a_dialog_as_a_second_window(desktop, sandbox, tmp_path, capsys):
    assert cli.main(["probe", str(write_board(tmp_path, desktop, STEPS)), "--until", "3"]) == 0
    out = capsys.readouterr().out
    assert '- dialog "About Fixture"' in out and '- frame "Fixture"' in out
    assert "step 4" not in out


def test_within_limits_the_outline_to_one_element(desktop, sandbox, tmp_path, capsys):
    arguments = ["probe", str(write_board(tmp_path, desktop, STEPS)), "--until", "3", "--within", "{role: dialog}"]
    assert cli.main(arguments) == 0
    out = capsys.readouterr().out
    assert '- dialog "About Fixture"' in out and '- frame "Fixture"' not in out


def test_setup_and_cleanup_run_commands_in_the_container(desktop, sandbox, tmp_path, capsys):
    path = write_board(
        tmp_path, desktop, [{"do": [{"wait_for": {"role": "button", "name": "Add"}}]}],
        setup=[{"run": "echo made > /home/howto/note.txt"}],
        cleanup=[{"run": "test -f /home/howto/note.txt && rm /home/howto/note.txt"}, {"run": "test -f /home/howto/note.txt"}],
    )
    assert cli.main(["probe", str(path)]) == 0
    out = capsys.readouterr().out
    # The first cleanup found the file that setup made and removed it. The second then found none.
    assert "warning: cleanup[2]: run test -f /home/howto/note.txt: it ended with exit code 1" in out
    assert "cleanup[1]" not in out


def test_an_app_that_does_not_start_exits_1_with_what_it_said(desktop, sandbox, tmp_path, capsys):
    path = write_board(tmp_path, desktop, STEPS[:1])
    path.write_text(path.read_text().replace(desktop.run, "no-such-app --now"), encoding="utf-8")
    assert cli.main(["probe", str(path)]) == 1
    err = capsys.readouterr().err
    assert "howto: the app ended with exit code 127" in err and "no-such-app" in err


def test_an_image_that_does_not_exist_exits_1_with_the_command_that_builds_it(desktop, sandbox, tmp_path, capsys):
    path = write_board(tmp_path, desktop, STEPS[:1])
    path.write_text(path.read_text().replace(desktop.image, "howto-no-such-image"), encoding="utf-8")
    assert cli.main(["probe", str(path)]) == 1
    assert "the image howto-no-such-image does not exist: run `docker build -t howto-no-such-image DIR`" in capsys.readouterr().err
