"""
Job placement as known from LightBurn: "Start From" (absolute coordinates,
user origin, current position), the 3x3 "Job Origin" and
"Cut Selected Graphics". The planner moves the copied plan data,
the elements on the scene must stay where they are.
"""

import unittest

from meerk40t.core.planner import (
    START_FROM_ABSOLUTE,
    START_FROM_CURRENT_POSITION,
    START_FROM_USER_ORIGIN,
    job_origin_anchor,
)
from meerk40t.core.units import Length
from test import bootstrap


def plan_elements(plan):
    return [
        child
        for op in plan.plan
        if getattr(op, "type", "").startswith("op ")
        for child in op.children
    ]


class TestJobOriginAnchor(unittest.TestCase):
    def test_corners_and_center(self):
        bounds = (10, 20, 30, 60)
        self.assertEqual(job_origin_anchor(bounds, 0), (10, 20))
        self.assertEqual(job_origin_anchor(bounds, 2), (30, 20))
        self.assertEqual(job_origin_anchor(bounds, 4), (20, 40))
        self.assertEqual(job_origin_anchor(bounds, 6), (10, 60))
        self.assertEqual(job_origin_anchor(bounds, 8), (30, 60))

    def test_index_is_clamped(self):
        bounds = (0, 0, 10, 10)
        self.assertEqual(job_origin_anchor(bounds, -3), (0, 0))
        self.assertEqual(job_origin_anchor(bounds, 42), (10, 10))


