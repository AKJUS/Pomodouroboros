from itertools import cycle
from pathlib import Path
from typing import Any, TypeVar

from twisted.internet.defer import Deferred
from twisted.internet.task import deferLater

from ..common import animatePct
from .gtk_progress_bar import MultiBar
from .platspec import Gio, GObject, Gtk

T = TypeVar("T")


def gSimpleProp(name: str, type: type[T]) -> T:
    gprop = GObject.Property(type=type)
    storeName = f"_{name}"

    def getter(self: object) -> T:
        result: T = getattr(self, storeName)
        return result

    getter.__name__ = name

    prop = gprop(getter)

    @prop.setter
    def setter(self: object, value: Any) -> None:
        setattr(self, storeName, value)

    # return type is a polite fiction for class scope
    return setter  # type:ignore[return-value]


class PomItemModel(GObject.Object):
    __gtype_name__ = "PomItemModel"

    number = gSimpleProp("number", int)
    description = gSimpleProp("description", str)
    start = gSimpleProp("start", str)
    end = gSimpleProp("end", str)
    success = gSimpleProp("success", str)


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
        # cscope = Gtk.BuilderCScope.new()
        # scope: Gtk.Builder.BuilderScope = cscope  # type:ignore[assignment]
        # builder.set_scope(scope)
        # cscope.add_callback_symbol(
        #     "pom_bind",
        #     pom_bind_inner,  # type:ignore
        # )
        # c = builder.create_closure("pom_bind", Gtk. BuilderClosureFlags(0))
        # print("created", c)
        builder.add_from_file(str(Path(__file__).parent / "linuxlegacypom.ui"))
        print("added")

        # set up column views

        itemFactory = builder.get_object("description-item-factory")
        assert isinstance(itemFactory, Gtk.SignalListItemFactory)

        def descriptionItemSetup(
            itemFactory: Gtk.SignalListItemFactory, item: Gtk.ListItem
        ) -> None:
            """
            Item setup callback: construct a Gtk.Widget and call set_child on
            item with it.
            """
            print("setup")
            label = Gtk.Label(halign=Gtk.Align.START)
            label.set_selectable(False)
            item.set_child(label)

        itemFactory.connect("setup", descriptionItemSetup)

        def descriptionItemBind(
            itemFactory: Gtk.SignalListItemFactory, item: Gtk.ListItem
        ) -> None:
            print("bind")
            widget = item.get_child()
            assert isinstance(
                widget, Gtk.Label
            ), "should be set up in descriptionItemSetup"
            itemsItem = item.get_item()
            assert isinstance(
                itemsItem, PomItemModel
            ), "should be added with store.insert"
            widget.set_label(itemsItem.description)
            itemsItem.bind_property(
                "description",
                widget,
                "label",
                GObject.BindingFlags.SYNC_CREATE,
            )

        itemFactory.connect("bind", descriptionItemBind)

        loaded: object = builder.get_object("my-window")
        assert isinstance(loaded, Gtk.Window)
        loaded.present()
        store: object = builder.get_object("the-list-store")
        assert isinstance(store, Gio.ListStore), store

        print("creating model")
        one = PomItemModel(description="one")
        store.insert(0, one)
        two = PomItemModel(description="two")
        store.insert(0, two)
        # store.insert(1, one)

        button = builder.get_object("debug-button")
        def setdesc(theButton: Gtk.Button)->None:
            one.description = "three"
        assert isinstance(button, Gtk.Button), "should be a button declared in the UI"
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

        Deferred.fromCoroutine(forever())

    app.connect("activate", makeBar)

    # Run the application
    reactor.registerGApplication(app)
    reactor.run()
