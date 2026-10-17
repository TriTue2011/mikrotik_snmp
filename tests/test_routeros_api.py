"""Test máy khách API RouterOS CHỈ ĐỌC (tên máy từ DHCP): giao thức câu-từ, chỉ cho phép lệnh print, ghim vân tay, ánh xạ lease → tên."""
from __future__ import annotations

import hashlib
import pathlib
import socket
import sys
import threading
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if "mikrotik_snmp" not in sys.modules:
    goi = types.ModuleType("mikrotik_snmp")
    goi.__path__ = [str(ROOT / "custom_components" / "mikrotik_snmp")]
    sys.modules["mikrotik_snmp"] = goi

from mikrotik_snmp import routeros_api as R  # noqa: E402


class RouterGia:
    """Router giả nói giao thức API (không TLS): nhận /login, trả lease; ghi lại mọi lệnh nhận được."""

    def __init__(self, mat_khau="mk-gia", lease=None):
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(1)
        self.port = self.srv.getsockname()[1]
        self.mat_khau = mat_khau
        self.lease = lease if lease is not None else []
        self.nhan: list[list[str]] = []
        threading.Thread(target=self._chay, daemon=True).start()

    def _doc_cau(self, c):
        def n_byte(n):
            b = b""
            while len(b) < n:
                x = c.recv(n - len(b))
                if not x:
                    raise EOFError
                b += x
            return b
        tu = []
        while True:
            d = n_byte(1)[0]
            if d == 0:
                return tu
            if d < 0x80:
                n = d
            elif d < 0xC0:
                n = ((d & 0x3F) << 8) | n_byte(1)[0]
            else:
                raise ValueError("độ dài không hỗ trợ trong test")
            tu.append(n_byte(n).decode())

    def _gui(self, c, *tu):
        for w in tu:
            b = w.encode()
            c.sendall(R._ma_do_dai(len(b)) + b)
        c.sendall(b"\x00")

    def _chay(self):
        c, _ = self.srv.accept()
        try:
            while True:
                cau = self._doc_cau(c)
                self.nhan.append(cau)
                if cau[0] == "/login":
                    if f"=password={self.mat_khau}" in cau:
                        self._gui(c, "!done")
                    else:
                        self._gui(c, "!trap", "=message=invalid user name or password")
                        self._gui(c, "!done")
                elif cau[0] == "/ip/kid-control/device/print":
                    for k in getattr(self, "kid", []):
                        self._gui(c, "!re", *[f"={a}={b}" for a, b in k.items()])
                    self._gui(c, "!done")
                elif cau[0] == "/ip/dhcp-server/lease/print":
                    for ls in self.lease:
                        self._gui(c, "!re", *[f"={k}={v}" for k, v in ls.items()])
                    self._gui(c, "!done")
                else:
                    self._gui(c, "!trap", "=message=not allowed in test")
                    self._gui(c, "!done")
        except (EOFError, OSError):
            pass


