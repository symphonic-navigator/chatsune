import pytest
from backend.modules.chat._context import get_ampel_status, calculate_budget, select_message_pairs


class TestGetAmpelStatus:
    def test_green_below_50_percent(self):
        assert get_ampel_status(0.0) == "green"
        assert get_ampel_status(0.3) == "green"
        assert get_ampel_status(0.49) == "green"

    def test_yellow_at_50_percent(self):
        assert get_ampel_status(0.50) == "yellow"
        assert get_ampel_status(0.55) == "yellow"
        assert get_ampel_status(0.64) == "yellow"

    def test_orange_at_65_percent(self):
        assert get_ampel_status(0.65) == "orange"
        assert get_ampel_status(0.70) == "orange"
        assert get_ampel_status(0.79) == "orange"

    def test_red_at_80_percent(self):
        assert get_ampel_status(0.80) == "red"
        assert get_ampel_status(0.835) == "red"
        assert get_ampel_status(1.0) == "red"
