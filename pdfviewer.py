# Copyright (C) 2012, One Laptop Per Child
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

import os
import logging
from gettext import gettext as _

from gi.repository import GObject
from gi.repository import Gtk
from gi.repository import GLib
from gi.repository import WebKit

from sugar4.graphics.toolbarbox import ToolbarBox
from sugar4.graphics.toolbutton import ToolButton
from sugar4.graphics.toggletoolbutton import ToggleToolButton
from sugar4.graphics.icon import Icon
from sugar4.graphics import style
from sugar4.datastore import datastore
from sugar4.activity import activity
from sugar4.bundle.activitybundle import ActivityBundle

import downloadmanager


class EvinceViewer(Gtk.Box):
    """PDF viewer using WebKit, with a bottom toolbar for basic navigation
    and an option to save to Journal.

    Note: The native EvinceView is unavailable, so this viewer renders
    PDFs via WebKit.WebView instead.

    """
    __gsignals__ = {
        'save-to-journal': (GObject.SignalFlags.RUN_FIRST,
                            None,
                            ([])),
        'open-link': (GObject.SignalFlags.RUN_FIRST,
                      None,
                      ([str])), }

    def __init__(self, uri):
        Gtk.Box.__init__(self, orientation=Gtk.Orientation.VERTICAL)

        self._uri = uri

        # Use WebKit.WebView instead of Evince since the native EvinceView
        # widget is unavailable
        self._view = WebKit.WebView()
        self._view.connect('decide-policy', self.__decide_policy_cb)
        self._view.load_uri(uri)

        self._toolbar_box = self._create_toolbar()

        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.set_hexpand(True)
        scrolled_window.set_vexpand(True)
        scrolled_window.set_child(self._view)
        self.append(scrolled_window)
        scrolled_window.show()
        self._view.show()

        self._toolbar_box.set_halign(Gtk.Align.FILL)
        self.append(self._toolbar_box)
        self._toolbar_box.show()

    def _create_toolbar(self):
        toolbar_box = ToolbarBox()

        zoom_out_button = ToolButton('zoom-out')
        zoom_out_button.set_tooltip(_('Zoom out'))
        zoom_out_button.connect('clicked', self.__zoom_out_cb)
        toolbar_box.toolbar.append(zoom_out_button)
        zoom_out_button.show()

        zoom_in_button = ToolButton('zoom-in')
        zoom_in_button.set_tooltip(_('Zoom in'))
        zoom_in_button.connect('clicked', self.__zoom_in_cb)
        toolbar_box.toolbar.append(zoom_in_button)
        zoom_in_button.show()

        zoom_original_button = ToolButton('zoom-original')
        zoom_original_button.set_tooltip(_('Actual size'))
        zoom_original_button.connect('clicked', self.__zoom_original_cb)
        toolbar_box.toolbar.append(zoom_original_button)
        zoom_original_button.show()

        separator = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        toolbar_box.toolbar.append(separator)
        separator.show()

        self._save_to_journal_button = ToolButton('save-to-journal')
        self._save_to_journal_button.set_tooltip(_('Save PDF to Journal'))
        self._save_to_journal_button.connect('clicked',
                                             self.__save_to_journal_button_cb)
        toolbar_box.toolbar.append(self._save_to_journal_button)
        self._save_to_journal_button.show()

        separator = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        toolbar_box.toolbar.append(separator)
        separator.show()

        self._inverted_colors = ToggleToolButton(icon_name='dark-theme')
        self._inverted_colors.set_tooltip(_('Inverted Colors'))
        self._inverted_colors.set_accelerator('<Ctrl>i')
        self._inverted_colors.connect(
            'toggled', self.__inverted_colors_toggled_cb)
        toolbar_box.toolbar.append(self._inverted_colors)
        self._inverted_colors.show()

        return toolbar_box

    def disable_journal_button(self):
        self._save_to_journal_button.props.sensitive = False

    def __decide_policy_cb(self, web_view, decision, decision_type):
        if decision_type == WebKit.PolicyDecisionType.NAVIGATION_ACTION:
            action = decision.get_navigation_action()
            nav_type = action.get_navigation_type()
            if nav_type == WebKit.NavigationType.LINK_CLICKED:
                request = action.get_request()
                if request:
                    uri = request.get_uri()
                    # Allow in-document anchor links (e.g. #page=5)
                    # to be handled by WebKit's PDF viewer instead
                    # of opening a new tab.
                    if uri.startswith(self._uri):
                        return False
                    self.emit('open-link', uri)
                    decision.ignore()
                    return True
        return False

    def __zoom_out_cb(self, widget):
        self.zoom_out()

    def __zoom_in_cb(self, widget):
        self.zoom_in()

    def __zoom_original_cb(self, widget):
        self.zoom_original()

    def __save_to_journal_button_cb(self, widget):
        self.emit('save-to-journal')
        self._save_to_journal_button.props.sensitive = False

    def __inverted_colors_toggled_cb(self, button):
        # EvinceView had set_inverted_colors(); WebKit does not.
        # Use a CSS filter on the document as a best-effort substitute.
        # Note: this relies on WebKitGTK compositing the PDF within
        # the normal page rendering pipeline.  If a future version
        # renders PDFs via a native plugin that bypasses DOM
        # compositing, the filter will silently have no effect.
        if button.props.active:
            self._view.evaluate_javascript(
                "document.documentElement.style.filter = "
                "'invert(1) hue-rotate(180deg)';",
                -1, None, None, None, None, None)
            button.set_icon_name('light-theme')
            button.set_tooltip(_('Normal Colors'))
        else:
            self._view.evaluate_javascript(
                "document.documentElement.style.filter = 'none';",
                -1, None, None, None, None, None)
            button.set_icon_name('dark-theme')
            button.set_tooltip(_('Inverted Colors'))

    def show_inverted_colors_button(self):
        self._inverted_colors.show()

    def toggle_inverted_colors(self):
        self._inverted_colors.set_active(
            not self._inverted_colors.get_active())

    def zoom_original(self):
        self._view.set_zoom_level(1.0)

    def zoom_in(self):
        self._view.set_zoom_level(self._view.get_zoom_level() + 0.1)

    def zoom_out(self):
        self._view.set_zoom_level(max(0.1, self._view.get_zoom_level() - 0.1))

    def get_pdf_title(self):
        # WebKit returns the page/filename title, not the PDF metadata title.
        return self._view.get_title()


