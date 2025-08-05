from itertools import cycle

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

    def makeBar(app: Gtk.Application) -> None:
        bar = MultiBar.create(app)
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
