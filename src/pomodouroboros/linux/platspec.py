"""
Platform-specific linux imports, isolated to their own file so we can have
custom type-checking configuration as necessary.
"""

# Load Gtk
import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib
from gi.repository import GObject
from gi.repository import Gio


gi.require_version("Gdk", "4.0")
from gi.repository import Gdk

Gdk.set_allowed_backends("x11")
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk
from gi.repository import GdkX11  # type:ignore

from Xlib.display import Display as XOpenDisplay
from ewmh import EWMH  # type:ignore

# sometimes cairo is installed for development, it carries its own types, but
# it also has a bunch of C code and C dependencies and we don't want to make it
# required for CI.

# mypy: no-warn-unused-ignores
from cairo import Region, RectangleInt  # type:ignore


__all__ = [
    "GObject",
    "GLib",
    "Gio",
    "Gdk",
    "Gtk",
    "GdkX11",
    "XOpenDisplay",
    "Region",
    "RectangleInt",
]
