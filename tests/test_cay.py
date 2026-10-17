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

    def test_cong_nam_trong_bridge_thi_cha_la_bridge(self):
        cay = xay_cay(GIAO_DIEN, BANG_MAC, ARP, ZTE, "MikroTik", bridge_cua={"ether2": "BridgeLAN", "ether4": "BridgeLAN"})
        nut = {n["id"]: n for n in cay["nodes"]}
        self.assertEqual(nut["ether2"]["parent"], "BridgeLAN")
        self.assertEqual(nut["ether4"]["parent"], "BridgeLAN")
        self.assertEqual(nut["BridgeLAN"]["parent"], "router")          # chính bridge và cổng ngoài bridge giữ cha là router
        self.assertEqual(nut["WAN-ETHER1"]["parent"], "router")
        self.assertEqual(nut["zte"]["parent"], "ether4")                # ZTE vẫn là con của cổng nó cắm vào
        self.assertEqual(theo_mac(cay)["AA:00:00:00:00:11"]["parent"], "zte")

    def test_bridge_khong_co_trong_snmp_hoac_vong_thi_ve_router(self):
        cay = xay_cay(GIAO_DIEN, BANG_MAC, ARP, None, "MikroTik",
                      bridge_cua={"ether2": "BridgeMa", "BridgeLAN": "BridgeLAN", "ether4": "ether2"})
        nut = {n["id"]: n for n in cay["nodes"]}
        self.assertEqual(nut["ether2"]["parent"], "router")             # bridge không có trong SNMP: không bịa cha
        self.assertEqual(nut["BridgeLAN"]["parent"], "router")          # bridge tự trỏ vào mình: bỏ
        self.assertEqual(nut["ether4"]["parent"], "router")             # cha không phải bridge: bỏ

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


class TenMayTest(unittest.TestCase):
    def test_ten_theo_mac_uu_tien_hon_ten_zte(self):
        ten = {"AA:00:00:00:00:01": "Máy in", "AA:00:00:00:00:11": "Honor của Tuệ"}
        c = {m["mac"]: m for m in xay_cay(GIAO_DIEN, BANG_MAC, ARP, ZTE, "MikroTik", ten)["clients"]}
        self.assertEqual(c["AA:00:00:00:00:01"]["name"], "Máy in")          # máy có dây: tên tự đặt
        self.assertEqual(c["AA:00:00:00:00:11"]["name"], "Honor của Tuệ")   # ghi đè tên ZTE
        self.assertEqual(c["AA:00:00:00:00:12"]["name"], "Galaxy")          # không đặt thì dùng tên ZTE

    def test_ten_tu_dat_khong_phan_biet_hoa_thuong_mac(self):
        c = {m["mac"]: m for m in xay_cay(GIAO_DIEN, BANG_MAC, ARP, None, "MikroTik", {"aa:00:00:00:00:03": "NAS"})["clients"]}
        self.assertEqual(c["AA:00:00:00:00:03"]["name"], "NAS")

    def test_phan_tich_van_ban_ten(self):
        from mikrotik_snmp.logic import phan_tich_ten_may
        vb = "aa:bb:cc:dd:ee:01 = Máy in\nAA-BB-CC-DD-EE-02=NAS Synology\n  \nkhong-phai-mac=Bo\nAA:BB:CC:DD:EE:03 =   \n# ghi chú"
        self.assertEqual(phan_tich_ten_may(vb), {"AA:BB:CC:DD:EE:01": "Máy in", "AA:BB:CC:DD:EE:02": "NAS Synology"})
        self.assertEqual(phan_tich_ten_may(""), {})
        self.assertEqual(len(next(iter(phan_tich_ten_may("AA:BB:CC:DD:EE:01=" + "x" * 200).values()))), 40)


class LoopbackTest(unittest.TestCase):
    def test_bo_giao_dien_loopback_theo_mtu(self):
        from mikrotik_snmp import logic as L
        ten = {f"{L.IF_NAME}.1": "lo", f"{L.IF_NAME}.2": "ether1"}
        loai = {f"{L.IF_TYPE}.1": 1, f"{L.IF_TYPE}.2": 6}                    # lo báo loại «other», không phải 24
        mtu = {f"{L.IF_MTU}.1": 65536, f"{L.IF_MTU}.2": 1500}
        gd = L.phan_tich_giao_dien(ten, loai, mtu)
        self.assertEqual([g["name"] for g in gd.values()], ["ether1"])


