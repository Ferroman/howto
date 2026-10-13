"""The app that the desktop tests film: one window with one of each thing a storyboard can name."""
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, Gtk  # noqa: E402


class Fixture(Gtk.Window):
    def __init__(self):
        super().__init__(title="Fixture")
        self.dark = False
        self.painted = "Painted words"
        column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(column)

        bar = Gtk.MenuBar()
        file_item = Gtk.MenuItem(label="File")
        menu = Gtk.Menu()
        file_item.set_submenu(menu)
        about = Gtk.MenuItem(label="About")
        about.connect("activate", self.on_about)
        menu.append(about)
        leave = Gtk.MenuItem(label="Quit")
        leave.connect("activate", Gtk.main_quit)
        menu.append(leave)
        bar.append(file_item)
        column.pack_start(bar, False, False, 0)

        form = Gtk.Box(spacing=8, margin=12)
        column.pack_start(form, False, False, 0)
        name = Gtk.Label(label="Name")
        self.entry = Gtk.Entry()
        name.set_mnemonic_widget(self.entry)
        role = Gtk.Label(label="Role")
        self.role = Gtk.ComboBoxText()
        for choice in ("Member", "Admin"):
            self.role.append_text(choice)
        self.role.set_active(0)
        role.set_mnemonic_widget(self.role)
        add = Gtk.Button(label="Add")
        add.connect("clicked", self.on_add)
        flash = Gtk.Button(label="Flash")
        flash.connect("clicked", self.on_flash)
        for widget in (name, self.entry, role, self.role, add, flash):
            form.pack_start(widget, False, False, 0)

        self.people = Gtk.ListBox()
        column.pack_start(self.people, False, False, 0)
        self.status = Gtk.Label(label="Nothing added yet", xalign=0, margin=12)
        column.pack_start(self.status, False, False, 0)
        # Painted, so the tree has no name for the words in it. A press on it changes the words.
        self.area = Gtk.DrawingArea()
        self.area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.area.connect("draw", self.on_draw)
        self.area.connect("button-press-event", self.on_area)
        column.pack_start(self.area, True, True, 0)
        self.connect("destroy", Gtk.main_quit)

    def on_add(self, _button):
        who = self.entry.get_text()
        row = Gtk.Label(label=f"{who}, {self.role.get_active_text()}", xalign=0, margin=6)
        self.people.add(row)
        row.show()
        self.status.set_text(f"Added {who}")

    def on_flash(self, _button):
        self.dark = not self.dark
        self.area.queue_draw()

    def on_area(self, _area, _event):
        self.painted = "Pressed once"
        self.area.queue_draw()

    def on_about(self, _item):
        dialog = Gtk.Dialog(title="About Fixture", transient_for=self, modal=True)
        dialog.get_content_area().add(Gtk.Label(label="A window for the tests of howto", margin=24))
        dialog.add_button("Close", Gtk.ResponseType.CLOSE)
        dialog.connect("response", lambda shown, _response: shown.destroy())
        dialog.show_all()

    def on_draw(self, _area, context):
        shade = 0.0 if self.dark else 1.0
        context.set_source_rgb(shade, shade, shade)
        context.paint()
        context.set_source_rgb(1 - shade, 1 - shade, 1 - shade)
        context.select_font_face("DejaVu Sans")
        context.set_font_size(36)
        context.move_to(40, 80)
        context.show_text(self.painted)


window = Fixture()
window.show_all()
Gtk.main()
