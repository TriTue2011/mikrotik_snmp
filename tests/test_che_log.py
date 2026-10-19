"""scripts/che_log.py: che MAC/IP/mật khẩu/token/cookie. Chuỗi toàn là GIẢ (kho công khai)."""
from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
DUONG = ROOT / "scripts" / "che_log.py"
_spec = importlib.util.spec_from_file_location("che_log", DUONG)
che_log = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(che_log)

MK_GIA = "mk-gia-khong-that-123"
TOKEN_GIA = "tok-gia-987654"
COOKIE_GIA = "SID=phien-gia-abcdef"
BAM_GIA = "ab" * 32


class CheLogTest(unittest.TestCase):
    def test_che_mac_ip_va_giu_nhan_nhat_quan(self):
        ra = che_log.Che().van_ban(
            "tracker 02:00:00:00:00:01 ip 192.168.88.41\n"
            "lại 02-00-00-00-00-01 và 02:00:00:00:00:02 ip 192.168.88.41 / 192.168.88.42\n"
        )
        for goc in ("02:00:00:00:00:01", "02-00-00-00-00-01", "02:00:00:00:00:02", "192.168.88.41", "192.168.88.42"):
            self.assertNotIn(goc, ra)
        d1, d2 = ra.splitlines()
        self.assertIn("MAC-1", d1)
        self.assertIn("MAC-1", d2)  # cùng một MAC (dấu : hay -) ra cùng một nhãn
        self.assertIn("MAC-2", d2)
        self.assertEqual(d1.count("IP-1"), 1)
        self.assertIn("IP-2", d2)

    def test_che_mat_khau_token_cookie_va_bam(self):
        mau = (
            f"Password={BAM_GIA}&Username=user&_sessionTOKEN=98765\n"
            f'POST body mat_khau="{MK_GIA}" token: {TOKEN_GIA}\n'
            f"Set-Cookie: {COOKIE_GIA}; Path=/\n"
            f"Cookie: {COOKIE_GIA}\n"
            f"Check: {BAM_GIA}\n"
            f"Authorization: Bearer {TOKEN_GIA}\n"
            f"băm trơ trọi {BAM_GIA} giữa câu\n"
        )
        ra = che_log.Che().van_ban(mau)
        for bi_mat in (MK_GIA, TOKEN_GIA, COOKIE_GIA, BAM_GIA, "phien-gia", "98765"):
            self.assertNotIn(bi_mat, ra)
        self.assertIn("Username=user", ra, "tên đăng nhập không phải bí mật, giữ để còn chẩn đoán")

    def test_che_ten_may_trong_json(self):
        ra = che_log.Che().van_ban('{"MacAddr": "02:00:00:00:00:01", "HostName": "Thiết bị WiFi 1", "Rssi": "-47"}\n')
        self.assertNotIn("Thiết bị WiFi 1", ra)
        self.assertNotIn("02:00:00:00:00:01", ra)
        self.assertIn('"Rssi": "-47"', ra)

    def test_khong_che_nham_so_phien_ban_va_thoi_gian(self):
        mau = "firmware V1.0.4 lúc 12:34:56 chu kỳ 60 giây, 1.2.3 và 300.1.1.1 không phải IP\n"
        self.assertEqual(che_log.Che().van_ban(mau), mau)

    def test_chay_nhu_lenh_doc_stdin(self):
        kq = subprocess.run([sys.executable, str(DUONG)], input="ip 192.168.88.41 Password=" + MK_GIA + "\n",
                            capture_output=True, text=True, timeout=20)
        self.assertEqual(kq.returncode, 0, kq.stderr)
        self.assertNotIn("192.168.88.41", kq.stdout)
        self.assertNotIn(MK_GIA, kq.stdout)

    # ── Vòng soát độc lập ────────────────────────────────────────────────────────────────────────────────
    def test_che_user_mat_khau_trong_url(self):
        ra = che_log.Che().van_ban("url https://quantri:S3cr3t!Xyz@192.168.77.1/login và http://admin@router.nha-test.example/\n")
        for lo in ("quantri", "S3cr3t", "Xyz@", "admin@"):
            self.assertNotIn(lo, ra)
        self.assertIn("/login", ra)

    def test_che_ten_mien_bo_phat_trong_url_va_truong_host(self):
        ra = che_log.Che().van_ban(
            "Error fetching: không tới được https://router.nha-test.example\n"
            "entry data={'host': 'router.nha-test.example', 'xac_minh_ssl': False}\n"
        )
        self.assertNotIn("nha-test", ra)
        d1, d2 = ra.splitlines()
        self.assertIn("HOST-1", d1)
        self.assertIn("HOST-1", d2, "cùng một tên miền ra cùng một nhãn")

    def test_khong_che_nham_ten_mo_dun_va_thu_vien(self):
        mau = "custom_components.mikrotik_snmp và homeassistant.helpers.update_coordinator chạy https://www.home-assistant.io/docs ok\n"
        ra = che_log.Che().van_ban(mau)
        self.assertIn("custom_components.mikrotik_snmp", ra)
        self.assertIn("homeassistant.helpers.update_coordinator", ra)

    def test_mat_khau_co_khoang_trang_dau_phay_nhay_bi_che_het(self):
        mau = (
            "data={'mat_khau': 'mat khau co dau cach, va phay;x', 'host': '192.168.77.1'}\n"
            '{"password": "p@ss \\"quoted\\" word", "Password": "x y z"}\n'
            '{"mat_khau": "it\'s me tail"}\n'
            "POST Password=abcdef&Username=quantri&action=login\n"
        )
        ra = che_log.Che().van_ban(mau)
        for lo in ("mat khau", "phay", "quoted", "p@ss", "x y z", "me tail", "abcdef"):
            self.assertNotIn(lo, ra)
        self.assertIn("Username=quantri", ra)
        self.assertIn("action=login", ra)
        self.assertEqual(ra.count("***"), 5)

    def test_khong_che_nham_so_phien_ban_bon_nhom_sau_tu_khoa(self):
        mau = "firmware V1.0.4 ver 1.2.3.4 version: 5.6.7.8 phiên bản 9.9.9.9 build 10.2.3\n"
        self.assertEqual(che_log.Che().van_ban(mau), mau)
        ra = che_log.Che().van_ban("version 1.2.3.4 từ 192.168.77.1\n")
        self.assertIn("version 1.2.3.4", ra)
        self.assertNotIn("192.168.77.1", ra)

    def test_dong_devicename_hostname_chi_che_gia_tri_ten(self):
        ra = che_log.Che().van_ban("DeviceName: ZTE:ZXHN E2633 HostName=Laptop Ong Ba\n")
        self.assertNotIn("Laptop", ra)
        self.assertNotIn("Ong Ba", ra)
        self.assertIn("DeviceName", ra)
        self.assertIn("HostName", ra)
        self.assertIn("TEN-2", ra, "hai giá trị tên khác nhau → hai nhãn")

    def test_che_ipv6_va_cookie_dong_rieng(self):
        ra = che_log.Che().van_ban("ipv6 2405:4800:1234:abcd::1 và fe80::1ff:fe23:4567:890a\nCookie: SID=abc; lang=vi\n")
        self.assertNotIn("2405", ra)
        self.assertNotIn("fe80", ra)
        self.assertNotIn("lang=vi", ra)
        self.assertNotIn("abc", ra)


if __name__ == "__main__":
    unittest.main()
