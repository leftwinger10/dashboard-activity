# Copyright 2009 Simon Schampijer
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


import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, Pango, GObject
import logging

from gettext import gettext as _

from sugar3.activity import activity
from sugar3.activity.activity import launch_bundle
from sugar3.graphics.toolbarbox import ToolbarBox
from sugar3.graphics.icon import Icon, CellRendererIcon
from sugar3.graphics import style
from sugar3.activity.widgets import ActivityButton
from sugar3.activity.widgets import StopButton
from sugar3.datastore import datastore
from sugar3.graphics.xocolor import XoColor
from sugar3 import profile
from sugar3 import util
from jarabe.model import bundleregistry
from jarabe.journal import misc

from charts import Chart
from readers import JournalReader
from collections import Counter
import utils
import os
import time
import datetime

# logging 
_logger = logging.getLogger('analyze-journal-activity')
_logger.setLevel(logging.DEBUG)
logging.basicConfig()


class DashboardActivity(activity.Activity):

    def __init__(self, handle):

        activity.Activity.__init__(self, handle)

        self.current_chart = None
        self.x_label = ""
        self.y_label = ""
        self.chart_color = utils.get_user_fill_color('str')
        self.chart_line_color = utils.get_user_stroke_color('str')
        self.chart_data = []

        # toolbar with the new toolbar redesign
        toolbar_box = ToolbarBox()

        activity_button = ActivityButton(self)
        toolbar_box.toolbar.insert(activity_button, 0)
        activity_button.show()

        separator = Gtk.SeparatorToolItem()
        separator.props.draw = False
        separator.set_expand(True)
        toolbar_box.toolbar.insert(separator, -1)
        separator.show()

        stop_button = StopButton(self)
        toolbar_box.toolbar.insert(stop_button, -1)
        stop_button.show()

        self.set_toolbar_box(toolbar_box)
        toolbar_box.show()

        # Frane as the main container
        scrolled_window_main = Gtk.ScrolledWindow()
        scrolled_window_main.set_can_focus(False)
        scrolled_window_main.set_policy(Gtk.PolicyType.NEVER,
                                         Gtk.PolicyType.AUTOMATIC)
        scrolled_window_main.set_shadow_type(Gtk.ShadowType.NONE)
        scrolled_window_main.show()
        self.set_canvas(scrolled_window_main)

        frame = Gtk.Frame()
        scrolled_window_main.add(frame)
        frame.show()
        grid = Gtk.Grid(column_spacing=6, row_spacing=3.5)
        grid.set_border_width(20)
        grid.set_halign(Gtk.Align.CENTER)
        frame.add(grid)

        vbox_total_activities = Gtk.VBox()
        vbox_journal_entries = Gtk.VBox()
        vbox_total_contribs = Gtk.VBox()
        hbox_heatmap = Gtk.VBox()

        # VBoxes for total activities, journal entries and total files
        vbox_total_activities.override_background_color(Gtk.StateFlags.NORMAL, Gdk.RGBA(1, 1, 1, 1))
        vbox_journal_entries.override_background_color(Gtk.StateFlags.NORMAL, Gdk.RGBA(1, 1, 1, 1))
        vbox_total_contribs.override_background_color(Gtk.StateFlags.NORMAL, Gdk.RGBA(1, 1, 1, 1))
        hbox_heatmap.override_background_color(Gtk.StateFlags.NORMAL, Gdk.RGBA(1, 1, 1, 1))
       
        vbox_tree = Gtk.VBox()
        vbox_tree.override_background_color(Gtk.StateFlags.NORMAL, Gdk.RGBA(1, 1, 1, 1))

        vbox_pie = Gtk.VBox()
        vbox_pie.override_background_color(Gtk.StateFlags.NORMAL, Gdk.RGBA(1, 1, 1, 1))

        label_dashboard = Gtk.Label()
        label_dashboard.set_markup(_("<b>Dashboard</b>"))

        # label for total activities
        label_TA = Gtk.Label()
        label_TA.set_markup(_("<b>Activities Installed</b>"))
        vbox_total_activities.add(label_TA)

        label_total_activities = Gtk.Label()
        vbox_total_activities.add(label_total_activities)

        # label for total journal entries
        label_JE = Gtk.Label()
        label_JE.set_markup(_("<b>Journal Entries</b>"))
        vbox_journal_entries.add(label_JE)

        label_journal_entries = Gtk.Label()
        vbox_journal_entries.add(label_journal_entries)

        # label for files
        label_CE = Gtk.Label()
        label_CE.set_markup(_("<b>Total Files</b>"))
        vbox_total_contribs.add(label_CE)

         # label for pie
        label_PIE = Gtk.Label()
        label_PIE.set_markup(_("<b>Total Files</b>"))
    
        label_contribs = Gtk.Label()
        vbox_total_contribs.add(label_contribs)

        # empty label(s)
        label_empt = Gtk.Label("")
        label_placeholder = Gtk.Label(_("Recently opened activities"))

        # pie chart
        self.labels_and_values = ChartData(self)
        self.labels_and_values.connect("label-changed", self._label_changed)
        self.labels_and_values.connect("value-changed", self._value_changed)

        eventbox = Gtk.EventBox()
        self.charts_area = ChartArea(self)
        self.charts_area.connect('size_allocate', self._chart_size_allocate)
        eventbox.modify_bg(Gtk.StateType.NORMAL, Gdk.color_parse("white"))
        eventbox.add(self.charts_area)
        vbox_pie.pack_start(eventbox, True, True, 0)

        reader = JournalReader()
        self._graph_from_reader(reader)
        self.current_chart = Chart("pie")
        self.update_chart()     

        # font
        font_main = Pango.FontDescription("Granada 14")
        label_JE.modify_font(font_main)
        label_CE.modify_font(font_main)
        label_TA.modify_font(font_main)

        font_actual = Pango.FontDescription("12")
        label_journal_entries.modify_font(font_actual)
        label_total_activities.modify_font(font_actual)
        label_contribs.modify_font(font_actual)
        label_dashboard.modify_font(font_actual)

        # get total number of activities
        registry = bundleregistry.get_registry()
        dsobjects, journal_entries = datastore.find({})
        
        mime_types = ['image/bmp', 'image/gif', 'image/jpeg',
                        'image/png', 'image/tiff', 'application/pdf',
                        'text/plain', 'application/vnd.olpc-sugar',
                        'application/rtf', 'text/rtf', 
                        'application/epub+zip', 'text/html',
                        'application/x-pdf']
        
        self.treeview_list = []
        self.files_list = []
        self.old_list = []
        self.heatmap_list = []

        # to check journal entries which are only a file
        for dsobject in dsobjects:
            new = []
            new.append(dsobject.metadata['title'])
            new.append(misc.get_icon_name(dsobject.metadata))
            new.append(dsobject.metadata['activity_id'])
            new.append(profile.get_color())
            new.append(dsobject.get_object_id())
            new.append(dsobject.metadata)
            new.append(misc.get_date(dsobject.metadata))
            new.append(dsobject.metadata['mtime'])
            self.treeview_list.append(new)
            self.old_list.append(new)

            if dsobject.metadata['mime_type'] in mime_types:
                new2 = []
                new2.append(dsobject.metadata['title'])
                new2.append(misc.get_icon_name(dsobject.metadata))
                new2.append(dsobject.metadata['activity_id'])
                new2.append(profile.get_color())
                new2.append(dsobject.get_object_id())
                new2.append(dsobject.metadata)
                new2.append(misc.get_date(dsobject.metadata))
                new2.append(dsobject.metadata['mtime'])
                self.files_list.append(new2)

            self.old_list = sorted(self.old_list, key=lambda x:x[6])

        # treeview for Journal entries

        self.liststore = Gtk.ListStore(str, str, str, object, str, datastore.DSMetadata, str, str)
        self.treeview = Gtk.TreeView(self.liststore)
        self.treeview.set_headers_visible(False)

        for i, col_title in enumerate(["Recently Opened Activities"]):
            
            renderer_title = Gtk.CellRendererText()
            icon_renderer = CellRendererActivityIcon()
            renderer_time = Gtk.CellRendererText()

            column1 = Gtk.TreeViewColumn("Icon", icon_renderer, text=0)
            column1.add_attribute(icon_renderer, 'file-name',
                                    1)
            column1.set_sizing(Gtk.TreeViewColumnSizing.AUTOSIZE)
            column1.add_attribute(icon_renderer, 'xo-color',
                                    3)
            column2 = Gtk.TreeViewColumn(col_title, renderer_title, text=0)
            column3 = Gtk.TreeViewColumn(col_title, renderer_time, text=6)

            self.treeview.append_column(column1)
            self.treeview.append_column(column2)
            self.treeview.append_column(column3)

        # combobox for sort selection
        cbox_store = Gtk.ListStore(str)
        cbox_entries = ["All", "Files", "Oldest"]

        for item in cbox_entries:
            cbox_store.append([item])

        combobox = Gtk.ComboBox.new_with_model(cbox_store)
        combobox.connect("changed", self._on_name_combo_changed)
        renderer_text = Gtk.CellRendererText()
        combobox.pack_start(renderer_text, True)
        combobox.add_attribute(renderer_text, "text", 0)
        combobox.set_active(0)

        self._add_to_treeview(self.treeview_list)

        selected_row = self.treeview.get_selection()
        selected_row.connect("changed", self._item_select_cb)

        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.set_can_focus(False)
        scrolled_window.set_policy(Gtk.PolicyType.NEVER,
                                         Gtk.PolicyType.AUTOMATIC)
        scrolled_window.set_shadow_type(Gtk.ShadowType.NONE)
        scrolled_window.show()

        hbox_tree2 = Gtk.HBox()
        self.label_treeview = Gtk.Label(_("  Journal Entries  "))
        hbox_tree2.pack_start(self.label_treeview, False, True, 0)
        hbox_tree2.pack_start(combobox, True, True, 0)

        vbox_tree.pack_start(hbox_tree2, False, False, 5)
        scrolled_window.add(self.treeview)

        #label for recent activities
        label_rec = Gtk.Label(expand=False)
        label_rec.set_markup("<b>Recently Opened Activities</b>")
        #hbox_tree.add(label_rec)
        
        vbox_tree.add(scrolled_window)

        label_total_activities.set_text(str(len(registry)))
        label_journal_entries.set_text(str(journal_entries))
        label_contribs.set_text(str(len(self.files_list)))

        # heatmap
        label_heatmap = Gtk.Label(_("User Activity"))
        grid_heatmap = Gtk.Grid(column_spacing=3, row_spacing=2)
        grid_heatmap.set_halign(Gtk.Align.CENTER)
        hbox_heatmap.add(label_heatmap)
        hbox_heatmap.add(grid_heatmap)

        self.dates = self._generate_dates()
        self._build_heatmap(grid_heatmap, self.dates)

        self.heatmap_liststore = Gtk.ListStore(str, str, str, object, str, datastore.DSMetadata, str, str)
        heatmap_treeview = Gtk.TreeView(self.heatmap_liststore)
        heatmap_treeview.set_headers_visible(False)

        for i, col_title in enumerate(["Activity"]):
            
            renderer_title = Gtk.CellRendererText()
            icon_renderer = CellRendererActivityIcon()
            renderer_time = Gtk.CellRendererText()

            column1 = Gtk.TreeViewColumn("Icon", icon_renderer, text=0)
            column1.add_attribute(icon_renderer, 'file-name',
                                    1)
            column1.set_sizing(Gtk.TreeViewColumnSizing.AUTOSIZE)
            column1.add_attribute(icon_renderer, 'xo-color',
                                    3)
            column2 = Gtk.TreeViewColumn(col_title, renderer_title, text=0)
            column3 = Gtk.TreeViewColumn(col_title, renderer_time, text=6)

            heatmap_treeview.append_column(column1)
            heatmap_treeview.append_column(column2)
            heatmap_treeview.append_column(column3)

        hbox_heatmap.add(heatmap_treeview)

        selected_row_heatmap = heatmap_treeview.get_selection()
        selected_row_heatmap.connect("changed", self._item_select_cb)

        # add views to grid
        grid.attach(label_dashboard, 1, 2, 20, 20)
        grid.attach_next_to(vbox_total_activities, label_dashboard, Gtk.PositionType.BOTTOM, 50, 35)
        grid.attach_next_to(vbox_journal_entries, vbox_total_activities, Gtk.PositionType.RIGHT, 50, 35)
        grid.attach_next_to(vbox_total_contribs, vbox_journal_entries, Gtk.PositionType.RIGHT, 50, 35)
        grid.attach_next_to(vbox_tree, vbox_total_activities, Gtk.PositionType.BOTTOM, 75, 90)
        grid.attach_next_to(vbox_pie, vbox_tree, Gtk.PositionType.RIGHT, 75, 90)
        grid.attach_next_to(hbox_heatmap, vbox_tree, Gtk.PositionType.BOTTOM, 150, 75)
        grid.show_all()

    def _build_heatmap(self, grid, dates):
        j = 0
        k = 0
        for i in range(0, 365):
            if (i%7 == 0):
                j = j + 1
                k = 0
            k = k + 1
            count = 0 
            for x in range(0, len(self.old_list)):
                date = self.old_list[x][7][:-16]
                if date == dates[i]:
                        count = count + 1
            box = HeatMapBlock(dates[i], count, i)
            box.connect('on-clicked', self._on_clicked_cb)
            grid.attach(box, j, k, 1, 1)

    def _on_clicked_cb(self, i, index):
        _logger.info(str(index))
        self.heatmap_liststore.clear()
        del self.heatmap_list[:]
        
        for y in range(0, len(self.old_list)):
            date = self.old_list[y][7][:-16]
            if date == self.dates[index]:
                self.heatmap_list.append(self.old_list[y])
                _logger.info(self.heatmap_list[0][0])
    
        for item in self.heatmap_list:
            self.heatmap_liststore.append(item)

    def _generate_dates(self):
        year = datetime.date.today().year

        dt = datetime.datetime(year, 1, 1)
        end = datetime.datetime(year, 12, 31, 23, 59, 59)
        step = datetime.timedelta(days=1)

        result = []
        while dt < end:
            result.append(dt.strftime('%Y-%m-%d'))
            dt += step
        return result

    def _add_to_treeview(self, tlist):
        self.liststore.clear()
        for item in tlist:
            self.liststore.append(item)

    def _on_name_combo_changed(self, combo):
        tree_iter = combo.get_active_iter()
        if tree_iter is not None:
            model = combo.get_model()
            selected_item = model[tree_iter][0]
            if selected_item == "Files":
                self._add_to_treeview(self.files_list)
            elif selected_item == "All":
                self._add_to_treeview(self.treeview_list)
            elif selected_item == "Oldest":
                self._add_to_treeview(self.old_list)

    def _item_select_cb(self, selection):
        model, row = selection.get_selected()
        registry = bundleregistry.get_registry()
        bundle = registry.get_bundle(model[row][1])

        if row is not None:
            metadata = model[row][5]
            bundle_id = metadata.get('activity', '')
            launch_bundle(bundle_id, model[row][4])

    def _chart_size_allocate(self, widget, allocation):
        self._render_chart()

    def _render_chart(self):
        if self.current_chart is None or self.charts_area is None:
            return
        try:
            # Resize the chart for all the screen sizes
            alloc = self.get_allocation()
            #alloc = self.charts_area.get_allocation()

            new_width = alloc.width - 520
            new_height = alloc.height - 520

            self.current_chart.width = new_width
            self.current_chart.height = new_height

            # Set options
            self.current_chart.set_color_scheme(color=self.chart_color)
            self.current_chart.set_line_color(self.chart_line_color)

            if self.current_chart.type == "pie":
                self.current_chart.render(self)
            else:
                self.current_chart.render()
            self.charts_area.queue_draw()

        except (ZeroDivisionError, ValueError):
            pass

        return False

    def _graph_from_reader(self, reader):
        self.labels_and_values.model.clear()
        self.chart_data = []

        chart_data = reader.get_chart_data()
        horizontal, vertical = reader.get_labels_name()

        # Load the data
        for row  in chart_data:
            self._add_value(None, 
                                label=row[0], value=float(row[1]))

            self.update_chart()

    def _add_value(self, widget, label="", value="0.0"):
        data = (label, float(value))
        if not data in self.chart_data:
            pos = self.labels_and_values.add_value(label, value)
            self.chart_data.insert(pos, data)
            self._update_chart_data()

    def update_chart(self):
        if self.current_chart:
            self.current_chart.data_set(self.chart_data)
            #self.current_chart.set_title(self.metadata["title"])
            self.current_chart.set_x_label(self.x_label)
            self.current_chart.set_y_label(self.y_label)
            self._render_chart()

    def _update_chart_data(self):
        if self.current_chart is None:
            return
        self.current_chart.data_set(self.chart_data)
        self._update_chart_labels()

    def _update_chart_labels(self, title=""):
        if self.current_chart is None:
            return
        self.current_chart.set_title(title)
        self.current_chart.set_x_label(self.x_label)
        self.current_chart.set_y_label(self.y_label)
        self._render_chart()

    def _value_changed(self, treeview, path, new_value):
        path = int(path)
        self.chart_data[path] = (self.chart_data[path][0], float(new_value))
        self._update_chart_data()

    def _label_changed(self, treeview, path, new_label):
        path = int(path)
        self.chart_data[path] = (new_label, self.chart_data[path][1])
        self._update_chart_data()


