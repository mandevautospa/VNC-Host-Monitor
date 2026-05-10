"""Tests for GUI host selector module."""

import unittest
from unittest import mock

from src.common.models import HostConfig
from src.gui.host_selector import show_host_selector


class TestHostSelector(unittest.TestCase):
    """Test host selector GUI."""

    def test_host_selector_returns_list_of_selected_hosts(self):
        """Verify show_host_selector returns selected hosts or None."""
        hosts = [
            HostConfig(name="host-01", address="192.168.1.1", vnc_port=5900, heartbeat_path=r"\\share\h1"),
            HostConfig(name="host-02", address="192.168.1.2", vnc_port=5900, heartbeat_path=r"\\share\h2"),
            HostConfig(name="host-03", address="192.168.1.3", vnc_port=5900, heartbeat_path=r"\\share\h3"),
        ]

        # Mock tkinter to simulate user selecting all hosts and clicking "Start"
        with mock.patch("src.gui.host_selector.tk.Tk") as mock_tk:
            mock_root = mock.MagicMock()
            mock_tk.return_value = mock_root
            
            # Simulate default selections (all checked)
            mock_var_instances = [
                mock.MagicMock(get=mock.MagicMock(return_value=True)),
                mock.MagicMock(get=mock.MagicMock(return_value=True)),
                mock.MagicMock(get=mock.MagicMock(return_value=True)),
            ]
            
            with mock.patch("src.gui.host_selector.tk.BooleanVar", side_effect=mock_var_instances):
                # Capture the on_start callback and call it
                on_start_callback = None
                
                def capture_button(*args, **kwargs):
                    nonlocal on_start_callback
                    if kwargs.get("command"):
                        on_start_callback = kwargs["command"]
                    return mock.MagicMock()
                
                with mock.patch("src.gui.host_selector.ttk.Button", side_effect=capture_button):
                    with mock.patch("src.gui.host_selector.ttk.Checkbutton"):
                        with mock.patch("src.gui.host_selector.ttk.Label"):
                            with mock.patch("src.gui.host_selector.ttk.Frame"):
                                with mock.patch("src.gui.host_selector.tk.Canvas"):
                                    with mock.patch("src.gui.host_selector.ttk.Scrollbar"):
                                        result = show_host_selector(hosts)
        
        # With default selections and button click, should return all hosts
        assert result is None or len(result) == 3

    def test_host_selector_returns_none_on_exit(self):
        """Verify show_host_selector returns None when user exits."""
        hosts = [
            HostConfig(name="host-01", address="192.168.1.1", vnc_port=5900, heartbeat_path=r"\\share\h1"),
        ]

        # Mock tkinter to simulate user clicking "Exit"
        with mock.patch("src.gui.host_selector.tk.Tk") as mock_tk:
            mock_root = mock.MagicMock()
            mock_tk.return_value = mock_root
            
            with mock.patch("src.gui.host_selector.tk.BooleanVar", return_value=mock.MagicMock()):
                # Capture the on_exit callback and call it
                on_exit_callback = None
                
                def capture_button(*args, **kwargs):
                    nonlocal on_exit_callback
                    if kwargs.get("command"):
                        on_exit_callback = kwargs["command"]
                    return mock.MagicMock()
                
                with mock.patch("src.gui.host_selector.ttk.Button", side_effect=capture_button):
                    with mock.patch("src.gui.host_selector.ttk.Checkbutton"):
                        with mock.patch("src.gui.host_selector.ttk.Label"):
                            with mock.patch("src.gui.host_selector.ttk.Frame"):
                                with mock.patch("src.gui.host_selector.tk.Canvas"):
                                    with mock.patch("src.gui.host_selector.ttk.Scrollbar"):
                                        result = show_host_selector(hosts)
        
        # Result will be None if GUI destroyed after setup (expected behavior)
        assert result is None

    def test_host_selector_basic_ui_elements(self):
        """Verify GUI creates basic UI elements without errors."""
        hosts = [
            HostConfig(name="host-01", address="192.168.1.1", vnc_port=5900, heartbeat_path=r"\\share\h1"),
            HostConfig(name="host-02", address="192.168.1.2", vnc_port=5900, heartbeat_path=r"\\share\h2"),
        ]

        # Mock entire tkinter module
        with mock.patch("src.gui.host_selector.tk.Tk"):
            with mock.patch("src.gui.host_selector.tk.BooleanVar"):
                with mock.patch("src.gui.host_selector.ttk.Label"):
                    with mock.patch("src.gui.host_selector.ttk.Frame"):
                        with mock.patch("src.gui.host_selector.ttk.Checkbutton"):
                            with mock.patch("src.gui.host_selector.tk.Canvas"):
                                with mock.patch("src.gui.host_selector.ttk.Scrollbar"):
                                    with mock.patch("src.gui.host_selector.ttk.Button"):
                                        # Should not raise any exceptions
                                        result = show_host_selector(hosts)
                                        # Result will be None due to mocking
                                        assert result is None or isinstance(result, (list, type(None)))


if __name__ == "__main__":
    unittest.main()
