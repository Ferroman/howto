"""The helper's parts that touch no bus: the names of roles, which element a locator names, and the outline."""
from howto.desktop.helper.roles import web_role
from howto.desktop.helper.tree import Node, match, names, nearest, outline, tighter

PICTURE = (1920, 1080)


def node(role, name="", box=(100, 100, 80, 30), **more):
    more.setdefault("states", ("enabled",))
    return Node(role=role, name=name, box=box, **more)


def window():
    return node("frame", "logo.svg - Inkscape", box=(0, 0, 1920, 1080), states=("enabled", "active"), children=[
        node("menubar", box=(0, 0, 1920, 30), children=[
            node("menu", "File", box=(0, 0, 40, 30)),
            node("menu", "Edit", box=(40, 0, 40, 30)),
        ]),
        node("filler", box=(0, 30, 1920, 1000), children=[
            node("label", "Email address", box=(20, 60, 120, 24)),
            node("textbox", "Email address", box=(150, 60, 300, 30), text="sam@example.com", labels=("Email address",)),
            node("button", "Export", box=(500, 60, 90, 30)),
            node("button", "Export As…", box=(600, 60, 110, 30)),
            node("button", "Hidden", box=(700, 60, 90, 30), showing=False),
            node("button", "Far away", box=(2500, 60, 90, 30)),
            node("list", "Layers", box=(20, 200, 300, 400), children=[
                node("listitem", "Layer 1", box=(20, 200, 300, 30), children=[node("button", "Remove", box=(280, 200, 30, 30))]),
                node("listitem", "Layer 2", box=(20, 230, 300, 30), children=[node("button", "Remove", box=(280, 230, 30, 30))]),
            ]),
        ]),
    ])


def found(locator, **options):
    return [element.name for element, _ in match([window()], locator, PICTURE, **options)]


def test_a_role_has_the_name_that_a_web_outline_uses():
    assert [web_role(name) for name in ("push button", "menu item", "check box", "text", "page tab")] == [
        "button", "menuitem", "checkbox", "textbox", "tab",
    ]


def test_a_role_without_a_web_name_keeps_its_own():
    assert web_role("drawing area") == "drawing area"
    assert web_role("frame") == "frame"


def test_a_name_matches_a_part_without_regard_to_case():
    assert found({"role": "button", "name": "export"}) == ["Export", "Export As…"]


def test_exact_matches_the_whole_name():
    assert found({"role": "button", "name": "Export", "exact": True}) == ["Export"]
    assert found({"role": "button", "name": "export", "exact": True}) == []


def test_a_role_alone_matches_every_element_of_that_role():
    assert found({"role": "menu"}) == ["File", "Edit"]


def test_a_window_is_an_element_too():
    assert found({"role": "frame"}) == ["logo.svg - Inkscape"]


def test_a_label_names_the_control_and_not_the_words_beside_it():
    (element, _), = match([window()], {"label": "email"}, PICTURE)
    assert element.role == "textbox"


def test_a_label_matches_through_the_relation_when_the_control_has_another_name():
    field = node("textbox", "q", labels=("Search the notes",))
    assert [e.name for e, _ in match([node("frame", "W", children=[field])], {"label": "Search"}, PICTURE)] == ["q"]


def test_text_matches_a_name_or_what_a_field_holds():
    assert found({"text": "Layer 1"}) == ["Layer 1"]
    (element, _), = match([window()], {"text": "sam@example.com"}, PICTURE)
    assert element.role == "textbox"


def test_text_names_the_smallest_element_that_has_the_words():
    inner = node("label", "Save")
    tree = [node("frame", "W", children=[node("button", "Save", children=[inner])])]
    assert [element for element, _ in match(tree, {"text": "Save"}, PICTURE)] == [inner]


def test_within_looks_only_inside_the_element_it_names():
    locator = {"role": "button", "name": "Remove", "within": {"role": "listitem", "name": "Layer 2"}}
    (element, _), = match([window()], locator, PICTURE)
    assert element.box == (280, 230, 30, 30)


def test_nth_takes_one_of_several_in_the_order_of_the_tree():
    (element, _), = match([window()], {"role": "button", "name": "Remove", "nth": 1}, PICTURE)
    assert element.box == (280, 230, 30, 30)
    assert match([window()], {"role": "button", "name": "Remove", "nth": 2}, PICTURE) == []


