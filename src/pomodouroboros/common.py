"""
Cross-platform stuff that isn't really part of the model, just general UI
utility things that don't depend on anything platform specific, or a specific
version of the model (i.e. old-style .pommodel or new-style .model).
"""

import math
from typing import Protocol

from twisted.internet.defer import Deferred
from twisted.internet.interfaces import IReactorTime
from twisted.internet.task import LoopingCall


class AnimValues(Protocol):
    """
    The interesting stuff that Pomodouroboros wants to animate: the percentage
    and the alpha value.
    """

    def setPercentage(self, percentage: float) -> None: ...

    def setAlpha(self, alpha: float) -> None: ...

    def setReticleText(self, newText: str) -> None: ...


def animatePct(
    values: AnimValues,
    clock: IReactorTime,
    percentageElapsed: float,
    previousPercentageElapsed: float,
    pulseTime: float,
    baseAlphaValue: float,
    alphaVariance: float,
) -> Deferred[None]:
    if percentageElapsed < previousPercentageElapsed:
        previousPercentageElapsed = 0
    elapsedDelta = percentageElapsed - previousPercentageElapsed
    startTime = clock.seconds()

    def updateSome() -> None:
        now = clock.seconds()

        percentDone = (now - startTime) / pulseTime
        easedEven = math.sin((percentDone * math.pi))
        easedUp = math.sin((percentDone * math.pi) / 2.0)
        values.setPercentage(
            previousPercentageElapsed + (easedUp * elapsedDelta)
        )
        if percentDone >= 1.0:
            alphaValue = baseAlphaValue
            lc.stop()
        else:
            alphaValue = (easedEven * alphaVariance) + baseAlphaValue
        values.setAlpha(alphaValue)

    lc = LoopingCall(updateSome)
    return lc.start(1.0 / 30.0).addCallback(lambda ignored: None)
