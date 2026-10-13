"""The helper's reading of the screen, with tesseract's table given as text."""
from howto.desktop.helper.screen import Line, lacking, lines_of, spot
from howto.desktop.helper.tree import Node

PICTURE = (1920, 1080)
HEAD = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"


def table(*words):
    """A table as `tesseract ... tsv` prints it. A word is (block, line, left, top, width, height, sure, text)."""
    rows = [HEAD, "1\t1\t0\t0\t0\t0\t0\t0\t1920\t1080\t-1\t"]
    for block, line, left, top, width, height, sure, text in words:
        rows.append(f"5\t1\t{block}\t1\t{line}\t1\t{left}\t{top}\t{width}\t{height}\t{sure}\t{text}")
    return "\n".join(rows) + "\n"


EXPORT = table(
    (1, 1, 100, 200, 60, 20, 96.1, "Export"),
    (1, 1, 168, 200, 90, 20, 95.0, "selection"),
    (1, 1, 266, 200, 24, 20, 91.3, "as"),
    (1, 1, 298, 200, 40, 20, 93.0, "PNG"),
    (2, 1, 1620, 200, 50, 24, 90.0, "Layer"),
    (2, 1, 1676, 200, 12, 24, 88.0, "1"),
    (3, 1, 100, 600, 60, 20, 94.0, "Export"),
)


def test_the_words_of_one_line_are_one_line_with_a_box_around_them():
    first, second, third = lines_of(EXPORT)
    assert first.text == "Export selection as PNG" and first.box == (100, 200, 238, 20)
    assert second.text == "Layer 1" and second.box == (1620, 200, 68, 24)
    assert third.text == "Export"


def test_a_picture_that_was_enlarged_gives_places_of_its_own_size():
    (line,) = lines_of(table((1, 1, 200, 400, 120, 40, 96.0, "Export")), shrink=2)
    assert line.box == (100, 200, 60, 20)


def test_what_tesseract_is_not_sure_of_and_what_is_no_word_are_left_out():
    read = lines_of(table(
        (1, 1, 10, 10, 20, 20, 12.0, "Fi1e"),
        (1, 1, 40, 10, 20, 20, 95.0, "|"),
        (1, 1, 70, 10, 20, 20, 95.0, "—"),
        (2, 1, 10, 50, 40, 20, 95.0, "Edit"),
    ))
    assert [line.text for line in read] == ["Edit"]


def test_a_table_with_no_word_gives_no_line():
    assert lines_of(table()) == []
    assert lines_of("") == []


def test_words_are_found_as_a_part_of_a_line_without_regard_to_case():
    places = spot(lines_of(EXPORT), "selection AS")
    assert places == [(168, 200, 122, 20)]


def test_the_place_of_a_part_of_a_word_is_the_whole_word():
    assert spot(lines_of(EXPORT), "Lay") == [(1620, 200, 50, 24)]


def test_words_that_the_screen_shows_twice_have_two_places():
    assert spot(lines_of(EXPORT), "Export") == [(100, 200, 60, 20), (100, 600, 60, 20)]


def test_exact_takes_a_line_that_is_those_words_and_nothing_else():
    assert spot(lines_of(EXPORT), "Export", exact=True) == [(100, 600, 60, 20)]
    assert spot(lines_of(EXPORT), "export", exact=True) == []


def test_words_that_are_not_there_have_no_place():
    assert spot(lines_of(EXPORT), "Import") == []
    assert spot(lines_of(EXPORT), "  ") == []


def test_a_line_that_an_element_has_at_its_place_is_left_out():
    button = Node("button", "Export selection as PNG", box=(90, 190, 260, 40), states=("enabled",))
    window = Node("frame", "Drawing", box=(0, 0, 1920, 1080), children=[button])
    assert [line.text for line in lacking(lines_of(EXPORT), [window], PICTURE)] == ["Layer 1", "Export"]


def framed(*elements):
    return [Node("frame", "Drawing", box=(0, 0, 1920, 1080), children=list(elements))]


def test_the_same_words_somewhere_else_are_not_left_out():
    far = Node("button", "Layer 1", box=(0, 900, 100, 30), states=("enabled",))
    assert "Layer 1" in [line.text for line in lacking(lines_of(EXPORT), framed(far), PICTURE)]


def test_a_word_is_not_left_out_because_it_is_a_part_of_another():
    # The screen shows `port`. An element that says `Export` at that place does not have that word.
    read = lines_of(table((1, 1, 100, 200, 40, 20, 95.0, "port")))
    button = Node("button", "Export", box=(90, 190, 260, 40), states=("enabled",))
    assert [line.text for line in lacking(read, framed(button), PICTURE)] == ["port"]


def test_the_title_of_a_window_hides_no_words_in_it():
    # A window that fills the monitor shows no title, and its box holds every word on the screen.
    read = lines_of(table((1, 1, 100, 200, 90, 20, 95.0, "Drawing")))
    assert [line.text for line in lacking(read, framed(), PICTURE)] == ["Drawing"]


def test_a_line_across_two_elements_loses_the_words_that_each_of_them_has():
    read = lines_of(table(
        (1, 1, 20, 60, 50, 20, 95.0, "Name"),
        (1, 1, 300, 60, 40, 20, 95.0, "Role"),
        (1, 1, 500, 60, 70, 20, 95.0, "Painted"),
    ))
    # A label often ends in a sign that the screen reads as a part of the word, or not at all.
    labels = framed(Node("label", "Name:", box=(16, 56, 60, 28)), Node("label", "Role", box=(296, 56, 50, 28)))
    assert [line.text for line in lacking(read, labels, PICTURE)] == ["Painted"]


def test_what_a_field_holds_counts_as_words_that_the_tree_has():
    field = Node("textbox", "Name", text="sam", box=(100, 190, 300, 40), states=("enabled",))
    read = lines_of(table((1, 1, 110, 200, 40, 20, 95.0, "sam")))
    assert lacking(read, framed(field), PICTURE) == []


def test_a_line_is_its_words_and_their_boxes():
    line = Line((("Layer", (10, 10, 50, 20)), ("1", (64, 12, 10, 18))))
    assert (line.text, line.box) == ("Layer 1", (10, 10, 64, 20))
