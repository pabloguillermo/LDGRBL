from copy import copy

from meerk40t.kernel import Service

from ..core.cutcode.cutcode import CutCode
from .cutplan import CutPlan, CutPlanningFailedError
from .node.op_cut import CutOpNode
from .node.op_dots import DotsOpNode
from .node.op_engrave import EngraveOpNode
from .node.op_image import ImageOpNode
from .node.op_raster import RasterOpNode
from .node.util_console import ConsoleOperation
from .node.util_goto import GotoOperation
from .node.util_home import HomeOperation
from .node.util_output import OutputOperation
from .node.util_wait import WaitOperation
from .units import Length

"""
The planner module provides cut planning services. This provides a method of going from operations + elements into
cutcode which is then put inside a laserjob and sent to a spooler. Most of these operations are called on the
individual CutPlan objects.
"""


# Where the job is placed when it is sent to the laser (LightBurn "Start From")
START_FROM_ABSOLUTE = 0
START_FROM_USER_ORIGIN = 1
START_FROM_CURRENT_POSITION = 2


def job_origin_anchor(bounds, index):
    """
    Return the point of the bounds that serves as job origin.
    index is a 3x3 grid position in reading order:
    0=top-left, 1=top-center, 2=top-right, ... 4=center ... 8=bottom-right
    """
    index = min(8, max(0, int(index)))
    col = index % 3
    row = index // 3
    x = bounds[0] + (bounds[2] - bounds[0]) * col / 2
    y = bounds[1] + (bounds[3] - bounds[1]) * row / 2
    return x, y


def union_bounds(bounds_list):
    result = None
    for b in bounds_list:
        if b is None:
            continue
        if result is None:
            result = list(b)
        else:
            result[0] = min(result[0], b[0])
            result[1] = min(result[1], b[1])
            result[2] = max(result[2], b[2])
            result[3] = max(result[3], b[3])
    return result


def operations_bounds(operations, require_output=True):
    """
    Bounds of all elements contained in the given operations.
    """
    bounds = []
    for op in operations:
        if not hasattr(op, "type") or op.type is None:
            continue
        if not op.type.startswith("op "):
            continue
        if require_output and not getattr(op, "output", True):
            continue
        for child in op.children:
            node = child.node if child.type == "reference" else child
            try:
                bounds.append(node.bounds)
            except AttributeError:
                pass
    return union_bounds(bounds)


def shift_node(node, dx, dy):
    """
    Translate a (detached) node and its children by dx, dy.
    """
    for child in node.children:
        shift_node(child, dx, dy)
    if getattr(node, "_convex_hull", None) is not None:
        # Copies share the hull object with the scene element, so let it be rebuilt
        node._convex_hull = None
    try:
        node.matrix.post_translate(dx, dy)
    except AttributeError:
        node.set_dirty_bounds()
        return
    node.translated(dx, dy)