class ApiTest(unittest.TestCase):
    def _phien(self, rt):
        s = socket.create_connection(("127.0.0.1", rt.port), timeout=3)
        p = R.Phien(s)
        p.dang_nhap("doc", rt.mat_khau)
        return p

    def test_dang_nhap_va_doc_lease(self):
        rt = RouterGia(lease=[
            {"mac-address": "AA:BB:CC:DD:EE:01", "host-name": "may-in", "comment": "Máy in phòng khách", "address": "172.16.10.50"},
            {"mac-address": "aa:bb:cc:dd:ee:02", "host-name": "iphone", "address": "172.16.10.51"},
            {"address": "172.16.10.99"},                                         # lease không có MAC: bỏ
        ])
        ten = R.ten_tu_dhcp(self._phien(rt))
        self.assertEqual(ten["AA:BB:CC:DD:EE:01"], {"comment": "Máy in phòng khách", "host_name": "may-in"})
        self.assertEqual(ten["AA:BB:CC:DD:EE:02"], {"comment": "", "host_name": "iphone"})
        self.assertEqual(len(ten), 2)
        lenh = [c for c in rt.nhan if c[0] == "/ip/dhcp-server/lease/print"][0]
        self.assertTrue(any(w.startswith("=.proplist=") for w in lenh))          # chỉ hỏi các cột cần, không kéo cả bảng

    def test_kid_control_doc_byte_va_rate(self):
        rt = RouterGia()
        rt.kid = [{"mac-address": "aa:bb:cc:dd:ee:01", "bytes-down": "1000", "bytes-up": "500", "rate-down": "2000000", "rate-up": "100000"},
                  {"mac-address": "AA:BB:CC:DD:EE:02", "bytes-down": "x"}]
        kid = R.kid_control(self._phien(rt))
        self.assertEqual(kid["AA:BB:CC:DD:EE:01"], {"bytes_down": 1000, "bytes_up": 500, "rate_down": 2000000, "rate_up": 100000})
        self.assertEqual(kid["AA:BB:CC:DD:EE:02"]["bytes_down"], None)          # số hỏng → None, không ném lỗi

    def test_sai_mat_khau_bao_dang_nhap_khong_lo_mat_khau(self):
        rt = RouterGia(mat_khau="dung-mk")
        s = socket.create_connection(("127.0.0.1", rt.port), timeout=3)
        p = R.Phien(s)
        with self.assertRaises(R.ApiLoiDangNhap) as ctx:
            p.dang_nhap("doc", "sai-mat-khau-nhap-vao")
        self.assertNotIn("sai-mat-khau-nhap-vao", str(ctx.exception))
        self.assertNotIn("dung-mk", str(ctx.exception))

    def test_chi_cho_phep_lenh_print_chi_doc_theo_cau_tao(self):
        rt = RouterGia()
        p = self._phien(rt)
        for cam in ("/ip/firewall/filter/set", "/system/reboot", "/user/add", "/ip/dhcp-server/lease/make-static",
                    "/ip/dhcp-server/lease/print; /system/reboot", "/tool/fetch"):
            with self.assertRaises(R.ApiLoi, msg=cam):
                p.goi_doc(cam)
        self.assertFalse([c for c in rt.nhan if c[0] != "/login"])                # không lệnh cấm nào tới được router

    def test_van_tay_chung_chi(self):
        self.assertTrue(R.van_tay_khop("AA" * 32, "aa" * 32))
        self.assertFalse(R.van_tay_khop("aa" * 32, "bb" * 32))
        self.assertFalse(R.van_tay_khop("", "aa" * 32))
        self.assertEqual(R.van_tay_cua(b"abc"), hashlib.sha256(b"abc").hexdigest())

    def test_toc_do_chiu_duoc_so_tho_va_chuoi_co_don_vi(self):
        for vao, ra in (("19600", 19600), ("19.6kbps", 19600), ("19.6 kbps", 19600), ("1.2Mbps", 1200000), ("488 bps", 488),
                        ("43.6k", 43600), ("", None), ("abc", None), (None, None)):
            self.assertEqual(R._bps(vao), ra, vao)

    def test_ma_hoa_do_dai(self):
        self.assertEqual(R._ma_do_dai(5), b"\x05")
        self.assertEqual(R._ma_do_dai(200), (200 | 0x8000).to_bytes(2, "big"))




