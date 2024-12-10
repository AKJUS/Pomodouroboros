import gi  # type:ignore

gi.require_version("GLib", "2.0")
from gi.repository import GLib  # type:ignore
from gi.repository import Gio, GObject

gi.require_version("Gdk", "4.0")
from gi.repository import Gdk

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk


class MyThing(GObject.Object):
    def __init__(self, aValue: int) -> None:
        super().__init__()
        self.aValue = aValue


def on_activate(app: Gtk.Application) -> None:
    print("creating application window")
    win = Gtk.ApplicationWindow(application=app)
    print("created")
    box = Gtk.Box()

    button = Gtk.Button()
    button.set_label("hello world?")

    button2 = Gtk.Button()
    button2.set_label("goodbye world?")
    lm = Gio.ListStore.new(MyThing)
    lm.append(MyThing(7))
    lm.append(MyThing(8))
    lm.append(MyThing(9))
    signalFactory = Gtk.SignalListItemFactory()

    def onsetup(
        factory: Gtk.SignalListItemFactory, item: Gtk.ListItem
    ) -> None:
        value = item.get_item().aValue
        item.set_child(Gtk.Label.new(f"setup {value}"))

    def onbind(factory: Gtk.SignalListItemFactory, item: Gtk.ListItem) -> None:
        value = item.get_item().aValue
        item.set_child(Gtk.Label.new(f"bind {value}"))

    signalFactory.connect("setup", onsetup)
    signalFactory.connect("bind", onbind)
    lv = Gtk.ListView.new(Gtk.SingleSelection.new(lm), signalFactory)
    box.append(button)
    box.append(lv)
    box.append(button2)
    win.set_child(box)
    win.present()
    print("presented")


if __name__ == "__main__":
    # Create a new application
    app = Gtk.Application(application_id="im.glyph.and.this.is.a.detail.view")
    app.connect("activate", on_activate)

    # Run the application
    print("running?")
    app.run()
    print("goodbye?")
