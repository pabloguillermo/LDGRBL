"""
This module provides a LightBurn-like "Cuts / Layers" panel:
a table with all operations (layers) showing their colour, mode,
speed/power, output, show and air-assist states, an editor for the
most important settings of the selected layer and a colour palette
to assign the selected elements to a layer.
"""

import wx

from meerk40t.core.elements.element_types import elem_nodes
from meerk40t.gui.laserrender import swizzlecolor

from ..kernel import Job, lookup_listener, signal_listener
from ..svgelements import Color
from .icons import (
    icon_air_off,
    icon_air_on,
    icon_ignore,
    icons8_down,
    icons8_up,
)
from .wxutils import (
    StaticBoxSizer,
    TextCtrl,
    create_menu,
    dip_size,
    wxButton,
    wxCheckBox,
    wxComboBox,
    wxListCtrl,
    wxStaticText,
)

_ = wx.GetTranslation

BUTTONSIZE = 20

COL_INDEX = 0
COL_MODE = 1
COL_SPEED_POWER = 2
COL_OUTPUT = 3
COL_SHOW = 4
COL_AIR = 5
COL_NAME = 6

# Operation types that can be chosen as layer mode
MODES = (
    ("op engrave", "Engrave"),
    ("op cut", "Cut"),
    ("op raster", "Raster"),
    ("op image", "Image"),
    ("op dots", "Dots"),
)

# Default palette, the classic LightBurn order starts with black, blue, red...
PALETTE = (
    "#000000",
    "#0000FF",
    "#FF0000",
    "#00E000",
    "#D0D000",
    "#FF8000",
    "#00E0E0",
    "#FF00FF",
    "#B4B4B4",
    "#0000A0",
    "#A00000",
    "#00A000",
    "#A0A000",
    "#C08000",
    "#00A0FF",
    "#A000A0",
)


def mode_name(optype):
    for key, label in MODES:
        if key == optype:
            return _(label)
    return optype[3:].capitalize() if optype.startswith("op ") else optype


def contrast_colour(colour):
    """Black or white, whatever is better readable on the given wx.Colour"""
    lum = 0.299 * colour.Red() + 0.587 * colour.Green() + 0.114 * colour.Blue()
    return wx.BLACK if lum > 140 else wx.WHITE


