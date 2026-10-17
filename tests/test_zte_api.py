"""Kiểm lớp đăng nhập và đọc dữ liệu trên MÁY CHỦ GIẢ cục bộ. Không chạm tới ZTE thật.

Máy chủ giả chỉ mô phỏng đúng luồng đã đọc từ mã trang đăng nhập; nó chứng minh code làm đúng theo luồng đó,
KHÔNG chứng minh ZTE thật chấp nhận luồng đó (việc đó chủ máy kiểm bằng phiên đăng nhập thật).
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys
import threading
import types
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures"

# Nạp gói dưới tên «mikrotik_snmp» mà KHÔNG chạy __init__.py (cần Home Assistant). Quan hệ import tương đối vẫn đúng.
goi = types.ModuleType("mikrotik_snmp")
goi.__path__ = [str(ROOT / "custom_components" / "mikrotik_snmp")]
sys.modules["mikrotik_snmp"] = goi

from mikrotik_snmp.zte_api import ZteE2633, ZteLoiDangNhap, ZteLoiKetNoi  # noqa: E402
from mikrotik_snmp.zte_parser import phan_tich_ap, phan_tich_thiet_bi  # noqa: E402

MK = "mk-gia-lap-khong-that"
TOKEN = "tok-gia-lap"
TRANG_DANG_NHAP = '<html><script>addParameter("_sessionTOKEN", "98765");</script><input id="Frm_Password"></html>'
TRANG_CHU = "<html>trang chu</html>"


class GiaZte(BaseHTTPRequestHandler):
    def log_message(self, *args):  # im lặng
        pass

    def _gui(self, ma: int, noi_dung: str, ctype: str = "text/html; charset=utf-8", cookie: str | None = None):
        b = noi_dung.encode()
        self.send_response(ma)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(b)

    def _co_phien(self) -> bool:
        return "SID=ok" in (self.headers.get("Cookie") or "")

    def do_GET(self):
        s = self.server
        if self.path == "/":
            return self._gui(200, TRANG_CHU if self._co_phien() else TRANG_DANG_NHAP)
        if self.path.startswith("/function_module/login_module/login_page/logintoken_lua.lua"):
            return self._gui(200, f"<response>{TOKEN}</response>", "text/xml")
        if self.path.startswith("/getpage.lua"):
            if s.het_phien_luot > 0:  # mô phỏng phiên đã hết
                s.het_phien_luot -= 1
                return self._gui(200, TRANG_DANG_NHAP)
            if not self._co_phien():
                return self._gui(200, TRANG_DANG_NHAP)
            act = parse_qs(urlparse(self.path).query).get("Action", [""])[0]
            du = {"GetALLClients": s.clients_json, "GetALLAP": s.ap_json}.get(act)
            if du is None:
                return self._gui(404, "")
            return self._gui(200, json.dumps(du), "application/json")
        self._gui(404, "")

    def do_POST(self):
        s = self.server
        s.dem_dang_nhap += 1
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n)
        f = {k: v[0] for k, v in parse_qs(raw.decode()).items()}
        # Đúng như ZTE thật (đo từ trình duyệt): header `check` = SHA-256 của body, và đủ các trường, đúng thứ tự.
        thu_tu = list(parse_qs(raw.decode(), keep_blank_values=True).keys())
        dung = (
            f.get("Username") == s.ten
            and f.get("Password") == hashlib.sha256((MK + TOKEN).encode()).hexdigest()
            and f.get("_sessionTOKEN") == "98765"
            and f.get("action") == "login"
            and thu_tu == ["Username", "Password", "action", "Frm_Logintoken", "captchaCode", "_sessionTOKEN"]
            and self.headers.get("Check") == hashlib.sha256(raw).hexdigest()
        )
        if dung:
            return self._gui(200, TRANG_CHU, cookie="SID=ok; Path=/")
        self._gui(200, TRANG_DANG_NHAP)


class DangNhapVaDocTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.may = HTTPServer(("127.0.0.1", 0), GiaZte)
        cls.may.ten = "user"
        cls.may.clients_json = json.loads((FIX / "zte_e2633_clients.json").read_text(encoding="utf-8"))
        cls.may.ap_json = json.loads((FIX / "zte_e2633_ap.json").read_text(encoding="utf-8"))
        cls.luong = threading.Thread(target=cls.may.serve_forever, daemon=True)
        cls.luong.start()

    @classmethod
    def tearDownClass(cls):
        cls.may.shutdown()
        cls.may.server_close()

    def setUp(self):
        self.may.het_phien_luot = 0
        self.may.dem_dang_nhap = 0

    def _may(self, mat_khau: str) -> ZteE2633:
        return ZteE2633(f"127.0.0.1:{self.may.server_port}", "user", mat_khau, scheme="http", thoi_gian_cho=5)

    def test_dang_nhap_dung_doc_duoc_danh_sach_may(self):
        kq = self._may(MK).doc_thiet_bi()
        self.assertEqual(self.may.dem_dang_nhap, 1)
        mong = phan_tich_thiet_bi(self.may.clients_json)
        self.assertEqual([c["mac"] for c in kq["clients"]], [c["mac"] for c in mong])
        self.assertTrue(kq["clients"], "fixture phải có máy")
        self.assertEqual(kq["ap"], phan_tich_ap(self.may.ap_json))

    def test_sai_mat_khau_chi_dang_nhap_mot_lan_va_khong_lo_mat_khau(self):
        mat_khau_sai = "mat-khau-sai-rieng-de-kiem-tra"
        with self.assertRaises(ZteLoiDangNhap) as cm:
            self._may(mat_khau_sai).doc_thiet_bi()
        self.assertEqual(self.may.dem_dang_nhap, 1, "không được tự thử lại trong cùng một lần đọc")
        self.assertNotIn(mat_khau_sai, str(cm.exception))
        self.assertNotIn(MK, str(cm.exception))

    def test_het_phien_thi_dang_nhap_lai_dung_mot_lan(self):
        c = self._may(MK)
        c.doc_thiet_bi()
        self.may.het_phien_luot = 1
        kq = c.doc_thiet_bi()
        self.assertEqual(self.may.dem_dang_nhap, 2)
        self.assertTrue(kq["clients"])

    def test_khong_toi_duoc_thiet_bi(self):
        c = ZteE2633("127.0.0.1:1", "user", MK, scheme="http", thoi_gian_cho=2)
        with self.assertRaises(ZteLoiKetNoi):
            c.doc_thiet_bi()

    def test_dong_du_lieu_hong_bi_bo(self):
        du = {"clientsData": {
            "1": {"MacAddr": "02:00:00:00:00:01", "AccessType": "2", "Rssi": "-60"},
            "2": {"MacAddr": "khong-phai-mac"},
            "3": "khong-phai-doi-tuong",
            "MGET_INST_NUM": 3,
        }}
        ds = phan_tich_thiet_bi(du)
        self.assertEqual([c["mac"] for c in ds], ["02:00:00:00:00:01"])
        self.assertEqual(ds[0]["band"], "5G")
        self.assertEqual(ds[0]["rssi"], -60)
        self.assertEqual(phan_tich_thiet_bi({"khac": 1}), [])


class HienHetTest(unittest.TestCase):
    """Mọi trường bộ phát trả về đều phải xuất hiện đâu đó (chuẩn hoá hoặc «goc»), không trường nào bị bỏ."""

    def test_may_giu_moi_truong_goc(self):
        from mikrotik_snmp.zte_parser import TEN_GOC_MAY
        du = json.loads((FIX / "zte_e2633_clients.json").read_text(encoding="utf-8"))
        goc = du["clientsData"]["1"]
        may = phan_tich_thiet_bi(du)[0]
        for ten_goc, v in goc.items():
            if v in (None, ""):
                continue
            co = ten_goc in TEN_GOC_MAY.values() or ten_goc in may["goc"]
            self.assertTrue(co, f"trường «{ten_goc}» bị mất")
        self.assertEqual(may["rx_mbps"], int(goc["RxRateMbps"]))

    def test_ap_giu_moi_truong_goc(self):
        from mikrotik_snmp.zte_parser import TEN_GOC_AP
        du = json.loads((FIX / "zte_e2633_ap.json").read_text(encoding="utf-8"))
        goc = du["apData"]["1"]
        ap = phan_tich_ap(du)
        for ten_goc, v in goc.items():
            if v in (None, ""):
                continue
            self.assertTrue(ten_goc in TEN_GOC_AP.values() or ten_goc in ap["goc"], f"trường «{ten_goc}» bị mất")


if __name__ == "__main__":
    unittest.main()