def plugin(kernel, lifecycle=None):
    if lifecycle == "register":
        kernel.add_service("planner", Planner(kernel))

    elif lifecycle == "boot":
        context = kernel.get_context("planner")  # specifically get this planner context
        _ = context._
        choices = [
            {
                "attr": "auto_spooler",
                "object": context,
                "default": True,
                "type": bool,
                "label": _("Launch Spooler on Job Start"),
                "tip": _(
                    "Open the Spooler window automatically when you Execute a Job"
                ),
            },
        ]
        kernel.register_choices("planner", choices)
        INNER_WARNING = _(
            "Notabene: Reduce Travel Time and Burn Inner First cannot be used at the same time."
        )
        choices = [
            {
                "attr": "opt_raster_optimisation",
                "object": context,
                "default": True,
                "type": bool,
                "label": _("Cluster raster objects"),
                "tip": _(
                    "Separate non-overlapping raster objects.\n"
                    "Active: this will raster close (i.e. overlapping) objects as one,\n"
                    "but will separately process objects lying apart from each other.\n"
                    "Inactive: all objects will be lasered as one single unit."
                ),
                "page": "Optimisations",
                # Hint for translation _("Reducing Movements")
                "section": "_20_Reducing Movements",
                # Hint for translation _("Splitting rasters")
                "subsection": "Splitting rasters",
            },
            {
                "attr": "opt_raster_opt_margin",
                "object": context,
                "default": "1mm",
                "type": Length,
                "label": _("Margin:"),
                "tip": _(
                    "Allowed gap between rasterable objects, to still be counted as one."
                ),
                "page": "Optimisations",
                # Hint for translation _("Reducing Movements")
                "section": "_20_Reducing Movements",
                # Hint for translation _("Splitting rasters")
                "subsection": "Splitting rasters",
                "conditional": (context, "opt_raster_optimisation"),
            },
            {
                "attr": "opt_reduce_travel",
                "object": context,
                "default": True,
                "type": bool,
                "label": _("Reduce Travel Time"),
                "tip": _(
                    "Using this option can significantly reduce the time spent "
                    + "moving between elements with the laser off "
                    + "by optimizing the sequence that elements are burned. "
                )
                + "\n\n"
                + _(
                    "When this option is NOT checked, elements are burned strictly "
                    + "in the order they appear in the Operation tree, "
                    + "and the Merge options will have no effect on the burn time. "
                )
                + "\n\n"
                + _(
                    "When this option IS checked, Meerk40t will burn each subpath "
                    + "and then move to the nearest remaining subpath instead, "
                    + "reducing the time taken moving between burn items."
                )
                + "\n"
                + INNER_WARNING,
                "page": "Optimisations",
                # Hint for translation _("Reducing Movements")
                "section": "_20_Reducing Movements",
            },
            {
                "attr": "opt_complete_subpaths",
                "object": context,
                "default": True,
                "type": bool,
                "label": _("Burn Complete Subpaths"),
                "tip": _(
                    "By default Reduce Travel Time optimises using SVG individual path segments, "
                    + "which means that non-closed subpaths can be burned in several shorter separate burns "
                    + "rather than one continuous burn from start to end. "
                )
                + "\n\n"
                + _(
                    "This option only affects non-closed paths. "
                    + "When this option is checked, non-closed subpaths are always burned in one continuous burn "
                    + "from start to end rather than having burns start in the middle. "
                    + "Whilst this may create a longer travel move to the end of the subpath,"
                    + "it also avoids later travel moves to or from the intermediate point. "
                    + "The total travel time may therefore be shorter or longer. "
                    + "It may also avoid minor differences in total burn depth "
                    + "at the point the burns join. "
                ),
                "page": "Optimisations",
                # Hint for translation _("Reducing Movements")
                "section": "_20_Reducing Movements",
                "conditional": (context, "opt_reduce_travel"),
            },
            {
                "attr": "opt_merge_passes",
                "object": context,
                "default": False,
                "type": bool,
                "label": _("Merge Passes"),
                "tip": _(
                    "Combine multiple passes into the same optimization. "
                    + "This will typically result in each subpath being burned multiple times in succession, "
                    + "burning closed paths round-and-round "
                    + "and non-closed paths back-and-forth, "
                    + "before Meerk40t moves to the next path. "
                )
                + "\n\n"
                + _(
                    "If you have a complex design with many paths and are burning with multiple passes, "
                    + "using this option can significantly REDUCE the optimisation time. "
                )
                + "\n\n"
                + _(
                    "NOTE: Where you burn very short paths multiple times in quick succession, "
                    + "this does not allow time for the material to cool down between burns, "
                    + "and this can result in greater charring "
                    + "or even an increased risk of the material catching fire."
                ),
                "page": "Optimisations",
                # Hint for translation _("Reducing Movements")
                "section": "_20_Reducing Movements",
                "conditional": (context, "opt_reduce_travel"),
            },
            {
                "attr": "opt_merge_ops",
                "object": context,
                "default": False,
                "type": bool,
                "label": _("Merge Operations"),
                "tip": _(
                    "Combine multiple consecutive burn operations and optimise across them globally. "
                    + "Operations of different types will be optimised together to reduce travel time, "
                    + "so vector and raster burns will be mixed. "
                )
                + "\n\n"
                + _(
                    "If Merge Passes is not checked, Operations with >1 passes will only have the same passes merged. "
                    + "If Merge Passes is also checked, then all burns will be optimised globally."
                )
                + "\n\n"
                + _(
                    "If you have a complex design with many paths across multiple consecutive burn operations, "
                    + "using this option can significantly INCREASE the optimisation time. "
                ),
                "page": "Optimisations",
                # Hint for translation _("Reducing Movements")
                "section": "_20_Reducing Movements",
                "conditional": (context, "opt_reduce_travel"),
            },
            {
                "attr": "opt_stitching",
                "object": context,
                "default": False,
                "type": bool,
                "label": _("Combine path segments"),
                "tip": _(
                    "Stitch segments together that are very close (ideally having joint start/end points)."
                )
                + "\n"
                + _("Only inside a single cut/engrave operation."),
                "page": "Optimisations",
                # Hint for translation _("Stitching")
                "section": "_05_Stitching",
            },
            {
                "attr": "opt_stitch_tolerance",
                "object": context,
                "default": "0",
                "type": Length,
                "label": _("Tolerance"),
                "tip": _(
                    "Tolerance to decide whether two path segments should be joined."
                ),
                "page": "Optimisations",
                # Hint for translation _("Stitching")
                "section": "_05_Stitching",
                "conditional": (context, "opt_stitching"),
            },
            {
                "attr": "opt_inner_first",
                "object": context,
                "default": True,
                "type": bool,
                "label": _("Burn Inner First"),
                "tip": _(
                    "Ensure that inside burns are done before an outside cut in order to ensure that burns inside "
                    + "a cut-out piece are done before the cut piece shifts or drops out of the material."
                )
                + "\n\n"
                + _(
                    "If you find that using this option significantly increases the optimisation time, "
                    + "alternatives are: \n"
                    + "* Deselecting Cut Inner First if you are not cutting fully through your material \n"
                    + "* Putting the inner paths into a separate earlier operation(s) and not using Merge Operations or Cut Inner First \n"
                    + "* If you are using multiple passes, check Merge Passes"
                )
                + "\n"
                + INNER_WARNING,
                "page": "Optimisations",
                # Hint for translation _("Burn sequence")
                "section": "_10_Burn sequence",
            },
            {
                "attr": "opt_inner_tolerance",
                "object": context,
                "default": "0",
                "type": Length,
                "label": _("Tolerance"),
                "tip": _("Tolerance to decide if a shape is truly inside another one."),
                "page": "Optimisations",
                # Hint for translation _("Burn sequence")
                "section": "_10_Burn sequence",
                "conditional": (context, "opt_inner_first"),
            },
            {
                "attr": "opt_inners_grouped",
                "object": context,
                "default": False,
                "type": bool,
                "label": _("Group Inner Burns"),
                "tip": _(
                    "Try to complete a set of inner burns and the associated outer cut before moving onto other elements.\n"
                    + "This option only does something if Burn Inner First is also selected. "
                    + "If your design has multiple separate pieces on it, "
                    + "this should mostly cause each piece to be burned in entirety "
                    + "before moving on to burn another piece. "
                    + "This can reduce the risk of e.g. a shift ruining an entire piece of material "
                    + "by trying to ensure that one piece is finished before starting on another."
                )
                + "\n\n"
                + _(
                    "This optimization works best with Merge Operations also checked though this is not a requirement. "
                )
                + "\n\n"
                + _(
                    "Because this optimisation is done once rasters have been turned into images, "
                    + "inner elements may span multiple design pieces, "
                    + "in which case they may be optimised together."
                ),
                "page": "Optimisations",
                # Hint for translation _("Burn sequence")
                "section": "_10_Burn sequence",
                "conditional": (context, "opt_inner_first"),
            },
            {
                "attr": "opt_closed_distance",
                "object": context,
                "default": 15,
                "type": int,
                "label": _("Closed Distance"),
                "tip": _(
                    "How close in device specific natural units do endpoints need to be to count as closed?"
                ),
                "page": "Optimisations",
                # Hint for translation _("Reducing Movements")
                "section": "_20_Reducing Movements",
                "hidden": True,
            },
            {
                "attr": "opt_effect_combine",
                "object": context,
                "default": True,
                "type": bool,
                "label": _("Keep effect lines together"),
                "tip": (
                    _("Active: effects like hatches are dealt with as a bigger shape")
                    + "\n"
                    + _(
                        "Inactive: every single line segment will be dealt with individually."
                    )
                ),
                "page": "Optimisations",
                # Hint for translation _("Effects")
                "section": "_25_Effects",
            },
            {
                "attr": "opt_effect_optimize",
                "object": context,
                "default": False,
                "type": bool,
                "label": _("Optimize internally"),
                "tip": (
                    _("Active: hatch lines will be optimized internally")
                    + "\n"
                    + _("Inactive: hatch lines will be burnt sequentially.")
                ),
                "page": "Optimisations",
                # Hint for translation _("Effects")
                "section": "_25_Effects",
                "conditional": (context, "opt_effect_combine"),
            },
            {
                "attr": "opt_reduce_details",
                "object": context,
                "default": False,
                "type": bool,
                "label": _("Reduce polyline details"),
                "tip": _(
                    "Active: reduce the details of polyline elements,\n"
                    + "so that less information needs to be sent to the laser."
                )
                + "\n"
                + _(
                    "This can reduce the processing and laser time but can as well\n"
                    + "compromise the quality at higher levels, so use with care and preview in simulation."
                ),
                "page": "Optimisations",
                # Hint for translation _("Details")
                "section": "_30_Details",
                "subsection": "_10_",
            },
            {
                "attr": "opt_reduce_tolerance",
                "object": context,
                "default": 10,
                "type": int,
                "label": _("Level"),
                "style": "option",
                "choices": (1, 10, 50, 100),
                "display": (_("Minimal"), _("Fine"), _("Medium"), _("Coarse")),
                "tip": _(
                    "This can reduce the processing and laser time but can as well\n"
                    + "compromise the quality at higher levels, so use with care and preview in simulation."
                ),
                "page": "Optimisations",
                # Hint for translation _("Details")
                "section": "_30_Details",
                "subsection": "_10_",
                "conditional": (context, "opt_reduce_details"),
            },
        ]
        for c in choices:
            c["help"] = "optimisation"
        kernel.register_choices("optimize", choices)
        context.setting(bool, "opt_2opt", False)
        context.setting(bool, "opt_nearest_neighbor", True)
        context.setting(bool, "opt_reduce_directions", False)
        context.setting(bool, "opt_remove_overlap", False)
        context.setting(bool, "opt_start_from_position", False)

        root = kernel.root
        root.setting(int, "job_start_from", START_FROM_ABSOLUTE)
        root.setting(int, "job_origin", 0)
        root.setting(bool, "job_cut_selected", False)
        root.setting(bool, "job_use_selection_origin", False)

        # context.setting(int, "opt_closed_distance", 15)
        # context.setting(bool, "opt_merge_passes", False)
        # context.setting(bool, "opt_merge_ops", False)
        # context.setting(bool, "opt_inner_first", True)

    elif lifecycle == "poststart":
        planner = kernel.planner
        auto = hasattr(kernel.args, "auto") and kernel.args.auto
        console = hasattr(kernel.args, "console") and kernel.args.console
        quit = hasattr(kernel.args, "quit") and kernel.args.quit
        if auto:
            planner("plan copy preprocess validate blob preopt optimize\n")
            if quit or not console:
                planner("plan console quit\n")
            planner("plan spool\n")


