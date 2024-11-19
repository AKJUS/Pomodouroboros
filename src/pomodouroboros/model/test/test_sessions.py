from contextlib import contextmanager
from datetime import datetime, time
from typing import Callable, Iterator
from unittest import TestCase
from zoneinfo import ZoneInfo

from datetype import DateTime, aware
from fritter.boundaries import Scheduler
from fritter.drivers.datetimes import DateTimeDriver
from fritter.drivers.memory import MemoryDriver
from fritter.scheduler import schedulerFromDriver

from ..sessions import ActiveSessionManager, DailySessionRule, Session, Weekday

PT = ZoneInfo("America/Los_Angeles")

testingRule = DailySessionRule(
    aware(time(3, 4, 5, tzinfo=PT), ZoneInfo),
    aware(time(4, 5, 6, tzinfo=PT), ZoneInfo),
    days={Weekday.tuesday, Weekday.wednesday, Weekday.friday},
)


class SessionStartEndSchedulingTests(TestCase):
    def test_observeScheduledSession(self) -> None:
        dateScheduler: Scheduler[
            DateTime[ZoneInfo], Callable[[], None], int
        ] = schedulerFromDriver(
            DateTimeDriver(memory := MemoryDriver(), zone=PT)
        )
        desiredStart = aware(
            datetime(2023, 11, 7, 3, 4, 5, tzinfo=PT), ZoneInfo
        ).timestamp()
        desiredEnd = aware(
            datetime(2023, 11, 7, 4, 5, 6, tzinfo=PT), ZoneInfo
        ).timestamp()
        # start at a reasonable time that is not in the 1970s
        memory.advance(
            aware(datetime(2023, 11, 7, 2, tzinfo=PT), ZoneInfo).timestamp()
            - memory.now()
        )
        sessionChanges = []
        extraneousChanges = []

        class Observe:
            @contextmanager
            def added(self, key: object, new: object) -> Iterator[None]:
                yield
                extraneousChanges.append(("add", key, new))

            @contextmanager
            def removed(self, key: object, old: object) -> Iterator[None]:
                yield
                extraneousChanges.append(("remove", key, old))

            @contextmanager
            def changed(
                self, key: object, old: object, new: object
            ) -> Iterator[None]:
                yield
                sessionChanges.append((key, old, new))

        asm = ActiveSessionManager.new(Observe(), dateScheduler)
        asm.rules.append(testingRule)
        self.assertIs(asm.activeSession, None)
        memory.advance(desiredStart + 10 - memory.now())
        self.assertEqual(
            asm.activeSession,
            Session(start=desiredStart, end=desiredEnd, automatic=True),
        )
        memory.advance(desiredEnd + 15 - memory.now())
        self.assertEqual(asm.activeSession, None)
        expectedSession = Session(
            start=desiredStart, end=desiredEnd, automatic=True
        )
        self.assertEqual(
            sessionChanges,
            [
                ("activeSession", None, expectedSession),
                ("activeSession", expectedSession, None),
            ],
        )
        expectedRule = DailySessionRule(
            dailyStart=aware(
                time(3, 4, 5, tzinfo=ZoneInfo(key="America/Los_Angeles")),
                ZoneInfo,
            ),
            dailyEnd=aware(
                time(4, 5, 6, tzinfo=ZoneInfo(key="America/Los_Angeles")),
                ZoneInfo,
            ),
            days={Weekday.tuesday, Weekday.wednesday, Weekday.friday},
        )
        self.assertEqual(
            extraneousChanges,
            [
                (
                    "add",
                    "rules",
                    [expectedRule],
                )
            ],
        )


class SessionGenerationTests(TestCase):
    def test_sameDay(self) -> None:
        desiredStart = aware(
            datetime(2023, 11, 7, 3, 4, 5, tzinfo=PT), ZoneInfo
        ).timestamp()
        desiredEnd = aware(
            datetime(2023, 11, 7, 4, 5, 6, tzinfo=PT), ZoneInfo
        ).timestamp()
        self.assertEqual(
            testingRule.nextAutomaticSession(
                aware(datetime(2023, 11, 7, 2, tzinfo=PT), ZoneInfo)
            ),
            Session(desiredStart, desiredEnd, True),
        )

    def test_nextDay(self) -> None:
        desiredStart = aware(
            datetime(2023, 11, 8, 3, 4, 5, tzinfo=PT), ZoneInfo
        ).timestamp()
        desiredEnd = aware(
            datetime(2023, 11, 8, 4, 5, 6, tzinfo=PT), ZoneInfo
        ).timestamp()
        self.assertEqual(
            testingRule.nextAutomaticSession(
                aware(datetime(2023, 11, 7, 8, tzinfo=PT), ZoneInfo)
            ),
            Session(desiredStart, desiredEnd, True),
        )

    def test_skipDay(self) -> None:
        desiredStart = aware(
            datetime(2023, 11, 10, 3, 4, 5, tzinfo=PT), ZoneInfo
        ).timestamp()
        desiredEnd = aware(
            datetime(2023, 11, 10, 4, 5, 6, tzinfo=PT), ZoneInfo
        ).timestamp()
        self.assertEqual(
            testingRule.nextAutomaticSession(
                aware(datetime(2023, 11, 8, 8, tzinfo=PT), ZoneInfo)
            ),
            Session(desiredStart, desiredEnd, True),
        )

    def test_noDays(self) -> None:
        noDaysRule = DailySessionRule(
            aware(time(3, 4, 5, tzinfo=PT), ZoneInfo),
            aware(time(4, 5, 6, tzinfo=PT), ZoneInfo),
            days=set(),
        )
        self.assertIs(
            noDaysRule.nextAutomaticSession(
                aware(datetime(2023, 11, 8, 8, tzinfo=PT), ZoneInfo)
            ),
            None,
        )
