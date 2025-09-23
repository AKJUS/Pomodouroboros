from itertools import cycle
from pathlib import Path
from typing import Any, TypeVar

from twisted.internet.defer import Deferred
from twisted.internet.task import deferLater

from ..common import animatePct
from .old_gtk_gui import PomItemModel
from .gtk_progress_bar import MultiBar
from .platspec import Gio, GObject, Gtk
from .gobj_utils import gSimpleProp, bindLabelColumns


if __name__ == "__main__":
    from twisted.internet.gireactor import install

    reactor = install()
    # Create a new application
    app = Gtk.Application(application_id="im.glyph.and.this.is.Pomodouroboros")
    # settings = Gtk.Settings.get_default()
    # # settings.set_property("gtk-application-prefer-dark-theme", True)
    # print("theme", settings.get_property("gtk-theme-name"))
    # print("dark", settings.get_property("gtk-application-prefer-dark-theme"))
    # for i in settings.list_properties():
    #     print(i)

    def _on_theme_name_changed(
        settings: Gtk.Settings, gparam: GObject.Parameter
    ) -> None:
        print("Theme name:", settings.get_property("gtk-theme-name"))

    settings = Gtk.Settings.get_default()
    assert settings is not None
    settings.connect("notify::gtk-theme-name", _on_theme_name_changed)

    def _on_dark_changed(
        settings: Gtk.Settings, gparam: GObject.Parameter
    ) -> None:
        print(
            "dark:", settings.get_property("gtk-application-prefer-dark-theme")
        )

    settings.connect(
        "notify::gtk-application-prefer-dark-theme", _on_dark_changed
    )

    def makeBar(app: Gtk.Application) -> None:
        bar = MultiBar.create(app)
        # def pom_bind_inner() -> None:
        #     print("pom_bind_inner!!!!!!!*!********!")
        builder = Gtk.Builder.new()
        builder.add_from_file(str(Path(__file__).parent / "linuxlegacypom.ui"))
        print("added")

        # set up column views
        descriptionItemFactory = builder.get_object("description-item-factory")
        assert isinstance(descriptionItemFactory, Gtk.SignalListItemFactory)
        numberItemFactory = builder.get_object("number-item-factory")
        assert isinstance(numberItemFactory, Gtk.SignalListItemFactory)
        selector = builder.get_object("the-store-model")
        assert isinstance(selector, Gtk.SingleSelection)
        bindLabelColumns(
            {
                "description": descriptionItemFactory,
                "number": numberItemFactory,
            },
            selector,
        )

        loaded: object = builder.get_object("my-window")
        assert isinstance(loaded, Gtk.Window)
        loaded.present()
        store: object = builder.get_object("the-list-store")
        assert isinstance(store, Gio.ListStore), store

        print("creating model")
        one = PomItemModel(description="one", number=1, editable=True)
        store.insert(0, one)
        two = PomItemModel(description="two", number=2, editable=False)
        store.insert(0, two)
        # store.insert(1, one)

        button = builder.get_object("debug-button")

        def setdesc(theButton: Gtk.Button) -> None:
            one.description = "three"

        assert isinstance(
            button, Gtk.Button
        ), "should be a button declared in the UI"
        button.connect("clicked", setdesc)

        texts = cycle(
            [
                "let's start with this text",
                "then move on to this text",
                "then hide the text",
                "",
                "",
                "",
            ]
        )
        styles = cycle(["active", "prompt", "break", "grace"])

        async def forever() -> None:
            pct = 0.0
            while True:
                newpct = pct + 0.1
                await animatePct(
                    bar,
                    reactor,
                    newpct,
                    pct,
                    1.0,
                    0.15,
                    0.3,
                )
                await deferLater(reactor, 1.0)
                newpct %= 1.0
                pct = newpct
                newText = next(texts)
                print(f"setting reticle text {newText!r}")
                bar.setReticleText(newText)
                newStyle = next(styles)
                bar.setStyle(newStyle)

        Deferred.fromCoroutine(forever())

    app.connect("activate", makeBar)

    # Run the application
    reactor.registerGApplication(app)
    reactor.run()
