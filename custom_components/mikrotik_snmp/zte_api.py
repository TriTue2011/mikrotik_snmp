"""Đăng nhập trang quản trị ZTE E2633 và đọc danh sách máy WiFi. CHỈ ĐỌC: không ghi cấu hình, không đổi mật khẩu.

Luồng lấy từ mã trang đăng nhập của chính thiết bị (không đoán):
  GET /                              → lấy số `_sessionTOKEN` trong form
  GET logintoken_lua.lua             → lấy token đăng nhập
  POST /  Username, Password=sha256(mật khẩu + token), action=login, _sessionTOKEN

Quy tắc an toàn:
- Mật khẩu và cookie không bao giờ vào thông báo lỗi hay log.
- Mỗi lần đọc chỉ đăng nhập tối đa MỘT lần; phiên cũ hết hạn mới đăng nhập lại đúng một lần.
- Không kiểm được dữ liệu (không đúng khuôn JSON) thì ném lỗi, không trả dữ liệu rỗng giả.
"""
from __future__ import annotations

import hashlib
import http.cookiejar
import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .zte_parser import phan_tich_ap, phan_tich_thiet_bi

TOKEN_FORM_RE = re.compile(r'addParameter\("_sessionTOKEN",\s*"(\d+)"\)')
DUONG_TOKEN = "/function_module/login_module/login_page/logintoken_lua.lua"
DUONG_DU_LIEU = "/getpage.lua?pid=1005&nextpage=topo_lua.lua&Action={}"


class ZteLoiDangNhap(Exception):
    """Đăng nhập bị từ chối hoặc không đọc được dữ liệu sau khi đăng nhập. Thông báo không chứa mật khẩu."""


class ZteLoiKetNoi(Exception):
    """Không tới được thiết bị."""


def _json_co_khoa(chuoi: str, khoa: str) -> dict | None:
    """JSON dạng đối tượng có khoá cần tìm; khác đi (trang đăng nhập, trang lỗi) thì None."""
    try:
        du = json.loads(chuoi)
    except ValueError:
        return None
    return du if isinstance(du, dict) and khoa in du else None


class ZteE2633:
    def __init__(
        self,
        host: str,
        ten: str,
        mat_khau: str,
        *,
        xac_minh_ssl: bool = False,
        scheme: str = "https",
        thoi_gian_cho: float = 15,
    ) -> None:
        self._goc = f"{scheme}://{host}"
        self._ten = ten
        self._mat_khau = mat_khau
        self._cho = thoi_gian_cho
        ngu = ssl.create_default_context()
        if not xac_minh_ssl:
            # Bộ phát dùng chứng chỉ tự ký trong mạng nhà; bật xác minh nếu có chứng chỉ hợp lệ.
            ngu.check_hostname = False
            ngu.verify_mode = ssl.CERT_NONE
        self._jar = http.cookiejar.CookieJar()
        self._mo = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPSHandler(context=ngu),
            urllib.request.HTTPCookieProcessor(self._jar),
        )
        self._co_phien = False

    def _doc(self, duong: str, du_lieu: bytes | None = None, them: dict[str, str] | None = None) -> str:
        tieu_de = {"Referer": self._goc + "/", **(them or {})}
        yc = urllib.request.Request(self._goc + duong, data=du_lieu, headers=tieu_de)
        try:
            with self._mo.open(yc, timeout=self._cho) as r:
                return r.read().decode("utf-8", "replace")
        except (urllib.error.URLError, OSError) as loi:
            raise ZteLoiKetNoi(f"không tới được {self._goc}") from loi

    def dang_nhap(self) -> None:
        """Một lần đăng nhập. Không tự thử lại."""
        self._co_phien = False
        self._jar.clear()  # bắt đầu từ trang đăng nhập sạch, không mang cookie phiên cũ
        m = TOKEN_FORM_RE.search(self._doc("/"))
        if not m:
            raise ZteLoiDangNhap("trang đăng nhập không có _sessionTOKEN (có thể không phải ZTE E2633)")
        token = re.sub(r"<[^>]+>", "", self._doc(DUONG_TOKEN)).strip()
        if not token:
            raise ZteLoiDangNhap("không lấy được token đăng nhập")
        bam = hashlib.sha256((self._mat_khau + token).encode()).hexdigest()
        # Đúng thứ tự và các trường mà trình duyệt gửi (đo: body 168 byte). Header `check` là SHA-256 của đúng chuỗi body.
        du = urllib.parse.urlencode([
            ("Username", self._ten),
            ("Password", bam),
            ("action", "login"),
            ("Frm_Logintoken", ""),
            ("captchaCode", ""),
            ("_sessionTOKEN", m.group(1)),
        ]).encode()
        self._doc("/", du, {"Check": hashlib.sha256(du).hexdigest(), "Content-Type": "application/x-www-form-urlencoded"})
        self._co_phien = True

    def _lay(self, hanh_dong: str, khoa: str) -> dict | None:
        return _json_co_khoa(self._doc(DUONG_DU_LIEU.format(hanh_dong)), khoa)

    def doc_thiet_bi(self) -> dict[str, Any]:
        """{'clients': [...], 'ap': {...}}. Ném ZteLoiDangNhap / ZteLoiKetNoi khi không đọc được."""
        vua_dang_nhap = not self._co_phien
        if vua_dang_nhap:
            self.dang_nhap()
        du = self._lay("GetALLClients", "clientsData")
        if du is None and not vua_dang_nhap:
            # Phiên cũ đã hết: đăng nhập lại đúng một lần rồi đọc lại.
            self.dang_nhap()
            vua_dang_nhap = True
            du = self._lay("GetALLClients", "clientsData")
        if du is None:
            self._co_phien = False
            raise ZteLoiDangNhap("không đọc được danh sách máy sau khi đăng nhập: kiểm tên và mật khẩu, "
                                 "hoặc tài khoản đang được đăng nhập ở nơi khác")
        ap = self._lay("GetALLAP", "apData")  # không bắt buộc: thiếu thì để trống
        return {"clients": phan_tich_thiet_bi(du), "ap": phan_tich_ap(ap or {})}
