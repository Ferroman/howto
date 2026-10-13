"""The names of roles. AT-SPI has its own, and a storyboard uses the ones a web outline has."""
from __future__ import annotations

WEB = {
    "push button": "button",
    "toggle button": "button",
    "check box": "checkbox",
    "radio button": "radio",
    "menu bar": "menubar",
    "menu item": "menuitem",
    "check menu item": "menuitemcheckbox",
    "radio menu item": "menuitemradio",
    "popup menu": "menu",
    "text": "textbox",
    "entry": "textbox",
    "password text": "textbox",
    "combo box": "combobox",
    "list box": "listbox",
    "list item": "listitem",
    "page tab": "tab",
    "page tab list": "tablist",
    "table cell": "cell",
    "table row": "row",
    "table column header": "columnheader",
    "table row header": "rowheader",
    "tree item": "treeitem",
    "tree table": "treegrid",
    "spin button": "spinbutton",
    "progress bar": "progressbar",
    "scroll bar": "scrollbar",
    "tool bar": "toolbar",
    "tool tip": "tooltip",
    "status bar": "status",
    "image": "img",
    "icon": "img",
    "alert": "alertdialog",
    "notification": "alert",
    "document frame": "document",
    "document web": "document",
    "document text": "document",
    "panel": "group",
    "grouping": "group",
    "static": "label",
}


def web_role(name: str) -> str:
    """The name a web outline has for an AT-SPI role. A role that the web lacks keeps its own name."""
    return WEB.get(name, name)
