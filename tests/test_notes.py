"""The HTML of what lies over a picture: the note, the strip, the title card, the ring of a click."""
from howto.notes import CARD_FADE_MS, RING_MS, card_html, note_html, ring_html, strip_html
from howto.zoom import Box


def test_a_note_is_a_box_at_the_bottom_with_its_text_escaped():
    html = note_html('Use <b>"work"</b> & co')
    assert "Use &lt;b&gt;&quot;work&quot;&lt;/b&gt; &amp; co" in html
    assert "bottom:48px" in html and html.startswith("<div style=") and html.endswith("</div>")


def test_a_note_of_a_cropped_picture_is_written_in_its_strip():
    strip = Box(100, 300, 340, 44)
    assert "left:100px;top:300px;width:340px;height:44px" in note_html("Pick a style", strip)
    assert "left:100px;top:300px;width:340px;height:44px" in strip_html(strip)


def test_a_title_card_is_in_the_middle_and_escapes_its_title():
    html = card_html("Files & <folders>")
    assert "Files &amp; &lt;folders&gt;" in html
    assert "align-items:center;justify-content:center" in html
    assert f"{CARD_FADE_MS}ms" in html and "animation:" in html


def test_a_ring_spreads_from_the_point_of_the_click():
    html = ring_html(140.0, 55.5)
    assert "left:140.0px;top:55.5px" in html
    assert f"{RING_MS}ms" in html and "border-radius:50%" in html
