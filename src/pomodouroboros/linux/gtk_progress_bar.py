# installation instructions:
# sudo apt install libgirepository1.0-dev gcc libcairo2-dev pkg-config python3-dev gir1.2-gtk-4.0

# python-devel python3-gobject-devel cairo-devel cairo-gobject-devel

# deps:
# ewmh==0.1.6
# pycairo==1.26.0
# PyGObject==3.48.2
# python-xlib==0.33
# six==1.16.0

from typing import Any

from .platspec import (
    EWMH,
    Gdk,
    GdkX11,
    GLib,
    Gtk,
    RectangleInt,
    Region,
    XOpenDisplay,
)

css = Gtk.CssProvider()

# css.load_from_data("""
# button {background-image: image(cyan);}
# button:hover {background-image: image(green);}
# button:active {background-image: image(brown);}
# """)

css.load_from_data(
    """
progressbar.overlay text {
  color: yellow;
  font-weight: bold;
}
progressbar.overlay trough, progress {
  min-height: 100px;
}
progressbar.pomodoro progress {
  background-image: none;
  background-color: #0f0;
}
progressbar.pomodoro trough {
 background-image: none;
 background-color: #00f;
}
"""
)


def makeOneProgressBar(
    display: XOpenDisplay, monitor: Gdk.Monitor, ewmh: EWMH
) -> Gtk.ApplicationWindow:
    win = Gtk.ApplicationWindow(application=app, title="Should Never Focus")
    win.set_opacity(0.25)
    win.set_decorated(False)
    monitor_geom = monitor.get_geometry()
    win.set_default_size(monitor_geom.width, 100)

    prog = Gtk.ProgressBar()
    prog.add_css_class("pomodoro")
    prog.add_css_class("overlay")
    frac = 0.7

    def refraction() -> bool:
        nonlocal frac
        frac += 0.01
        frac %= 1.0
        prog.set_fraction(frac)
        return True

    to = GLib.timeout_add((1000 // 10), refraction)
    prog.set_fraction(0.7)
    win.set_child(prog)

    # we can't actually avoid getting focus, but in case the compositors ever
    # fix themselves, let's give it our best try

    win.realize()
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

    def showgeom() -> bool:
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

    GLib.timeout_add(2000, showgeom)
    return win


# When the application is launched…
def on_activate(app: Gtk.Application) -> None:
    # … create a new window…
    gdisplay = Gdk.Display.get_default()
    assert gdisplay is not None, "cannot run without a display"
    Gtk.StyleContext.add_provider_for_display(
        gdisplay, css, Gtk.STYLE_PROVIDER_PRIORITY_USER
    )

    display = XOpenDisplay()
    screen = display.screen()
    ewmh = EWMH(display, screen.root)
    bars: list[Gtk.ApplicationWindow] = []

    def remonitor() -> bool:
        print("remonitoring")
        prevbars = bars[:]
        # pygobject-stubs seems to have a bug where gdisplay.get_monitors()
        # yields Objects rather than Monitors
        monitor: Any
        for monitor in gdisplay.get_monitors():
            bars.append(makeOneProgressBar(display, monitor, ewmh))
        for prevbar in prevbars:
            prevbar.close()
        return False

    def remonitor_later(
        display: str,
        path: str,
        iface: str,
        signal: str,
        args: tuple[object, ...],
    ) -> None:
        print("remonitoring...", display)
        GLib.timeout_add(1000, remonitor)

    from pydbus import SessionBus

    bus = SessionBus()
    bus.subscribe(
        iface="org.gnome.Mutter.DisplayConfig",
        signal="MonitorsChanged",
        signal_fired=remonitor_later,
    )
    remonitor()


if __name__ == "__main__":
    # Create a new application
    app = Gtk.Application(application_id="com.example.GtkApplication")
    app.connect("activate", on_activate)

    # Run the application
    app.run(None)
