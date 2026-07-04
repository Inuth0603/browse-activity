# Copyright (C) 2006, Red Hat, Inc.
# Copyright (C) 2011, One Laptop Per Child
# Copyright (C) 2009, Tomeu Vizoso, Simon Schampijer
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

from gi.repository import GObject
from gi.repository import Gtk
from gi.repository import Gdk

from sugar4.graphics.icon import Icon, EventIcon
from sugar4.graphics.tray import HTray
from sugar4.graphics import style
from sugar4.graphics.xocolor import XoColor


class TabAdd(Gtk.Box):
    __gtype_name__ = 'BrowseTabAdd'

    tab_added = GObject.Signal('tab-added', arg_types=[object])

    def __init__(self):
        Gtk.Box.__init__(self, orientation=Gtk.Orientation.HORIZONTAL)

        add_tab_icon = Icon(icon_name='add')
        button = Gtk.Button()
        drop_target = Gtk.DropTarget.new(
            GObject.TYPE_STRING, Gdk.DragAction.COPY)
        drop_target.connect('drop', self.__on_drop)
        button.add_controller(drop_target)
        button.set_has_frame(False)
        button.set_focus_on_click(False)
        icon_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        icon_box.append(add_tab_icon)
        button.set_child(icon_box)
        button.connect('clicked', self.__button_clicked_cb)
        button.set_name('browse-tab-add')
        button.set_hexpand(True)
        self.append(button)

    def __on_drop(self, target, value, x, y):
        if isinstance(value, str):
            for uri in value.splitlines():
                uri = uri.strip()
                if uri:
                    self.tab_added.emit(uri)
            return True
        return False

    def __button_clicked_cb(self, button):
        self.tab_added.emit(None)


class BrowserNotebook(Gtk.Notebook):
    """Handle an extra tab at the end with an Add Tab button."""
    __gtype_name__ = 'BrowseNotebook'

    def __init__(self):
        super().__init__()

        tab_add = TabAdd()
        tab_add.connect('tab-added', self.on_add_tab)
        self.set_action_widget(tab_add, Gtk.PackType.END)

    def on_add_tab(self, obj, uri):
        raise NotImplementedError("implement this in the subclass")


class TitledTray(Gtk.Box):
    '''
    This is a tray that has a title bar.  The title bar has buttons.

    Args:
        title (str): title of the tray

    Attributes:
        tray (HTray): The underlying horizontal tray widget for holding items.
    '''

    def __init__(self, title):
        Gtk.Box.__init__(self, orientation=Gtk.Orientation.VERTICAL)

        self._top_event_box = Gtk.Box()
        click_gesture = Gtk.GestureClick.new()
        click_gesture.connect('released', self.__top_event_box_release_cb)
        self._top_event_box.add_controller(click_gesture)
        self.append(self._top_event_box)

        self._top_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                                halign=Gtk.Align.CENTER,
                                hexpand=True)
        self._top_bar.add_css_class('TitledTray-top-bar')

        # Inject scoped CSS using toolkit helper (uses PRIORITY_APPLICATION
        # instead of PRIORITY_USER).
        # Silently swallows CSS parsing errors per toolkit helper design, but
        # cleanly scopes to widget.
        css = f"""
        .TitledTray-top-bar {{
            color: white;
            background: {style.COLOR_BUTTON_GREY.get_css_rgba()};
            min-height: {int((style.GRID_CELL_SIZE * 2) / 5)}px;
        }}
        .TitledTray-top-bar label {{
            color: white;
        }}
        """
        style.apply_css_to_widget(self._top_bar, css)
        # NOTE: CSS .TitledTray-top-bar min-height is 2/5 of GRID_CELL_SIZE,
        # but this set_size_request uses 3/5. The larger value here takes
        # precedence for layout to maintain the correct visual proportions.
        self._top_bar.set_size_request(-1, int((style.GRID_CELL_SIZE * 3) / 5))
        self._top_event_box.append(self._top_bar)

        self._title = Gtk.Label(label=title)
        self._top_bar.append(self._title)

        self._hide = self.add_button('go-down', 'Hide')
        self._show = self.add_button('go-up', 'Show')
        self._show.hide()

        self._revealer = Gtk.Revealer(reveal_child=True)
        self.append(self._revealer)
        self.tray = HTray()
        self._revealer.set_child(self.tray)

    def __top_event_box_release_cb(self, gesture, n_press, x, y):
        if 0 < x < self._top_event_box.get_width(
        ) and 0 < y < self._top_event_box.get_height():
            self.toggle_expanded()

    def toggle_expanded(self):
        if self._revealer.props.reveal_child:
            self._revealer.props.reveal_child = False
            self._hide.hide()
            self._show.show()
        else:
            self._revealer.props.reveal_child = True
            self._hide.show()
            self._show.hide()

    def add_button(self, icon_name, description, clicked_cb=None):
        icon = EventIcon(icon_name=icon_name,
                         pixel_size=int((style.GRID_CELL_SIZE * 2) / 5),
                         xo_color=XoColor('#ffffff,#ffffff'))
        icon.set_tooltip(description)
        self._top_bar.append(icon)

        if clicked_cb:
            icon.connect('clicked', lambda icon: clicked_cb(icon))
        return icon
