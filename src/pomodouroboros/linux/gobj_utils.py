from typing import Any

from .platspec import GObject, Gtk


def gSimpleProp[T](name: str, type: type[T], default: T | None = None) -> T:
    gprop = GObject.Property(type=type, default=default)
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


# class SelectionManagingEditableLabel(Gtk.EditableLabel):
#     pass


def _bindOneAttribute(
    name: str,
    factory: Gtk.SignalListItemFactory,
    selector: Gtk.SingleSelection,
) -> None:
    print(f"binding attribute {name}")

    bindings = {}

    def setup(
        itemFactory: Gtk.SignalListItemFactory, item: Gtk.ListItem
    ) -> None:
        print(f"setting up label for {name}")
        label = Gtk.EditableLabel(
            halign=Gtk.Align.START,
            hexpand=True,
            max_width_chars=10000,
        )
        # label.set_selectable(False)
        item.set_child(label)
        print(f"finished setup for {name}")

    def bind(
        itemFactory: Gtk.SignalListItemFactory, item: Gtk.ListItem
    ) -> None:
        widget = item.get_child()
        assert isinstance(
            widget, Gtk.EditableLabel
        ), "should be set up in setup()"
        itemsItem: Any = item.get_item()
        assert itemsItem is not None, "every item should be setup()"
        # TODO: let's have actual type information for canEditProperty
        editable = itemsItem.canEditProperty(name)
        widget.set_editable(editable)
        widget.set_sensitive(editable)

        def editstartstop(
            label: Gtk.EditableLabel, param: GObject.ParamSpecBoolean
        ) -> None:
            pos = item.get_position()
            if widget.get_editing():
                selector.set_selected(pos)

        widget.connect("notify::editing", editstartstop)
        # assert isinstance(
        #     itemsItem, PomItemModel
        # ), "should be added with store.insert"
        # widget.set_text(str(getattr(itemsItem, name)))
        print(f"binding {itemsItem} to {widget}")
        bindings[(name, widget)] = itemsItem.bind_property(
            name,
            widget,
            "text",
            GObject.BindingFlags.BIDIRECTIONAL
            | GObject.BindingFlags.SYNC_CREATE,
        )

    def unbind(
        itemFactory: Gtk.SignalListItemFactory, item: Gtk.ListItem
    ) -> None:
        widget = item.get_child()
        print(f"unbinding {name} from {widget}")
        assert isinstance(
            widget, Gtk.EditableLabel
        ), "should be set up in setup()"
        bindings.pop((name, widget)).unbind()

    # per https://toshiocp.github.io/Gtk4-tutorial/sec29.html, teardown
    # *should* be taken care of by the GC? if we have resource leaks, we might
    # want to investigate connecting them here.
    factory.connect("setup", setup)
    factory.connect("bind", bind)
    factory.connect("unbind", unbind)


def bindLabelColumns(
    itemFactories: dict[str, Gtk.SignalListItemFactory],
    selector: Gtk.SingleSelection,
) -> None:
    for attrName, listItemFactory in itemFactories.items():
        _bindOneAttribute(attrName, listItemFactory, selector)
