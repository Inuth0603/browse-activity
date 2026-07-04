# Copyright (C) 2008, One Laptop Per Child
# Copyright (C) 2009 Simon Schampijer
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

from gi.repository import WebKit
from gi.repository import GObject
from gi.repository import Gtk
from gi.repository import Gdk
from gettext import gettext as _

from sugar4.activity.widgets import EditToolbar as BaseEditToolbar
from sugar4.graphics import iconentry
from sugar4.graphics.toolbutton import ToolButton
from sugar4.graphics import style

from browser import Browser


class EditToolbar(BaseEditToolbar):
    def __init__(self, act):
        BaseEditToolbar.__init__(self)

        self._activity = act
        self._browser = None
        self._source_id = None

        self.undo.connect('clicked', self.__undo_cb)
        self.redo.connect('clicked', self.__redo_cb)
        self.copy.connect('clicked', self.__copy_cb)
        self.paste.connect('clicked', self.__paste_cb)

        separator = Gtk.Box()
        separator.set_hexpand(True)
        self.append(separator)
        separator.show()

        search_item = Gtk.Box()
        self.search_entry = iconentry.IconEntry()

        css = f'''
        .browse-search-not-found {{
            color: {style.COLOR_BUTTON_GREY.get_css_rgba()};
        }}
        '''
        style.apply_css_to_widget(self.search_entry, css)

        self.search_entry.set_icon_from_name(iconentry.ICON_ENTRY_PRIMARY,
                                             'entry-search')
        self.search_entry.add_clear_button()
        self.search_entry.connect('activate', self.__search_entry_activate_cb)
        self.search_entry.connect('changed', self.__search_entry_changed_cb)

        width = 400
        display = Gdk.Display.get_default()
        if display is not None:
            monitors = display.get_monitors()
            # Calculate search entry width based on primary monitor geometry
            if monitors.get_n_items() > 0:
                width = int(monitors.get_item(0).get_geometry().width / 3)
        self.search_entry.set_size_request(width, -1)

        search_item.append(self.search_entry)
        self.search_entry.show()

        self.append(search_item)
        search_item.show()

        self._prev = ToolButton('go-previous-paired')
        self._prev.set_tooltip(_('Previous'))
        self._prev.props.sensitive = False
        self._prev.connect('clicked', self.__find_previous_cb)
        self.append(self._prev)
        self._prev.show()

        self._next = ToolButton('go-next-paired')
        self._next.set_tooltip(_('Next'))
        self._next.props.sensitive = False
        self._next.connect('clicked', self.__find_next_cb)
        self.append(self._next)
        self._next.show()

        tabbed_view = self._activity.get_canvas()

        GObject.idle_add(lambda: self._connect_to_browser(
            tabbed_view.props.current_browser))

        tabbed_view.connect_after('switch-page', self.__switch_page_cb)

    def __switch_page_cb(self, tabbed_view, page, page_num):
        self._connect_to_browser(tabbed_view.props.current_browser)

    def _connect_to_browser(self, browser):
        find = None
        self._browser = browser

        self._update_buttons()

        # FIXME: 'selection-changed' signal is missing in WebKit2/6 multiprocess API.
        # We must poll via timeout_add until a web extension is implemented.
        if self._source_id is not None:
            GObject.source_remove(self._source_id)
        self._source_id = \
            GObject.timeout_add(300, self.__selection_changed_cb)

        if isinstance(self._browser, Browser):
            find = self._browser.get_find_controller()
        if find is not None:
            find.connect('found-text', self.__found_text_cb)
            find.connect('failed-to-find-text', self.__failed_to_find_text_cb)

    def __selection_changed_cb(self, *args):
        self._update_buttons()
        return True

    def _update_buttons(self):
        if not self._browser or not hasattr(self._browser, 'get_editor_state'):
            self.undo.set_sensitive(False)
            self.redo.set_sensitive(False)
            self.copy.set_sensitive(False)
            self.paste.set_sensitive(False)
            return

        editor_state = self._browser.get_editor_state()
        self.undo.set_sensitive(editor_state.is_undo_available())
        self.redo.set_sensitive(editor_state.is_redo_available())
        self.copy.set_sensitive(editor_state.is_copy_available())

        clipboard = Gdk.Display.get_default().get_clipboard()
        formats = clipboard.get_formats()
        self.paste.set_sensitive(
            formats.contain_mime_type('text/plain') if formats else False)

    def __undo_cb(self, button):
        self._browser.execute_editing_command(WebKit.EDITING_COMMAND_UNDO)
        self._update_buttons()

    def __redo_cb(self, button):
        self._browser.execute_editing_command(WebKit.EDITING_COMMAND_REDO)
        self._update_buttons()

    def __copy_cb(self, button):
        self._browser.execute_editing_command(WebKit.EDITING_COMMAND_COPY)

    def __paste_cb(self, button):
        self._browser.execute_editing_command(WebKit.EDITING_COMMAND_PASTE)

    def _find_and_mark_text(self, entry):
        search_text = entry.get_text()
        controller = self._browser.get_find_controller()
        options = WebKit.FindOptions.CASE_INSENSITIVE
        options |= WebKit.FindOptions.WRAP_AROUND
        controller.search(search_text, options, (2 << 31) - 1)

    def __search_entry_activate_cb(self, entry):
        self._find_and_mark_text(entry)

    def __search_entry_changed_cb(self, entry):
        self._find_and_mark_text(entry)

    def __found_text_cb(self, controller, match_count):
        self._prev.props.sensitive = True
        self._next.props.sensitive = True
        self.search_entry.remove_css_class('browse-search-not-found')

    def __failed_to_find_text_cb(self, controller):
        self._prev.props.sensitive = False
        self._next.props.sensitive = False
        self.search_entry.add_css_class('browse-search-not-found')

    def __find_previous_cb(self, button):
        self._browser.get_find_controller().search_previous()

    def __find_next_cb(self, button):
        self._browser.get_find_controller().search_next()
