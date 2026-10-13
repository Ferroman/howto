"""A second app, whose one window covers the whole monitor."""
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, Gtk  # noqa: E402

window = Gtk.Window(title="Cover")
window.set_decorated(False)
screen = Gdk.Screen.get_default()
window.set_default_size(screen.get_width(), screen.get_height())
window.move(0, 0)
window.add(Gtk.Label(label="In the way"))
window.connect("destroy", Gtk.main_quit)
window.show_all()
Gtk.main()
