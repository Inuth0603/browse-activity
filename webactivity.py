# Copyright (C) 2006, Red Hat, Inc.
# Copyright (C) 2009 Martin Langhoff, Simon Schampijer, Daniel Drake,
#                    Tomeu Vizoso
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
from gettext import gettext as _
from gettext import ngettext
import os

import gi
gi.require_version('Gtk', '4.0')
try:
    incompatible = False
    gi.require_version('WebKit', '6.0')
except BaseException:
    incompatible = True
gi.require_version('Soup', '3.0')

from gi.repository import Gtk
from gi.repository import Gdk
from gi.repository import GLib
from gi.repository import Gio
from gi.repository import WebKit
from gi.repository import Soup

from base64 import b64decode, b64encode
import time
import shutil
import json
from hashlib import sha1

from sugar4.activity import activity
from sugar4.activity.widgets import StopButton
from sugar4.graphics import style
from sugar4.graphics.alert import Alert
from sugar4.graphics.alert import NotifyAlert
from sugar4.graphics.icon import Icon
from sugar4 import mime
from sugar4.graphics.toolbarbox import ToolbarBox, ToolbarButton
from sugar4 import profile

from collabwrapper import CollabWrapper
from widgets import TitledTray


_BLANK_THUMBNAIL_PNG = (
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDw'
    'AChwGA60e6kgAAAABJRU5ErkJggg=='
)

THUMB_WIDTH, THUMB_HEIGHT = style.zoom(100), style.zoom(80)

_logger = logging.getLogger('web-activity')

_profile_path = os.path.join(activity.get_activity_root(), 'data', 'profile')
_old_profile_path = os.path.join(activity.get_activity_root(), 'data', 'gecko')

# Migrate the legacy XULRunner 'data/gecko' directory to a generic
# 'data/profile' directory, as Gecko/NSS specific artifacts (cert8.db)
# are no longer used.
if os.path.exists(_old_profile_path) and not os.path.exists(_profile_path):
    try:
        shutil.move(_old_profile_path, _profile_path)
    except OSError as e:
        _logger.error('Failed to migrate profile directory: %s', e)
elif not os.path.exists(_profile_path):
    os.makedirs(_profile_path)

# Clean up stray version file if it migrated over
_version_file = os.path.join(_profile_path, 'version')
if os.path.exists(_version_file):
    try:
        os.remove(_version_file)
    except OSError:
        pass

_cookies_db_path = os.path.join(_profile_path, 'cookies.sqlite')


def _seed_xs_cookie(cookie_jar):
    """Create a HTTP Cookie to authenticate with the Schoolserver.

    Do nothing if the laptop is not registered with Schoolserver, or
    if the cookie already exists.

    """
    settings = Gio.Settings('org.sugarlabs')
    backup_url = settings.get_string('backup-url')
    if not backup_url:
        _logger.debug('seed_xs_cookie: Not registered with Schoolserver')
        return

    settings = Gio.Settings('org.sugarlabs.collaboration')
    jabber_server = settings.get_string('jabber-server')

    glib_uri = GLib.Uri.build(GLib.UriFlags.NONE, 'xmpp', None,
                              jabber_server, -1, '/', None, None)
    xs_cookie = cookie_jar.get_cookies(glib_uri, for_http=False)
    if xs_cookie is not None:
        _logger.debug('seed_xs_cookie: Cookie exists already')
        return

    pubkey = profile.get_profile().pubkey
    cookie_data = {'color': profile.get_color().to_string(),
                   'pkey_hash': sha1(pubkey).hexdigest()}

    expire = int(time.time()) + 10 * 365 * 24 * 60 * 60

    xs_cookie = Soup.Cookie()
    xs_cookie.set_name('xoid')
    xs_cookie.set_value(json.dumps(cookie_data))
    xs_cookie.set_domain(jabber_server)
    xs_cookie.set_path('/')
    xs_cookie.set_max_age(expire)
    cookie_jar.add_cookie(xs_cookie)
    _logger.debug('seed_xs_cookie: Updated cookie successfully')


from browser import TabbedView
from webtoolbar import PrimaryToolbar
from edittoolbar import EditToolbar
from viewtoolbar import ViewToolbar
import downloadmanager

# TODO: make the registration clearer SL #3087

from model import Model
from linkbutton import LinkButton

