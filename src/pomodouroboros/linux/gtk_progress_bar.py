# installation instructions:
# sudo apt install libgirepository1.0-dev gcc libcairo2-dev pkg-config python3-dev gir1.2-gtk-4.0

# python-devel python3-gobject-devel cairo-devel cairo-gobject-devel

# deps:
# ewmh==0.1.6
# pycairo==1.26.0
# PyGObject==3.48.2
# python-xlib==0.33
# six==1.16.0

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..common import AnimValues
from .platspec import (
    EWMH,
    Gdk,
    GdkX11,
    GLib,
    Gtk,
    RectangleInt,
    Region,
    XDisplay,
)

css = Gtk.CssProvider()

# css.load_from_data("""
# button {background-image: image(cyan);}
# button:hover {background-image: image(green);}
# button:active {background-image: image(brown);}
# """)

css.load_from_data(
    (Path(__file__).parent / "progbar.css").read_text(),
)

BASE_CLASSES = ["pomodoro", "overlay"]


def makeOneProgressBar(
    app: Gtk.Application,
    display: XDisplay,
    monitor: GdkX11.X11Monitor,
    ewmh: EWMH,
    cssClasses: list[str],
) -> tuple[Gtk.ProgressBar, Gtk.ApplicationWindow]:
    win = Gtk.ApplicationWindow(application=app, title="Should Never Focus")
    win.set_opacity(0.25)
    win.set_decorated(False)

    # note: deprecated, but there's no alternative; the general
    # Gdk.Monitor.get_workarea() was removed in Gdk4, the X11 one is deprecated
    # with no replacement.
    monitor_geom = monitor.get_workarea()

    win.set_default_size(monitor_geom.width, 100)

    prog = Gtk.ProgressBar()
    prog.set_css_classes(cssClasses)

    win.set_child(prog)

    # we can't actually avoid getting focus, but in case the compositors ever
    # fix themselves, let's give it our best try

    win.set_can_focus(False)
    win.set_focusable(False)
    win.set_focus_on_click(False)
    win.set_can_target(False)
    win.set_auto_startup_notification(False)
    win.set_receives_default(False)
    win.realize()
    gdk_x11_win = win.get_surface()
    assert isinstance(
        gdk_x11_win, GdkX11.X11Surface
    ), "only the x11 backend supports this"
    gdk_x11_win.set_input_region(Region(rectangle=RectangleInt(0, 0, 0, 0)))

    # cribbed from the (deprecated, removed) implementation of
    # gdk_x11_window_set_focus_on_map ( see
    # https://github.com/GNOME/gtk/blob/v3.22.20/gdk/x11/gdkwindow-x11.c#L3513
    # ) this prevents the window from stealing focus from the focused wayland
    # application
    gdk_x11_win.set_user_time(0)

    win.set_visible(True)
    xid = gdk_x11_win.get_xid()
    xlibwin = display.create_resource_object("window", xid)

    # Always on top
    winx, winy, winw, winh = (
        monitor_geom.x,
        monitor_geom.y + (monitor_geom.height - 150),
        monitor_geom.width,
        150,
    )
    print(f"moving to {winx} {winy} ({winw} {winh})")
    ewmh.setMoveResizeWindow(xlibwin, x=winx, y=winy, w=winw, h=winh)
    ewmh.setWmState(xlibwin, 1, "_NET_WM_STATE_ABOVE")

    # Draw even over the task bar (this breaks stuff)
    # ewmh.setWmState(xlibwin, 1, '_NET_WM_STATE_FULLSCREEN')

    # Don't show the icon in the task bar
    ewmh.setWmState(xlibwin, 1, "_NET_WM_STATE_SKIP_TASKBAR")
    ewmh.setWmState(xlibwin, 1, "_NET_WM_STATE_SKIP_PAGER")
    display.flush()

    def reshuffle_geometry() -> bool:
        if not win.is_visible():
            print("window hidden")
            return False
        geom = xlibwin.get_geometry()
        xdelta = winx - geom.x
        print(f"xdelta: {xdelta}")
        if xdelta:
            ewmh.setMoveResizeWindow(
                xlibwin, x=winx + xdelta, y=winy, w=winw - xdelta, h=winh
            )
            return True
        else:
            print("xdelta resolved")
            return False

    GLib.timeout_add(2000, reshuffle_geometry)
    return (prog, win)


@dataclass
class MultiBar:
    # required parameters
    _ewmh: EWMH
    _gtkApp: Gtk.Application
    _gdkDisplay: Gdk.Display
    _xDisplay: XDisplay

    # internal state
    _bars: list[tuple[Gtk.ProgressBar, Gtk.ApplicationWindow]] = field(
        default_factory=list
    )
    _percentage: float = 0.0
    _alpha: float = 1.0
    _text: str = ""
    _cssClasses: list[str] = field(default_factory=lambda: BASE_CLASSES[:])

    def setCssClasses(self, cssClasses: list[str]) -> None:
        self._cssClasses = cssClasses
        for bar, win in self._bars:
            bar.set_css_classes(cssClasses)

    def setStyle(self, cssClass: str)-> None:
        self.setCssClasses(BASE_CLASSES + [cssClass])

    def setPercentage(self, percentage: float) -> None:
        self._percentage = percentage
        for bar, win in self._bars:
            bar.set_fraction(percentage)

    def setAlpha(self, alpha: float) -> None:
        """
        Placeholder: should set the alpha blending of the windows.
        """
        for bar, win in self._bars:
            win.set_opacity(alpha)

    def setReticleText(self, newText: str) -> None:
        self._text = newText
        if newText:
            for bar, win in self._bars:
                bar.set_show_text(True)
                bar.set_text(newText)
        else:
            for bar, win in self._bars:
                bar.set_show_text(False)

    def remonitor(self) -> bool:
        prevbars = self._bars[:]
        self._bars[:] = []
        # pygobject-stubs seems to have a bug where gdisplay.get_monitors()
        # yields Objects rather than Monitors
        monitor: Any
        for monitor in self._gdkDisplay.get_monitors():
            self._bars.append(
                makeOneProgressBar(
                    self._gtkApp,
                    self._xDisplay,
                    monitor,
                    self._ewmh,
                    self._cssClasses,
                )
            )
        for prevbar, prevwin in prevbars:
            prevwin.close()
        return False

    # When the application is launched…
    @classmethod
    def create(cls, app: Gtk.Application) -> MultiBar:
        # … create a new window…
        gdisplay = Gdk.Display.get_default()
        assert gdisplay is not None, "cannot run without a display"
        Gtk.StyleContext.add_provider_for_display(
            gdisplay, css, Gtk.STYLE_PROVIDER_PRIORITY_USER
        )

        xdisplay = XDisplay()
        xscreen = xdisplay.screen()
        self = cls(
            EWMH(xdisplay, xscreen.root),
            app,
            gdisplay,
            xdisplay,
        )

        def remonitor_later(
            display: str,
            path: str,
            iface: str,
            signal: str,
            args: tuple[object, ...],
        ) -> None:
            print("remonitoring...", display)
            GLib.timeout_add(1000, self.remonitor)

        from pydbus import SessionBus

        bus = SessionBus()
        bus.subscribe(
            iface="org.gnome.Mutter.DisplayConfig",
            signal="MonitorsChanged",
            signal_fired=remonitor_later,
        )
        self.remonitor()
        return self