class ChartArea(Gtk.DrawingArea):

    def __init__(self, parent):
        """A class for Draw the chart"""
        super(ChartArea, self).__init__()
        self._parent = parent
        self.add_events(Gdk.EventMask.EXPOSURE_MASK | Gdk.EventMask.VISIBILITY_NOTIFY_MASK)
        self.connect("draw", self._draw_cb)

    def _draw_cb(self, widget, context):
        alloc = self.get_allocation()

        # White Background:
        context.rectangle(0, 0, alloc.width, alloc.height)
        context.set_source_rgb(255, 255, 255)
        context.fill()

        # Paint the chart:
        chart_width = self._parent.current_chart.width
        chart_height = self._parent.current_chart.height

        cxpos = alloc.width / 2 - chart_width / 2
        cypos = alloc.height / 2 - chart_height / 2

        context.set_source_surface(self._parent.current_chart.surface,
                                   cxpos,
                                   cypos)
        context.paint()


class ChartData(Gtk.TreeView):

    __gsignals__ = {
             'label-changed': (GObject.SignalFlags.RUN_FIRST, None, [str, str], ),
             'value-changed': (GObject.SignalFlags.RUN_FIRST, None, [str, str], ), }

    def __init__(self, activity):

        GObject.GObject.__init__(self)


        self.model = Gtk.ListStore(str, str)
        self.set_model(self.model)

        self._selection = self.get_selection()
        self._selection.set_mode(Gtk.SelectionMode.SINGLE)

        # Label column

        column = Gtk.TreeViewColumn(_("Label"))
        label = Gtk.CellRendererText()
        label.set_property('editable', True)
        label.connect("edited", self._label_changed, self.model)

        column.pack_start(label, True)
        column.add_attribute(label, 'text', 0)
        self.append_column(column)

        # Value column

        column = Gtk.TreeViewColumn(_("Value"))
        value = Gtk.CellRendererText()
        value.set_property('editable', True)
        value.connect("edited", self._value_changed, self.model, activity)

        column.pack_start(value, True)
        column.add_attribute(value, 'text', 1)

        self.append_column(column)
        self.set_enable_search(False)

        self.show_all()

    def add_value(self, label, value):
        treestore, selected = self._selection.get_selected()
        if not selected:
            path = 0

        elif selected:
            path = int(str(self.model.get_path(selected))) + 1
        try:
            _iter = self.model.insert(path, [label, value])
        except ValueError:
            _iter = self.model.append([label, str(value)])


        self.set_cursor(self.model.get_path(_iter),
                        self.get_column(1),
                        True)

        _logger.info("Added: %s, Value: %s" % (label, value))

        return path

    def remove_selected_value(self):
        model, iter = self._selection.get_selected()
        value = (self.model.get(iter, 0)[0], float(self.model.get(iter, 1)[0]))
        _logger.info('VALUE: ' + str(value))
        self.model.remove(iter)

        return value

    def _label_changed(self, cell, path, new_text, model):
        _logger.info("Change '%s' to '%s'" % (model[path][0], new_text))
        model[path][0] = new_text

        self.emit("label-changed", str(path), new_text)

    def _value_changed(self, cell, path, new_text, model, activity):
        _logger.info("Change '%s' to '%s'" % (model[path][1], new_text))
        is_number = True
        number = new_text.replace(",", ".")
        try:
            float(number)
        except ValueError:
            is_number = False

        if is_number:
            decimals = utils.get_decimals(str(float(number)))
            new_text = locale.format('%.' + decimals + 'f', float(number))
            model[path][1] = str(new_text)

            self.emit("value-changed", str(path), number)

        elif not is_number:
            alert = Alert()

            alert.props.title = _('Invalid Value')
            alert.props.msg = \
                           _('The value must be a number (integer or decimal)')

            ok_icon = Icon(icon_name='dialog-ok')
            alert.add_button(Gtk.ResponseType.OK, _('Ok'), ok_icon)
            ok_icon.show()

            alert.connect('response', lambda a, r: activity.remove_alert(a))

            activity.add_alert(alert)

            alert.show()
            

