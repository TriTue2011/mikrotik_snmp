"""Thiết bị con tạo thẳng trong sổ thiết bị phải dùng `via_device_id` (HA báo `via_device` đã lỗi thời và sẽ ngừng hỗ trợ)."""
from __future__ import annotations

import pathlib
import sys
import types
import unittest
from types import SimpleNamespace

ROOT = pathlib.Path(__file__).resolve().parents[1]
if "mikrotik_snmp" not in sys.modules:
    goi = types.ModuleType("mikrotik_snmp")
    goi.__path__ = [str(ROOT / "custom_components" / "mikrotik_snmp")]
    sys.modules["mikrotik_snmp"] = goi

from mikrotik_snmp.thiet_bi_con import tao_thiet_bi_con  # noqa: E402

CHA = ("mikrotik_snmp", "e1")


class SoGia:
    def __init__(self, co_cha=True):
        self.co_cha = co_cha
        self.goi = []

    def async_get_device(self, identifiers=None, connections=None):
        return SimpleNamespace(id="id-cha") if self.co_cha and identifiers == {CHA} else None

    def async_get_or_create(self, **kw):
        self.goi.append(kw)
        return SimpleNamespace(id="id-con")


class ThietBiConTest(unittest.TestCase):
    def test_dung_via_device_id_va_khong_dung_via_device(self):
        so = SoGia()
        tao_thiet_bi_con(so, "e1", {("mikrotik_snmp", "e1_2")}, CHA, name="ether1")
        self.assertEqual(len(so.goi), 1)
        kw = so.goi[0]
        self.assertEqual(kw["via_device_id"], "id-cha")
        self.assertNotIn("via_device", kw)
        self.assertEqual(kw["config_entry_id"], "e1")
        self.assertEqual(kw["name"], "ether1")

    def test_cha_chua_co_thi_van_tao_con_khong_gan_cha(self):
        so = SoGia(co_cha=False)
        tao_thiet_bi_con(so, "e1", {("mikrotik_snmp", "e1_2")}, CHA, name="ether1")
        self.assertNotIn("via_device_id", so.goi[0])
        self.assertNotIn("via_device", so.goi[0])


if __name__ == "__main__":
    unittest.main()