class Planner(Service):
    """
    Planner is a service that adds 'plan' commands to the kernel. These are text based versions of the job preview and
    should be permitted to control the job creation process.
    """

    def __init__(self, kernel, *args, **kwargs):
        Service.__init__(self, kernel, "planner")
        self._plan = dict()
        self._default_plan = "0"
        self.do_optimization = True

    def length(self, v):
        return float(Length(v))

    def length_x(self, v):
        return float(Length(v, relative_length=self.device.view.width))

    def length_y(self, v):
        return float(Length(v, relative_length=self.device.view.height))

    def get_or_make_plan(self, plan_name):
        """
        Plans are a tuple of 3 lists and the name. Plan, Original, Commands, and Plan-Name
        """
        try:
            return self._plan[plan_name]
        except KeyError:
            self._plan[plan_name] = CutPlan(plan_name, self)
            return self._plan[plan_name]

    @property
    def default_plan(self):
        return self.get_or_make_plan(self._default_plan)

    # ----------------------------------------------------------------
    # Job placement (LightBurn-like "Start From" / "Job Origin")
    # ----------------------------------------------------------------

    def get_user_origin(self):
        """
        The user origin of the active device in scene units, or None if unset.
        """
        device = getattr(self, "device", None)
        if device is None:
            return None
        x = device.setting(float, "user_origin_x", None)
        y = device.setting(float, "user_origin_y", None)
        if x is None or y is None:
            return None
        return x, y

    def set_user_origin(self, value):
        """
        Set (or clear with None) the user origin of the active device.
        """
        device = getattr(self, "device", None)
        if device is None:
            return
        device.setting(float, "user_origin_x", None)
        device.setting(float, "user_origin_y", None)
        if value is None:
            device.user_origin_x = None
            device.user_origin_y = None
        else:
            device.user_origin_x = float(value[0])
            device.user_origin_y = float(value[1])
        self.signal("user_origin", value)

    def job_target(self):
        """
        Where the job origin should be placed, in scene units.
        Returns None for absolute placement (or if the target is unknown).
        """
        mode = self.kernel.root.setting(int, "job_start_from", START_FROM_ABSOLUTE)
        if mode == START_FROM_USER_ORIGIN:
            return self.get_user_origin()
        if mode == START_FROM_CURRENT_POSITION:
            try:
                return self.device.current
            except AttributeError:
                return None
        return None

    def job_bounds(self, plan_operations=None):
        """
        Bounds that are used to establish the job origin.
        plan_operations: the operations of a plan, if that's already available.
        """
        root = self.kernel.root
        selected_only = root.setting(bool, "job_cut_selected", False)
        use_selection = root.setting(bool, "job_use_selection_origin", False)
        if selected_only and not use_selection:
            # The origin is established by the whole job, not the selection.
            return operations_bounds(self.elements.ops())
        if plan_operations is not None:
            return operations_bounds(plan_operations, require_output=False)
        if selected_only:
            return union_bounds(
                node.bounds
                for node in self.elements.elems(emphasized=True)
                if node.bounds is not None
            )
        return operations_bounds(self.elements.ops())

    def job_offset(self, plan_operations=None, bounds=None):
        """
        Offset that needs to be applied to the job to place it according to the
        Start From / Job Origin settings, or None if no offset needs to be applied.
        """
        target = self.job_target()
        if target is None:
            return None
        if bounds is None:
            bounds = self.job_bounds(plan_operations)
        if bounds is None:
            return None
        index = self.kernel.root.setting(int, "job_origin", 0)
        anchor = job_origin_anchor(bounds, index)
        dx = target[0] - anchor[0]
        dy = target[1] - anchor[1]
        if dx == 0 and dy == 0:
            return None
        return dx, dy

    def job_plan_command(self, plan_name, optimize=True, final="spool"):
        """
        Console command to build (and spool / finish) a plan honoring the job settings.
        """
        copy_cmd = "copy"
        if self.kernel.root.setting(bool, "job_cut_selected", False):
            copy_cmd = "copy --emphasized"
        steps = f"clear {copy_cmd} origin preprocess validate blob"
        if optimize:
            steps += " preopt optimize"
        return f"plan{plan_name} {steps} {final}\n"

    def service_attach(self, *args, **kwargs):
        _ = self.kernel.translation

        @self.console_command(
            "plan",
            help=_("plan<?> <command>"),
            regex=True,
            input_type=(None, "ops"),
            output_type="plan",
        )
        def plan_base(command, channel, _, data=None, remainder=None, **kwgs):
            if len(command) > 4:
                self._default_plan = command[4:]
                self.signal("plan", self._default_plan, None)

            cutplan = self.default_plan
            if data is not None:
                # If ops data is in data, then we copy that and move on to next step.
                for c in data:
                    if not c.output:
                        continue
                    try:
                        if len(c.children) == 0:
                            continue
                    except TypeError:
                        pass
                    copy_c = copy(c)
                    try:
                        copy_c.copy_children_as_real(c)
                    except AttributeError:
                        pass
                    cutplan.plan.append(copy_c)
                self.signal("plan", self._default_plan, 1)
                return "plan", cutplan
            if remainder is None:
                channel(_("----------"))
                channel(_("Plan:"))
                for i, plan_name in enumerate(cutplan.name):
                    channel(f"{i}: {plan_name}")
                channel(_("----------"))
                channel(_("Plan {plan}:").format(plan=self._default_plan))
                for i, op_name in enumerate(cutplan.plan):
                    channel(f"{i}: {op_name}")
                channel(_("Commands {plan}:").format(plan=self._default_plan))
                for i, cmd_name in enumerate(cutplan.commands):
                    channel(f"{i}: {cmd_name}")
                channel(_("----------"))

            return "plan", cutplan

        @self.console_option(
            "emphasized",
            "e",
            type=bool,
            action="store_true",
            help=_("only copy the elements that are selected on the scene"),
        )
        @self.console_command(
            ("copy", "copy-selected"),
            help=_("plan(-selected)<?> copy"),
            input_type="plan",
            output_type="plan",
        )
        def plan_copy(
            command, channel, _, data_type=None, data=None, emphasized=False, **kwgs
        ):
            # Update Info-panel if displayed
            busy = self.kernel.busyinfo
            if busy.shown:
                busy.change(msg=_("Copy data"), keep=1)
                busy.show()

            operations = data  # unused.
            if command == "copy-selected":
                operations = list(self.elements.ops(emphasized=True))
                copy_selected = True
            else:
                operations = list(self.elements.ops())
                copy_selected = False

            def init_settings():
                for prefix in ("prepend", "append"):
                    str_count = f"{prefix}_op_count"
                    self.device.setting(int, str_count, 0)
                    value = getattr(self.device, str_count, 0)
                    if value > 0:
                        for idx in range(value):
                            attr1 = f"{prefix}_op_{idx:02d}"
                            attr2 = f"{prefix}_op_param_{idx:02d}"
                            self.device.setting(str, attr1, "")
                            self.device.setting(str, attr2, "")

            def add_ops(is_prepend):
                # Do we have any default actions to include first?
                if is_prepend:
                    prefix = "prepend"
                else:
                    prefix = "append"
                try:
                    if is_prepend:
                        count = self.device.prepend_op_count
                    else:
                        count = self.device.append_op_count
                except AttributeError:
                    count = 0
                idx = 0
                while idx <= count - 1:
                    addop = None
                    attr1 = f"{prefix}_op_{idx:02d}"
                    attr2 = f"{prefix}_op_param_{idx:02d}"
                    if hasattr(self.device, attr1):
                        optype = getattr(self.device, attr1, None)
                        opparam = getattr(self.device, attr2, None)
                        if optype is not None:
                            if optype == "util console":
                                addop = ConsoleOperation(command=opparam)
                            elif optype == "util home":
                                addop = HomeOperation()
                            elif optype == "util output":
                                if opparam is not None:
                                    params = opparam.split(",")
                                    mask = 0
                                    setvalue = 0
                                    if len(params) > 0:
                                        try:
                                            mask = int(params[0])
                                        except ValueError:
                                            mask = 0
                                    if len(params) > 1:
                                        try:
                                            setvalue = int(params[1])
                                        except ValueError:
                                            setvalue = 0
                                    if mask != 0 or setvalue != 0:
                                        addop = OutputOperation(
                                            output_mask=mask, output_value=setvalue
                                        )
                            elif optype == "util goto":
                                if opparam is not None:
                                    params = opparam.split(",")
                                    x = 0
                                    y = 0
                                    if len(params) > 0:
                                        try:
                                            x = float(Length(params[0]))
                                        except ValueError:
                                            x = 0
                                    if len(params) > 1:
                                        try:
                                            y = float(Length(params[1]))
                                        except ValueError:
                                            y = 0
                                    absolute = False
                                    if len(params) > 2:
                                        absolute = params[2] not in ("False", "0")
                                    addop = GotoOperation(x=x, y=y, absolute=absolute)
                            elif optype == "util wait":
                                if opparam is not None:
                                    try:
                                        opparam = float(opparam)
                                    except ValueError:
                                        opparam = None
                                if opparam is not None:
                                    addop = WaitOperation(wait=opparam)
                    if addop is not None:
                        try:
                            if not addop.output:
                                continue
                        except AttributeError:
                            pass
                        try:
                            if len(addop) == 0:
                                continue
                        except TypeError:
                            pass
                        if addop.type == "cutcode":
                            # CutNodes are denuded into normal objects.
                            addop = addop.cutcode
                        copy_c = copy(addop)
                        try:
                            copy_c.copy_children_as_real(addop)
                        except AttributeError:
                            pass
                        data.plan.append(copy_c)

                    idx += 1

            init_settings()

            # Add default start ops
            add_ops(True)
            # types = (
            #     "op cut",
            #     "op raster",
            #     "op image",
            #     "op engrave",
            #     "op dots",
            #     "cutcode",
            #     "util console",
            #     "util wait",
            #     "util home",
            #     "util goto",
            #     "util input",
            #     "util output",
            #     "place point"
            #     "blob",
            # )
            for c in operations:
                isactive = True
                try:
                    if not c.output:
                        isactive = False
                except AttributeError:
                    pass
                if not isactive and copy_selected and len(operations) == 1:
                    # If it's the only one we make an exception
                    isactive = True
                if not isactive:
                    continue
                if not hasattr(c, "type") or c.type is None:
                    # Node must be a type of node.
                    continue
                if c.type.startswith("op ") and len(c.children) == 0:
                    # We don't need empty operations.
                    continue
                if c.type == "cutcode":
                    # CutNodes are denuded into normal objects.
                    c = c.cutcode

                # Make copy of node.
                copy_c = copy(c)
                if emphasized and c.type.startswith("op "):
                    # Only the elements that are selected on the scene
                    for child in c.children:
                        node = child.node if child.type == "reference" else child
                        if not getattr(node, "emphasized", False):
                            continue
                        copy_child = copy(node)
                        copy_c.add_node(copy_child)
                        copy_child.copy_children_as_real(node)
                    if len(copy_c.children) == 0:
                        continue
                else:
                    try:
                        # Make copy of real (non-referenced) children if that is permitted.
                        copy_c.copy_children_as_real(c)
                    except AttributeError:
                        pass
                data.plan.append(copy_c)

            # Add default trailing ops
            add_ops(False)
            channel(_("Copied Operations."))
            self.signal("plan", data.name, 1)
            return data_type, data

        @self.console_command(
            "origin",
            help="plan<?> origin : "
            + _("place the job according to the Start From / Job Origin settings"),
            input_type="plan",
            output_type="plan",
        )
        def plan_origin(command, channel, _, data_type=None, data=None, **kwgs):
            offset = self.job_offset(data.plan)
            if offset is None:
                return data_type, data
            dx, dy = offset
            for c in data.plan:
                if hasattr(c, "type") and c.type is not None and c.type.startswith("op "):
                    for child in c.children:
                        shift_node(child, dx, dy)
                    c.set_dirty_bounds()
            channel(
                _("Job moved by {dx}, {dy}").format(
                    dx=Length(amount=dx, digits=2).length_mm,
                    dy=Length(amount=dy, digits=2).length_mm,
                )
            )
            self.signal("plan", data.name, 1)
            return data_type, data

        @self.console_option(
            "index", "i", type=int, help=_("index of location to insert command")
        )
        @self.console_argument("console", type=str, help=_("console command to append"))
        @self.console_command(
            "console",
            help=_("plan<?> command"),
            input_type="plan",
            output_type="plan",
            all_arguments_required=True,
        )
        def plan_command(
            command,
            channel,
            _,
            data_type=None,
            data=None,
            console=None,
            index=None,
            **kwgs,
        ):
            if not console:
                channel(
                    _(
                        "plan console... requires a console command to inject into the current plan"
                    )
                )
            else:
                cmd = ConsoleOperation(command=console)
                if index is None:
                    data.plan.append(cmd)
                else:
                    try:
                        data.plan.insert(index, cmd)
                    except ValueError:
                        channel(_("Invalid index for command insert."))
                self.signal("plan", data.name, None)
            return data_type, data

        @self.console_command(
            "preprocess",
            help=_("plan<?> preprocess"),
            input_type="plan",
            output_type="plan",
        )
        def plan_preprocess(command, channel, _, data_type=None, data=None, **kwgs):
            # Update Info-panel if displayed
            busy = self.kernel.busyinfo
            if busy.shown:
                busy.change(msg=_("Preprocessing"), keep=1)
                busy.show()

            data.preprocess()
            self.signal("plan", data.name, 2)
            return data_type, data

        @self.console_command(
            "validate",
            help=_("plan<?> validate"),
            input_type="plan",
            output_type="plan",
        )
        def plan_validate(command, channel, _, data_type=None, data=None, **kwgs):
            # Update Info-panel if displayed
            busy = self.kernel.busyinfo
            if busy.shown:
                busy.change(msg=_("Validating"), keep=1)
                busy.show()

            try:
                data.execute()
            except CutPlanningFailedError as e:
                self.signal("cutplanning;failed", str(e))
                data.clear()
                return
            self.signal("plan", data.name, 3)
            return data_type, data

        @self.console_command(
            "geometry",
            help=_("plan<?> geometry"),
            input_type="plan",
            output_type="plan",
        )
        def plan_geometry(data_type=None, data=None, **kwgs):
            # Update Info-panel if displayed
            busy = self.kernel.busyinfo
            if busy.shown:
                busy.change(msg=_("Converting data"), keep=1)
                busy.show()

            data.geometry()
            self.signal("plan", data.name, 4)
            return data_type, data

        @self.console_command(
            "blob",
            help=_("plan<?> blob"),
            input_type="plan",
            output_type="plan",
        )
        def plan_blob(data_type=None, data=None, **kwgs):
            # Update Info-panel if displayed
            busy = self.kernel.busyinfo
            if busy.shown:
                busy.change(msg=_("Converting data"), keep=1)
                busy.show()

            data.blob()
            self.signal("plan", data.name, 4)
            return data_type, data

        @self.console_command(
            "preopt",
            help=_("plan<?> preopt"),
            input_type="plan",
            output_type="plan",
        )
        def plan_preopt(data_type=None, data=None, **kwgs):
            # Update Info-panel if displayed
            busy = self.kernel.busyinfo
            if busy.shown:
                busy.change(msg=_("Preparing optimisation"), keep=1)
                busy.show()

            data.preopt()
            self.signal("plan", data.name, 5)
            return data_type, data

        @self.console_command(
            "optimize",
            help=_("plan<?> optimize"),
            input_type="plan",
            output_type="plan",
        )
        def plan_optimize(data_type=None, data=None, **kwgs):
            # Update Info-panel if displayed
            busy = self.kernel.busyinfo
            if busy.shown:
                busy.change(msg=_("Optimising"), keep=1)
                busy.show()

            data.execute()
            self.signal("plan", data.name, 6)
            return data_type, data

        @self.console_command(
            "clear",
            help=_("plan<?> clear"),
            input_type="plan",
            output_type="plan",
        )
        def plan_clear(data_type=None, data=None, **kwgs):
            # Update Info-panel if displayed
            busy = self.kernel.busyinfo
            if busy.shown:
                busy.change(msg=_("Clearing data"), keep=1)
                busy.show()

            data.clear()
            self.signal("plan", data.name, 0)
            return data_type, data

        @self.console_command(
            "return",
            help=_("plan<?> return"),
            input_type="plan",
            output_type="plan",
        )
        def plan_return(command, channel, _, data_type=None, data=None, **kwgs):
            operations = self.elements.get(type="branch ops")
            operations.remove_all_children()

            for c in data.plan:
                if isinstance(c, CutCode):
                    operations.add(type="cutcode", cutcode=c)
                if isinstance(
                    c,
                    (
                        RasterOpNode,
                        ImageOpNode,
                        CutOpNode,
                        EngraveOpNode,
                        DotsOpNode,
                    ),
                ):
                    copy_c = copy(c)
                    operations.add_node(copy_c)
            channel(_("Returned Operations."))
            self.signal("plan", data.name, None)
            return data_type, data

        @self.console_argument(
            "start", help="start index for cutcode", type=int, default=0
        )
        @self.console_argument(
            "end", help="end index for cutcode (-1 is last value)", type=int, default=-1
        )
        @self.console_command(
            "sublist",
            help=_("plan<?> sublist"),
            input_type="plan",
            output_type="plan",
        )
        def plan_sublist(
            command, channel, _, start=None, end=None, data_type=None, data=None, **kwgs
        ):
            if end == -1:
                end = float("inf")
            pos = 0
            index = 0
            size = 0
            plan = list(data.plan)
            data.plan.clear()
            c = None
            while pos < start:
                # Process prestart elements.
                try:
                    c = plan[index]
                except IndexError:
                    break
                index += 1
                if isinstance(c, CutCode):
                    c = CutCode(c.flat())
                    size = len(c)
                else:
                    size = 0
                if (pos + size) > start:
                    break
                pos += size
                size = 0
            if (pos + size) > start:
                # We overshot the start
                c = CutCode(c[start - pos :])
                pos = start
                data.plan.append(c)
            while end > pos:
                try:
                    c = plan[index]
                except IndexError:
                    break
                index += 1
                if isinstance(c, CutCode):
                    c = CutCode(c.flat())
                    size = len(c)
                else:
                    size = 0
                pos += size
                if pos > end:
                    c = CutCode(c[: end - pos])
                data.plan.append(c)

            self.signal("plan", data.name, None)
            return data_type, data

    def plan(self, **kwargs):
        yield from self._plan
