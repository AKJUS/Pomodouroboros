"""
Common UI logic for old-style L{.pommodel} objects.
"""

from __future__ import annotations
from typing import Iterable

from pomodouroboros.pommodel import IntentionSuccess, Pomodoro

from .pommodel import Day


def poms2Dicts(
    day: Day, now: float, poms: Iterable[Pomodoro]
) -> Iterable[dict[str, object]]:
    """
    Convert a set of pomodoros to pretty-printed dictionaries for display with
    respect to a given POSIX epoch timestamp.
    """
    # TODO: would this be useful for other frontends? Is it really
    # mac-specific?
    hasCurrent = False
    for i, pomOrBreak in enumerate(poms, start=1):
        # todo: bind editability to one of these attributes so we can
        # control it on a per-row basis
        desc = (
            pomOrBreak.intention.description or ""
            if pomOrBreak.intention is not None
            else ""
        )
        canChange = (now < pomOrBreak.startTimestamp) or (
            (pomOrBreak.intention is None)
            and (now < (pomOrBreak.startTimestamp + day.intentionGracePeriod))
        )
        if not canChange:
            desc = "🔒 " + desc

        isCurrent = False
        if not hasCurrent:
            if now < pomOrBreak.endTimestamp:
                hasCurrent = isCurrent = True

        yield {
            "index": f"{i}{'→' if isCurrent else ''}",
            "startTime": pomOrBreak.startTime.time().isoformat(
                timespec="minutes"
            ),
            "endTime": pomOrBreak.endTime.time().isoformat(timespec="minutes"),
            "description": desc,
            "success": (
                ("❌" if now > pomOrBreak.endTimestamp else "…")
                if pomOrBreak.intention is None
                else {
                    None: "…" if now < pomOrBreak.startTimestamp else "📝",
                    IntentionSuccess.Achieved: "✅",
                    IntentionSuccess.Focused: "🤔",
                    IntentionSuccess.Distracted: "🦋",
                    IntentionSuccess.NeverEvaluated: "👋",
                    True: "✅",
                    False: "🦋",
                }[pomOrBreak.intention.wasSuccessful]
            ),
            "pom": pomOrBreak,
            "canChange": canChange,
        }
