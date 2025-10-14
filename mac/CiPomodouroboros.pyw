from twisted.scripts.trial import run

if __name__ == "__main__":
    from sys import argv
    argv[1:] = "pomodouroboros.macos.test"
    run()
