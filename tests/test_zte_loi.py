"""Kiểm tra hồi phục lỗi ZTE, phân loại lỗi bằng cấu trúc và giữ dữ liệu cũ.

Không cần Home Assistant. Chạy trên máy chủ giả cục bộ.
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import pathlib
import re
import sys
import threading
import types
import unittest
import urllib.error
from http.server import HTTPServer

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures"

if "mikrotik_snmp" not in sys.modules:
    goi = types.ModuleType("mikrotik_snmp")
    goi.__path__ = [str(ROOT / "custom_components" / "mikrotik_snmp")]
    sys.modules["mikrotik_snmp"] = goi

from mikrotik_snmp.thu_thap import ThuThap
from mikrotik_snmp.zte_api import ZteE2633, ZteLoiDangNhap, ZteLoiKetNoi
from mikrotik_snmp.zte_nguon import NguonZte, ZteTamNgung
from tests.test_mikrotik_snmp import DongHo, RouterGia
from tests.test_zte_api import GiaZte, MK

try:
    from mikrotik_snmp.zte_parser import DuLieuSaiKhuon, phan_tich_thiet_bi
except ImportError:
    DuLieuSaiKhuon = None
    from mikrotik_snmp.zte_parser import phan_tich_thiet_bi


class GiaZteLoi(GiaZte):
    def _hong(self, gui_trang: bool) -> bool:
        che_do = self.server.che_do
        if che_do == "rot":
            self.close_connection = True
            return True
        if che_do == "rac":
            self.wfile.write(b"khong phai http\r\n\r\n")
            self.close_connection = True
            return True
        if gui_trang and che_do == "boot":
            self._gui(200, "<html>he thong dang khoi dong</html>")
            return True
        if gui_trang and che_do == "http500":
            self._gui(500, "loi may chu")
            return True
        if not gui_trang and che_do == "post503":
            self._gui(503, "dich vu tam ngung")
            return True
        return False

    def do_GET(self):
        if self._hong(gui_trang=self.path == "/"):
            return
        if self.server.che_do == "token_rong" and self.path.startswith("/function_module/login_module/login_page/logintoken_lua.lua"):
            return self._gui(200, "<response></response>", "text/xml")
        if self.server.che_do == "token503" and self.path.startswith("/function_module/login_module/login_page/logintoken_lua.lua"):
            return self._gui(503, "tam ngung", "text/plain")
        super().do_GET()

    def do_POST(self):
        if self._hong(gui_trang=False):
            return
        super().do_POST()


def dung_may_chu() -> HTTPServer:
    may = HTTPServer(("127.0.0.1", 0), GiaZteLoi)
    may.ten = "user"
    may.che_do = ""
    may.het_phien_luot = 0
    may.dem_dang_nhap = 0
    may.clients_json = json.loads((FIX / "zte_e2633_clients.json").read_text(encoding="utf-8"))
    may.ap_json = json.loads((FIX / "zte_e2633_ap.json").read_text(encoding="utf-8"))
    threading.Thread(target=may.serve_forever, daemon=True).start()
    return may


def clients_lon(so_may: int) -> dict:
    ten_dai = ("Thiết bị WiFi thử nghiệm có tên rất dài để đo kích thước tối đa " * 3)[:64]
    return {"clientsData": {
        str(i): {"MacAddr": f"02:00:00:00:{i // 256:02x}:{i % 256:02x}", "HostName": ten_dai, "IpAddr": f"192.168.88.{i % 250 + 2}",
                 "Rssi": "-47", "AccessType": "2", "WirelessMode": "802.11ax", "AssocTime": str(1000 + i),
                 "RxRateBps": "0", "TxRateBps": "0"}
        for i in range(1, so_may + 1)
    }}


def chay(coro):
    return asyncio.run(coro)


class DocMucTest(unittest.TestCase):
    def setUp(self):
        if DuLieuSaiKhuon is None:
            self.skipTest("DuLieuSaiKhuon chưa được định nghĩa")

    def _may(self, mac="02:00:00:00:00:0%d", khoa="MacAddr", n=3):
        return {str(i): {khoa: mac % i, "HostName": "x"} for i in range(1, n + 1)}

    def test_bo_phat_doi_ten_truong_mac_la_loi_khong_phai_khong_co_may(self):
        with self.assertRaises(DuLieuSaiKhuon):
            phan_tich_thiet_bi({"clientsData": self._may(khoa="Mac")})

    def test_moi_muc_khong_phai_doi_tuong_la_loi(self):
        with self.assertRaises(DuLieuSaiKhuon):
            phan_tich_thiet_bi({"clientsData": {"1": "a", "2": "b"}})

    def test_moi_muc_co_mac_sai_khuon_la_loi(self):
        with self.assertRaises(DuLieuSaiKhuon):
            phan_tich_thiet_bi({"clientsData": self._may(mac="khong-phai-mac-%d")})

    def test_bao_so_may_lon_hon_0_ma_khong_co_muc_nao_la_loi(self):
        with self.assertRaises(DuLieuSaiKhuon):
            phan_tich_thiet_bi({"clientsData": {"MGET_INST_NUM": 3}})

    def test_mot_phan_muc_hong_thi_giu_muc_doc_duoc_va_ghi_log_debug_so_muc_bo(self):
        du = {"clientsData": {**self._may(n=2), "3": "rac", "4": {"MacAddr": "hong"}, "MGET_INST_NUM": 4}}
        with self.assertLogs("mikrotik_snmp.zte_parser", level="DEBUG") as log:
            ds = phan_tich_thiet_bi(du)
        self.assertEqual(len(ds), 2)
        self.assertTrue(any("2" in d and "bỏ" in d for d in log.output), log.output)
        self.assertFalse(any("hong" in d or "rac" in d for d in log.output), "log không chứa giá trị của bộ phát")

    def test_rong_hop_le_la_khong_co_may(self):
        for rong in ({"MGET_INST_NUM": 0}, {}, []):
            with self.subTest(rong=rong):
                self.assertEqual(phan_tich_thiet_bi({"clientsData": rong}), [])


class HoiPhucTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.may = dung_may_chu()
        cls.clients_goc = dict(cls.may.clients_json)
        cls.ap_goc = dict(cls.may.ap_json)

    @classmethod
    def tearDownClass(cls):
        cls.may.shutdown()
        cls.may.server_close()

    def setUp(self):
        self.may.che_do = ""
        self.may.het_phien_luot = 0
        self.may.dem_dang_nhap = 0
        self.may.ten = "user"
        self.may.clients_json = self.clients_goc
        self.may.ap_json = self.ap_goc

    def _client(self) -> ZteE2633:
        return ZteE2633(f"127.0.0.1:{self.may.server_port}", "user", MK, scheme="http", thoi_gian_cho=5)

    def test_trang_dang_nhap_hoac_thieu_khoa_la_phien_mat_thi_loi_dang_nhap(self):
        self.may.clients_json = {"khong_co_clientsData": 1}
        with self.assertRaises(ZteLoiDangNhap):
            self._client().doc_thiet_bi()
        self.assertEqual(self.may.dem_dang_nhap, 1)

    def test_khoi_du_lieu_sai_kieu_la_loi_doc_khong_phai_danh_sach_rong_cung_khong_phai_tu_choi(self):
        for hong in ({"clientsData": "loi"}, {"clientsData": ["a"]}, {"clientsData": None}, {"clientsData": 7}):
            with self.subTest(hong=hong):
                self.may.clients_json = hong
                self.may.dem_dang_nhap = 0
                with self.assertRaises(ZteLoiKetNoi):
                    self._client().doc_thiet_bi()
                self.assertEqual(self.may.dem_dang_nhap, 1, "không được đăng nhập lại chỉ vì dữ liệu sai kiểu")

    def test_bo_phat_that_su_khong_co_may_nao_la_danh_sach_rong_hop_le(self):
        self.may.clients_json = {"clientsData": {"MGET_INST_NUM": 0}}
        self.assertEqual(self._client().doc_thiet_bi()["clients"], [])

    def test_sai_mat_khau_la_tu_choi_dang_nhap(self):
        self.may.ten = "nguoi-khac"
        with self.assertRaises(ZteLoiDangNhap):
            self._client().doc_thiet_bi()

    def test_trang_khong_co_token_khong_phai_tu_choi_dang_nhap(self):
        self.may.che_do = "boot"
        with self.assertRaises(ZteLoiKetNoi):
            self._client().doc_thiet_bi()

    def test_ma_http_loi_o_trang_lay_token_la_loi_ket_noi_co_ghi_ma(self):
        self.may.che_do = "http500"
        with self.assertRaises(ZteLoiKetNoi) as cm:
            self._client().doc_thiet_bi()
        self.assertIn("500", str(cm.exception))

    def test_token_503_khong_gui_post_dang_nhap(self):
        self.may.che_do = "token503"
        with self.assertRaises(ZteLoiKetNoi) as cm:
            self._client().doc_thiet_bi()
        self.assertIn("503", str(cm.exception))
        self.assertEqual(self.may.dem_dang_nhap, 0, "token trả 503 không được gửi POST đăng nhập")

    def test_phan_hoi_khong_phai_http_thanh_loi_ket_noi(self):
        self.may.che_do = "rac"
        with self.assertRaises(ZteLoiKetNoi):
            self._client().doc_thiet_bi()

    def test_dong_ket_noi_giua_chung_thanh_loi_ket_noi(self):
        self.may.che_do = "rot"
        with self.assertRaises(ZteLoiKetNoi):
            self._client().doc_thiet_bi()

    def test_dang_xuat_xoa_phien_phia_may_khach(self):
        c = self._client()
        c.doc_thiet_bi()
        self.assertEqual(self.may.dem_dang_nhap, 1)
        c.dang_xuat()
        self.assertEqual(len(c._jar), 0)
        c.doc_thiet_bi()
        self.assertEqual(self.may.dem_dang_nhap, 2)
        c.dang_xuat()
        c.dang_xuat()

    def test_trang_token_rong_la_loi_ket_noi_khong_phai_tu_choi(self):
        self.may.che_do = "token_rong"
        with self.assertRaises(ZteLoiKetNoi):
            self._client().doc_thiet_bi()

    def test_khoi_bo_phat_khong_bat_buoc_sai_kieu_thi_van_doc_duoc_may(self):
        for hong in ({"apData": "loi"}, {"apData": None}, {"khong_co": 1}):
            with self.subTest(hong=hong):
                self.may.ap_json = hong
                kq = self._client().doc_thiet_bi()
                self.assertTrue(kq["clients"])
                self.assertEqual(kq["ap"], {})
        self.may.ap_json = self.ap_goc

    def test_phan_hoi_loi_http_duoc_dong(self):
        c = self._client()
        fp = io.BytesIO(b"loi")
        loi = urllib.error.HTTPError("http://x/", 500, "loi", {}, fp)

        def _mo(*_a, **_k):
            raise loi
        c._mo.open = _mo
        with self.assertRaises(ZteLoiKetNoi):
            c.doc_thiet_bi()
        self.assertTrue(fp.closed)

    def test_tu_api_doi_ten_truong_thanh_loi_ket_noi_khong_dang_nhap_lai(self):
        self.may.clients_json = {"clientsData": {"1": {"Mac": "02:00:00:00:00:01"}}}
        with self.assertRaises(ZteLoiKetNoi):
            self._client().doc_thiet_bi()
        self.assertEqual(self.may.dem_dang_nhap, 1)


class NhatKyTest(unittest.TestCase):
    CAM = [MK, "tok-gia", "98765", "SID", "Check", "02:00:00:00", "127.0.0.1", "192.168", "user"]

    @classmethod
    def setUpClass(cls):
        cls.may = dung_may_chu()

    @classmethod
    def tearDownClass(cls):
        cls.may.shutdown()
        cls.may.server_close()

    def setUp(self):
        self.may.che_do = ""
        self.may.het_phien_luot = 0
        self.may.dem_dang_nhap = 0

    def _client(self):
        return ZteE2633(f"127.0.0.1:{self.may.server_port}", "user", MK, scheme="http", thoi_gian_cho=5)

    def _sach(self, log):
        van_ban = "\n".join(log.output)
        for cam in self.CAM:
            self.assertNotIn(cam, van_ban)
        self.assertIsNone(re.search(r"\b[0-9a-f]{32,}\b", van_ban))
        return van_ban

    def test_cac_moc_khi_doc_binh_thuong_va_khi_phien_het_han(self):
        c = self._client()
        with self.assertLogs("mikrotik_snmp.zte_api", level="DEBUG") as log:
            c.doc_thiet_bi()
            self.may.het_phien_luot = 1
            c.doc_thiet_bi()
        van_ban = self._sach(log)
        self.assertIn("bắt đầu đăng nhập", van_ban)
        self.assertIn("đăng nhập xong", van_ban)
        self.assertIn("phiên hết hạn", van_ban)
        self.assertRegex(van_ban, r"đọc xong \d+ máy")
        self.assertEqual(van_ban.count("phiên hết hạn"), 1)

    def test_phan_loai_loi_ghi_loai_va_ma_http_khong_ghi_dia_chi(self):
        self.may.che_do = "http500"
        with self.assertLogs("mikrotik_snmp.zte_api", level="DEBUG") as log:
            with self.assertRaises(ZteLoiKetNoi):
                self._client().doc_thiet_bi()
        van_ban = self._sach(log)
        self.assertIn("ZteLoiKetNoi", van_ban)
        self.assertIn("500", van_ban)
        self.may.che_do = ""
        self.may.ten = "nguoi-khac"
        with self.assertLogs("mikrotik_snmp.zte_api", level="DEBUG") as log:
            with self.assertRaises(ZteLoiDangNhap):
                self._client().doc_thiet_bi()
        self.assertIn("ZteLoiDangNhap", self._sach(log))
        self.may.ten = "user"


class ThuThapZteLoiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.may = dung_may_chu()
        cls.clients_goc = dict(cls.may.clients_json)

    @classmethod
    def tearDownClass(cls):
        cls.may.shutdown()
        cls.may.server_close()

    def setUp(self):
        self.may.che_do = ""
        self.may.het_phien_luot = 0
        self.may.dem_dang_nhap = 0
        self.may.ten = "user"
        self.may.clients_json = self.clients_goc

    def test_thuthap_doc_zte_hong_du_lieu_sai_kieu_giu_danh_sach_cu(self):
        r, dh = RouterGia(), DongHo()
        client = ZteE2633(f"127.0.0.1:{self.may.server_port}", "user", MK, scheme="http", thoi_gian_cho=5)
        async def chay_nen(f):
            return f()
        nguon = NguonZte(client, f"127.0.0.1:{self.may.server_port}", chay_nen, dh)
        tt = ThuThap(r, None, dh, zte=nguon)

        d1 = chay(tt.cap_nhat())
        self.assertEqual(d1["zte"]["trang_thai"], "ok")
        so_may = len(d1["zte"]["clients"])
        self.assertGreater(so_may, 0)

        # Lỗi dữ liệu sai kiểu
        for hong in ({"clientsData": "loi"}, {"clientsData": ["a"]}, {"clientsData": None}):
            with self.subTest(hong=hong):
                self.may.clients_json = hong
                dh.t += 20
                d2 = chay(tt.cap_nhat())
                self.assertEqual(d2["zte"]["trang_thai"], "loi_ket_noi", f"phải là loi_ket_noi với {hong}")
                self.assertEqual(len(d2["zte"]["clients"]), so_may, "phải giữ danh sách cũ")
                self.assertTrue(any(c.get("wifi") for c in d2["tree"]["clients"]), "cây vẫn phải có máy WiFi")

    def test_thuthap_doc_zte_doi_ten_truong_giu_danh_sach_cu(self):
        r, dh = RouterGia(), DongHo()
        client = ZteE2633(f"127.0.0.1:{self.may.server_port}", "user", MK, scheme="http", thoi_gian_cho=5)
        async def chay_nen(f):
            return f()
        nguon = NguonZte(client, f"127.0.0.1:{self.may.server_port}", chay_nen, dh)
        tt = ThuThap(r, None, dh, zte=nguon)

        d1 = chay(tt.cap_nhat())
        so_may = len(d1["zte"]["clients"])
        self.assertGreater(so_may, 0)

        self.may.clients_json = {"clientsData": {"1": {"Mac": "02:00:00:00:00:01"}}}
        dh.t += 20
        d2 = chay(tt.cap_nhat())
        self.assertEqual(d2["zte"]["trang_thai"], "loi_ket_noi")
        self.assertEqual(len(d2["zte"]["clients"]), so_may)

    def test_thuthap_doc_zte_rong_hop_le_la_ok_va_danh_sach_rong(self):
        r, dh = RouterGia(), DongHo()
        client = ZteE2633(f"127.0.0.1:{self.may.server_port}", "user", MK, scheme="http", thoi_gian_cho=5)
        async def chay_nen(f):
            return f()
        nguon = NguonZte(client, f"127.0.0.1:{self.may.server_port}", chay_nen, dh)
        tt = ThuThap(r, None, dh, zte=nguon)

        self.may.clients_json = {"clientsData": {"MGET_INST_NUM": 0}}
        d = chay(tt.cap_nhat())
        self.assertEqual(d["zte"]["trang_thai"], "ok")
        self.assertEqual(d["zte"]["clients"], [])


class BackoffTest(unittest.TestCase):
    def test_loi_ket_noi_khong_tam_ngung_va_doc_lai_ngay(self):
        class May:
            so = 0
            def doc_thiet_bi(self):
                May.so += 1
                raise ZteLoiKetNoi("mat mang")

        async def chay_nen(f):
            return f()

        dh = DongHo()
        n = NguonZte(May(), "192.168.88.24", chay_nen, dh)
        with self.assertRaises(ZteLoiKetNoi):
            chay(n.doc())
        self.assertEqual(May.so, 1)

        # Lần kế tiếp (không tăng 1800 giây) đọc lại ngay
        dh.t += 1
        with self.assertRaises(ZteLoiKetNoi):
            chay(n.doc())
        self.assertEqual(May.so, 2, "ZteLoiKetNoi không được kích hoạt backoff")


if __name__ == "__main__":
    unittest.main()
