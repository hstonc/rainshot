"""Protocol peer for isolated tests. Never takes a desktop screenshot."""
import os
import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

DBusGMainLoop(set_as_default=True)
bus = dbus.SessionBus()
name = dbus.service.BusName("org.freedesktop.portal.Desktop", bus)
requests = []


class Request(dbus.service.Object):
    @dbus.service.signal("org.freedesktop.portal.Request", signature="ua{sv}")
    def Response(self, response, results):
        pass

    @dbus.service.method("org.freedesktop.portal.Request", in_signature="", out_signature="")
    def Close(self):
        with open(os.environ["CLOSE_MARKER"], "w") as file:
            file.write("closed")


class Portal(dbus.service.Object):
    @dbus.service.method("org.freedesktop.portal.Screenshot", in_signature="sa{sv}", out_signature="o", sender_keyword="sender")
    def Screenshot(self, parent, options, sender):
        if os.environ.get("FAKE_MODE") == "error":
            raise dbus.exceptions.DBusException("No backend", name="org.freedesktop.portal.Error.NotFound")
        token = str(options["handle_token"])
        path = "/org/freedesktop/portal/desktop/request/" + sender.lstrip(":").replace(".", "_") + "/" + token
        request = Request(bus, path)
        requests.append(request)
        if os.environ.get("FAKE_MODE") == "delayed":
            GLib.timeout_add(50, lambda: request.Response(dbus.UInt32(0), {"uri": dbus.String(os.environ["FAKE_URI"])}))
        elif os.environ.get("FAKE_MODE") != "timeout":
            # Intentionally emit before the method returns to exercise the response race.
            request.Response(dbus.UInt32(int(os.environ.get("FAKE_CODE", "0"))), {"uri": dbus.String(os.environ.get("FAKE_URI", ""))})
        return dbus.ObjectPath(path)


portal = Portal(bus, "/org/freedesktop/portal/desktop")
print("READY", flush=True)
GLib.MainLoop().run()