def test_only_what_is_showing_and_on_the_picture_matches():
    assert found({"role": "button", "name": "Hidden"}) == []
    assert found({"role": "button", "name": "Far away"}) == []
    assert found({"role": "button", "name": "Hidden"}, hidden=True) == ["Hidden"]
    assert found({"role": "button", "name": "Far away"}, hidden=True) == ["Far away"]


def test_an_element_without_a_size_does_not_match():
    tree = [node("frame", "W", children=[node("button", "Ghost", box=(10, 10, 0, 0)), node("button", "None", box=None)])]
    assert match(tree, {"role": "button"}, PICTURE) == []


def test_each_element_comes_with_its_window():
    (_, top), = match([window()], {"role": "button", "name": "Export", "exact": True}, PICTURE)
    assert top.name == "logo.svg - Inkscape"


def test_an_option_is_an_item_of_a_list_with_exactly_that_name():
    tree = [node("frame", "W", children=[
        node("label", "Admin"),
        node("menuitem", "Admin"),
        node("menuitem", "Administrator"),
    ])]
    (element, _), = match(tree, {"option": "Admin"}, PICTURE)
    assert element.role == "menuitem" and element.name == "Admin"


def test_the_outline_reads_as_a_web_outline():
    assert outline([window()], PICTURE) == (
        '- frame "logo.svg - Inkscape" [active]:\n'
        "  - menubar:\n"
        '    - menu "File"\n'
        '    - menu "Edit"\n'
        '  - label "Email address"\n'
        '  - textbox "Email address": sam@example.com\n'
        '  - button "Export"\n'
        '  - button "Export As…"\n'
        '  - list "Layers":\n'
        '    - listitem "Layer 1":\n'
        '      - button "Remove"\n'
        '    - listitem "Layer 2":\n'
        '      - button "Remove"'
    )


def test_a_quote_and_a_line_break_in_a_name_stay_on_one_line():
    assert outline([node("button", 'Say "hi"\nnow')], PICTURE) == '- button "Say \\"hi\\" now"'


def test_the_outline_says_what_is_checked_and_what_is_disabled():
    tree = [
        node("checkbox", "Wrap lines", states=("enabled", "checked")),
        node("button", "Save", states=()),
        node("label", "Ready", states=()),
    ]
    assert outline(tree, PICTURE) == '- checkbox "Wrap lines" [checked]\n- button "Save" [disabled]\n- label "Ready"'


def test_a_group_with_a_name_stays_and_one_without_gives_way_to_what_is_in_it():
    tree = [node("group", "Options", children=[node("group", children=[node("button", "Reset")])])]
    assert outline(tree, PICTURE) == '- group "Options":\n  - button "Reset"'


def test_what_lies_in_an_element_without_a_place_is_still_listed():
    tree = [node("section", "Body", box=(0, 0, 0, 0), children=[node("button", "Go")])]
    assert outline(tree, PICTURE) == '- button "Go"'


def test_no_window_gives_an_empty_outline():
    assert outline([], PICTURE) == ""


def test_the_nearest_words_come_closest_first_and_as_they_are_written():
    assert nearest("Exprot", ["File", "Export", "Export As…", "Edit"]) == ["Export", "Export As…"]
    assert nearest("Zzz", ["File", "Edit"]) == []


def test_the_names_a_locator_could_have_meant_are_those_of_its_role():
    assert names([window()], {"role": "menu", "name": "Fiel"}, PICTURE) == ["File", "Edit"]
    assert "sam@example.com" in names([window()], {"text": "sam"}, PICTURE)
    assert names([window()], {"label": "Emial"}, PICTURE) == ["Email address", "sam@example.com"]


LABEL = (12, 300, 1256, 24)


def test_the_box_of_the_words_is_taken_when_it_lies_in_the_element():
    assert tighter(LABEL, (12, 303, 140, 18)) == (12, 303, 140, 18)


def test_words_within_a_pixel_of_the_element_still_lie_in_it():
    assert tighter(LABEL, (11.5, 299.5, 140, 25)) == (11.5, 299.5, 140, 25)


def test_words_that_the_app_places_outside_the_element_are_not_believed():
    assert tighter(LABEL, (0, 0, 140, 18)) == LABEL
    assert tighter(LABEL, (12, 303, 1400, 18)) == LABEL


def test_no_words_and_words_without_a_size_leave_the_element_as_it_is():
    assert tighter(LABEL, None) == LABEL
    assert tighter(LABEL, (12, 303, 0, 18)) == LABEL