class DummyBrowser(GObject.GObject):
    """Has the same interface as browser.Browser ."""
    __gsignals__ = {
        'new-tab': (GObject.SignalFlags.RUN_FIRST, None, ([str])),
        'tab-close': (GObject.SignalFlags.RUN_FIRST, None, ([object])),
        'load-changed': (GObject.SignalFlags.RUN_FIRST, None, ([int])),
        'selection-changed': (GObject.SignalFlags.RUN_FIRST, None, ([])),
        'security-status-changed': (GObject.SignalFlags.RUN_FIRST, None, ([])),
        'enter-fullscreen': (GObject.SignalFlags.RUN_FIRST, None, ([])),
        'leave-fullscreen': (GObject.SignalFlags.RUN_FIRST, None, ([])),
    }

    __gproperties__ = {
        'title': (object, 'title', 'Title', GObject.PARAM_READWRITE),
        'uri': (object, 'uri', 'URI', GObject.PARAM_READWRITE),
        'estimated-load-progress': (object, 'estimated-load-progress',
                                    'Progress', GObject.PARAM_READWRITE),
    }

    def __init__(self, tab):
        GObject.GObject.__init__(self)
        self._tab = tab
        self._title = ""
        self._uri = ""
        self._progress = 0.0
        self.security_status = None

    def get_web_inspector(self):
        return None

    def do_get_property(self, prop):
        if prop.name == 'title':
            return self._title
        elif prop.name == 'uri':
            return self._uri
        elif prop.name == 'estimated-load-progress':
            return self._progress
        else:
            raise AttributeError('Unknown property %s' % prop.name)

    def do_set_property(self, prop, value):
        if prop.name == 'title':
            self._title = value
        elif prop.name == 'uri':
            self._uri = value
        elif prop.name == 'estimated-load-progress':
            self._progress = value
            if self._progress >= 1.0:
                # Clear spinning cursor
                self.emit('load-changed', WebKit.LoadEvent.FINISHED)
        else:
            raise AttributeError('Unknown property %s' % prop.name)

    def get_state(self):
        return {'uri': self.props.uri, 'title': self.props.title}

    def get_title(self):
        return self._title

    def get_uri(self):
        return self._uri

    def emit_new_tab(self, uri):
        self.emit('new-tab', uri)

    def emit_close_tab(self):
        self.emit('tab-close', self._tab)

    def get_legacy_history(self):
        return [{'url': self.props.uri, 'title': self.props.title}]

    def set_history_index(self, index):
        pass

    def get_history_index(self):
        return 0

    def set_zoom_level(self, zoom_level):
        pass

    def get_zoom_level(self):
        return 0

    def stop_loading(self):
        self._tab.close_tab()

    def reload(self):
        pass

    def load_uri(self, uri):
        pass

    def grab_focus(self):
        pass

    def destroy(self):
        pass

    def get_root(self):
        return self._tab.get_root()

    def get_snapshot(self, region, options, cancellable, callback, *args):
        if self._tab._evince_viewer and self._tab._evince_viewer._view:
            self._tab._evince_viewer._view.get_snapshot(
                region, options, cancellable, callback, *args)
        else:
            raise AttributeError("PDF viewer not initialized")

    def get_realized(self):
        # Stub for duck-typing: browser.py and palettes.py call this directly
        # on the browser object. Mapped is the closest equivalent state.
        return self._tab.get_mapped()

    def get_allocation(self):
        return self._tab.get_allocation()

    def translate_coordinates(self, widget, x, y):
        return self._tab.translate_coordinates(widget, x, y)

    def can_query_editing_commands(self):
        # PDFs opened in this viewer are not editable.
        return False

    # FIXME provide implementations
    def can_execute_editing_command_finish(self, result=None):
        pass

    def get_find_controller(self):
        return


