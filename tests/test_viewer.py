"""The window on the monitor of a container: its address, and the Chromium that shows it."""
import pytest

from howto.desktop import viewer


def test_the_address_connects_at_once_and_carries_the_password_of_the_run():
    assert viewer.address(49153, "a1b2c3d4", view_only=False) == (
        "http://127.0.0.1:49153/vnc.html?autoconnect=1&resize=scale&reconnect=0&password=a1b2c3d4"
    )


def test_a_watcher_s_address_asks_the_page_to_send_no_input_either():
    assert viewer.address(49153, "a1b2c3d4", view_only=True).endswith("&password=a1b2c3d4&view_only=1")


def test_the_port_is_the_one_that_the_helper_serves():
    from howto.desktop.helper.watch import WEB_PORT

    assert viewer.PORT == WEB_PORT


@pytest.mark.browser
def test_the_window_is_a_page_of_chromium_that_can_be_closed(chromium):
    window = viewer.Viewer("data:text/html,<title>Monitor</title><p>Hi</p>", headless=True)
    try:
        assert window.page.title() == "Monitor"
    finally:
        window.close()
    # Closing twice is not an error: the person may have closed the window already.
    window.close()
