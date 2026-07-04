# Copyright (C) 2016 Utkarsh Tiwari <iamutkarshtiwari@gmail.com>
# Copyright (C) 2016 Sam Parkinson <sam@sam.today>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
'''
The progress toolbutton fits into a toolbar and displays a static icon.
Because ProgressIcon is no longer available in the toolkit, this is currently
a standard ToolButton that accepts progress updates as a no-op compatibility stub.

Using the progress toolbutton is just like using a regular toolbutton; you
set the icon name and add it to the toolbar (e.g. using `toolbar.append(...)`
instead of GTK3's `toolbar.insert(..., -1)`). You can then use the `update`
function as the operation progresses, although it currently has no visual effect.

Example::

    self._download_icon = ProgressToolButton(icon_name='emblem-downloads')
    self._download_icon.props.tooltip = _('No Download Running')
    toolbar.append(self._download_icon)

    def __download_progress_cb(self, progress):
        self._download_icon.props.tooltip = _('Downloading')
        self._download_icon.update(progress)
'''

import logging

from gi.repository import Gtk
from gi.repository import GObject

from sugar4.graphics import style
from sugar4.graphics.toolbutton import ToolButton
from sugar4.graphics.icon import Icon
from sugar4.graphics.xocolor import XoColor


class ProgressToolButton(ToolButton):
    '''
    This button is just like a normal tool button. Because `ProgressIcon`
    is no longer available, the icon no longer fills dynamically based on a
    progress number — this class is a stub for API compatibility with
    visual progress disabled.
    '''

    __gtype_name__ = 'SugarProgressToolButton'

    def __init__(self, **kwargs):
        self._xo_color = XoColor('insensitive')
        self._icon_name = None
        self._progress = 0.0
        self._direction = 'vertical'
        self._icon = None

        ToolButton.__init__(self, **kwargs)
        # GObject should do this, but something down the ToolButton chain of
        # parents is not passing the kwargs to GObject
        if 'xo_color' in kwargs:
            self.props.xo_color = kwargs['xo_color']
        if 'icon_name' in kwargs:
            self.props.icon_name = kwargs['icon_name']
        if 'direction' in kwargs:
            self.props.direction = kwargs['direction']
        self._updated()

    @GObject.property
    def xo_color(self):
        '''
        This property defines the stroke and fill of the icon, and is
        the type :class:`sugar4.graphics.xocolor.XoColor`
        '''
        return self._xo_color

    @xo_color.setter
    def xo_color(self, new):
        self._xo_color = new
        self._updated()

    @GObject.property
    def icon_name(self):
        '''
        Icon name (same as with a :class:`sugar4.graphics.icon.Icon`), as the
        type :class:`str`
        '''
        return self._icon_name

    @icon_name.setter
    def icon_name(self, new):
        self._icon_name = new
        self._updated()

    @GObject.property
    def direction(self):
        '''
        DEPRECATED: This property is fully inert and is only
        preserved for API compatibility (specifically, kwargs/constructor
        compatibility with existing Activities that pass `direction=...`).

        Historically, it set the direction for the icon to fill as it progresses:
        * :class:`Gtk.Orientation.VERTICAL` - bottom to top
        * :class:`Gtk.Orientation.HORIZONTAL` - user's text direction
        '''
        if self._direction == 'vertical':
            return Gtk.Orientation.VERTICAL
        else:
            return Gtk.Orientation.HORIZONTAL

    @direction.setter
    def direction(self, new):
        if new == Gtk.Orientation.VERTICAL:
            self._direction = 'vertical'
        else:
            self._direction = 'horizontal'
        self._updated()

    def _updated(self):
        if self._icon_name is None:
            # We explicitly return early here to suppress the Icon widget's
            # built-in fallback to "document-generic". For a ToolButton,
            # an empty button is preferred over a misleading generic icon.
            logging.warning('ProgressToolButton updated with no icon_name set')
            return

        self._icon = Icon(
            icon_name=self._icon_name,
            pixel_size=style.STANDARD_ICON_SIZE,
            stroke_color=self._xo_color.get_stroke_color(),
            fill_color=self._xo_color.get_fill_color())
        # TODO: self._direction is stored but not currently passed to Icon.
        # Icon currently has no update() method to re-apply progress
        # after icon recreation; _progress is preserved in state only.
        self.set_icon_widget(self._icon)
        self._icon.show()

    def update(self, progress):
        '''
        Stub for API compatibility.
        Because ProgressIcon is no longer available in the toolkit,
        this method currently just stores state without visual effect.

        Note: This method explicitly calls queue_draw() for forward compatibility,
        ensuring that if a progress-rendering icon is ever reintroduced, callers
        won't need to change their code to trigger a repaint.

        Args:
            progress (float): A number between 0.0 and 1.0 representing
                              the progress percentage.
        '''
        self._progress = progress
        # Preserve queue_draw() for forward compatibility: if a progress-
        # rendering icon is ever reintroduced, callers expect update() to
        # trigger a repaint.
        self.queue_draw()
