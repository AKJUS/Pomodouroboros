from __future__ import annotations

from dataclasses import dataclass
from itertools import islice

from AppKit import NSColor, NSApp
from quickmachotkey import mask, quickHotKey
from quickmachotkey.constants import cmdKey, controlKey, kVK_ANSI_P, optionKey
from quickmacapp import DockIconManager, answer
from twisted.internet.defer import Deferred

from ..model.intention import Intention
from ..model.nexus import Nexus
from ..model.util import interactionRootAsync
from ..model.intervals import Pomodoro, Break
from .multiple_choice import multipleChoiceButtons


@dataclass
class NexusHolder:
    """
    implement HasNexus protocol for L{interactionRoot}
    """

    nexus: Nexus


def registerHotKey(nexus: Nexus, background: DockIconManager) -> None:
    """
    Register the global hotkey for setting an intention from a fixed list.
    """
    holder = NexusHolder(nexus)
    active: bool = False

    @interactionRootAsync
    async def showIntentionChoice(holder: NexusHolder) -> None:
        nonlocal active
        if active:
            NSApp().activate()
            return
        active = True
        try:
            rainbow = [
                NSColor.redColor(),
                NSColor.orangeColor(),
                NSColor.yellowColor(),
                NSColor.greenColor(),
                NSColor.blueColor(),
                NSColor.systemIndigoColor(),
                NSColor.purpleColor(),
            ]
            irainbow = iter(rainbow)
            with background.noDockIcon():
                # If the current interval doesn't allow it, let's let the user
                # know the reason they can't start a pomodoro right now.
                match nexus.currentInterval:
                    case Pomodoro(intention=i):
                        await answer(
                            f"A pomodoro is already running: «{i.title}»"
                        )
                        return
                    case Break():
                        await answer(
                            "A break is currently running; take it easy."
                        )
                        return

                intention: Intention | None = await multipleChoiceButtons(
                    "Choose an intention to set for this Pomodoro:",
                    list(
                        islice(
                            (
                                (
                                    next(irainbow),
                                    intention.title,
                                    intention,
                                )
                                for intention in nexus.intentions
                                if not (
                                    intention.abandoned or intention.completed
                                )
                            ),
                            len(rainbow),
                        )
                    )
                    + [
                        # this should be the one that gets hit with "escape"?
                        (NSColor.systemGrayColor(), "Cancel", None)
                    ],
                )
                if intention is not None:
                    nexus.startPomodoro(intention)
        finally:
            active = False

    @quickHotKey(
        # FIXME: needs a 'configurator' once we have UI to change the hotkey
        # as well as somewhere to store the configuration.
        virtualKey=kVK_ANSI_P,
        modifierMask=mask(cmdKey, controlKey, optionKey),
    )
    def quickSetIntention() -> None:
        Deferred.fromCoroutine(showIntentionChoice(holder))
