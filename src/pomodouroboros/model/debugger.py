def debug(*x: object) -> None:
    """
    Emit some messages while debugging.
    """
    if 0:
        print(*x)


if __name__ == "__main__":
    from pomodouroboros.model.storage import loadDefaultNexus
    from pomodouroboros.model.test.test_model import TestUserInterface
    from twisted.internet.task import Clock
    from time import time

    clock = Clock()
    clock.advance(time())
    ui = TestUserInterface(clock)
    nexus = loadDefaultNexus(clock.seconds(), ui.setIt)
