# Copyright (C) 2007, One Laptop Per Child
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301
# USA

from gi.repository import Gtk
from gi.repository import Gdk
from gi.repository import GObject
from gi.repository import GLib
from gi.repository import Rsvg

import os
import io
import cairo
import logging
from gettext import gettext as _
import re

from sugar4.graphics.palettemenu import PaletteMenuItemSeparator
from sugar4.graphics.palettemenu import PaletteMenuItem
from sugar4.graphics.palettemenu import PaletteMenuBox
from sugar4.graphics.palette import Palette
from sugar4.graphics.tray import TrayButton
from sugar4.graphics import style


class LinkButton(TrayButton, GObject.GObject):
    __gtype_name__ = 'LinkButton'
    __gsignals__ = {
        'remove_link': (GObject.SignalFlags.RUN_FIRST,
                        None, ([str])),
    }
    notes_changed_signal = GObject.Signal(
        'notes-changed', arg_types=[str, str])

    _dest_x = style.zoom(10)
    _dest_y = style.zoom(20)

    def __init__(self, buf, color, title, owner, hash, notes=None):
        TrayButton.__init__(self)

        self._fill, self._stroke = color.split(',')
        self.set_image(buf)

        self.hash = hash
        self.notes = notes
        info = title + '\n' + owner
        self.setup_rollover_options(info)

    def show_thumb(self):
        if getattr(self, '_texture_bg', None) is not None:
            self._img.set_paintable(self._texture_bg)

    def hide_thumb(self):
        if not hasattr(self, '_texture_hidden_bg'):
            self._texture_hidden_bg = None
            xo_buddy = os.path.join(
                os.path.dirname(__file__), "icons/link.svg")
            bg_surface = self._read_link_background(xo_buddy)

            if bg_surface:
                stream = io.BytesIO()
                bg_surface.write_to_png(stream)
                png_bytes = GLib.Bytes.new(stream.getvalue())
                try:
                    self._texture_hidden_bg = Gdk.Texture.new_from_bytes(
                        png_bytes)
                except Exception as e:
                    logging.error(
                        'Failed to load hidden background texture: %s', e)

        if self._texture_hidden_bg is not None:
            self._img.set_paintable(self._texture_hidden_bg)

    def set_image(self, buf):
        self._img = Gtk.Picture()
        str_buf = io.BytesIO(buf)
        try:
            thumb_surface = cairo.ImageSurface.create_from_png(str_buf)
        except Exception as e:
            logging.error(
                'Failed to create ImageSurface from thumbnail bytes: %s', e)
            thumb_surface = None

        xo_buddy = os.path.join(os.path.dirname(__file__), "icons/link.svg")

        bg_surface = self._read_link_background(xo_buddy)

        bg_width, bg_height = style.zoom(120), style.zoom(110)

        self._texture_bg = None
        if bg_surface:
            cairo_context = cairo.Context(bg_surface)
            if thumb_surface:
                cairo_context.save()
                thumb_width, thumb_height = style.zoom(100), style.zoom(80)
                orig_w = thumb_surface.get_width()
                orig_h = thumb_surface.get_height()
                if orig_w > 0 and orig_h > 0:
                    scale_x = thumb_width / orig_w
                    scale_y = thumb_height / orig_h
                    cairo_context.translate(self._dest_x, self._dest_y)
                    cairo_context.scale(scale_x, scale_y)
                    cairo_context.set_source_surface(thumb_surface, 0, 0)
                    cairo_context.rectangle(0, 0, orig_w, orig_h)
                    cairo_context.fill()
                cairo_context.restore()

            stream = io.BytesIO()
            bg_surface.write_to_png(stream)
            png_bytes = GLib.Bytes.new(stream.getvalue())
            try:
                self._texture_bg = Gdk.Texture.new_from_bytes(png_bytes)
            except Exception as e:
                logging.error('Failed to load background texture: %s', e)

        if self._texture_bg is not None:
            self._img.set_paintable(self._texture_bg)
        self._img.set_size_request(bg_width, bg_height)
        self.set_icon_widget(self._img)

    def _read_link_background(self, filename):
        with open(filename, 'rb') as icon_file:
            data = icon_file.read()

        entity = b'<!ENTITY fill_color "%s">' % self._fill.encode()
        data = re.sub(b'<!ENTITY fill_color .*>', entity, data)

        entity = b'<!ENTITY stroke_color "%s">' % self._stroke.encode()
        data = re.sub(b'<!ENTITY stroke_color .*>', entity, data)

        link_width, link_height = style.zoom(120), style.zoom(110)
        link_surface = cairo.ImageSurface(cairo.FORMAT_ARGB32,
                                          link_width, link_height)
        link_context = cairo.Context(link_surface)
        try:
            handler = Rsvg.Handle.new_from_data(data)
            rect = Rsvg.Rectangle()
            rect.x = float(0)
            rect.y = float(0)
            rect.width = float(link_width)
            rect.height = float(link_height)
            handler.render_document(link_context, rect)
        except Exception as e:
            logging.error('Error rendering SVG background: %s', e)
            return None

        return link_surface

    def setup_rollover_options(self, info):
        palette = Palette(info, text_maxlen=50)
        self.set_palette(palette)

        box = PaletteMenuBox()
        palette.set_content(box)

        menu_item = PaletteMenuItem(_('Remove'), 'list-remove')
        menu_item.connect('clicked', self.item_remove_cb)
        box.append_item(menu_item)

        separator = PaletteMenuItemSeparator()
        box.append_item(separator)

        textview = Gtk.TextView()
        textview.props.height_request = style.GRID_CELL_SIZE * 2
        textview.props.width_request = style.GRID_CELL_SIZE * 3
        textview.props.hexpand = True
        textview.props.vexpand = True
        box.append_item(textview)

        buffer = textview.get_buffer()
        if self.notes is None:
            buffer.set_text(_('Take notes on this page'))
        else:
            buffer.set_text(self.notes)
        buffer.connect('changed', self.__buffer_changed_cb)

    def item_remove_cb(self, widget):
        self.emit('remove_link', self.hash)

    def __buffer_changed_cb(self, buffer):
        start, end = buffer.get_bounds()
        self.notes = buffer.get_text(start, end, False)
        self.notes_changed_signal.emit(self.hash, self.notes)
