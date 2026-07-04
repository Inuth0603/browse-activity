# Copyright (C) 2008, One Laptop Per Child
# Copyright (C) 2009, Tomeu Vizoso, Simon Schampijer
# Copyright (C) 2015, Sam Parkinson
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

import logging
import os
import tempfile
import urllib.request
import urllib.error

from gettext import gettext as _

from gi.repository import Gtk
from gi.repository import Gdk
from gi.repository import GLib

from sugar4.graphics.palette import Palette, Invoker
from sugar4.graphics.palettemenu import PaletteMenuItem
from sugar4.graphics.palettemenu import PaletteMenuItemSeparator
from sugar4 import profile


class ContentInvoker(Invoker):
    def __init__(self, browser):
        Invoker.__init__(self)
        self._position_hint = self.AT_CURSOR
        self._browser = browser
        self.attach(self._browser)
        self._browser.connect('context-menu', self.__context_menu_cb)
        self._long_press = Gtk.GestureLongPress.new()
        self._long_press.connect('pressed', self.__long_pressed_cb)
        self._browser.add_controller(self._long_press)

    def __long_pressed_cb(self, gesture, x, y):
        # TODO: The synthetic DOM dispatch is untrusted (isTrusted = false)
        # and fails to trigger WebKit's native hit testing correctly.
        # This requires replacing with a custom JS hit-test and duck-typed
        # HitTestResult, but implementation is deferred until real touch
        # hardware QA is available to verify.

        # Trigger a context menu at the given coordinates using JavaScript.
        js = f"""
            var element = document.elementFromPoint({x}, {y});
            if (element) {{
                var e = new MouseEvent('contextmenu', {{
                    bubbles: true,
                    cancelable: true,
                    view: window,
                    clientX: {x},
                    clientY: {y}
                }});
                element.dispatchEvent(e);
            }}
        """
        self._browser.evaluate_javascript(js, -1, None, None, None, None, None)

    def get_default_position(self):
        return self.AT_CURSOR

    def __context_menu_cb(self, webview, context_menu, hit_test):
        self.palette = BrowsePalette(self._browser, hit_test)
        self.notify_right_click()

        # Don't show the default menu
        return True


