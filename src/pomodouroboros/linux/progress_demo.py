
from itertools import cycle
from pathlib import Path

from twisted.internet.defer import Deferred
from twisted.internet.task import deferLater

from ..common import animatePct
from .gtk_progress_bar import MultiBar
from .platspec import Gtk

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
    def _on_theme_name_changed(settings, gparam):
        print("Theme name:", settings.get_property("gtk-theme-name"))
    Gtk.Settings.get_default().connect("notify::gtk-theme-name", _on_theme_name_changed)
    def _on_dark_changed(settings, gparam):
        print("dark:", settings.get_property("gtk-application-prefer-dark-theme"))
    Gtk.Settings.get_default().connect("notify::gtk-application-prefer-dark-theme", _on_dark_changed)

    def makeBar(app: Gtk.Application) -> None:
        bar = MultiBar.create(app)
        stuff = Gtk.Builder.new_from_file(str(Path(__file__).parent/"linuxlegacypom.ui"))
        stuff.get_object("my-window").present()

        texts = cycle([
            "let's start with this text",
            "then move on to this text",
            "then hide the text",
            "",
            "",
            "",
        ])

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