class TenMikTest(unittest.TestCase):
    def test_thu_tu_uu_tien_ten(self):
        """tên tự đặt > ghi chú DHCP trên MikroTik > tên ZTE > tên máy tự báo (host-name)."""
        ten_mik = {
            "AA:00:00:00:00:01": {"comment": "Máy in", "host_name": "HP123"},
            "AA:00:00:00:00:03": {"comment": "", "host_name": "nas-host"},
            "AA:00:00:00:00:11": {"comment": "Honor của Tuệ", "host_name": "HONOR"},
            "AA:00:00:00:00:12": {"comment": "", "host_name": "galaxy-host"},
        }
        c = {m["mac"]: m for m in xay_cay(GIAO_DIEN, BANG_MAC, ARP, ZTE, "MikroTik", {"AA:00:00:00:00:01": "Tên tay"}, ten_mik)["clients"]}
        self.assertEqual(c["AA:00:00:00:00:01"]["name"], "Tên tay")            # tự đặt thắng
        self.assertEqual(c["AA:00:00:00:00:03"]["name"], "nas-host")           # chỉ có host-name
        self.assertEqual(c["AA:00:00:00:00:11"]["name"], "Honor của Tuệ")      # ghi chú MikroTik thắng tên ZTE
        self.assertEqual(c["AA:00:00:00:00:12"]["name"], "Galaxy")             # ZTE thắng host-name

    def test_khong_co_nguon_ten_mik_thi_nhu_cu(self):
        c = {m["mac"]: m for m in xay_cay(GIAO_DIEN, BANG_MAC, ARP, ZTE, "MikroTik")["clients"]}
        self.assertEqual(c["AA:00:00:00:00:11"]["name"], "Honor")


class TocDoKidTest(unittest.TestCase):
    def test_toc_do_tu_byte_theo_thoi_gian_va_tu_rate_khi_chua_co_lan_truoc(self):
        from mikrotik_snmp.logic import toc_do_tu_kid
        truoc = {}
        kid = {"AA:00:00:00:00:01": {"bytes_down": 0, "bytes_up": 0, "rate_down": 4_000_000, "rate_up": 1_000_000}}
        d1 = toc_do_tu_kid(truoc, kid, 100.0)
        self.assertEqual(d1["AA:00:00:00:00:01"], {"rx_mbps": 4.0, "tx_mbps": 1.0})       # lần đầu: dùng rate của router
        kid2 = {"AA:00:00:00:00:01": {"bytes_down": 6_250_000, "bytes_up": 125_000, "rate_down": 0, "rate_up": 0}}
        d2 = toc_do_tu_kid(truoc, kid2, 105.0)
        self.assertEqual(d2["AA:00:00:00:00:01"], {"rx_mbps": 10.0, "tx_mbps": 0.2})     # 50 Mbit / 5 s; 1 Mbit / 5 s
        kid3 = {"AA:00:00:00:00:01": {"bytes_down": 10, "bytes_up": 10, "rate_down": None, "rate_up": None}}
        d3 = toc_do_tu_kid(truoc, kid3, 110.0)
        self.assertEqual(d3["AA:00:00:00:00:01"], {"rx_mbps": None, "tx_mbps": None})     # bộ đếm đặt lại: không bịa số

    def test_toc_do_vao_cay_cho_tung_may(self):
        toc = {"AA:00:00:00:00:11": {"rx_mbps": 5.5, "tx_mbps": 0.5}}
        c = {m["mac"]: m for m in xay_cay(GIAO_DIEN, BANG_MAC, ARP, ZTE, "MikroTik", None, None, toc)["clients"]}
        self.assertEqual((c["AA:00:00:00:00:11"]["rx_mbps"], c["AA:00:00:00:00:11"]["tx_mbps"]), (5.5, 0.5))
        self.assertEqual(c["AA:00:00:00:00:11"]["rx_bps"], 5_500_000)
        self.assertIsNone(c["AA:00:00:00:00:01"]["rx_mbps"])                               # máy không có số đo: None, không phải 0
