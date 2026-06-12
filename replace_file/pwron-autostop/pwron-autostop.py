#!/usr/bin/env python3
"""arkos4clone: power off after a charger-triggered boot.

The RK817 PMIC powers the device on when a charger is plugged in, and
neither u-boot (charge-animation thresholds are pass-through) nor this
4.4 kernel (no power-on-reason in dmesg) lets us veto or identify that
boot. So we approximate: if the charger is connected at boot and the
user touches no control for WINDOW seconds, treat the boot as
plug-in-triggered and power off (the device keeps charging while off).
Any key/button/stick input cancels the shutdown.

Runs once per boot via pwron-autostop.service. Log: /var/local/pwron-autostop.log
"""

import os
import select
import subprocess
import sys
import time

WINDOW_SECONDS = 300
AC_ONLINE = "/sys/class/power_supply/ac/online"
LOG = "/var/local/pwron-autostop.log"

def log(msg):
    line = "%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        with open(LOG, "a") as f:
            f.write(line)
    except OSError:
        pass

def charger_online():
    try:
        with open(AC_ONLINE) as f:
            return f.read().strip() == "1"
    except OSError:
        return False

def main():
    if not charger_online():
        log("boot: charger offline -> normal boot, exiting")
        return 0

    try:
        import evdev
    except ImportError:
        log("boot: python-evdev missing, cannot watch input; exiting")
        return 0

    devices = []
    for path in evdev.list_devices():
        try:
            devices.append(evdev.InputDevice(path))
        except OSError:
            pass
    if not devices:
        log("boot: no input devices found; exiting without shutdown")
        return 0

    log("boot: charger online -> watching %d input devices for %ds"
        % (len(devices), WINDOW_SECONDS))

    fd_map = {d.fd: d for d in devices}
    deadline = time.monotonic() + WINDOW_SECONDS
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        r, _, _ = select.select(list(fd_map), [], [], remaining)
        for fd in r:
            try:
                for ev in fd_map[fd].read():
                    # Button/key presses only: analog sticks idle-jitter ABS
                    # events, which would silently cancel every shutdown.
                    if ev.type == evdev.ecodes.EV_KEY:
                        log("input on %s -> user present, no shutdown"
                            % fd_map[fd].name)
                        return 0
            except OSError:
                fd_map.pop(fd, None)
                if not fd_map:
                    log("all input devices vanished; exiting without shutdown")
                    return 0

    log("no input within %ds and charger online -> powering off" % WINDOW_SECONDS)
    subprocess.call(["systemctl", "poweroff"])
    return 0

if __name__ == "__main__":
    sys.exit(main())
