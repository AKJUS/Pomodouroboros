import os
from pathlib import Path

from encrust.api import AppDescription, SparkleData

description = AppDescription(
    bundleID="im.glyph.and.this.is.pomodouroboros",
    bundleName="Pomodouroboros",
    icnsFile=Path("icon.icns"),
    mainPythonScript=Path("mac/Pomodouroboros.pyw"),
    dataFiles=list(Path("PomodouroborosMac").glob("*.xib")),
    dockIconAtStart=False,
    sparkleData=SparkleData.withConfig(
        sparkleVersion="2.6.4",
        publicEDKey="e4lwY+RAzYj1jgwjAqq6fIQJHpZVh/O2Od9aYSpY3CI=",
        feedURL="https://www.glyph.im/apps/pomodouroboros/updates/appcast.xml",
        keychainAccount="im.glyph.and.this.is.my.sparkle.key",
        localUpdatesFolder=(
            Path.home() / "Storage" / "Sparkle" / "Pomodouroboros" / "Releases"
        ),
        remoteHost="public.glyph.im",
        remotePath="/site/www.glyph.im/apps/pomodouroboros/updates/",
    ),
).varyBundleForTesting()
