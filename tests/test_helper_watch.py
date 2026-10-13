"""The two servers that show the helper's monitor to a person, as the commands that start them."""
from howto.desktop.helper.watch import WEB_PORT, vnc_command, web_command


def test_the_vnc_server_listens_inside_the_container_only_and_asks_for_the_password():
    command = vnc_command(view_only=False)
    assert command[0] == "x11vnc" and command[command.index("-display") + 1] == ":99"
    assert "-localhost" in command and "-forever" in command and "-shared" in command
    assert command[command.index("-passwdfile") + 1] == "/tmp/howto/vnc-password"
    assert "-viewonly" not in command and "-nopw" not in command


def test_a_watcher_gets_a_server_that_takes_no_input():
    assert vnc_command(view_only=True)[-1] == "-viewonly"


def test_novnc_is_served_at_the_port_that_docker_publishes():
    assert WEB_PORT == 6080
    assert web_command() == ["websockify", "--web", "/usr/share/novnc", "6080", "localhost:5900"]
