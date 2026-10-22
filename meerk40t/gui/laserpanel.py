import platform

import wx
from wx import aui

from meerk40t.gui.choicepropertypanel import ChoicePropertyPanel
from meerk40t.core.planner import START_FROM_ABSOLUTE, START_FROM_USER_ORIGIN
from meerk40t.core.units import Length
from meerk40t.gui.icons import (
    get_default_icon_size,
    icons8_home_filled,
    icons8_place_marker,
    icons8_user_location,
    icon_closed_door,
    icon_open_door,
    icon_update_plan,
    icons8_computer_support,
    icons8_delete,
    icons8_emergency_stop_button,
    icons8_gas_industry,
    icons8_laser_beam_hazard,
    icons8_pause,
    icons8_pentagon,
    icons8_save,
)
from meerk40t.gui.navigationpanels import Drag, Jog, JogDistancePanel, MovePanel
from meerk40t.gui.wxutils import (
    HoverButton,
    ScrolledPanel,
    StaticBoxSizer,
    TextCtrl,
    dip_size,
    disable_window,
    wxButton,
    wxCheckBox,
    wxComboBox,
    wxStaticText,
)
from meerk40t.kernel import lookup_listener, signal_listener

_ = wx.GetTranslation


def register_panel_laser(window, context):
    laser_panel = LaserPanel(window, wx.ID_ANY, context=context)
    plan_panel = JobPanel(window, wx.ID_ANY, context=context)

    optimize_panel = OptimizePanel(window, wx.ID_ANY, context=context)
    # jog_drag = wx.Panel(window, wx.ID_ANY)
    jog_drag = ScrolledPanel(window, wx.ID_ANY)
    jog_drag.SetupScrolling()
    jog_panel = Jog(jog_drag, wx.ID_ANY, context=context, suppress_z_controls=True)
    drag_panel = Drag(jog_drag, wx.ID_ANY, context=context)
    distance_panel = JogDistancePanel(jog_drag, wx.ID_ANY, context=context)
    main_sizer = wx.BoxSizer(wx.VERTICAL)
    sub_sizer = wx.BoxSizer(wx.HORIZONTAL)
    # main_sizer.AddStretchSpacer()
    sub_sizer.Add(jog_panel, 1, wx.ALIGN_CENTER_VERTICAL, 0)
    sub_sizer.Add(drag_panel, 1, wx.ALIGN_CENTER_VERTICAL, 0)
    main_sizer.Add(sub_sizer, 1, wx.EXPAND, 0)
    main_sizer.Add(distance_panel, 0, wx.EXPAND, 0)
    # main_sizer.AddStretchSpacer()
    jog_drag.SetSizer(main_sizer)
    jog_drag.Layout()
    move_panel = MovePanel(window, wx.ID_ANY, context=context)
    notebook = wx.aui.AuiNotebook(
        window,
        -1,
        style=wx.aui.AUI_NB_TAB_EXTERNAL_MOVE
        | wx.aui.AUI_NB_SCROLL_BUTTONS
        | wx.aui.AUI_NB_TAB_SPLIT
        | wx.aui.AUI_NB_TAB_MOVE
        | wx.aui.AUI_NB_BOTTOM,
    )
    # ARGGH, the color setting via the ArtProvider does only work
    # if you set the tabs to the bottom! wx.aui.AUI_NB_BOTTOM
    context.themes.set_window_colors(notebook)
    bg_std = context.themes.get("win_bg")
    bg_active = context.themes.get("highlight")
    notebook.GetArtProvider().SetColour(bg_std)
    notebook.GetArtProvider().SetActiveColour(bg_active)

    pane = (
        aui.AuiPaneInfo()
        .Right()
        .MinSize(200, 180)
        .BestSize(300, 270)
        .FloatingSize(300, 270)
        .Caption(_("Laser-Control"))
        .CaptionVisible(not context.pane_lock)
        .Name("laser")
    )
    pane.submenu = "_10_" + _("Laser")
    pane.helptext = _("Laser job control panel")
    pane.control = notebook
    pane.dock_proportion = 270
    notebook.AddPage(laser_panel, _("Laser"))
    notebook.AddPage(jog_drag, _("Jog"))
    notebook.AddPage(plan_panel, _("Plan"))
    notebook.AddPage(optimize_panel, _("Optimize"))
    notebook.AddPage(move_panel, _("Move"))

    def on_page_change(event):
        event.Skip()
        page = notebook.GetCurrentPage()
        if page is None:
            return
        pages = [jog_panel, drag_panel, distance_panel] if page is jog_drag else [page]
        for p in pages:
            if hasattr(p, "pane_show"):
                p.pane_show()

    notebook.Bind(aui.EVT_AUINOTEBOOK_PAGE_CHANGED, on_page_change)
    window.on_pane_create(pane)
    window.context.register("pane/laser", pane)
    choices = [
        {
            "attr": "laserpane_arm",
            "object": context.root,
            "default": False,
            "type": bool,
            "label": _("Enable Laser Arm"),
            "tip": _("Enable Laser Panel Arm/Disarm feature."),
            "page": "Laser",
            # Hint for translation _("General")
            "section": "General",
        },
    ]
    context.kernel.register_choices("preferences", choices)

    def on_resize(event):
        wb_size = jog_drag.ClientSize
        if platform.system() == "Linux":
            # They don't resize well
            panel_size = (max(20, wb_size[0] / 2 - 40), wb_size[1])
        else:
            panel_size = (wb_size[0] / 2, wb_size[1])

        for panel in (jog_panel, drag_panel, distance_panel):
            if hasattr(panel, "set_icons"):
                panel.set_icons(dimension=panel_size)

    jog_drag.Bind(wx.EVT_SIZE, on_resize)


