"""
Platform-specific linux imports, isolated to their own file so we can have
custom type-checking configuration as necessary.
"""

# Load Gtk
import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib

gi.require_version("Gdk", "4.0")
from gi.repository import Gdk

Gdk.set_allowed_backends("x11")
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk
from gi.repository import GdkX11  # type:ignore

from Xlib.display import Display as XOpenDisplay
from ewmh import EWMH  # type:ignore

from cairo import Region, RectangleInt


__all__ = [
    "GLib",
    "Gdk",
    "Gtk",
    "GdkX11",
    "XOpenDisplay",
    "Region",
    "RectangleInt",
]
