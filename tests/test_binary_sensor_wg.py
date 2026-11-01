"""Hồi quy log HA 30/10/2026: «Error while setting up mikrotik_snmp platform for binary_sensor: name 'slug' is not defined».

WgKetNoi dùng `slug` và `DeviceInfo` mà tệp không nhập, nên cả nền tảng binary_sensor không nạp được khi có peer WireGuard."""
from __future__ import annotations

import pathlib
import sys
import types
import unittest
from unittest.mock import MagicMock

ROOT = pathlib.Path(__file__).resolve().parents[1]
if "mikrotik_snmp" not in sys.modules:
    goi = types.ModuleType("mikrotik_snmp")
    goi.__path__ = [str(ROOT / "custom_components" / "mikrotik_snmp")]
    sys.modules["mikrotik_snmp"] = goi

from mikrotik_snmp.binary_sensor import WgKetNoi  # noqa: E402
from mikrotik_snmp.const import DOMAIN  # noqa: E402


class WgKetNoiTest(unittest.TestCase):
    def _dung(self, ten="peer-Điện thoại 1"):
        cd = MagicMock()
        cd.tien_to = "mk"
        cd.data = {"wireguard": [{"name": ten, "connected": True}]}
        entry = MagicMock()
        entry.entry_id = "e1"
        return WgKetNoi(cd, entry, ten)

    def test_dung_duoc_va_dinh_danh_thiet_bi_theo_ten_peer(self):
        e = self._dung()
        self.assertTrue(e.unique_id.startswith("e1_wg_") and e.unique_id.endswith("_connected"))
        (kieu, ma), = e.device_info["identifiers"]
        self.assertEqual(kieu, DOMAIN)
        self.assertTrue(ma.startswith("e1_wg_"))
        self.assertTrue(e.entity_id.startswith("binary_sensor.mk_wireguard_"))

    def test_trang_thai_theo_du_lieu(self):
        e = self._dung()
        self.assertIs(e.is_on, True)
        e.coordinator.data = {"wireguard": []}      # peer đã bị xoá khỏi router
        self.assertIsNone(e.is_on)


if __name__ == "__main__":
    unittest.main()