class PDFProgressMessageBox(Gtk.Box):
    def __init__(self, message, button_callback):
        Gtk.Box.__init__(self, orientation=Gtk.Orientation.VERTICAL)
        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.CENTER)

        self.add_css_class('pdf-message-box')
        # CSS is injected dynamically here instead of sugar-artwork because
        # the colour value is resolved at runtime from sugar4.graphics.style.
        white = style.COLOR_WHITE.get_css_rgba()
        css = f".pdf-message-box {{ background-color: {white}; }}"
        style.apply_css_to_widget(self, css)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.append(box)
        box.show()

        # ProgressIcon is unavailable. We fallback to a standard static Icon
        # paired with a native Gtk.ProgressBar.
        icon = Icon(icon_name='book',
                    pixel_size=style.LARGE_ICON_SIZE,
                    stroke_color=style.COLOR_BUTTON_GREY.get_svg(),
                    fill_color=style.COLOR_SELECTION_GREY.get_svg())

        box.append(icon)
        icon.show()

        self.progress_bar = Gtk.ProgressBar()
        box.append(self.progress_bar)
        self.progress_bar.show()

        label = Gtk.Label()
        color = style.COLOR_BUTTON_GREY.get_html()
        label.set_markup('<span weight="bold" color="%s">%s</span>' % (
            color, GLib.markup_escape_text(message)))
        box.append(label)
        label.show()

        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        button_box.set_halign(Gtk.Align.CENTER)
        box.append(button_box)
        button_box.show()

        button = Gtk.Button()
        button.connect('clicked', button_callback)
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        btn_box.append(Icon(icon_name='dialog-cancel',
                            pixel_size=style.SMALL_ICON_SIZE))
        btn_box.append(Gtk.Label(label=_('Cancel')))
        button.set_child(btn_box)
        button_box.append(button)
        button.show()


