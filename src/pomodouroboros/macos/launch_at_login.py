from ServiceManagement import (
    SMAppService,
    SMAppServiceStatusEnabled,
    SMAppServiceStatusRequiresApproval,
)

from Foundation import NSObject, NSLog
from AppKit import (
    NSMenuItem,
    NSControlStateValueOn,
    NSControlStateValueOff,
)

from objc import IBAction, super


class LoginLaunchObject(NSObject):

    def init(self) -> None:
        super().init()
        self.myAppService = SMAppService.mainAppService()

    def wantsToLaunchAtLogin(self) -> bool:
        return self.myAppService.status() in {
            SMAppServiceStatusEnabled,
            SMAppServiceStatusRequiresApproval,
        }

    @IBAction
    def toggleLaunchAtLogin_(self, sender: NSObject) -> None:
        nowOn = self.wantsToLaunchAtLogin()
        if nowOn:
            didUnregister, err = self.myAppService.unregisterAndReturnError_(
                None
            )
            NSLog(
                "unregistered app service launch; got %@ %@",
                didUnregister,
                err,
            )
            nowOn = not didUnregister
        else:
            didRegister, err = self.myAppService.registerAndReturnError_(None)
            NSLog("registered app service launch; got %@ %@", didRegister, err)
            nowOn = didRegister

    def validateMenuItem_(self, item: NSMenuItem) -> bool:
        item.setState_(
            NSControlStateValueOn
            if self.wantsToLaunchAtLogin()
            else NSControlStateValueOff
        )
        return True