class TestPlannerJobOrigin(unittest.TestCase):
    def setUp(self):
        self.kernel = bootstrap.bootstrap(profile="MeerK40t_TEST_joborigin")
        self.kernel.console("service device start -i grbl 0\n")
        self.kernel.console("element* delete\noperation* delete\n")
        self.kernel.console("rect 1cm 1cm 2cm 2cm\n")
        self.kernel.console("rect 5cm 5cm 1cm 1cm\n")
        # New elements get classified automatically, we want a single cut op
        self.kernel.console("operation* delete\n")
        self.kernel.console("element* cut\n")
        root = self.kernel.root
        root.job_start_from = START_FROM_ABSOLUTE
        root.job_origin = 0
        root.job_cut_selected = False
        root.job_use_selection_origin = False
        self.planner = self.kernel.planner
        self.planner.set_user_origin(None)

    def tearDown(self):
        self.kernel()

    def _bounds(self, nodes):
        b = [n.bounds for n in nodes]
        return (
            min(x[0] for x in b),
            min(x[1] for x in b),
            max(x[2] for x in b),
            max(x[3] for x in b),
        )

    def assertPoint(self, point, expected):
        self.assertAlmostEqual(point[0], expected[0], delta=1)
        self.assertAlmostEqual(point[1], expected[1], delta=1)

    def test_absolute_keeps_position(self):
        self.kernel.console("plan clear copy origin\n")
        nodes = plan_elements(self.planner.default_plan)
        self.assertEqual(len(nodes), 2)
        scene = self._bounds(list(self.kernel.elements.elems()))
        self.assertPoint(self._bounds(nodes), scene)

    def test_user_origin_top_left(self):
        target = (float(Length("10cm")), float(Length("8cm")))
        self.planner.set_user_origin(target)
        self.kernel.root.job_start_from = START_FROM_USER_ORIGIN
        self.kernel.root.job_origin = 0
        before = self._bounds(list(self.kernel.elements.elems()))
        self.kernel.console("plan clear copy origin\n")
        moved = self._bounds(plan_elements(self.planner.default_plan))
        self.assertPoint(moved, target)
        # Same size, just moved
        self.assertAlmostEqual(moved[2] - moved[0], before[2] - before[0], delta=1)
        # The scene itself is untouched
        after = self._bounds(list(self.kernel.elements.elems()))
        self.assertPoint(after, before)

    def test_user_origin_center(self):
        target = (float(Length("10cm")), float(Length("8cm")))
        self.planner.set_user_origin(target)
        self.kernel.root.job_start_from = START_FROM_USER_ORIGIN
        self.kernel.root.job_origin = 4
        self.kernel.console("plan clear copy origin\n")
        moved = self._bounds(plan_elements(self.planner.default_plan))
        center = ((moved[0] + moved[2]) / 2, (moved[1] + moved[3]) / 2)
        self.assertPoint(center, target)

    def test_missing_user_origin_does_not_move(self):
        self.kernel.root.job_start_from = START_FROM_USER_ORIGIN
        before = self._bounds(list(self.kernel.elements.elems()))
        self.kernel.console("plan clear copy origin\n")
        self.assertPoint(self._bounds(plan_elements(self.planner.default_plan)), before)

    def test_current_position(self):
        self.kernel.root.job_start_from = START_FROM_CURRENT_POSITION
        self.kernel.root.job_origin = 8
        target = self.kernel.device.current
        self.kernel.console("plan clear copy origin\n")
        moved = self._bounds(plan_elements(self.planner.default_plan))
        self.assertPoint((moved[2], moved[3]), target)

    def test_copy_emphasized_only(self):
        elements = self.kernel.elements
        first = list(elements.elems())[0]
        elements.set_emphasis([first])
        self.kernel.console("plan clear copy --emphasized\n")
        nodes = plan_elements(self.planner.default_plan)
        self.assertEqual(len(nodes), 1)
        self.assertPoint(nodes[0].bounds, first.bounds)

    def test_selection_origin(self):
        elements = self.kernel.elements
        second = list(elements.elems())[1]
        elements.set_emphasis([second])
        target = (float(Length("10cm")), float(Length("8cm")))
        self.planner.set_user_origin(target)
        root = self.kernel.root
        root.job_start_from = START_FROM_USER_ORIGIN
        root.job_cut_selected = True
        # Without selection origin the whole job establishes the origin
        root.job_use_selection_origin = False
        whole = self._bounds(list(elements.elems()))
        self.kernel.console("plan clear copy --emphasized origin\n")
        node = plan_elements(self.planner.default_plan)[0]
        self.assertPoint(
            node.bounds,
            (
                target[0] + second.bounds[0] - whole[0],
                target[1] + second.bounds[1] - whole[1],
            ),
        )
        # With selection origin the selection itself is placed at the origin
        root.job_use_selection_origin = True
        self.kernel.console("plan clear copy --emphasized origin\n")
        node = plan_elements(self.planner.default_plan)[0]
        self.assertPoint(node.bounds, target)

    def test_job_plan_command(self):
        root = self.kernel.root
        root.job_cut_selected = False
        command = self.planner.job_plan_command("z", optimize=False)
        self.assertEqual(
            command, "planz clear copy origin preprocess validate blob spool\n"
        )
        root.job_cut_selected = True
        command = self.planner.job_plan_command("z", optimize=True, final="finish")
        self.assertIn("copy --emphasized origin", command)
        self.assertTrue(command.endswith("preopt optimize finish\n"))

class TestJobOriginImage(unittest.TestCase):
    def test_scene_image_is_not_moved(self):
        import os
        import tempfile

        from PIL import Image

        kernel = bootstrap.bootstrap(profile="MeerK40t_TEST_joborigin_img")
        try:
            kernel.console("service device start -i grbl 0\n")
            kernel.console("element* delete\noperation* delete\n")
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "t.png")
                Image.new("RGB", (200, 100), "black").save(path)
                kernel.console(f"load {path}\n")
            node = list(kernel.elements.elems())[0]
            node.convex_hull  # populate the cached hull
            before = tuple(node.bounds)
            hull_before = list(node._convex_hull.points) if node._convex_hull else None
            planner = kernel.planner
            planner.set_user_origin((float(Length("10cm")), float(Length("8cm"))))
            kernel.root.job_start_from = START_FROM_USER_ORIGIN
            kernel.console("plan clear copy origin\n")
            self.assertEqual(tuple(node.bounds), before)
            if hull_before is not None:
                self.assertEqual(list(node._convex_hull.points), hull_before)
            self.assertEqual(kernel.elements.translate_node(node, 100, 50), None)
            self.assertNotEqual(tuple(node.bounds), before)
        finally:
            kernel()


if __name__ == "__main__":
    unittest.main()
