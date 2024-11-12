from datetime import datetime, time
from typing import Callable
from unittest import TestCase
from zoneinfo import ZoneInfo

from datetype import DateTime, aware
from fritter.boundaries import Scheduler
from fritter.drivers.datetimes import DateTimeDriver
from fritter.drivers.memory import MemoryDriver
from fritter.scheduler import schedulerFromDriver

from ..sessions import DailySessionRule, Session, Weekday, ActiveSessionManager

PT = ZoneInfo("America/Los_Angeles")

testingRule = DailySessionRule(
    aware(time(3, 4, 5, tzinfo=PT), ZoneInfo),
    aware(time(4, 5, 6, tzinfo=PT), ZoneInfo),
    days={Weekday.tuesday, Weekday.wednesday, Weekday.friday},
)


class SessionStartEndSchedulingTests(TestCase):
    def test_observeScheduledSessions(self) -> None:
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
        asm = ActiveSessionManager.new(dateScheduler)
        asm.rules.append(testingRule)
        self.assertIs(asm._currentSession, None)
        memory.advance(desiredStart + 10 - memory.now())
        self.assertEqual(asm._currentSession, Session(start=desiredStart, end=desiredEnd, automatic=True))


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