class BrowsePalette(Palette):
    def __init__(self, browser, hit):
        Palette.__init__(self)
        self._browser = browser
        self._hit = hit

        self._browser.evaluate_javascript('''
            (function () {
                if (window.getSelection) {
                    return window.getSelection().toString();
                } else if (document.selection &&
                           document.selection.type != "Control") {
                    return document.selection.createRange().text;
                }
                return '';
            })()''', -1, None, None, None, self.__after_get_text_cb, None)

    def __after_get_text_cb(self, browser, async_result, user_data):
        try:
            js_result = browser.evaluate_javascript_finish(async_result)
            if hasattr(js_result, 'get_js_value'):
                js_value = js_result.get_js_value()
            else:
                js_value = js_result
            self._all_text = js_value.to_string()
        except Exception as e:
            logging.error('Error getting selection text: %s', e)
            self._all_text = ''

        self._link_text = self._hit.props.link_label \
            or self._hit.props.link_title

        self._title = self._link_text or self._all_text
        self._url = self._hit.props.link_uri or self._hit.props.image_uri \
            or self._hit.props.media_uri
        self._image_url = self._hit.props.image_uri \
            or self._hit.props.media_uri

        if self._title not in (None, ''):
            self.props.primary_text = GLib.markup_escape_text(self._title)
            if self._url is not None:
                self.props.secondary_text = GLib.markup_escape_text(self._url)
        else:
            if self._url is not None:
                self.props.primary_text = GLib.markup_escape_text(self._url)

        if not self._all_text and not self._url:
            self.popdown(immediate=True)
            return  # Nothing to see here!

        menu_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(menu_box)
        self._content.set_margin_start(1)
        self._content.set_margin_end(1)
        self._content.set_margin_top(1)
        self._content.set_margin_bottom(1)

        first_section_added = False
        if self._hit.context_is_link():
            first_section_added = True

            menu_item = PaletteMenuItem(_('Follow link'), 'browse-follow-link')
            menu_item.connect('clicked', self.__follow_activate_cb)
            menu_box.append(menu_item)

            menu_item = PaletteMenuItem(_('Follow link in new tab'),
                                        'browse-follow-link-new-tab')
            menu_item.connect('clicked', self.__follow_activate_cb, True)
            menu_box.append(menu_item)

            # Add "keep link" only if it is not an image.  "Keep
            # image" will be shown in that case.
            if not self._hit.context_is_image():
                menu_item = PaletteMenuItem(_('Keep link'), 'document-save')
                menu_item.icon.props.xo_color = profile.get_color()
                menu_item.connect('clicked', self.__download_activate_cb)
                menu_box.append(menu_item)

            menu_item = PaletteMenuItem(_('Copy link'), 'edit-copy')
            menu_item.icon.props.xo_color = profile.get_color()
            menu_item.connect('clicked', self.__copy_cb, self._url)
            menu_box.append(menu_item)

            if self._link_text:
                menu_item = PaletteMenuItem(_('Copy link text'), 'edit-copy')
                menu_item.icon.props.xo_color = profile.get_color()
                menu_item.connect('clicked', self.__copy_cb, self._link_text)
                menu_box.append(menu_item)

        if self._hit.context_is_image():
            if not first_section_added:
                first_section_added = True
            else:
                separator = PaletteMenuItemSeparator()
                menu_box.append(separator)

            menu_item = PaletteMenuItem(_('Copy image'), 'edit-copy')
            menu_item.icon.props.xo_color = profile.get_color()
            menu_item.connect('clicked', self.__copy_image_activate_cb)
            menu_box.append(menu_item)

            menu_item = PaletteMenuItem(_('Keep image'), 'document-save')
            menu_item.icon.props.xo_color = profile.get_color()
            menu_item.connect('clicked', self.__download_activate_cb,
                              self._image_url)
            menu_box.append(menu_item)

        if self._hit.context_is_selection() and self._all_text:
            if not first_section_added:
                first_section_added = True
            else:
                separator = PaletteMenuItemSeparator()
                menu_box.append(separator)

            menu_item = PaletteMenuItem(_('Copy text'), 'edit-copy')
            menu_item.icon.props.xo_color = profile.get_color()
            menu_item.connect('clicked', self.__copy_cb, self._all_text)
            menu_box.append(menu_item)

    def __follow_activate_cb(self, menu_item, new_tab=False):
        if new_tab:
            self._browser.open_new_tab(self._url)
        else:
            self._browser.load_uri(self._url)
            self._browser.grab_focus()

    def __download_activate_cb(self, menu_item, url=None):
        self._browser.download_uri(url or self._url)

    def __copy_image_activate_cb(self, menu_item):
        # Download the image
        temp_file_name = None

        try:
            with tempfile.NamedTemporaryFile(delete=False) as temp_file:
                temp_file_name = temp_file.name

                user_agent = self._browser.get_settings().props.user_agent
                req = urllib.request.Request(self._image_url)
                req.add_header('User-Agent', user_agent)
                data = urllib.request.urlopen(req).read()

                temp_file.write(data)

            # Read image into a texture and place it on the clipboard,
            # ensuring proper error handling and cleanup.
            texture = Gdk.Texture.new_from_filename(temp_file_name)
            clipboard = Gdk.Display.get_default().get_clipboard()
            clipboard.set_content(Gdk.ContentProvider.new_for_value(texture))
        except urllib.error.URLError as e:
            logging.error('Network error copying image to clipboard: %s', e)
        except GLib.Error as e:
            logging.error(
                'Failed to load image for clipboard (GLib Error): %s', e)
        except Exception as e:
            logging.error('Error copying image to clipboard: %s', e)
        finally:
            if temp_file_name and os.path.exists(temp_file_name):
                os.unlink(temp_file_name)

    def __copy_cb(self, menu_item, text):
        clipboard = Gdk.Display.get_default().get_clipboard()
        clipboard.set_content(Gdk.ContentProvider.new_for_value(text))