class LaserPanel(wx.Panel):
    """
    Contains all elements to control the execution of the job
    """

    def __init__(self, *args, context=None, **kwds):
        # begin wxGlade: MovePanel.__init__
        kwds["style"] = kwds.get("style", 0) | wx.TAB_TRAVERSAL
        wx.Panel.__init__(self, *args, **kwds)
        self.context = context
        self.context.themes.set_window_colors(self)
        self.SetHelpText("laserpanel")
        self.context.root.setting(bool, "laserpane_arm", True)
        root = self.context.root
        root.setting(int, "job_start_from", START_FROM_ABSOLUTE)
        root.setting(int, "job_origin", 0)
        root.setting(bool, "job_cut_selected", False)
        root.setting(bool, "job_use_selection_origin", False)

        sizer_main = wx.BoxSizer(wx.VERTICAL)
        self.icon_size = 0.5 * get_default_icon_size(self.context)

        self.sizer_devices = StaticBoxSizer(self, wx.ID_ANY, _("Device"), wx.HORIZONTAL)
        sizer_main.Add(self.sizer_devices, 0, wx.EXPAND, 0)

        # Devices Initialize.
        self.available_devices = self.context.kernel.services("device")

        self.combo_devices = wxComboBox(
            self, wx.ID_ANY, style=wx.CB_DROPDOWN | wx.CB_READONLY
        )
        self.combo_devices.SetToolTip(
            _("Select device from list of configured devices")
        )
        ss = dip_size(self, 23, 23)
        bsize = ss[0] * self.context.root.bitmap_correction_scale
        self.btn_config_laser = wxButton(self, wx.ID_ANY, size=ss)
        self.btn_config_laser.SetBitmap(icons8_computer_support.GetBitmap(resize=bsize))
        self.btn_config_laser.SetToolTip(
            _("Opens device-specific configuration window")
        )
        kernel = self.context.kernel
        if (
            hasattr(kernel.args, "lock_device_config")
            and kernel.args.lock_device_config
        ):
            self.btn_config_laser.Enable(False)
        self.sizer_devices.Add(self.combo_devices, 1, wx.EXPAND, 0)
        minsize = 32
        self.btn_config_laser.SetMinSize(dip_size(self, minsize, -1))
        self.sizer_devices.Add(self.btn_config_laser, 0, wx.EXPAND, 0)

        # Laser position, like the status line of LightBurn's laser window
        sizer_position = wx.BoxSizer(wx.HORIZONTAL)
        self.label_position = wxStaticText(self, wx.ID_ANY, "")
        self.label_position.SetToolTip(
            _("Last known position of the laser head (double click to refresh)")
        )
        self.label_origin = wxStaticText(self, wx.ID_ANY, "", style=wx.ALIGN_RIGHT)
        self.label_origin.SetToolTip(_("User origin of the active device"))
        sizer_position.Add(self.label_position, 1, wx.ALIGN_CENTER_VERTICAL, 0)
        sizer_position.Add(self.label_origin, 1, wx.ALIGN_CENTER_VERTICAL, 0)
        sizer_main.Add(sizer_position, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 4)

        sizer_control = wx.BoxSizer(wx.HORIZONTAL)
        sizer_main.Add(sizer_control, 0, wx.EXPAND, 0)

        self.button_start = HoverButton(self, wx.ID_ANY, _("Start"))
        self.button_start.SetToolTip(_("Execute the Job"))
        self.button_start.SetBitmap(
            icons8_gas_industry.GetBitmap(
                resize=self.icon_size,
                color=wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT),
                keepalpha=True,
                force_darkmode=True,
            )
        )
        self.button_start.SetBitmapFocus(
            icons8_gas_industry.GetBitmap(
                resize=self.icon_size,
            )
        )
        self.button_start.SetBackgroundColour(self.context.themes.get("start_bg"))
        self.button_start.SetForegroundColour(self.context.themes.get("start_fg"))
        self.button_start.SetFocusColour(self.context.themes.get("start_fg_focus"))

        sizer_control.Add(self.button_start, 1, wx.EXPAND, 0)

        self.button_pause = HoverButton(self, wx.ID_ANY, _("Pause"))
        self.button_pause.SetToolTip(_("Pause/Resume the laser"))
        self.button_pause.SetBitmap(
            icons8_pause.GetBitmap(
                resize=self.icon_size,
            )
        )
        sizer_control.Add(self.button_pause, 1, wx.EXPAND, 0)

        self.button_stop = HoverButton(self, wx.ID_ANY, _("Stop"))
        self.button_stop.SetToolTip(_("Stop the laser"))
        self.button_stop.SetBitmap(
            icons8_emergency_stop_button.GetBitmap(
                resize=self.icon_size,
                color=self.context.themes.get("stop_fg"),
                keepalpha=True,
                force_darkmode=True,
            )
        )
        self.button_stop.SetBitmapFocus(
            icons8_emergency_stop_button.GetBitmap(
                resize=self.icon_size,
            )
        )
        self.button_stop.SetBackgroundColour(self.context.themes.get("stop_bg"))
        self.button_stop.SetForegroundColour(self.context.themes.get("stop_fg"))
        self.button_stop.SetFocusColour(self.context.themes.get("stop_fg_focus"))
        sizer_control.Add(self.button_stop, 1, wx.EXPAND, 0)

        sizer_control_move = wx.BoxSizer(wx.HORIZONTAL)
        sizer_main.Add(sizer_control_move, 0, wx.EXPAND, 0)

        self.button_outline = wxButton(self, wx.ID_ANY, _("Frame"))
        self.button_outline.SetToolTip(
            _("Trace the rectangular frame of the job")
            + "\n"
            + _("Right click: trace the convex hull of the job")
        )
        self.button_outline.SetBitmap(
            icons8_pentagon.GetBitmap(
                resize=self.icon_size,
            )
        )
        sizer_control_move.Add(self.button_outline, 1, wx.EXPAND, 0)

        self.button_home = wxButton(self, wx.ID_ANY, _("Home"))
        self.button_home.SetToolTip(_("Send the laser to its home position"))
        self.button_home.SetBitmap(
            icons8_home_filled.GetBitmap(
                resize=self.icon_size,
            )
        )
        sizer_control_move.Add(self.button_home, 1, wx.EXPAND, 0)

        self.button_goto_origin = wxButton(self, wx.ID_ANY, _("Go to Origin"))
        self.button_goto_origin.SetToolTip(
            _("Move the laser to the user origin (or to 0,0 if there is none)")
        )
        self.button_goto_origin.SetBitmap(
            icons8_place_marker.GetBitmap(
                resize=self.icon_size,
            )
        )
        sizer_control_move.Add(self.button_goto_origin, 1, wx.EXPAND, 0)

        sizer_control_misc = wx.BoxSizer(wx.HORIZONTAL)
        sizer_main.Add(sizer_control_misc, 0, wx.EXPAND, 0)

        self.arm_toggle = HoverButton(self, wx.ID_ANY, _("Arm"))
        self.arm_toggle.SetToolTip(_("Arm the job for execution"))
        self.arm_toggle.SetBitmap(
            icon_closed_door.GetBitmap(
                resize=self.icon_size,
                color=self.context.themes.get("arm_fg"),
            )
        )
        self.arm_toggle.SetBitmapFocus(
            icon_closed_door.GetBitmap(
                resize=self.icon_size,
            )
        )
        self.arm_toggle.SetForegroundColour(self.context.themes.get("arm_fg"))
        self.arm_toggle.SetFocusColour(self.context.themes.get("stop_fg_focus"))
        self.armed = False
        sizer_control_misc.Add(self.arm_toggle, 1, wx.EXPAND, 0)

        self.check_laser_arm()

        self.button_simulate = wxButton(self, wx.ID_ANY, _("Simulate"))
        self.button_simulate.SetToolTip(_("Simulate the Design"))
        self.button_simulate.SetBitmap(
            icons8_laser_beam_hazard.GetBitmap(
                resize=self.icon_size,
            )
        )
        sizer_control_misc.Add(self.button_simulate, 1, wx.EXPAND, 0)

        self.button_set_origin = wxButton(self, wx.ID_ANY, _("Set Origin"))
        self.button_set_origin.SetToolTip(
            _("Use the current laser position as user origin")
            + "\n"
            + _("Right click: clear the user origin")
        )
        self.button_set_origin.SetBitmap(
            icons8_user_location.GetBitmap(
                resize=self.icon_size,
            )
        )
        sizer_control_misc.Add(self.button_set_origin, 1, wx.EXPAND, 0)

        box = wx.BoxSizer(wx.HORIZONTAL)
        self.rotary_indicator = wxStaticText(
            self, wx.ID_ANY, _("Rotary active"), style=wx.ALIGN_CENTRE_HORIZONTAL
        )
        bg_color = self.context.themes.get("pause_bg")
        fg_color = self.context.themes.get("pause_fg")
        self.rotary_indicator.SetBackgroundColour(bg_color)
        self.rotary_indicator.SetForegroundColour(fg_color)
        box.Add(self.rotary_indicator, 1, wx.ALIGN_CENTER_VERTICAL, 0)
        sizer_main.Add(box, 0, wx.EXPAND, 0)

        # Job placement: Start From + Job Origin + cut options
        sizer_job = StaticBoxSizer(self, wx.ID_ANY, _("Job"), wx.HORIZONTAL)
        sizer_main.Add(sizer_job, 0, wx.EXPAND, 0)
        sizer_job_options = wx.BoxSizer(wx.VERTICAL)
        sizer_job.Add(sizer_job_options, 1, wx.EXPAND, 0)

        sizer_start_from = wx.BoxSizer(wx.HORIZONTAL)
        lbl_start_from = wxStaticText(self, wx.ID_ANY, _("Start From:"))
        self.combo_start_from = wxComboBox(
            self,
            wx.ID_ANY,
            choices=[
                _("Absolute Coords"),
                _("User Origin"),
                _("Current Position"),
            ],
            style=wx.CB_DROPDOWN | wx.CB_READONLY,
        )
        self.combo_start_from.SetToolTip(
            _("Absolute Coords: burn the job where it is placed on the scene")
            + "\n"
            + _("User Origin: place the job origin at the user origin")
            + "\n"
            + _("Current Position: place the job origin at the current laser position")
        )
        sizer_start_from.Add(lbl_start_from, 0, wx.ALIGN_CENTER_VERTICAL, 0)
        sizer_start_from.Add(self.combo_start_from, 1, wx.ALIGN_CENTER_VERTICAL, 0)
        sizer_job_options.Add(sizer_start_from, 0, wx.EXPAND, 0)

        self.checkbox_cut_selected = wxCheckBox(
            self, wx.ID_ANY, _("Cut Selected Graphics")
        )
        self.checkbox_cut_selected.SetToolTip(
            _("Only burn the elements that are selected on the scene")
        )
        self.checkbox_selection_origin = wxCheckBox(
            self, wx.ID_ANY, _("Use Selection Origin")
        )
        self.checkbox_selection_origin.SetToolTip(
            _("Establish the job origin from the selection instead of the whole job")
        )
        self.checkbox_optimize = wxCheckBox(self, wx.ID_ANY, _("Optimize Cut Path"))
        self.checkbox_optimize.SetToolTip(_("Enable/Disable Optimize"))
        self.checkbox_optimize.SetValue(self.context.planner.do_optimization)
        self.checkbox_adjust = wxCheckBox(self, wx.ID_ANY, _("Override"))
        self.checkbox_adjust.SetToolTip(
            _("Allow ad-hoc adjustment of speed and power.")
            + "\n"
            + _("This affects running jobs, so use with care!")
        )
        for ctrl in (
            self.checkbox_cut_selected,
            self.checkbox_selection_origin,
            self.checkbox_optimize,
            self.checkbox_adjust,
        ):
            sizer_job_options.Add(ctrl, 0, wx.EXPAND, 0)

        sizer_job_origin = wx.BoxSizer(wx.VERTICAL)
        lbl_job_origin = wxStaticText(self, wx.ID_ANY, _("Job Origin"))
        sizer_job_origin.Add(lbl_job_origin, 0, wx.ALIGN_CENTER_HORIZONTAL, 0)
        grid_origin = wx.GridSizer(3, 3, 0, 0)
        origin_tips = (
            _("Top left"),
            _("Top center"),
            _("Top right"),
            _("Middle left"),
            _("Center"),
            _("Middle right"),
            _("Bottom left"),
            _("Bottom center"),
            _("Bottom right"),
        )
        self.radio_origin = []
        for idx, tip in enumerate(origin_tips):
            radio = wx.RadioButton(
                self, wx.ID_ANY, "", style=wx.RB_GROUP if idx == 0 else 0
            )
            radio.SetToolTip(
                _("Job origin: {position}").format(position=tip)
                + "\n"
                + _("This point of the job is placed at the Start From position")
            )
            radio.Bind(wx.EVT_RADIOBUTTON, self.on_job_origin(idx))
            grid_origin.Add(radio, 0, wx.ALIGN_CENTER, 0)
            self.radio_origin.append(radio)
        sizer_job_origin.Add(grid_origin, 0, wx.ALIGN_CENTER_HORIZONTAL, 0)
        sizer_job.Add(sizer_job_origin, 0, wx.EXPAND | wx.LEFT, 4)

        sizer_manipulate = wx.BoxSizer(wx.VERTICAL)
        sizer_main.Add(sizer_manipulate, 0, wx.EXPAND, 0)

        self.sizer_power = wx.BoxSizer(wx.HORIZONTAL)
        sizer_manipulate.Add(self.sizer_power, 0, wx.EXPAND, 0)
        lb_power = wxStaticText(self, wx.ID_ANY, _("Power"))
        self.label_power = wxStaticText(self, wx.ID_ANY, "0%")
        self.slider_power = wx.Slider(
            self, wx.ID_ANY, value=10, minValue=1, maxValue=20
        )
        self.sizer_power.Add(lb_power, 1, wx.ALIGN_CENTER_VERTICAL, 0)
        self.sizer_power.Add(self.slider_power, 3, wx.ALIGN_CENTER_VERTICAL, 0)
        self.sizer_power.Add(self.label_power, 1, wx.ALIGN_CENTER_VERTICAL, 0)
        self.slider_power.SetToolTip(
            _("Increases/decreases the regular laser power by this amount.")
            + "\n"
            + _("This affects running jobs, so use with care!")
        )

        self.sizer_speed = wx.BoxSizer(wx.HORIZONTAL)
        sizer_manipulate.Add(self.sizer_speed, 0, wx.EXPAND, 0)
        lb_speed = wxStaticText(self, wx.ID_ANY, _("Speed"))
        self.label_speed = wxStaticText(self, wx.ID_ANY, "0%")
        self.slider_size = 20
        self.power_mode = "relative"
        self.slider_speed = wx.Slider(
            self, wx.ID_ANY, value=10, minValue=1, maxValue=20
        )
        self.sizer_speed.Add(lb_speed, 1, wx.ALIGN_CENTER_VERTICAL, 0)
        self.sizer_speed.Add(self.slider_speed, 3, wx.ALIGN_CENTER_VERTICAL, 0)
        self.sizer_speed.Add(self.label_speed, 1, wx.ALIGN_CENTER_VERTICAL, 0)
        self.slider_speed.SetToolTip(
            _("Increases/decreases the regular speed by this amount.")
            + "\n"
            + _("This affects running jobs, so use with care!")
        )

        self.SetSizer(sizer_main)
        self.Layout()

        self.Bind(wx.EVT_BUTTON, self.on_button_start, self.button_start)
        self.button_start.Bind(wx.EVT_LEFT_DOWN, self.on_start_left)
        self.Bind(wx.EVT_BUTTON, self.on_button_pause, self.button_pause)
        self.Bind(wx.EVT_BUTTON, self.on_button_stop, self.button_stop)
        self.Bind(wx.EVT_BUTTON, self.on_check_arm, self.arm_toggle)
        self.Bind(wx.EVT_RIGHT_DOWN, self.on_menu_arm, self)
        self.Bind(wx.EVT_RIGHT_DOWN, self.on_menu_arm, self.button_start)
        self.Bind(wx.EVT_RIGHT_DOWN, self.on_menu_arm, self.button_outline)
        self.Bind(wx.EVT_RIGHT_DOWN, self.on_menu_arm, self.button_simulate)
        self.Bind(wx.EVT_BUTTON, self.on_button_outline, self.button_outline)
        self.button_outline.Bind(wx.EVT_RIGHT_DOWN, self.on_button_outline_right)
        self.Bind(wx.EVT_BUTTON, self.on_button_simulate, self.button_simulate)
        self.Bind(wx.EVT_COMBOBOX, self.on_combo_devices, self.combo_devices)
        self.Bind(wx.EVT_CHECKBOX, self.on_check_adjust, self.checkbox_adjust)
        self.Bind(wx.EVT_SLIDER, self.on_slider_speed, self.slider_speed)
        self.Bind(wx.EVT_SLIDER, self.on_slider_power, self.slider_power)
        self.Bind(wx.EVT_CHECKBOX, self.on_optimize, self.checkbox_optimize)
        # self.btn_config_laser.Bind(wx.EVT_LEFT_DOWN, self.on_config_button)
        self.btn_config_laser.Bind(wx.EVT_BUTTON, self.on_config_button)
        self.combo_devices.Bind(wx.EVT_RIGHT_DOWN, self.on_control_right)
        self.btn_config_laser.Bind(wx.EVT_RIGHT_DOWN, self.on_control_right)
        self.Bind(wx.EVT_BUTTON, self.on_button_home, self.button_home)
        self.Bind(wx.EVT_BUTTON, self.on_button_goto_origin, self.button_goto_origin)
        self.Bind(wx.EVT_BUTTON, self.on_button_set_origin, self.button_set_origin)
        self.button_set_origin.Bind(wx.EVT_RIGHT_DOWN, self.on_button_clear_origin)
        self.Bind(wx.EVT_COMBOBOX, self.on_combo_start_from, self.combo_start_from)
        self.Bind(wx.EVT_CHECKBOX, self.on_check_cut_selected, self.checkbox_cut_selected)
        self.Bind(
            wx.EVT_CHECKBOX,
            self.on_check_selection_origin,
            self.checkbox_selection_origin,
        )
        self.label_position.Bind(wx.EVT_LEFT_DCLICK, self.update_position)
        # end wxGlade
        self.update_job_controls()
        self.update_position()
        self.checkbox_adjust.SetValue(False)
        self.on_check_adjust(None)
        self.update_override_controls()
        self.on_device_changes()
        index = self.combo_devices.GetSelection()
        if index == -1:
            disable_window(self)
        # Check for a real click of the execute button
        self.button_start_was_clicked = False

    def update_override_controls(self):
        def set_boundaries(slider, current_value, min_value, max_value):
            slider.SetMin(min_value)
            slider.SetMax(max_value)
            slider.SetValue(current_value)

        flag_power = False
        override = False
        if (
            hasattr(self.context.device.driver, "has_adjustable_power")
            and self.context.device.driver.has_adjustable_power
        ):
            flag_power = True
            # Let's establish the value and update the slider...
            value = self.context.device.driver.power_scale
            if value != 1:
                override = True
            half = self.slider_size / 2
            sliderval = int(value * half)
            sliderval = max(1, min(self.slider_size, sliderval))
            set_boundaries(self.slider_power, sliderval, 1, self.slider_size)
            self.slider_power.SetToolTip(
                _("Increases/decreases the regular laser power by this amount.")
                + "\n"
                + _("This affects running jobs, so use with care!")
            )
            self.power_mode = "relative"
            self.on_slider_power(None)
        elif (
            hasattr(self.context.device.driver, "has_adjustable_maximum_power")
            and self.context.device.driver.has_adjustable_maximum_power
        ):
            flag_power = True
            override = True
            dev_mode = getattr(self.context.kernel.root, "developer_mode", False)
            # Let's establish the value and update the slider...
            min_value = 1
            max_value = 100 if dev_mode else 50
            sliderval = min(max_value, self.context.device.driver.max_power_scale)
            set_boundaries(self.slider_power, sliderval, min_value, max_value)
            self.slider_power.SetToolTip(
                _("Sets the maximum laser power level.")
                + "\n"
                + _("Setting this too high may cause damage to your laser tube!")
            )
            self.power_mode = "maximum"
            self.on_slider_power(None)
        flag_speed = False
        if (
            hasattr(self.context.device.driver, "has_adjustable_speed")
            and self.context.device.driver.has_adjustable_speed
        ):
            flag_speed = True
            # Let's establish the value and update the slider...
            value = self.context.device.driver.speed_scale
            if value != 1:
                override = True
            half = self.slider_size / 2
            sliderval = int(value * half)
            sliderval = max(1, min(self.slider_size, sliderval))
            set_boundaries(self.slider_speed, sliderval, 1, self.slider_size)
            self.on_slider_speed(None)

        self.sizer_power.Show(flag_power)
        self.sizer_power.ShowItems(flag_power)
        self.sizer_power.Layout()
        self.sizer_speed.Show(flag_speed)
        self.sizer_speed.ShowItems(flag_speed)
        self.sizer_speed.Layout()
        self.checkbox_adjust.Show(bool(flag_power or flag_speed))
        self.checkbox_adjust.SetValue(override)
        self.slider_power.Enable(override)
        self.slider_speed.Enable(override)
        self.Layout()

    def on_check_adjust(self, event):
        if self.checkbox_adjust.GetValue():
            self.slider_power.Enable(True)
            self.slider_speed.Enable(True)
        else:
            self.slider_power.Enable(False)
            self.slider_speed.Enable(False)
            if (
                hasattr(self.context.device.driver, "has_adjustable_power")
                and self.context.device.driver.has_adjustable_power
            ):
                if event is not None:
                    self.context.device.driver.set_power_scale(1.0)
                self.slider_power.SetValue(10)
                self.on_slider_power(None)
            if (
                hasattr(self.context.device.driver, "has_adjustable_speed")
                and self.context.device.driver.has_adjustable_speed
            ):
                if event is not None:
                    self.context.device.driver.set_speed_scale(1.0)
                self.slider_speed.SetValue(10)
                self.on_slider_speed(None)

    def on_slider_speed(self, event):
        sliderval = self.slider_speed.GetValue()
        half = self.slider_size / 2
        newvalue = sliderval - half  # -> -9 to +10
        factor = 1 + newvalue / half
        if event is not None:
            self.context.device.driver.set_speed_scale(factor)
        msg = f"{'+' if factor > 1 else ''}{100 * (factor - 1.0):.0f}%"
        self.label_speed.SetLabel(msg)

    def on_slider_power(self, event):
        sliderval = self.slider_power.GetValue()
        if self.power_mode == "maximum":
            # Maximum power mode, so we just set the value.
            if event is not None:
                self.context.device.driver.max_power_scale = sliderval
            msg = f"{sliderval}%"
        else:
            half = self.slider_size / 2
            newvalue = sliderval - half  # -> -9 to +10
            factor = 1 + newvalue / half
            if event is not None:
                self.context.device.driver.set_power_scale(factor)
            msg = f"{'+' if factor > 1 else ''}{100 * (factor - 1.0):.0f}%"
        self.label_power.SetLabel(msg)

    def on_optimize(self, event):
        newval = bool(self.checkbox_optimize.GetValue())
        if newval != self.context.planner.do_optimization:
            self.context.planner.do_optimization = newval
            self.context.signal("optimize", newval)

    @signal_listener("optimize")
    def optimize_update(self, origin, *message):
        try:
            newvalue = bool(message[0])
        except ValueError:
            # You never know
            return
        if self.context.planner.do_optimization != newvalue:
            self.context.planner.do_optimization = newvalue
        if self.checkbox_optimize.GetValue() != newvalue:
            self.checkbox_optimize.SetValue(newvalue)

    @signal_listener("pwm_mode_changed")
    def on_pwm_mode_changed(self, origin, *message):
        """
        This is called when the power scale of the device changes.
        It updates the slider and label accordingly.
        """
        self.update_override_controls()

    @signal_listener("device;modified")
    @signal_listener("device;renamed")
    @lookup_listener("service/device/active")
    @lookup_listener("service/device/available")
    def on_device_changes(self, *args):
        # Devices Initialize.
        self.available_devices = self.context.kernel.services("device")
        self.selected_device = self.context.device
        index = -1
        count = 0
        self.combo_devices.Clear()
        for i, spool in enumerate(self.available_devices):
            if index < 0 and spool is self.selected_device:
                index = i
            self.combo_devices.Append(spool.label)
            count += 1
        self.combo_devices.SetSelection(index)
        self.set_pause_color()
        self.update_override_controls()
        showit = count > 1
        self.sizer_devices.ShowItems(showit)
        flag = False
        if hasattr(self.context.device, "rotary"):
            flag = self.context.device.rotary.active
        self.rotary_indicator.Show(flag)
        self.Layout()

    @signal_listener("device;connected")
    def on_connectivity(self, *args):
        # There's no signal yet, but there should be one...
        self.update_override_controls()

    def set_pause_color(self):
        new_bg_color = None
        new_fg_color = None
        new_caption = _("Pause")
        try:
            if self.context.device.driver.paused:
                new_bg_color = self.context.themes.get("pause_bg")
                new_fg_color = self.context.themes.get("pause_fg")
                new_caption = _("Resume")
        except AttributeError:
            pass
        self.button_pause.SetBackgroundColour(new_bg_color)
        self.button_pause.SetForegroundColour(new_fg_color)
        self.button_pause.SetLabelText(new_caption)

    @signal_listener("pause")
    def on_device_pause_toggle(self, origin, *args):
        self.set_pause_color()

    @signal_listener("laser_armed")
    def signal_laser_arm(self, origin, *message):
        try:
            newval = bool(message[0])
        except ValueError:
            # You never know
            newval = False
        if self.armed != newval:
            self.armed = newval
            self.check_laser_arm()

    @signal_listener("laserpane_arm")
    def check_laser_arm(self, *args):
        ctxt = self.context.kernel.root
        ctxt.setting(bool, "_laser_may_run", False)
        if self.context.root.laserpane_arm:
            if not self.arm_toggle.Shown:
                self.arm_toggle.Show(True)
                self.Layout()
            if self.armed:
                self.arm_toggle.SetBackgroundColour(self.context.themes.get("arm_bg"))
                self.button_start.SetBackgroundColour(
                    self.context.themes.get("start_bg")
                )
                self.arm_toggle.SetBitmap(
                    icon_open_door.GetBitmap(
                        resize=self.icon_size,
                        color=self.context.themes.get("arm_fg"),
                    )
                )
                self.arm_toggle.SetBitmapFocus(
                    icon_open_door.GetBitmap(
                        resize=self.icon_size,
                    )
                )
                self.arm_toggle.SetLabel(_("Disarm"))
                self.arm_toggle.SetToolTip(
                    _("Prevent the laser from accidentally executing")
                )
                self.button_start.Enable(True)
                ctxt._laser_may_run = True
            else:
                self.arm_toggle.SetBackgroundColour(
                    self.context.themes.get("arm_bg_inactive")
                )
                self.button_start.SetBackgroundColour(
                    self.context.themes.get("start_bg_inactive")
                )
                self.button_start.Enable(False)
                self.arm_toggle.SetBitmap(
                    icon_closed_door.GetBitmap(
                        resize=self.icon_size,
                        color=self.context.themes.get("arm_fg"),
                    )
                )
                self.arm_toggle.SetBitmapFocus(
                    icon_closed_door.GetBitmap(
                        resize=self.icon_size,
                    )
                )
                self.arm_toggle.SetLabel(_("Arm"))
                self.arm_toggle.SetToolTip(_("Arm the job for execution"))
                ctxt._laser_may_run = False
        else:
            if self.arm_toggle.Shown:
                self.arm_toggle.Show(False)
                self.Layout()
            self.button_start.SetBackgroundColour(self.context.themes.get("start_bg"))
            self.button_start.Enable(True)
            ctxt._laser_may_run = True
        self.context.signal("laser_armed", self.armed)
        self.context.signal("icons")

    def on_check_arm(self, event):
        self.armed = not self.armed
        self.check_laser_arm()

    def on_menu_arm_enable(self, event):
        self.context.root.laserpane_arm = True
        self.check_laser_arm()

    def on_menu_arm_disable(self, event):
        self.context.root.laserpane_arm = False
        self.check_laser_arm()

    def on_menu_arm(self, event):
        menu = wx.Menu()
        if not self.context.root.laserpane_arm:
            self.Bind(
                wx.EVT_MENU,
                self.on_menu_arm_enable,
                menu.Append(wx.ID_ANY, _("Enable Arm Requirement"), _("Enable Arm")),
            )
        else:
            self.Bind(
                wx.EVT_MENU,
                self.on_menu_arm_disable,
                menu.Append(wx.ID_ANY, _("Disable Arm Requirement"), _("Disable Arm")),
            )
        self.PopupMenu(menu)
        menu.Destroy()

    def on_start_left(self, event):
        self.button_start_was_clicked = True
        event.Skip()

    def on_button_start(self, event):  # wxGlade: LaserPanel.<event_handler>
        # We don't want this button to be executed if it has focus and
        # the user presses the space bar or the return key.
        # Cats can do wondrous things when they walk over a keyboard
        if not self.button_start_was_clicked:
            channel = self.context.kernel.channel("console")
            channel(
                _(
                    "We intentionally ignored a request to start a job via the keyboard.\n"
                    + "You need to make your intent clear by a deliberate mouse-click"
                )
            )
            return

        busy = self.context.kernel.busyinfo
        busy.start(msg=_("Preparing Laserjob..."))
        plan = self.context.planner.get_or_make_plan("z")
        self.context.setting(bool, "laserpane_hold", False)
        if not self.check_job_settings():
            busy.end()
            self.button_start_was_clicked = False
            return
        if plan.plan and self.context.laserpane_hold:
            self.context("planz spool\n")
        else:
            self.context(
                self.context.planner.job_plan_command(
                    "z", optimize=self.checkbox_optimize.GetValue()
                )
            )
        self.armed = False
        self.check_laser_arm()
        if self.context.auto_spooler:
            self.context("window open JobSpooler\n")
        busy.end()
        self.button_start_was_clicked = False

    def on_button_pause(self, event):  # wxGlade: LaserPanel.<event_handler>
        self.context("pause\n")

    def on_button_stop(self, event):  # wxGlade: LaserPanel.<event_handler>
        self.context("estop\n")

    def frame_job(self, method):
        """
        Trace the frame of the job at the place where it will be burnt.
        """
        planner = self.context.planner
        selected_only = self.context.root.job_cut_selected
        source = "" if selected_only else "element* "
        offset = planner.job_offset()
        if offset is None:
            if method == "quick" and not selected_only:
                try:
                    self.context.device.outline()
                    return
                except AttributeError:
                    pass
            self.context(f"{source}trace {method}\n")
            return
        dx = Length(amount=offset[0]).mm
        dy = Length(amount=offset[1]).mm
        self.context(f"{source}trace {method} --dx {dx:.3f}mm --dy {dy:.3f}mm\n")

    def on_button_outline(self, event):  # wxGlade: LaserPanel.<event_handler>
        self.frame_job("quick")

    def on_button_outline_right(self, event):  # wxGlade: LaserPanel.<event_handler>
        self.frame_job("hull")

    def on_button_home(self, event):
        self.context("home\n")

    def on_button_goto_origin(self, event):
        origin = self.context.planner.get_user_origin()
        if origin is None:
            origin = (0, 0)
        x = Length(amount=origin[0]).mm
        y = Length(amount=origin[1]).mm
        self.context(f".move_absolute {x:.3f}mm {y:.3f}mm\n")

    def on_button_set_origin(self, event):
        try:
            position = self.context.device.current
        except AttributeError:
            return
        self.context.planner.set_user_origin(position)
        self.update_position()

    def on_button_clear_origin(self, event):
        self.context.planner.set_user_origin(None)
        self.update_position()

    def on_combo_start_from(self, event):
        self.context.root.job_start_from = self.combo_start_from.GetSelection()
        self.update_job_controls()
        self.context.signal("job_settings")

    def on_check_cut_selected(self, event):
        self.context.root.job_cut_selected = self.checkbox_cut_selected.GetValue()
        self.update_job_controls()
        self.context.signal("job_settings")

    def on_check_selection_origin(self, event):
        self.context.root.job_use_selection_origin = (
            self.checkbox_selection_origin.GetValue()
        )
        self.context.signal("job_settings")

    def on_job_origin(self, index):
        def handler(event):
            self.context.root.job_origin = index
            self.context.signal("job_settings")

        return handler

    @signal_listener("job_settings")
    def update_job_controls(self, *args):
        if not wx.IsMainThread():
            wx.CallAfter(self.update_job_controls)
            return
        root = self.context.root
        start_from = root.job_start_from
        if start_from < 0 or start_from > 2:
            start_from = START_FROM_ABSOLUTE
        self.combo_start_from.SetSelection(start_from)
        origin = min(8, max(0, root.job_origin))
        self.radio_origin[origin].SetValue(True)
        relative = start_from != START_FROM_ABSOLUTE
        for radio in self.radio_origin:
            radio.Enable(relative)
        self.checkbox_cut_selected.SetValue(root.job_cut_selected)
        self.checkbox_selection_origin.SetValue(root.job_use_selection_origin)
        self.checkbox_selection_origin.Enable(root.job_cut_selected and relative)

    def _format_position(self, position):
        units = self.context.units_name
        x = Length(amount=position[0], preferred_units=units, digits=2)
        y = Length(amount=position[1], preferred_units=units, digits=2)
        return f"X: {x.preferred_length}  Y: {y.preferred_length}"

    @signal_listener("user_origin")
    @signal_listener("driver;position")
    @signal_listener("emulator;position")
    def update_position(self, *args):
        if not wx.IsMainThread():
            wx.CallAfter(self.update_position)
            return
        try:
            position = self.context.device.current
            self.label_position.SetLabel(self._format_position(position))
        except (AttributeError, TypeError):
            self.label_position.SetLabel("")
        origin = self.context.planner.get_user_origin()
        if origin is None:
            self.label_origin.SetLabel(_("No user origin"))
        else:
            self.label_origin.SetLabel(_("Origin") + " " + self._format_position(origin))
        user_mode = self.context.root.job_start_from == START_FROM_USER_ORIGIN
        if user_mode and origin is None:
            self.label_origin.SetForegroundColour(wx.RED)
        else:
            self.label_origin.SetForegroundColour(self.label_position.GetForegroundColour())
        self.Layout()

    def check_job_settings(self):
        """
        Warn about job settings that cannot be honoured. Returns False to cancel.
        """
        root = self.context.root
        if root.job_cut_selected and not list(
            self.context.elements.elems(emphasized=True)
        ):
            wx.MessageBox(
                _(
                    "'Cut Selected Graphics' is active, but nothing is selected.\n"
                    "Select the shapes to burn or uncheck the option."
                ),
                _("Start job"),
                wx.OK | wx.ICON_INFORMATION,
            )
            return False
        if (
            root.job_start_from == START_FROM_USER_ORIGIN
            and self.context.planner.get_user_origin() is None
        ):
            wx.MessageBox(
                _(
                    "'Start From' is set to 'User Origin', but no user origin is defined.\n"
                    "Move the laser and press 'Set Origin' first."
                ),
                _("Start job"),
                wx.OK | wx.ICON_WARNING,
            )
            return False
        return True

    def on_button_simulate(self, event):  # wxGlade: LaserPanel.<event_handler>
        self.context.kernel.busyinfo.start(msg=_("Preparing simulation..."))

        plan = self.context.planner.get_or_make_plan("z")
        param = "0"
        if not plan.plan or not self.context.laserpane_hold:
            optimize = self.checkbox_optimize.GetValue()
            self.context(
                self.context.planner.job_plan_command("z", optimize=optimize, final="")
            )
            if optimize:
                param = "1"
        self.context(f"window open Simulation z 0 {param}\n")
        self.context.kernel.busyinfo.end()

    def on_control_right(self, event):  # wxGlade: LaserPanel.<event_handler>
        self.context("window open DeviceManager\n")

    def on_combo_devices(self, event):  # wxGlade: LaserPanel.<event_handler>
        index = self.combo_devices.GetSelection()
        try:
            self.selected_device = self.available_devices[index]
        except IndexError:
            return
        self.selected_device.kernel.activate_service_path(
            "device", self.selected_device.path
        )
        # Device change, so let's focus properly...
        zl = self.context.zoom_margin
        self.context(f"scene focus -{zl}% -{zl}% {100 + zl}% {100 + zl}%\n")
        self.set_pause_color()

    def on_config_button(self, event):
        self.context.device("window toggle Configuration\n")


