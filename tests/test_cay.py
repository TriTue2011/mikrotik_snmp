"""Test việc gộp MikroTik (cổng, ARP, bảng MAC) với ZTE (máy WiFi) thành cây: Router → Cổng → ZTE → Thiết bị."""
from __future__ import annotations

import pathlib
import sys
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if "mikrotik_snmp" not in sys.modules:
    goi = types.ModuleType("mikrotik_snmp")
    goi.__path__ = [str(ROOT / "custom_components" / "mikrotik_snmp")]
    sys.modules["mikrotik_snmp"] = goi

from mikrotik_snmp.cay import xay_cay  # noqa: E402

GIAO_DIEN = {
    2: {"name": "WAN-ETHER1", "kind": "port", "up": True},
    3: {"name": "ether2", "kind": "port", "up": True},
    5: {"name": "ether4", "kind": "port", "up": True},
    6: {"name": "BridgeLAN", "kind": "bridge", "up": True},
}
# ether2 (SW1): máy A có dây. ether4 (SW2): máy C có dây + chính ZTE (MAC 24) + hai máy WiFi (học được qua ZTE)
BANG_MAC = {
    "ether2": ["AA:00:00:00:00:01"],
    "ether4": ["AA:00:00:00:00:03", "AA:00:00:00:00:24", "AA:00:00:00:00:11", "AA:00:00:00:00:12"],
}
ARP = {
    "AA:00:00:00:00:01": "172.16.10.50",
    "AA:00:00:00:00:03": "172.16.10.60",
    "AA:00:00:00:00:24": "172.16.10.24",      # chính ZTE
    "AA:00:00:00:00:11": "172.16.10.31",
    "AA:00:00:00:00:12": "172.16.10.32",
}
ZTE = {
    "host": "172.16.10.24",
    "trang_thai": "ok",
    "ap": {"mac": "02:11:22:33:44:55", "ip": "172.16.10.24", "name": "ZTE:ZXHN E2633", "firmware": "V1.0.4"},
    "clients": [
        {"mac": "aa:00:00:00:00:11", "ip": "172.16.10.31", "name": "Honor", "band": "5G", "rssi": -58, "mode": "802.11ax", "assoc_s": 13251},
        {"mac": "aa:00:00:00:00:12", "ip": "172.16.10.32", "name": "Galaxy", "band": "2.4G", "rssi": -70, "mode": "802.11n", "assoc_s": 90},
    ],
}


def theo_mac(cay):
    return {c["mac"]: c for c in cay["clients"]}


class CayTest(unittest.TestCase):
    def test_may_wifi_la_con_cua_zte_va_co_them_thong_tin(self):
        c = theo_mac(xay_cay(GIAO_DIEN, BANG_MAC, ARP, ZTE, "MikroTik"))
        honor = c["AA:00:00:00:00:11"]
        self.assertEqual(honor["parent"], "zte")
        self.assertEqual((honor["name"], honor["band"], honor["rssi"], honor["mode"], honor["assoc_s"]), ("Honor", "5G", -58, "802.11ax", 13251))
        self.assertEqual(honor["ip"], "172.16.10.31")
        self.assertTrue(honor["wifi"])

    def test_may_co_day_la_con_cua_cong(self):
        c = theo_mac(xay_cay(GIAO_DIEN, BANG_MAC, ARP, ZTE, "MikroTik"))
        self.assertEqual(c["AA:00:00:00:00:01"]["parent"], "ether2")
        self.assertEqual(c["AA:00:00:00:00:03"]["parent"], "ether4")
        self.assertFalse(c["AA:00:00:00:00:01"]["wifi"])
        self.assertIsNone(c["AA:00:00:00:00:01"]["rssi"])
        self.assertEqual(c["AA:00:00:00:00:01"]["ip"], "172.16.10.50")

    def test_zte_la_nut_con_cua_cong_no_cam_vao_va_khong_nam_trong_may(self):
        cay = xay_cay(GIAO_DIEN, BANG_MAC, ARP, ZTE, "MikroTik")
        nut = {n["id"]: n for n in cay["nodes"]}
        self.assertEqual(nut["zte"]["parent"], "ether4")            # suy từ IP 172.16.10.24 → MAC → cổng ether4
        self.assertEqual(nut["zte"]["kind"], "ap")
        self.assertNotIn("AA:00:00:00:00:24", theo_mac(cay))        # ZTE không tự là «máy» của chính nó

    def test_nut_router_va_cong(self):
        nut = {n["id"]: n for n in xay_cay(GIAO_DIEN, BANG_MAC, ARP, ZTE, "MikroTik")["nodes"]}
        self.assertEqual(nut["router"]["parent"], None)
        self.assertEqual(nut["ether2"]["parent"], "router")
        self.assertEqual(nut["BridgeLAN"]["kind"], "bridge")

    def test_khong_khai_zte_thi_chi_con_cua_cong(self):
        cay = xay_cay(GIAO_DIEN, BANG_MAC, ARP, None, "MikroTik")
        self.assertNotIn("zte", {n["id"] for n in cay["nodes"]})
        c = theo_mac(cay)
        self.assertEqual(c["AA:00:00:00:00:11"]["parent"], "ether4")    # không có ZTE: máy WiFi chỉ biết cổng
        self.assertFalse(c["AA:00:00:00:00:11"]["wifi"])

    def test_may_chi_co_trong_zte_van_hien_duoi_zte(self):
        zte = {**ZTE, "clients": ZTE["clients"] + [{"mac": "aa:00:00:00:00:99", "ip": "172.16.10.99", "name": "Moi", "band": "2.4G",
                                                    "rssi": -80, "mode": "802.11n", "assoc_s": 5}]}
        c = theo_mac(xay_cay(GIAO_DIEN, BANG_MAC, ARP, zte, "MikroTik"))
        self.assertEqual(c["AA:00:00:00:00:99"]["parent"], "zte")
        self.assertEqual(c["AA:00:00:00:00:99"]["ip"], "172.16.10.99")   # IP lấy từ ZTE khi MikroTik chưa có ARP

    def test_may_chi_co_arp_khong_co_cong_thi_dat_duoi_router(self):
        c = theo_mac(xay_cay(GIAO_DIEN, BANG_MAC, {**ARP, "AA:00:00:00:00:77": "172.16.10.77"}, ZTE, "MikroTik"))
        self.assertEqual(c["AA:00:00:00:00:77"]["parent"], "router")
        self.assertEqual(c["AA:00:00:00:00:77"]["interface"], "")

    def test_zte_loi_dang_nhap_thi_may_wifi_chi_biet_cong(self):
        zte_loi = {"host": "172.16.10.24", "trang_thai": "loi_dang_nhap", "ap": {}, "clients": []}
        cay = xay_cay(GIAO_DIEN, BANG_MAC, ARP, zte_loi, "MikroTik")
        c = theo_mac(cay)
        self.assertEqual(c["AA:00:00:00:00:11"]["parent"], "ether4")
        nut = {n["id"]: n for n in cay["nodes"]}
        self.assertEqual(nut["zte"]["parent"], "ether4")                 # vẫn thấy nút ZTE (IP khai) dù không đăng nhập được
        self.assertEqual(nut["zte"]["trang_thai"], "loi_dang_nhap")

    def test_thu_tu_on_dinh_theo_cha_roi_ip(self):
        ds = xay_cay(GIAO_DIEN, BANG_MAC, ARP, ZTE, "MikroTik")["clients"]
        self.assertEqual([c["ip"] for c in ds if c["parent"] == "zte"], ["172.16.10.31", "172.16.10.32"])


if __name__ == "__main__":
    unittest.main()