SERVICE = "org.laptop.WebActivity"
IFACE = SERVICE
PATH = "/org/laptop/WebActivity"


class WebActivity(activity.Activity):
    def __init__(self, handle):
        activity.Activity.__init__(self, handle)

        self._force_close = False
        if incompatible:
            return self._incompatible()

        self._collab = CollabWrapper(self)
        self._collab.message.connect(self.__message_cb)

        _logger.debug('Starting the web activity')

        # Whitelist directories for the WebKit sandbox BEFORE any WebView is
        # created.
        # Calling add_path_to_sandbox after WebProcess creation causes a C
        # abort.
        try:
            context = WebKit.WebContext.get_default()
            if hasattr(context, 'add_path_to_sandbox'):
                # 1. Downloads directory
                downloads_dir = GLib.get_user_special_dir(
                    GLib.UserDirectory.DIRECTORY_DOWNLOAD)
                if downloads_dir is None:
                    downloads_dir = os.path.join(
                        os.path.expanduser("~"), "Downloads")
                if not os.path.exists(downloads_dir):
                    os.makedirs(downloads_dir)
                context.add_path_to_sandbox(downloads_dir, True)

                # 2. Datastore/Journal directory
                from sugar4 import env
                datastore_dir = os.path.join(
                    env.get_profile_path(), 'datastore')
                if os.path.exists(datastore_dir):
                    context.add_path_to_sandbox(datastore_dir, True)
        except Exception as e:
            _logger.error('Failed to configure sandbox paths: %s', e)

        network_session = WebKit.NetworkSession.get_default()

        # WebKit 6.0 handles system CA resolution natively, and automatically
        # constructs the Accept-Language header based on the system locale.

        # NetworkSession handles TLS strictness directly via
        # TLSErrorsPolicy. TLS errors are explicitly ignored here.
        network_session.set_tls_errors_policy(WebKit.TLSErrorsPolicy.IGNORE)

        # Bit of a hack, but webkit doesn't let us change the cookie jar
        # contents, so we can just pre-seed it
        cookie_jar = Soup.CookieJarDB(filename=_cookies_db_path,
                                      read_only=False)
        _seed_xs_cookie(cookie_jar)
        # Explicitly delete the Soup.CookieJarDB instance to drop the Python
        # reference, which triggers synchronous cleanup of its underlying
        # SQLite connection. This prevents lock contention when WebKit's
        # NetworkSession opens the same file immediately below.
        del cookie_jar

        cookie_manager = network_session.get_cookie_manager()
        cookie_manager.set_persistent_storage(
            _cookies_db_path, WebKit.CookiePersistentStorage.SQLITE)

        # FIXME
        # downloadmanager.remove_old_parts()
        network_session.connect(
            'download-started',
            self.__download_requested_cb)

        self._tabbed_view = TabbedView(self)
        self._tabbed_view.connect('focus-url-entry', self._on_focus_url_entry)
        self._tabbed_view.connect('switch-page', self.__switch_page_cb)

        self._titled_tray = TitledTray(_('Bookmarks'))
        self._titled_tray.hide()
        self._tray = self._titled_tray.tray
        self.set_tray(self._titled_tray, Gtk.PositionType.BOTTOM)
        self._tray_links = {}

        self.model = Model()
        self.model.add_link_signal.connect(self._add_link_model_cb)

        self._primary_toolbar = PrimaryToolbar(self._tabbed_view, self)
        self._edit_toolbar = EditToolbar(self)
        self._view_toolbar = ViewToolbar(self)

        self._primary_toolbar.connect('add-link', self.__link_add_button_cb)
        self._primary_toolbar.connect('remove-link',
                                      self.__link_remove_button_cb)
        self._primary_toolbar.connect('go-home', self._go_home_button_cb)
        self._primary_toolbar.connect('go-library', self._go_library_button_cb)
        self._primary_toolbar.connect('set-home', self._set_home_button_cb)
        self._primary_toolbar.connect('reset-home', self._reset_home_button_cb)

        self._edit_toolbar_button = ToolbarButton(
            page=self._edit_toolbar, icon_name='toolbar-edit')

        first_child = self._primary_toolbar.toolbar.get_first_child()
        self._primary_toolbar.toolbar.insert_child_after(
            self._edit_toolbar_button, first_child)

        view_toolbar_button = ToolbarButton(
            page=self._view_toolbar, icon_name='toolbar-view')
        self._primary_toolbar.toolbar.insert_child_after(
            view_toolbar_button, self._edit_toolbar_button)

        self._primary_toolbar.show()
        self.set_toolbar_box(self._primary_toolbar)

        self.set_canvas(self._tabbed_view)
        self._tabbed_view.show()

        key_controller = Gtk.EventControllerKey()
        key_controller.connect('key-pressed', self._key_press_cb)
        self.add_controller(key_controller)

        if handle.uri:
            self._tabbed_view.current_browser.load_uri(handle.uri)
        elif not self._jobject.file_path:
            # TODO: we need this hack until we extend the activity API for
            # opening URIs and default docs.
            self._tabbed_view.load_homepage()

        # README: this is a workaround to remove old temp file
        # http://bugs.sugarlabs.org/ticket/3973
        self._cleanup_temp_files()

        self._collab.setup()

    def __download_requested_cb(self, context, download):
        # NetworkSession's download-started signal signature is void,
        # so no value is returned.
        if hasattr(self, 'busy'):
            while self.unbusy() > 0:
                continue
        logging.debug('__download_requested_cb %r',
                      download.get_request().get_uri())
        downloadmanager.add_download(download, self)

    def fullscreen(self):
        activity.Activity.fullscreen(self)
        self._tabbed_view.set_show_tabs(False)

    def unfullscreen(self):
        activity.Activity.unfullscreen(self)

        # Always show tabs here, because they are automatically hidden
        # if it is like a video fullscreening.  We ALWAYS need to make
        # sure these are visible.  Don't make the user lost
        self._tabbed_view.set_show_tabs(True)

    def _cleanup_temp_files(self):
        """Removes temporary files generated by Download Manager that
        were cancelled by the user or failed for any reason.

        There is a bug in GLib that makes this to happen:
            https://bugzilla.gnome.org/show_bug.cgi?id=629301
        """

        try:
            uptime_proc = open('/proc/uptime', 'r').read()
            uptime = int(float(uptime_proc.split()[0]))
        except EnvironmentError:
            logging.warning('/proc/uptime could not be read')
            uptime = None

        temp_path = os.path.join(self.get_activity_root(), 'instance')
        now = int(time.time())
        cutoff = now - 24 * 60 * 60  # yesterday
        if uptime is not None:
            boot_time = now - uptime
            cutoff = max(cutoff, boot_time)

        for f in os.listdir(temp_path):
            if f.startswith('.goutputstream-'):
                fpath = os.path.join(temp_path, f)
                mtime = int(os.path.getmtime(fpath))
                if mtime < cutoff:
                    logging.warning('Removing old temporary file: %s', fpath)
                    try:
                        os.remove(fpath)
                    except EnvironmentError:
                        logging.error('Temporary file could not be '
                                      'removed: %s', fpath)

    def _on_focus_url_entry(self, gobject):
        self._primary_toolbar.entry.grab_focus()

    def _get_data_from_file_path(self, file_path):
        fd = open(file_path, 'r')
        try:
            data = fd.read()
        finally:
            fd.close()
        return data

    def _get_save_as(self):
        if not hasattr(profile, 'get_save_as'):
            return False
        return profile.get_save_as()

    def read_file(self, file_path):
        if self.metadata['mime_type'] == 'text/plain':
            data = self._get_data_from_file_path(file_path)
            self.model.deserialize(data)

            for link in self.model.data['shared_links']:
                _logger.debug('read: url=%s title=%s d=%s' % (link['url'],
                                                              link['title'],
                                                              link['color']))
                self._add_link_totray(link['url'],
                                      b64decode(link['thumb']),
                                      link['color'], link['title'],
                                      link['owner'], -1, link['hash'],
                                      link.get('notes'))
            logging.debug('########## reading %s', data)
            if 'session_state' in self.model.data:
                self._tabbed_view.set_session_state(
                    self.model.data['session_state'])
            else:
                self._tabbed_view.set_legacy_history(
                    self.model.data['history'],
                    self.model.data['currents'])
                for number, tab in enumerate(self.model.data['currents']):
                    tab_page = self._tabbed_view.get_nth_page(number)
                    zoom_level = tab.get('zoom_level')
                    if zoom_level is not None:
                        tab_page.browser.set_zoom_level(zoom_level)
                    tab_page.browser.grab_focus()

            self._tabbed_view.set_current_page(self.model.data['current_tab'])

        elif self.metadata['mime_type'] == 'text/uri-list':
            data = self._get_data_from_file_path(file_path)
            uris = mime.split_uri_list(data)
            if len(uris) == 1:
                self._tabbed_view.props.current_browser.load_uri(uris[0])
            else:
                _logger.error('Open uri-list: Does not support'
                              'list of multiple uris by now.')
        else:
            file_uri = 'file://' + file_path
            self._tabbed_view.props.current_browser.load_uri(file_uri)
            self._tabbed_view.props.current_browser.grab_focus()

    def write_file(self, file_path):
        if not hasattr(self, '_tabbed_view'):
            _logger.debug('Called write_file before the tabbed_view was made')
            return

        if not self.metadata['mime_type']:
            self.metadata['mime_type'] = 'text/plain'

        if self.metadata['mime_type'] == 'text/plain':
            browser = self._tabbed_view.current_browser

            if not self._jobject.metadata['title_set_by_user'] == '1' and \
               not self._get_save_as():
                if browser.props.title is None:
                    self.metadata['title'] = _('Untitled')
                else:
                    self.metadata['title'] = browser.props.title

            self.model.data['history'] = self._tabbed_view.get_legacy_history()
            current_tab = self._tabbed_view.get_current_page()
            self.model.data['current_tab'] = current_tab

            self.model.data['currents'] = []
            for n in range(0, self._tabbed_view.get_n_pages()):
                tab_page = self._tabbed_view.get_nth_page(n)
                n_browser = tab_page.browser
                if n_browser is not None:
                    uri = n_browser.get_uri()
                    history_index = n_browser.get_history_index()
                    info = {'title': n_browser.props.title, 'url': uri,
                            'history_index': history_index,
                            'zoom_level': n_browser.get_zoom_level()}

                    self.model.data['currents'].append(info)

            self.model.data['session_state'] = \
                self._tabbed_view.get_state()

            f = open(file_path, 'w')
            try:
                logging.debug('########## writing %s', self.model.serialize())
                f.write(self.model.serialize())
            finally:
                f.close()

    def __link_add_button_cb(self, button):
        self._add_link()

    def __link_remove_button_cb(self, button):
        browser = self._tabbed_view.props.current_browser
        uri = browser.get_uri()
        self.__link_removed_cb(None, sha1(uri.encode('utf-8')).hexdigest())

    def _go_home_button_cb(self, button):
        self._tabbed_view.load_homepage()

    def _go_library_button_cb(self, button):
        self._tabbed_view.load_homepage(ignore_settings=True)

    def _set_home_button_cb(self, button):
        self._tabbed_view.set_homepage()
        self._alert(_('The initial page was configured'))

    def _reset_home_button_cb(self, button):
        self._tabbed_view.reset_homepage()
        self._alert(_('The default initial page was configured'))

    def _alert(self, title, text=None):
        alert = NotifyAlert(timeout=5)
        alert.props.title = title
        alert.props.msg = text
        self.add_alert(alert)
        alert.connect('response', self._alert_cancel_cb)
        alert.show()

    def _alert_cancel_cb(self, alert, response_id):
        self.remove_alert(alert)

    def _key_press_cb(self, controller, keyval, keycode, state):
        browser = self._tabbed_view.props.current_browser

        if state & Gdk.ModifierType.CONTROL_MASK:
            if keyval == Gdk.KEY_f:
                self._edit_toolbar_button.set_expanded(True)
                self._edit_toolbar.search_entry.grab_focus()
                return True
            if keyval == Gdk.KEY_l:
                self._primary_toolbar.entry.grab_focus()
                return True
            if keyval == Gdk.KEY_equal:
                # On US keyboards, KEY_equal is KEY_plus without
                # SHIFT_MASK, so for convenience treat this as the
                # same as the zoom in accelerator configured in
                # WebKit
                browser.zoom_in()
                return True
            if keyval == Gdk.KEY_t:
                self._tabbed_view.add_tab()
                return True
            if keyval == Gdk.KEY_w:
                self._tabbed_view.close_tab()
                return True

            # FIXME: copy and paste is supposed to be handled by
            # Gtk.Entry, but does not work when we catch
            # key-press-event and return False.
            if self._primary_toolbar.entry.has_focus():
                if keyval == Gdk.KEY_c:
                    self._primary_toolbar.entry.copy_clipboard()
                    return True
                if keyval == Gdk.KEY_v:
                    self._primary_toolbar.entry.paste_clipboard()
                    return True

            return False

        if keyval in (Gdk.KEY_KP_Up, Gdk.KEY_KP_Down,
                      Gdk.KEY_KP_Left, Gdk.KEY_KP_Right):
            scrolled_window = browser.get_parent()

            if keyval in (Gdk.KEY_KP_Up, Gdk.KEY_KP_Down):
                adjustment = scrolled_window.get_vadjustment()
            elif keyval in (Gdk.KEY_KP_Left, Gdk.KEY_KP_Right):
                adjustment = scrolled_window.get_hadjustment()
            value = adjustment.get_value()
            step = adjustment.get_step_increment()

            if keyval in (Gdk.KEY_KP_Up, Gdk.KEY_KP_Left):
                adjustment.set_value(value - step)
            else:
                adjustment.set_value(value + step)

            return True

        if keyval == Gdk.KEY_Escape:
            browser.stop_loading()
            return False  # allow toolbar entry to handle escape too

        return False

    def _add_link(self):
        ''' take screenshot and add link info to the model '''

        browser = self._tabbed_view.props.current_browser
        ui_uri = browser.get_uri()

        if self.model.has_link(ui_uri):
            return

        def add_link_with_buf(buf_bytes):
            if self.model.has_link(ui_uri):
                return
            buf = b64encode(buf_bytes).decode('ascii')
            timestamp = time.time()
            args = (ui_uri, browser.props.title, buf,
                    profile.get_nick_name(),
                    profile.get_color().to_string(), timestamp)
            self.model.add_link(*args, by_me=True)
            self._collab.post({'type': 'add_link', 'args': args})

        def snapshot_ready(webview, result):
            try:
                snapshot_texture = webview.get_snapshot_finish(result)
                bytes_data = snapshot_texture.save_to_png_bytes()
                add_link_with_buf(bytes_data.get_data())
            except Exception as e:
                logging.error('Failed to get/save snapshot: %s', e)
                add_link_with_buf(b64decode(_BLANK_THUMBNAIL_PNG))

        if not hasattr(browser, 'get_snapshot'):
            add_link_with_buf(b64decode(_BLANK_THUMBNAIL_PNG))
            return

        try:
            browser.get_snapshot(WebKit.SnapshotRegion.VISIBLE,
                                 WebKit.SnapshotOptions.NONE,
                                 None,
                                 snapshot_ready)
        except Exception as e:
            logging.error('Snapshot API error: %s', e)
            add_link_with_buf(b64decode(_BLANK_THUMBNAIL_PNG))

    def __message_cb(self, collab, buddy, message):
        type_ = message.get('type')
        if type_ == 'add_link':
            self.model.add_link(*message['args'])
        elif type_ == 'add_link_from_info':
            self.model.add_link_from_info(message['dict'])
        elif type_ == 'remove_link':
            self.remove_link(message['hash'])

    def get_data(self):
        return self.model.data

    def set_data(self, data):
        for link in data['shared_links']:
            if link['hash'] not in self.model.get_links_ids():
                self.model.add_link_from_info(link)
            # FIXME: Case where buddy has updated link desciption

        their_model = Model()
        their_model.data = data
        for link in self.model.data['shared_links']:
            if link['hash'] not in their_model.get_links_ids():
                self._collab.post({'type': 'add_link_from_info',
                                   'dict': link})

    def _add_link_model_cb(self, model, index, by_me):
        ''' receive index of new link from the model '''
        link = self.model.data['shared_links'][index]
        widget = self._add_link_totray(
            link['url'], b64decode(link['thumb']),
            link['color'], link['title'],
            link['owner'], index, link['hash'],
            link.get('notes'))

        if by_me:
            # TODO: Restore custom zoom/fade animation using Gtk.Snapshot.
            # For now, just show the thumb immediately.
            widget.show_thumb()

    def _add_link_totray(self, url, buf, color, title, owner, index, hash,
                         notes=None):
        ''' add a link to the tray '''
        item = LinkButton(buf, color, title, owner, hash, notes)
        item.connect('clicked', self._link_clicked_cb, url)
        item.connect('remove_link', self.__link_removed_cb)
        item.notes_changed_signal.connect(self.__link_notes_changed)
        # use index to add to the tray
        self._tray_links[hash] = item
        self._tray.add_item(item, index)
        self._titled_tray.show()
        item.show()
        self._view_toolbar.traybutton.props.sensitive = True
        self._view_toolbar.traybutton.props.active = True
        self._view_toolbar.update_traybutton_tooltip()
        return item

    def __link_removed_cb(self, button, hash):
        self.remove_link(hash)
        self._collab.post({'type': 'remove_link', 'hash': hash})

    def remove_link(self, hash):
        ''' remove a link from tray and delete it in the model '''
        self._tray_links[hash].unparent()
        del self._tray_links[hash]

        self.model.remove_link(hash)
        if self._tray.get_first_child() is None:
            self._view_toolbar.traybutton.props.sensitive = False
            self._view_toolbar.traybutton.props.active = False
            self._view_toolbar.update_traybutton_tooltip()
            self._titled_tray.hide()

    def __link_notes_changed(self, button, hash, notes):
        self.model.change_link_notes(hash, notes)

    def _link_clicked_cb(self, button, url):
        ''' an item of the link tray has been clicked '''
        browser = self._tabbed_view.add_tab()
        browser.load_uri(url)
        browser.grab_focus()

    def can_close(self):
        if self._force_close:
            return True
        elif downloadmanager.can_quit():
            return True
        else:
            alert = Alert()
            alert.props.title = ngettext('Download in progress',
                                         'Downloads in progress',
                                         downloadmanager.num_downloads())
            message = ngettext('Stopping now will erase your download',
                               'Stopping now will erase your downloads',
                               downloadmanager.num_downloads())
            alert.props.msg = message
            cancel_icon = Icon(icon_name='dialog-cancel')
            cancel_label = ngettext('Continue download', 'Continue downloads',
                                    downloadmanager.num_downloads())
            alert.add_button(Gtk.ResponseType.CANCEL, cancel_label,
                             cancel_icon)
            stop_icon = Icon(icon_name='dialog-ok')
            alert.add_button(Gtk.ResponseType.OK, _('Stop'), stop_icon)
            stop_icon.show()
            self.add_alert(alert)
            alert.connect('response', self.__inprogress_response_cb)
            alert.show()
            self.present()
            return False

    def __inprogress_response_cb(self, alert, response_id):
        self.remove_alert(alert)
        if response_id is Gtk.ResponseType.CANCEL:
            logging.debug('Keep on')
        elif response_id == Gtk.ResponseType.OK:
            logging.debug('Stop downloads and quit')
            self._force_close = True
            downloadmanager.remove_all_downloads()
            self.close()

    def __switch_page_cb(self, tabbed_view, page, page_num):
        if not hasattr(self, 'busy'):
            return

        browser = page._browser
        progress = browser.props.estimated_load_progress
        uri = browser.props.uri

        if progress < 1.0 and uri:
            self.busy()
        else:
            while self.unbusy() > 0:
                continue

    def get_document_path(self, async_cb, async_err_cb):
        browser = self._tabbed_view.props.current_browser
        browser.get_source(async_cb, async_err_cb)

    def get_canvas(self):
        return self._tabbed_view

    def _incompatible(self):
        ''' Display abbreviated activity user interface with alert '''
        toolbox = ToolbarBox()
        stop = StopButton(self)
        toolbox.toolbar.append(stop)
        self.set_toolbar_box(toolbox)

        title = _('Activity not compatible with this system.')
        msg = _('Please downgrade activity and try again.')
        alert = Alert(title=title, msg=msg)
        alert.add_button(0, 'Stop', Icon(icon_name='activity-stop'))
        self.add_alert(alert)

        label = Gtk.Label(_('Uh oh, WebKit is too old. '
                            'Browse-200 and later require WebKit API 6.0, '
                            'sorry!'))
        self.set_canvas(label)

        '''
        Workaround: start Terminal activity, then type

        sugar-erase-bundle org.laptop.WebActivity

        then in My Settings, choose Software Update, which will offer
        older Browse.
        '''

        alert.connect('response', self.__incompatible_response_cb)
        stop.connect('clicked', self.__incompatible_stop_clicked_cb,
                     alert)

        self.show()

    def __incompatible_stop_clicked_cb(self, button, alert):
        self.remove_alert(alert)

    def __incompatible_response_cb(self, alert, response):
        self.remove_alert(alert)
        self.close()
