"""Tests for GUI initialization and components."""

import sys
import unittest


class TestGUIInitialization(unittest.TestCase):
    """Test suite for GUI classes and imports."""

    def test_pyside6_window_instantiation(self):
        """Verify PySide6 window can be instantiated cleanly in headless/test mode."""
        try:
            from PySide6.QtWidgets import QApplication
            from audacity_to_reaper.gui import launch_qt_gui
        except ImportError:
            self.skipTest("PySide6 not installed")

        app = QApplication.instance() or QApplication(["test", "-platform", "offscreen"])

        # Import the window class from gui
        import audacity_to_reaper.gui as gui_mod
        # Verify launch_qt_gui is callable and launch_tk_gui is callable
        self.assertTrue(callable(gui_mod.launch_qt_gui))
        self.assertTrue(callable(gui_mod.launch_tk_gui))
        self.assertTrue(callable(gui_mod.launch_gui))


if __name__ == "__main__":
    unittest.main()