class WireGuardTest(unittest.TestCase):
    def test_thoi_gian_handshake(self):
        for vao, ra in (("1m33s", 93), ("00:01:33", 93), ("2h5m", 7500), ("1d", 86400), ("45s", 45), ("1w2d", 777600),
                        ("never", None), ("", None), (None, None), ("abc", None)):
            self.assertEqual(R.thoi_gian_giay(vao), ra, vao)

    def test_doc_peer(self):
        class P:
            def goi_doc(self, lenh, proplist=""):
                assert lenh == "/interface/wireguard/peers/print"
                return [
                    {"name": "phone", "interface": "wg-home", "comment": "Phone", "allowed-address": "192.16.0.2/32",
                     "current-endpoint-address": "123.16.0.35", "rx": "1103397888", "tx": "546222080", "last-handshake": "42s"},
                    {"name": "mik-sg", "interface": "mik-sg", "comment": "surfshark SING", "allowed-address": "0.0.0.0/0",
                     "rx": "0", "tx": "0", "last-handshake": "", "disabled": "true"},
                    {"interface": "wg-home"},                                          # không tên: bỏ
                ]
        ds = R.wireguard_peers(P())
        self.assertEqual([p["name"] for p in ds], ["phone", "mik-sg"])
        phone = ds[0]
        self.assertEqual((phone["rx_bytes"], phone["tx_bytes"], phone["last_handshake_s"]), (1103397888, 546222080, 42))
        self.assertEqual(phone["interface"], "wg-home")
        self.assertEqual(phone["allowed_address"], "192.16.0.2/32")
        self.assertIsNone(ds[1]["last_handshake_s"])
        self.assertTrue(ds[1]["disabled"])


class BridgeTest(unittest.TestCase):
    def test_doc_cong_bridge_chi_qua_print(self):
        goi = []

        class P:
            def goi_doc(self, lenh, proplist=""):
                goi.append(lenh)
                return [
                    {"interface": "ether2", "bridge": "BridgeLAN"},
                    {"interface": "ether3", "bridge": "BridgeLAN", "disabled": "false"},
                    {"interface": "ether5", "bridge": "BridgeKhach", "disabled": "true"},   # cổng tắt: không tính
                    {"interface": "", "bridge": "BridgeLAN"},                                 # không tên cổng: bỏ
                    {"interface": "ether4"},                                                  # không bridge: bỏ
                    {"interface": "x" * 200, "bridge": "b" * 200},                            # chuỗi dài: cắt
                ]
        ra = R.bridge_ports(P())
        self.assertEqual(goi, ["/interface/bridge/port/print"])
        self.assertEqual(ra["ether2"], "BridgeLAN")
        self.assertEqual(ra["ether3"], "BridgeLAN")
        self.assertNotIn("ether5", ra)
        self.assertNotIn("ether4", ra)
        self.assertNotIn("", ra)
        self.assertTrue(all(len(k) <= 40 and len(v) <= 40 for k, v in ra.items()))

    def test_nguon_api_lay_bridge_cung_nhip_voi_ten_va_loi_bridge_khong_mat_ten(self):
        from mikrotik_snmp import nguon_api as N

        for ten in ("mo_phien", "ten_tu_dhcp", "kid_control", "wireguard_peers", "bridge_ports"):
            self.addCleanup(setattr, N, ten, getattr(N, ten))       # trả lại hàm thật sau test, không để lẫn sang test khác

        class Phien:
            def dong(self):
                pass
        N.mo_phien = lambda *a, **k: Phien()
        N.ten_tu_dhcp = lambda p: {"AA:BB:CC:DD:EE:01": {"comment": "May in", "host_name": "hp"}}
        N.kid_control = lambda p: {}
        N.wireguard_peers = lambda p: []
        N.bridge_ports = lambda p: {"ether2": "BridgeLAN"}

        async def chay_nen(f):
            return f()
        import asyncio
        n = N.NguonApi("172.16.10.1", 8729, "doc", "mk", "vt", chay_nen)
        d = asyncio.run(n.doc(True, True, True))
        self.assertEqual(d["bridge"], {"ether2": "BridgeLAN"})
        d = asyncio.run(n.doc(False, True, True))
        self.assertNotIn("bridge", d)                         # chỉ đọc cùng nhịp với tên (cấu hình đổi chậm)

        def loi(p):
            raise R.ApiLoi("lệnh bị từ chối")
        N.bridge_ports = loi
        d = asyncio.run(n.doc(True, True, True))
        self.assertIsNone(d["bridge"])                        # lỗi bridge: chỉ mất phần bridge
        self.assertIn("AA:BB:CC:DD:EE:01", d["ten"])          # tên vẫn có


if __name__ == "__main__":
    unittest.main()