class CellRendererActivityIcon(CellRendererIcon):
    __gtype_name__ = 'JournalCellRendererActivityIcon'

    def __init__(self):
        CellRendererIcon.__init__(self)

        self.props.width = style.GRID_CELL_SIZE
        self.props.height = style.GRID_CELL_SIZE
        self.props.size = style.STANDARD_ICON_SIZE
        self.props.mode = Gtk.CellRendererMode.ACTIVATABLE

class HeatMapBlock(Gtk.EventBox):

    __gsignals__ = {
        'on-clicked': (GObject.SignalFlags.RUN_FIRST, None,
                            (int,)),
    }

    def __init__(self, date, contribs, index):
        Gtk.EventBox.__init__(self)

        text = "   "
        label = Gtk.Label(text)
        tooltip = date + "\nContributions:" + str(contribs)
        label.set_tooltip_text(tooltip)

        self.i = index

        if contribs == 0:
            self.modify_bg(Gtk.StateType.NORMAL, Gdk.color_parse("#cdcfd3"))
        elif contribs <= 2 and contribs > 0:
            self.modify_bg(Gtk.StateType.NORMAL, Gdk.color_parse("#98abd1"))
        elif contribs <= 5 and contribs > 2:
            self.modify_bg(Gtk.StateType.NORMAL, Gdk.color_parse("#7996d1"))
        elif contribs >= 6:
            self.modify_bg(Gtk.StateType.NORMAL, Gdk.color_parse("#507bd3"))

        self.add(label)
        self.set_events(Gdk.EventType.BUTTON_PRESS)
        self.connect('button-press-event', self._on_mouse)

    def _on_mouse(self, w, e):
        self.emit('on-clicked', self.i)