class JobPanel(wx.Panel):
    """
    Contains all elements to plan and save the job
    """

    def __init__(self, *args, context=None, **kwds):
        # begin wxGlade: MovePanel.__init__
        kwds["style"] = kwds.get("style", 0) | wx.TAB_TRAVERSAL
        wx.Panel.__init__(self, *args, **kwds)
        self.context = context
        self.context.themes.set_window_colors(self)

        sizer_main = wx.BoxSizer(wx.VERTICAL)
        self._optimize = True
        self.icon_size = 0.5 * get_default_icon_size(self.context)
        sizer_control_update = wx.BoxSizer(wx.HORIZONTAL)
        sizer_main.Add(sizer_control_update, 0, wx.EXPAND, 0)

        self.button_clear = wxButton(self, wx.ID_ANY, _("Clear"))
        self.button_clear.SetToolTip(_("Clear locally defined plan"))
        self.button_clear.SetBitmap(icons8_delete.GetBitmap(resize=self.icon_size))
        sizer_control_update.Add(self.button_clear, 1, 0, 0)

        self.button_update = wxButton(self, wx.ID_ANY, _("Update"))
        self.button_update.SetToolTip(_("Update the Plan"))
        self.button_update.SetBitmap(icon_update_plan.GetBitmap(resize=self.icon_size))
        sizer_control_update.Add(self.button_update, 1, 0, 0)

        self.button_save_file = wxButton(self, wx.ID_ANY, _("Save"))
        self.button_save_file.SetToolTip(_("Save the job"))
        self.button_save_file.SetBitmap(icons8_save.GetBitmap(resize=self.icon_size))
        sizer_control_update.Add(self.button_save_file, 1, 0, 0)

        sizer_source = wx.BoxSizer(wx.HORIZONTAL)
        sizer_main.Add(sizer_source, 0, wx.EXPAND, 0)

        self.text_plan = TextCtrl(
            self, wx.ID_ANY, _("--- Empty ---"), style=wx.TE_READONLY
        )
        sizer_source.Add(self.text_plan, 2, 0, 0)

        self.context.setting(bool, "laserpane_hold", False)
        self.checkbox_hold = wxCheckBox(self, wx.ID_ANY, _("Hold"))
        self.checkbox_hold.SetToolTip(
            _("Preserve the job between running, rerunning, and execution")
        )
        self.checkbox_hold.SetValue(self.context.laserpane_hold)
        sizer_source.Add(self.checkbox_hold, 1, wx.ALIGN_CENTER_VERTICAL, 0)

        self.SetSizer(sizer_main)
        self.Layout()

        self.Bind(wx.EVT_CHECKBOX, self.on_check_hold, self.checkbox_hold)
        self.Bind(wx.EVT_BUTTON, self.on_button_save, self.button_save_file)
        # self.Bind(wx.EVT_BUTTON, self.on_button_load, self.button_load)
        self.Bind(wx.EVT_BUTTON, self.on_button_clear, self.button_clear)
        self.Bind(wx.EVT_BUTTON, self.on_button_update, self.button_update)

    @signal_listener("plan")
    def plan_update(self, origin, *message):
        plan_name, stage = message[0], message[1]
        if plan_name == "z":
            plan = self.context.planner.get_or_make_plan("z")
            if not len(plan.plan):
                self.text_plan.SetValue(_("--- Empty ---"))
            else:
                self.text_plan.SetValue(f"{str(stage)}: {str(plan)}")

    def on_button_save(self, event):  # wxGlade: LaserPanel.<event_handler>
        gui = self.context.gui
        extension = "txt"
        if hasattr(self.context.device, "extension"):
            extension = self.context.device.extension
        filetype = f"*.{extension}"
        with wx.FileDialog(
            gui,
            _("Save Project"),
            wildcard=filetype,
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as fileDialog:
            if fileDialog.ShowModal() == wx.ID_CANCEL:
                return
            pathname = fileDialog.GetPath()

            if not pathname.lower().endswith(f".{extension}"):
                pathname += f".{extension}"
            optpart = "preopt optimize " if self.context.planner.do_optimization else ""
            self.context(
                f'planz clear copy preprocess validate blob {optpart}save_job "{pathname}"\n'
            )

    def on_button_load(self, event):  # wxGlade: LaserPanel.<event_handler>
        pass

    def on_button_clear(self, event):  # wxGlade: LaserPanel.<event_handler>
        self.context("planz clear\n")

    def on_button_update(self, event):  # wxGlade: LaserPanel.<event_handler>
        self.context.kernel.busyinfo.start(msg=_("Updating Plan..."))
        if self.context.planner.do_optimization:
            self.context("planz clear copy preprocess validate blob preopt optimize\n")
        else:
            self.context("planz clear copy preprocess validate blob\n")
        self.context.kernel.busyinfo.end()

    def on_check_hold(self, event):
        self.context.laserpane_hold = self.checkbox_hold.GetValue()

    def pane_show(self, *args):
        self.button_save_file.Enable(hasattr(self.context.device, "extension"))

    def pane_hide(self, *args):
        pass


class OptimizePanel(wx.Panel):
    """
    Contains all elements to adjust optimisation
    """

    def __init__(self, *args, context=None, **kwds):
        # begin wxGlade: MovePanel.__init__
        from copy import copy

        self.parent = args[0]

        kwds["style"] = kwds.get("style", 0) | wx.TAB_TRAVERSAL
        wx.Panel.__init__(self, *args, **kwds)
        self.context = context
        self.context.themes.set_window_colors(self)
        sizer_main = wx.BoxSizer(wx.VERTICAL)
        self.checkbox_optimize = wxCheckBox(self, wx.ID_ANY, _("Optimize"))
        self.checkbox_optimize.SetToolTip(_("Enable/Disable Optimize"))
        self.checkbox_optimize.SetValue(self.context.planner.do_optimization)
        prechoices = context.lookup("choices/optimize")
        choices = list(map(copy, prechoices))
        # Clear the page-entry
        for entry in choices:
            entry["page"] = ""
        self.optimize_panel = ChoicePropertyPanel(
            self, wx.ID_ANY, context=context, choices=choices
        )

        sizer_main.Add(self.checkbox_optimize, 0, 0, 0)
        sizer_main.Add(self.optimize_panel, 1, wx.EXPAND, 0)
        self.SetSizer(sizer_main)
        self.Layout()

        self.Bind(wx.EVT_CHECKBOX, self.on_optimize, self.checkbox_optimize)
        self.parent.add_module_delegate(self.optimize_panel)

    @signal_listener("optimize")
    def optimize_update(self, origin, *message):
        try:
            newvalue = bool(message[0])
        except ValueError:
            # You never know
            return
        if self.context.planner.do_optimization != newvalue:
            self.context.planner.do_optimization = newvalue
        if self.checkbox_optimize.GetValue() != newvalue:
            self.checkbox_optimize.SetValue(newvalue)
            self.optimize_panel.Enable(newvalue)

    def ensure_mutually_exclusive(self, prio: str):
        # Ensure that opt_inner_first and opt_reduce_travel are mutually exclusive
        inner_first = self.context.planner.opt_inner_first
        reduce_travel = self.context.planner.opt_reduce_travel
        if inner_first and reduce_travel:
            if prio == "opt_inner_first":
                self.context.planner.opt_reduce_travel = False
            else:
                self.context.planner.opt_inner_first = False
            self.optimize_panel.reload()

    @signal_listener("opt_inner_first")
    def opt_inner_update(self, origin, *message):
        self.ensure_mutually_exclusive("opt_inner_first")

    @signal_listener("opt_reduce_travel")
    def opt_reduce_travel_update(self, origin, *message):
        self.ensure_mutually_exclusive("opt_reduce_travel")

    def on_optimize(self, event):
        newvalue = bool(self.checkbox_optimize.GetValue())
        if newvalue != self.context.planner.do_optimization:
            self.context.planner.do_optimization = newvalue
            self.context.signal("optimize", newvalue)
            self.optimize_panel.Enable(newvalue)

    def pane_show(self, *args):
        pass

    def pane_hide(self, *args):
        pass