class PDFErrorMessageBox(Gtk.Box):
    def __init__(self, title, message, button_callback):
        Gtk.Box.__init__(self, orientation=Gtk.Orientation.VERTICAL)
        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.CENTER)

        self.add_css_class('pdf-message-box')
        # CSS is injected dynamically here instead of sugar-artwork because
        # the colour value is resolved at runtime from sugar4.graphics.style.
        white = style.COLOR_WHITE.get_css_rgba()
        css = f".pdf-message-box {{ background-color: {white}; }}"
        style.apply_css_to_widget(self, css)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.append(box)
        box.show()

        # Get the icon of this activity through the bundle path.
        bundle_path = activity.get_bundle_path()
        activity_bundle = ActivityBundle(bundle_path)
        icon = Icon(pixel_size=style.LARGE_ICON_SIZE,
                    file=activity_bundle.get_icon(),
                    stroke_color=style.COLOR_BUTTON_GREY.get_svg(),
                    fill_color=style.COLOR_TRANSPARENT.get_svg())

        box.append(icon)
        icon.show()

        color = style.COLOR_BUTTON_GREY.get_html()

        label = Gtk.Label()
        label.set_markup('<span weight="bold" color="%s">%s</span>' % (
            color, GLib.markup_escape_text(title)))
        box.append(label)
        label.show()

        label = Gtk.Label()
        label.set_markup('<span color="%s">%s</span>' % (
            color, GLib.markup_escape_text(message)))
        box.append(label)
        label.show()

        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        button_box.set_halign(Gtk.Align.CENTER)
        box.append(button_box)
        button_box.show()

        button = Gtk.Button()
        button.connect('clicked', button_callback)
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        btn_box.append(Icon(icon_name='entry-refresh',
                            pixel_size=style.SMALL_ICON_SIZE,
                            stroke_color=style.COLOR_WHITE.get_svg(),
                            fill_color=style.COLOR_TRANSPARENT.get_svg()))
        btn_box.append(Gtk.Label(label=_('Try again')))
        button.set_child(btn_box)
        button_box.append(button)
        button.show()