class BasicOpPanel(wx.Panel):
    """
    LightBurn-like "Cuts / Layers" interface to show operations,
    to edit their main properties and to assign elements to them.
    """

    def __init__(self, *args, context=None, **kwds):
        kwds["style"] = kwds.get("style", 0) | wx.TAB_TRAVERSAL
        wx.Panel.__init__(self, *args, **kwds)
        self.context = context
        self.context.themes.set_window_colors(self)

        # Refresh logic
        self.visible = False
        self.pending_ops = dict()
        self.ignore_refill = False
        self.filtered = False
        self._refill_job = Job(
            process=self.fill_operations,
            job_name="basicops_fillop",
            interval=0.5,
            times=1,
            run_main=True,
        )
        self.listed_ops = []
        self.selected_op = None
        self.use_percent = False
        self.use_mm_min = False
        self.std_color_back = None
        self.std_color_fore = None

        self.icon_size = dip_size(self, 18, 18)[0]
        self.image_list = wx.ImageList(self.icon_size, self.icon_size)
        self.idx_check_on = -1
        self.idx_check_off = -1
        self.idx_air = {}
        self.idx_layer = {}

        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # --- Toolbar
        tool_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.check_filtered = wxCheckBox(self, wx.ID_ANY, _("Hide unused"))
        self.check_filtered.SetToolTip(_("Suppress non-used operations"))
        self.check_filtered.SetValue(self.filtered)
        tool_sizer.Add(self.check_filtered, 1, wx.ALIGN_CENTER_VERTICAL, 0)

        bsize = dip_size(self, 25, 25)
        bmp_size = bsize[0] * 0.7 * self.context.root.bitmap_correction_scale
        self.btn_up = wxButton(self, wx.ID_ANY, size=bsize)
        self.btn_up.SetBitmap(icons8_up.GetBitmap(resize=bmp_size))
        self.btn_up.SetToolTip(_("Move the selected layer up (burnt earlier)"))
        self.btn_down = wxButton(self, wx.ID_ANY, size=bsize)
        self.btn_down.SetBitmap(icons8_down.GetBitmap(resize=bmp_size))
        self.btn_down.SetToolTip(_("Move the selected layer down (burnt later)"))
        self.btn_add = wxButton(self, wx.ID_ANY, "+", size=bsize)
        self.btn_add.SetToolTip(_("Add a new layer"))
        self.btn_config = wxButton(self, wx.ID_ANY, "...", size=bsize)
        self.btn_config.SetToolTip(_("Options for all operations"))
        for btn in (self.btn_up, self.btn_down, self.btn_add, self.btn_config):
            btn.SetMinSize(bsize)
            tool_sizer.Add(btn, 0, wx.ALIGN_CENTER_VERTICAL, 0)
        main_sizer.Add(tool_sizer, 0, wx.EXPAND, 0)

        # --- Layer table
        self.list_ops = wxListCtrl(
            self,
            wx.ID_ANY,
            style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.LC_HRULES | wx.LC_VRULES,
            context=self.context.root,
            list_name="list_cuts_layers",
        )
        self.list_ops.AppendColumn("#", format=wx.LIST_FORMAT_LEFT, width=dip_size(self, 42, -1)[0])
        self.list_ops.AppendColumn(_("Mode"), format=wx.LIST_FORMAT_LEFT, width=dip_size(self, 62, -1)[0])
        self.list_ops.AppendColumn(_("Spd/Pwr"), format=wx.LIST_FORMAT_LEFT, width=dip_size(self, 78, -1)[0])
        self.list_ops.AppendColumn(_("Output"), format=wx.LIST_FORMAT_CENTER, width=dip_size(self, 48, -1)[0])
        self.list_ops.AppendColumn(_("Show"), format=wx.LIST_FORMAT_CENTER, width=dip_size(self, 42, -1)[0])
        self.list_ops.AppendColumn(_("Air"), format=wx.LIST_FORMAT_CENTER, width=dip_size(self, 34, -1)[0])
        self.list_ops.AppendColumn(_("Name"), format=wx.LIST_FORMAT_LEFT, width=dip_size(self, 80, -1)[0])
        self.list_ops.resize_columns()
        self.list_ops.SetImageList(self.image_list, wx.IMAGE_LIST_SMALL)
        self.list_ops.SetToolTip(
            _("Click Output / Show / Air to toggle, click Mode to change the type.")
            + "\n"
            + _("Double click: open all properties of the layer")
            + "\n"
            + _("Right click: extended options for the layer")
        )
        main_sizer.Add(self.list_ops, 1, wx.EXPAND, 0)

        # --- Editor for the selected layer
        self.editor_sizer = StaticBoxSizer(
            self, wx.ID_ANY, _("Layer settings"), wx.VERTICAL
        )
        grid = wx.FlexGridSizer(cols=4, vgap=2, hgap=4)
        grid.AddGrowableCol(1, 1)
        grid.AddGrowableCol(3, 1)

        def textbox(check="float"):
            ctrl = TextCtrl(
                self,
                wx.ID_ANY,
                "",
                limited=True,
                check=check,
                style=wx.TE_PROCESS_ENTER,
                nonzero=True,
            )
            ctrl.SetMinSize(dip_size(self, 45, -1))
            return ctrl

        self.label_speed = wxStaticText(self, wx.ID_ANY, _("Speed"))
        self.text_speed = textbox()
        self.label_power = wxStaticText(self, wx.ID_ANY, _("Power"))
        self.text_power = textbox()
        self.label_passes = wxStaticText(self, wx.ID_ANY, _("Passes"))
        self.text_passes = textbox("int")
        self.label_dpi = wxStaticText(self, wx.ID_ANY, _("DPI"))
        self.text_dpi = textbox("int")
        self.text_passes.SetToolTip(_("How often shall this layer be burnt"))
        self.text_dpi.SetToolTip(_("Resolution (line interval) of raster / image layers"))
        for ctrl in (
            self.label_speed,
            self.text_speed,
            self.label_power,
            self.text_power,
            self.label_passes,
            self.text_passes,
            self.label_dpi,
            self.text_dpi,
        ):
            flag = wx.ALIGN_CENTER_VERTICAL
            if isinstance(ctrl, TextCtrl):
                flag |= wx.EXPAND
            grid.Add(ctrl, 1 if isinstance(ctrl, TextCtrl) else 0, flag, 0)
        self.label_no_layer = wxStaticText(
            self, wx.ID_ANY, _("Select a layer in the table to edit it")
        )
        self.editor_sizer.Add(self.label_no_layer, 0, wx.EXPAND | wx.ALL, 2)
        self.editor_grid = grid
        self.editor_sizer.Add(grid, 0, wx.EXPAND, 0)

        edit_btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_assign = wxButton(self, wx.ID_ANY, _("Assign selection"))
        self.btn_assign.SetToolTip(
            _("Assign the selected elements to the selected layer.")
        )
        self.btn_properties = wxButton(self, wx.ID_ANY, _("All properties..."))
        self.btn_properties.SetToolTip(
            _("Open the property dialog for the selected layer")
        )
        edit_btn_sizer.Add(self.btn_assign, 1, wx.EXPAND, 0)
        edit_btn_sizer.Add(self.btn_properties, 1, wx.EXPAND, 0)
        self.editor_sizer.Add(edit_btn_sizer, 0, wx.EXPAND, 0)
        main_sizer.Add(self.editor_sizer, 0, wx.EXPAND, 0)

        # --- Colour palette
        palette_sizer = wx.WrapSizer(wx.HORIZONTAL)
        swatch = dip_size(self, 18, 18)
        for hexcolor in PALETTE:
            btn = wx.Panel(self, wx.ID_ANY, size=swatch, style=wx.BORDER_SIMPLE)
            btn.SetMinSize(swatch)
            btn.SetBackgroundColour(wx.Colour(hexcolor))
            btn.SetToolTip(
                _("Assign the selected elements to the layer with this colour")
                + "\n"
                + _("(a new layer will be created if there is none)")
            )
            btn.Bind(wx.EVT_LEFT_DOWN, self.on_palette(hexcolor))
            palette_sizer.Add(btn, 0, wx.ALL, 1)
        main_sizer.Add(palette_sizer, 0, wx.EXPAND | wx.TOP, 2)

        # --- Classification options
        choices = [
            _("Leave color"),
            _("Op inherits color"),
            _("Elem inherits color"),
        ]
        self.combo_apply_color = wxComboBox(
            self,
            wx.ID_ANY,
            choices=choices,
            value=choices[0],
            style=wx.CB_READONLY | wx.CB_DROPDOWN,
        )
        self.check_exclusive = wxCheckBox(self, wx.ID_ANY, _("Exclusive"))
        self.check_all_similar = wxCheckBox(self, wx.ID_ANY, _("Similar"))
        self.combo_apply_color.SetToolTip(
            _(
                "Leave - neither the color of the operation nor of the elements will be changed"
            )
            + "\n"
            + _("-> OP - the assigned operation will adopt the color of the element")
            + "\n"
            + _("-> Elem - the elements will adopt the color of the assigned operation")
        )
        self.check_all_similar.SetToolTip(
            _("Assign as well all other elements with the same stroke-color")
        )
        self.check_exclusive.SetToolTip(
            _(
                "When assigning to an operation remove all assignments of the elements to other operations"
            )
        )
        self.context.elements.setting(bool, "classify_inherit_exclusive", True)
        self.context.elements.setting(bool, "classify_all_similar", True)
        self.context.elements.setting(int, "classify_impose_default", 0)
        self.check_exclusive.SetValue(self.context.elements.classify_inherit_exclusive)
        self.check_all_similar.SetValue(self.context.elements.classify_all_similar)
        self.combo_apply_color.SetSelection(
            self.context.elements.classify_impose_default
        )
        classif_sizer = StaticBoxSizer(
            self, wx.ID_ANY, _("Classification"), wx.HORIZONTAL
        )
        classif_sizer.Add(self.combo_apply_color, 1, wx.ALIGN_CENTER_VERTICAL, 0)
        classif_sizer.Add(self.check_exclusive, 0, wx.ALIGN_CENTER_VERTICAL, 0)
        classif_sizer.Add(self.check_all_similar, 0, wx.ALIGN_CENTER_VERTICAL, 0)
        main_sizer.Add(classif_sizer, 0, wx.EXPAND, 0)

        self.SetSizer(main_sizer)
        self.Layout()

        # --- Events
        self.check_filtered.Bind(wx.EVT_CHECKBOX, self.on_check_filtered)
        self.check_exclusive.Bind(wx.EVT_CHECKBOX, self.on_check_exclusive)
        self.check_all_similar.Bind(wx.EVT_CHECKBOX, self.on_check_allsimilar)
        self.combo_apply_color.Bind(wx.EVT_COMBOBOX, self.on_combo_color)
        self.btn_up.Bind(wx.EVT_BUTTON, self.on_move(-1))
        self.btn_down.Bind(wx.EVT_BUTTON, self.on_move(1))
        self.btn_add.Bind(wx.EVT_BUTTON, self.on_add_layer)
        self.btn_config.Bind(wx.EVT_BUTTON, self.on_config)
        self.btn_assign.Bind(wx.EVT_BUTTON, self.on_assign)
        self.btn_properties.Bind(wx.EVT_BUTTON, self.on_properties)
        self.list_ops.Bind(wx.EVT_LEFT_DOWN, self.on_list_left)
        self.list_ops.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_list_selected)
        self.list_ops.Bind(wx.EVT_LIST_ITEM_DESELECTED, self.on_list_deselected)
        self.list_ops.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_properties)
        self.list_ops.Bind(wx.EVT_LIST_ITEM_RIGHT_CLICK, self.on_list_right)
        self.text_speed.SetActionRoutine(self.on_text_speed)
        self.text_power.SetActionRoutine(self.on_text_power)
        self.text_passes.SetActionRoutine(self.on_text_passes)
        self.text_dpi.SetActionRoutine(self.on_text_dpi)

        self.set_display()
        self.build_static_images()
        self.update_editor()

    # ------------------------------------------------------------------
    # Images
    # ------------------------------------------------------------------

    def _checkbox_bitmap(self, checked):
        size = self.icon_size
        bmp = wx.Bitmap(size, size)
        dc = wx.MemoryDC(bmp)
        dc.SetBackground(wx.Brush(self.list_ops.GetBackgroundColour()))
        dc.Clear()
        flags = wx.CONTROL_CHECKED if checked else 0
        margin = max(1, size // 8)
        wx.RendererNative.Get().DrawCheckBox(
            self.list_ops,
            dc,
            wx.Rect(margin, margin, size - 2 * margin, size - 2 * margin),
            flags,
        )
        dc.SelectObject(wx.NullBitmap)
        return bmp

    def _layer_bitmap(self, colour, index):
        size = self.icon_size
        bmp = wx.Bitmap(size, size)
        dc = wx.MemoryDC(bmp)
        dc.SetBackground(wx.Brush(self.list_ops.GetBackgroundColour()))
        dc.Clear()
        dc.SetPen(wx.Pen(wx.Colour(80, 80, 80)))
        dc.SetBrush(wx.Brush(colour))
        dc.DrawRectangle(0, 0, size, size)
        font = self.list_ops.GetFont()
        font.SetPointSize(max(6, font.GetPointSize() - 2))
        dc.SetFont(font)
        dc.SetTextForeground(contrast_colour(colour))
        label = f"{index:02d}"
        tw, th = dc.GetTextExtent(label)
        dc.DrawText(label, (size - tw) // 2, (size - th) // 2)
        dc.SelectObject(wx.NullBitmap)
        return bmp

    def _fit_bitmap(self, bmp):
        if bmp.GetWidth() == self.icon_size and bmp.GetHeight() == self.icon_size:
            return bmp
        img = bmp.ConvertToImage()
        img = img.Scale(self.icon_size, self.icon_size, wx.IMAGE_QUALITY_HIGH)
        return wx.Bitmap(img)

    def build_static_images(self):
        self.image_list.RemoveAll()
        self.idx_layer = {}
        self.idx_check_on = self.image_list.Add(self._checkbox_bitmap(True))
        self.idx_check_off = self.image_list.Add(self._checkbox_bitmap(False))
        isize = self.icon_size
        air_icons = {
            0: icon_ignore.GetBitmap(resize=isize),
            1: icon_air_on.GetBitmap(resize=isize, color="green"),
            2: icon_air_off.GetBitmap(resize=isize, color="red"),
        }
        self.idx_air = {
            key: self.image_list.Add(self._fit_bitmap(bmp))
            for key, bmp in air_icons.items()
        }

    def layer_image(self, op, index):
        col = op.color
        if col is not None and col.argb is not None:
            colour = wx.Colour(swizzlecolor(col))
        else:
            colour = wx.LIGHT_GREY
        key = (colour.GetRGB(), index)
        if key not in self.idx_layer:
            self.idx_layer[key] = self.image_list.Add(self._layer_bitmap(colour, index))
        return self.idx_layer[key]

    # ------------------------------------------------------------------
    # Display helpers
    # ------------------------------------------------------------------

    def set_display(self):
        dev = self.context.device
        if dev is None:
            dev = self.context.root
        dev.setting(bool, "use_percent_for_power_display", False)
        self.use_percent = dev.use_percent_for_power_display
        dev.setting(bool, "use_mm_min_for_speed_display", False)
        self.use_mm_min = dev.use_mm_min_for_speed_display
        speed_unit = "mm/min" if self.use_mm_min else "mm/s"
        power_unit = "%" if self.use_percent else "ppi"
        self.label_speed.SetLabel(_("Speed") + f" ({speed_unit})")
        self.label_power.SetLabel(_("Power") + f" ({power_unit})")
        self.text_speed.SetToolTip(_("Speed ({unit})").format(unit=speed_unit))
        self.text_power.SetToolTip(_("Power ({unit})").format(unit=power_unit))

    def speed_text(self, op):
        value = getattr(op, "speed", None)
        if value is None:
            return ""
        if self.use_mm_min:
            return f"{value * 60:.0f}"
        return f"{value:.1f}"

    def power_text(self, op):
        value = getattr(op, "power", None)
        if value is None:
            return ""
        if self.use_percent:
            return f"{value / 10:.1f}"
        return f"{value:.0f}"

    @staticmethod
    def passes_value(op):
        if getattr(op, "passes_custom", False):
            return max(1, op.passes or 1)
        return 1

    def fill_row(self, row, op):
        index = self.listed_ops.index(op)
        self.list_ops.SetItem(row, COL_INDEX, "", self.layer_image(op, index))
        self.list_ops.SetItem(row, COL_MODE, mode_name(op.type))
        spd_pwr = ""
        if hasattr(op, "speed") and hasattr(op, "power"):
            spd_pwr = f"{self.speed_text(op)} / {self.power_text(op)}"
        passes = self.passes_value(op)
        if passes > 1:
            spd_pwr = f"{passes}x {spd_pwr}"
        self.list_ops.SetItem(row, COL_SPEED_POWER, spd_pwr)
        output = bool(getattr(op, "output", True))
        self.list_ops.SetItem(
            row,
            COL_OUTPUT,
            "",
            self.idx_check_on if output else self.idx_check_off,
        )
        visible = bool(getattr(op, "is_visible", True)) or output
        self.list_ops.SetItem(
            row,
            COL_SHOW,
            "",
            self.idx_check_on if visible else self.idx_check_off,
        )
        coolant = getattr(op, "coolant", 0)
        if coolant is None or coolant not in self.idx_air:
            coolant = 0
        self.list_ops.SetItem(row, COL_AIR, "", self.idx_air[coolant])
        label = op.display_label() if op.label is not None else ""
        self.list_ops.SetItem(row, COL_NAME, label or "")

    def refresh_op(self, op):
        try:
            row = self.listed_ops.index(op)
        except ValueError:
            return
        self.fill_row(row, op)

    # ------------------------------------------------------------------
    # Table population
    # ------------------------------------------------------------------

    def fill_operations(self):
        if self.context.kernel.is_shutdown:
            return
        try:
            self.list_ops.Freeze()
        except RuntimeError:
            return
        self.list_ops.DeleteAllItems()
        self.build_static_images()
        self.listed_ops = []
        for op in list(self.context.elements.ops()):
            if op is None or not op.type.startswith("op "):
                continue
            if self.filtered and len(op.children) == 0:
                continue
            self.listed_ops.append(op)
        selected_row = -1
        for row, op in enumerate(self.listed_ops):
            self.list_ops.InsertItem(row, "")
            self.fill_row(row, op)
            if op is self.selected_op:
                selected_row = row
        if self.std_color_back is None:
            self.std_color_back = self.list_ops.GetBackgroundColour()
            self.std_color_fore = self.list_ops.GetForegroundColour()
        if selected_row >= 0:
            self.list_ops.Select(selected_row)
            self.list_ops.EnsureVisible(selected_row)
        else:
            self.selected_op = None
        self.list_ops.Thaw()
        self.highlight_operations(source="fill_operations")
        self.update_editor()

    def highlight_operations(self, source=None):
        if self.std_color_back is None:
            return
        highlight_back = wx.SystemSettings().GetColour(wx.SYS_COLOUR_HIGHLIGHT)
        highlight_back = highlight_back.ChangeLightness(160)
        active_ops = set()
        emphasized = set(
            self.context.elements.flat(types=elem_nodes, emphasized=True)
        )
        if emphasized:
            for op in self.listed_ops:
                for node in op.children:
                    if node.type == "reference":
                        node = node.node
                    if node in emphasized:
                        active_ops.add(op)
                        break
        for row, op in enumerate(self.listed_ops):
            if row >= self.list_ops.GetItemCount():
                break
            if op in active_ops:
                self.list_ops.SetItemBackgroundColour(row, highlight_back)
                self.list_ops.SetItemTextColour(row, contrast_colour(highlight_back))
            else:
                self.list_ops.SetItemBackgroundColour(row, self.std_color_back)
                self.list_ops.SetItemTextColour(row, self.std_color_fore)

    # ------------------------------------------------------------------
    # Editor
    # ------------------------------------------------------------------

    def update_editor(self):
        op = self.selected_op
        has_op = op is not None
        for ctrl in (self.btn_up, self.btn_down, self.btn_assign, self.btn_properties):
            ctrl.Enable(has_op)
        self.label_no_layer.Show(not has_op)
        self.editor_grid.ShowItems(has_op)
        if not has_op:
            self.editor_sizer.SetLabel(_("Layer settings"))
            self.Layout()
            return
        title = mode_name(op.type)
        if op.label:
            title += ": " + op.display_label()
        self.editor_sizer.SetLabel(title)
        self.text_speed.Enable(hasattr(op, "speed"))
        self.text_speed.SetValue(self.speed_text(op))
        self.text_power.Enable(hasattr(op, "power"))
        self.text_power.SetValue(self.power_text(op))
        self.text_passes.Enable(hasattr(op, "passes"))
        self.text_passes.SetValue(str(self.passes_value(op)))
        has_dpi = op.type in ("op raster", "op image") and hasattr(op, "dpi")
        self.label_dpi.Show(has_dpi)
        self.text_dpi.Show(has_dpi)
        if has_dpi:
            self.text_dpi.SetValue(str(int(op.dpi)))
        self.Layout()

    def _changed(self, op, field):
        self.ignore_refill = True
        self.refresh_op(op)
        self.context.elements.signal("element_property_reload", [op], field)

    def on_text_speed(self):
        op = self.selected_op
        if op is None or not hasattr(op, "speed"):
            return
        try:
            value = float(self.text_speed.GetValue())
        except ValueError:
            return
        if self.use_mm_min:
            value /= 60
        if op.speed != value:
            op.speed = value
            self._changed(op, "text_speed")

    def on_text_power(self):
        op = self.selected_op
        if op is None or not hasattr(op, "power"):
            return
        try:
            value = float(self.text_power.GetValue())
        except ValueError:
            return
        if self.use_percent:
            value *= 10
        if op.power != value:
            op.power = value
            self._changed(op, "text_power")

    def on_text_passes(self):
        op = self.selected_op
        if op is None or not hasattr(op, "passes"):
            return
        try:
            value = max(1, int(self.text_passes.GetValue()))
        except ValueError:
            return
        if value != self.passes_value(op):
            op.passes = value
            op.passes_custom = value != 1
            self._changed(op, "text_passes")

    def on_text_dpi(self):
        op = self.selected_op
        if op is None or not hasattr(op, "dpi"):
            return
        try:
            value = int(self.text_dpi.GetValue())
        except ValueError:
            return
        if value > 0 and op.dpi != value:
            op.dpi = value
            self._changed(op, "text_dpi")

    # ------------------------------------------------------------------
    # Table events
    # ------------------------------------------------------------------

    def _op_at_row(self, row):
        if 0 <= row < len(self.listed_ops):
            return self.listed_ops[row]
        return None

    def on_list_selected(self, event):
        self.selected_op = self._op_at_row(event.GetIndex())
        self.update_editor()

    def on_list_deselected(self, event):
        if self.list_ops.GetSelectedItemCount() == 0:
            self.selected_op = None
            self.update_editor()

    def on_list_left(self, event):
        event.Skip()
        row, flags, col = self.list_ops.HitTestSubItem(event.GetPosition())
        op = self._op_at_row(row)
        if op is None:
            return
        if col == COL_OUTPUT:
            self.toggle_output(op)
        elif col == COL_SHOW:
            self.toggle_show(op)
        elif col == COL_AIR:
            self.toggle_air(op)
        elif col == COL_MODE:
            wx.CallAfter(self.popup_mode_menu, op)

    def on_list_right(self, event):
        op = self._op_at_row(event.GetIndex())
        if op is None:
            return
        op.selected = True
        create_menu(self, op, self.context.elements)

    def toggle_output(self, op):
        if not hasattr(op, "output"):
            return
        op.output = not op.output
        if op.output and hasattr(op, "is_visible"):
            op.is_visible = True
        op.updated()
        self._changed(op, "output")
        self.context.elements.signal("warn_state_update", "")
        self.context.elements.signal("refresh_scene", "Scene")

    def toggle_show(self, op):
        if not hasattr(op, "is_visible"):
            return
        if getattr(op, "output", False):
            # Burnt layers are always shown
            return
        op.is_visible = not op.is_visible
        op.updated()
        self.context.elements.validate_selected_area()
        self._changed(op, "is_visible")
        self.context.elements.signal("refresh_scene", "Scene")

    def toggle_air(self, op):
        if not hasattr(op, "coolant"):
            return
        value = op.coolant
        if value is None:
            value = 0
        value = (value + 1) % 3
        op.coolant = value
        op.updated()
        self._changed(op, "coolant")

    def popup_mode_menu(self, op):
        menu = wx.Menu()
        for optype, label in MODES:
            item = menu.AppendRadioItem(wx.ID_ANY, _(label))
            item.Check(optype == op.type)
            self.Bind(wx.EVT_MENU, self.on_change_mode(op, optype), item)
        self.PopupMenu(menu)
        menu.Destroy()

    def on_change_mode(self, op, optype):
        def handler(event):
            if op.type == optype:
                return
            elements = self.context.elements
            new_settings = dict(op.settings)
            new_settings["type"] = optype
            with elements.undoscope("Convert operation"):
                new_op = op.replace_node(keep_children=True, **new_settings)
            if self.selected_op is op:
                self.selected_op = new_op
            elements.signal("rebuild_tree", "operations")

        return handler

    # ------------------------------------------------------------------
    # Toolbar / editor buttons
    # ------------------------------------------------------------------

    def on_check_filtered(self, event):
        self.filtered = self.check_filtered.GetValue()
        self.context.schedule(self._refill_job)

    def on_move(self, direction):
        def handler(event):
            op = self.selected_op
            if op is None:
                return
            elements = self.context.elements
            children = elements.op_branch._children
            try:
                idx = children.index(op)
            except ValueError:
                return
            # Skip over hidden (filtered) operations
            target = idx + direction
            while 0 <= target < len(children) and children[target] not in self.listed_ops:
                target += direction
            if target < 0 or target >= len(children):
                return
            with elements.undoscope("Operation order"):
                children.pop(idx)
                children.insert(target, op)
            if hasattr(elements, "_invalidate_ops_cache"):
                elements._invalidate_ops_cache()
            elements.signal("rebuild_tree", "operations")

        return handler

    def on_add_layer(self, event):
        menu = wx.Menu()
        for optype, label in MODES:
            item = menu.Append(wx.ID_ANY, _(label))
            self.Bind(wx.EVT_MENU, self.on_add_type(optype), item)
        self.PopupMenu(menu)
        menu.Destroy()

    def on_add_type(self, optype, color=None):
        def handler(event):
            self.add_layer(optype, color)

        return handler

    def add_layer(self, optype, color=None):
        elements = self.context.elements
        kwargs = {}
        if color is not None:
            kwargs["color"] = Color(color)
        with elements.undoscope("Add operation"):
            op = elements.op_branch.add(type=optype, **kwargs)
        self.selected_op = op
        elements.signal("add_operation", op)
        return op

    def on_palette(self, hexcolor):
        def handler(event):
            target = Color(hexcolor)
            op = None
            for candidate in self.context.elements.ops():
                if not candidate.type.startswith("op "):
                    continue
                col = candidate.color
                if col is not None and Color.distance(col, target) < 1:
                    op = candidate
                    break
            if not list(self.context.elements.elems(emphasized=True)):
                if op is not None:
                    self.select_op(op)
                return
            if op is None:
                op = self.add_layer("op engrave", hexcolor)
            self.execute_single(op, "auto")
            self.select_op(op)

        return handler

    def select_op(self, op):
        self.selected_op = op
        try:
            row = self.listed_ops.index(op)
        except ValueError:
            self.context.schedule(self._refill_job)
            return
        self.list_ops.Select(row)
        self.list_ops.EnsureVisible(row)
        self.update_editor()

    def on_assign(self, event):
        if self.selected_op is not None:
            self.execute_single(self.selected_op, "auto")

    def on_properties(self, event):
        op = self.selected_op
        if op is None:
            return
        activate = self.context.kernel.lookup("function/open_property_window_for_node")
        if activate is not None:
            op.selected = True
            activate(op)

    def on_combo_color(self, event):
        value = self.combo_apply_color.GetCurrentSelection()
        self.context.elements.classify_impose_default = value

    def on_check_exclusive(self, event):
        newval = self.check_exclusive.GetValue()
        self.context.elements.classify_inherit_exclusive = newval

    def on_check_allsimilar(self, event):
        newval = self.check_all_similar.GetValue()
        self.context.elements.classify_all_similar = newval

    def execute_single(self, targetop, attrib):
        data = list(self.context.elements.flat(emphasized=True))
        idx = self.context.elements.classify_impose_default
        if idx == 1:
            impose = "to_op"
        elif idx == 2:
            impose = "to_elem"
        else:
            impose = None
        similar = self.context.elements.classify_all_similar
        exclusive = self.context.elements.classify_inherit_exclusive
        if len(data) == 0:
            return
        self.context.elements.assign_operation(
            op_assign=targetop,
            data=data,
            impose=impose,
            attrib=attrib,
            similar=similar,
            exclusive=exclusive,
        )

    def on_config(self, event):
        mynode = self.context.elements.op_branch
        mynode.selected = True
        create_menu(self, mynode, self.context.elements)

    # ------------------------------------------------------------------
    # Pane / signal handling
    # ------------------------------------------------------------------

    def pane_show(self, *args):
        self.visible = True
        if "set_display" in self.pending_ops:
            self.set_display()
        if "ask_for_refill" in self.pending_ops or not self.listed_ops:
            self.ask_for_refill()
            # Ask for refill will also highlight, so no need to check this
        elif "highlight_operations" in self.pending_ops:
            self.highlight_operations(source="pane_show")

        self.pending_ops = dict()

    def pane_hide(self, *args):
        self.visible = False

    @signal_listener("element_property_update")
    @signal_listener("element_property_reload")
    def signal_handler_update(self, origin, *args, **kwargs):
        if not self.visible:
            self.pending_ops["ask_for_refill"] = True
            return

        hadops = False
        if len(args) > 0:
            if isinstance(args[0], (list, tuple)):
                myl = args[0]
            else:
                if args[0] is self.context.elements.op_branch:
                    myl = list(self.context.elements.ops())
                else:
                    myl = [args[0]]
            for n in myl:
                if n.type.startswith("op "):
                    hadops = True
                    break
        if hadops:
            self.ask_for_refill()

    @signal_listener("rebuild_tree")
    @signal_listener("refresh_tree")
    @signal_listener("tree_changed")
    @signal_listener("operation_removed")
    @signal_listener("add_operation")
    @signal_listener("warn_state_update")
    def signal_handler_rebuild(self, origin, *args, **kwargs):
        if not self.visible:
            self.pending_ops["ask_for_refill"] = True
            return

        self.ask_for_refill()

    def ask_for_refill(self):
        # Endless cup
        if self.ignore_refill:
            self.ignore_refill = False
            return
        self.context.schedule(self._refill_job)

    @signal_listener("power_percent")
    @signal_listener("speed_min")
    @lookup_listener("service/device/active")
    def on_device_update(self, *args):
        if not self.visible:
            self.pending_ops["set_display"] = True
            self.pending_ops["ask_for_refill"] = True
            return

        self.set_display()
        self.ask_for_refill()

    @signal_listener("emphasized")
    def signal_handler_emphasized(self, origin, *args, **kwargs):
        if not self.IsShown():
            self.pending_ops["highlight_operations"] = True
            return
        self.context.elements.set_start_time("BasicOpPanel")
        self.highlight_operations(source="emphasized")
        self.context.elements.set_end_time(
            "BasicOpPanel", message=f"vis={self.visible}"
        )
