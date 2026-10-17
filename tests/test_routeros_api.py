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


if __name__ == "__main__":
    unittest.main()


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