class PDFTabPage(Gtk.Box):
    """Shows a basic PDF viewer, download the file first if the PDF is
    in a remote location.

    When the file is remote, display a message while downloading.

    """

    def __init__(self, state=None):
        Gtk.Box.__init__(self, orientation=Gtk.Orientation.HORIZONTAL)
        self._browser = DummyBrowser(self)
        self._message_box = None
        self._evince_viewer = None
        self._pdf_uri = None
        self._requested_uri = None
        self._download = None
        self._downloaded_pdf = False
        if state is not None:
            self.setup(state['uri'], state['title'])

    def setup(self, requested_uri, title=None):
        self._requested_uri = requested_uri

        # The title may be given from the Journal:
        if title is not None:
            self._browser.props.title = title

        self._browser.props.uri = requested_uri
        # show PDF directly if the file is local (from the system tree
        # or from the journal)

        if requested_uri.startswith('file://'):
            self._pdf_uri = requested_uri
            self._show_pdf()

        elif requested_uri.startswith('journal://'):
            self._pdf_uri = self._get_path_from_journal(requested_uri)
            self._show_pdf(from_journal=True)

        # download first if file is remote
        elif requested_uri.startswith('http://') or \
                requested_uri.startswith('https://'):

            downloads_dir = GLib.get_user_special_dir(
                GLib.UserDirectory.DIRECTORY_DOWNLOAD)
            if downloads_dir is None:
                downloads_dir = os.path.join(
                    os.path.expanduser("~"), "Downloads")
            if not os.path.exists(downloads_dir):
                os.makedirs(downloads_dir)
            local_path = os.path.join(
                downloads_dir, os.path.basename(requested_uri))

            if os.path.isfile(local_path):
                # If file already exists locally, no need to download
                self._pdf_uri = "file://" + local_path
                self._show_pdf()
            else:
                self._download_from_http(requested_uri)

    def _get_browser(self):
        return self._browser

    browser = GObject.property(type=object, getter=_get_browser)

    def _show_pdf(self, from_journal=False):
        self._evince_viewer = EvinceViewer(self._pdf_uri)
        self._evince_viewer.connect('save-to-journal',
                                    self.__save_to_journal_cb)
        self._evince_viewer.connect('open-link',
                                    self.__open_link_cb)

        # disable save to journal if the PDF is already loaded from
        # the journal:
        if from_journal:
            self._evince_viewer.disable_journal_button()

        self._evince_viewer.show()
        self._evince_viewer.set_hexpand(True)
        self._evince_viewer.set_vexpand(True)
        self.append(self._evince_viewer)

        # If the PDF has a title, set it as the browse page title,
        # otherwise use the last part of the URI.  Only when the title
        # was not set already from the Journal.
        if from_journal:
            self._browser.props.title = self._browser.props.title
            return
        pdf_title = self._evince_viewer.get_pdf_title()
        if pdf_title is not None:
            self._browser.props.title = pdf_title
        else:
            self._browser.props.title = os.path.basename(self._requested_uri)

    def _get_path_from_journal(self, journal_uri):
        """Get the system tree URI of the file for the Journal object."""
        journal_id = self.__journal_id_from_uri(journal_uri)
        jobject = datastore.get(journal_id)
        return 'file://' + jobject.file_path

    def _download_from_http(self, remote_uri):
        """Download the PDF from a remote location to a temporal file."""

        # Display a message
        self._message_box = PDFProgressMessageBox(
            message=_("Downloading document..."),
            button_callback=self.close_tab)
        self._message_box.set_hexpand(True)
        self._message_box.set_vexpand(True)
        self.append(self._message_box)
        self._message_box.show()

        session = WebKit.NetworkSession.get_default()
        session.connect('download-started', self.__download_started_cb)
        downloadmanager.ignore_pdf(remote_uri)

    def __download_started_cb(self, session, download):
        self._download = download
        download.connect('failed', self.__download_failed_cb)
        download.connect('finished', self.__download_finished_cb)
        download.connect('received-data', self.__download_received_data_cb)
        download.connect('decide-destination', self.__decide_destination_cb)
        session.disconnect_by_func(self.__download_started_cb)

    def __decide_destination_cb(self, download, suggested_filename):
        import os
        from gi.repository import GLib
        downloads_dir = GLib.get_user_special_dir(
            GLib.UserDirectory.DIRECTORY_DOWNLOAD)
        if downloads_dir is None:
            downloads_dir = os.path.join(os.path.expanduser("~"), "Downloads")
        if not os.path.exists(downloads_dir):
            os.makedirs(downloads_dir)
        local_path = os.path.join(downloads_dir, suggested_filename)
        download.set_destination(local_path)
        return True

    def __download_received_data_cb(self, download, data_size):
        self._browser.props.estimated_load_progress = \
            self._download.get_estimated_progress()
        self._message_box.progress_bar.set_fraction(
            self._browser.props.estimated_load_progress)

    def __download_finished_cb(self, download):
        self._pdf_uri = download.get_destination()
        if not self._pdf_uri.startswith('file://'):
            self._pdf_uri = "file://" + self._pdf_uri
        logging.debug('FINISHED %s', self._pdf_uri)

        from gi.repository import GLib

        def switch_to_pdf():
            if self._message_box:
                self.remove(self._message_box)
                self._message_box = None
            self._show_pdf()
            return False

        GLib.idle_add(switch_to_pdf)
        self._download = None
        self._downloaded_pdf = True

    def __download_failed_cb(self, download, error):
        logging.debug('Download error! code %s, message %s' %
                      (error.code, error.message))
        title = _('This document could not be loaded')
        self._browser.props.title = title

        from gi.repository import GLib

        def switch_to_error():
            if self._message_box is not None:
                self.remove(self._message_box)

            msg = _('Please make sure you are connected to the Internet.')
            self._message_box = PDFErrorMessageBox(
                title=title,
                message=msg,
                button_callback=self.reload)
            self._message_box.set_hexpand(True)
            self._message_box.set_vexpand(True)
            self.append(self._message_box)
            self._message_box.show()
            return False

        GLib.idle_add(switch_to_error)
        self._download = None

    def reload(self, button=None):
        self.remove(self._message_box)
        self._message_box = None
        self.setup(self._requested_uri)

    def close_tab(self, button=None):
        self._browser.emit_close_tab()

    def cancel_download(self):
        if self._download is not None:
            self._download.cancel()
        try:
            if self._downloaded_pdf:
                os.remove(self._pdf_uri[len("file://"):])
        except BaseException:
            pass

    def __journal_id_to_uri(self, journal_id):
        """Return an URI for a Journal object ID."""
        return "journal://" + journal_id + ".pdf"

    def __journal_id_from_uri(self, journal_uri):
        """Return a Journal object ID from an URI."""
        return journal_uri[len("journal://"):-len(".pdf")]

    def __save_to_journal_cb(self, widget):
        """Save the PDF in the Journal.

        Put the PDF title as the title, or if the PDF doesn't have
        one, use the filename instead.  Put the requested uri as the
        description.

        """
        jobject = datastore.create()

        jobject.metadata['title'] = self._browser.props.title
        jobject.metadata['description'] = _('From: %s') % self._requested_uri

        jobject.metadata['mime_type'] = "application/pdf"
        jobject.file_path = self._pdf_uri[len("file://"):]
        datastore.write(jobject)

        # display the new URI:
        self._browser.props.uri = self.__journal_id_to_uri(jobject.object_id)

    def __open_link_cb(self, widget, uri):
        """Open the external link of a PDF in a new tab."""
        self._browser.emit_new_tab(uri)
