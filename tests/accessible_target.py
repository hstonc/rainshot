import gi
import json
import os
gi.require_version('Gtk','3.0')
from gi.repository import Gtk, GLib
window = Gtk.Window(title='rainshot AT-SPI test')
window.set_default_size(500,250); window.move(2050,200)
box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=16)
box.set_border_width(24)
button = Gtk.Button(label='rainshot accessible test button')
box.pack_start(Gtk.Label(label='Synthetic element selection test'),False,False,0)
box.pack_start(button,False,False,0)
window.add(box); window.connect('destroy',Gtk.main_quit); window.show_all()
def ready():
    origin = window.get_window().get_origin()
    alloc = button.get_allocation()
    # Button bounds are relative to the top-level client in this simple layout.
    print(json.dumps({'pid':os.getpid(),'x':origin.x+alloc.x,'y':origin.y+alloc.y,'width':alloc.width,'height':alloc.height}),flush=True)
    return False
GLib.timeout_add(800,ready)
Gtk.main()
