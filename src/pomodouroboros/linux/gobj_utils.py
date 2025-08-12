from typing import Any

from .platspec import GObject, Gtk


def gSimpleProp[T](name: str, type: type[T]) -> T:
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


def _bindOneAttribute(name: str, factory: Gtk.SignalListItemFactory) -> None:
    def setup(
        itemFactory: Gtk.SignalListItemFactory, item: Gtk.ListItem
    ) -> None:
        label = Gtk.Label(halign=Gtk.Align.START)
        label.set_selectable(False)
        item.set_child(label)

    def bind(
        itemFactory: Gtk.SignalListItemFactory, item: Gtk.ListItem
    ) -> None:
        widget = item.get_child()
        assert isinstance(
            widget, Gtk.Label
        ), "should be set up in descriptionItemSetup"
        itemsItem = item.get_item()
        assert itemsItem is not None, "every item should be setup()"
        # assert isinstance(
        #     itemsItem, PomItemModel
        # ), "should be added with store.insert"
        widget.set_label(getattr(itemsItem, name))
        itemsItem.bind_property(
            name,
            widget,
            "label",
            GObject.BindingFlags.SYNC_CREATE,
        )

    # per https://toshiocp.github.io/Gtk4-tutorial/sec29.html, unbind and
    # teardown *should* be taken care of by the GC? if we have resource leaks,
    # we might want to investigate connecting them here.
    factory.connect("setup", setup)
    factory.connect("bind", bind)


def bindLabelColumns(itemFactories: dict[str, Gtk.SignalListItemFactory]) -> None:
    for attrName, listItemFactory in itemFactories.items():
        _bindOneAttribute(attrName, listItemFactory)
