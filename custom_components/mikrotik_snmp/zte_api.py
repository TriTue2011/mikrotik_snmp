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
import http.client
import http.cookiejar
import json
import logging
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .zte_parser import DuLieuSaiKhuon, phan_tich_ap, phan_tich_thiet_bi

LOGGER = logging.getLogger(__name__)

TOKEN_FORM_RE = re.compile(r'addParameter\("_sessionTOKEN",\s*"(\d+)"\)')
DUONG_TOKEN = "/function_module/login_module/login_page/logintoken_lua.lua"
DUONG_DU_LIEU = "/getpage.lua?pid=1005&nextpage=topo_lua.lua&Action={}"


class ZteLoiDangNhap(Exception):
    """Bộ phát TỪ CHỐI: đăng nhập xong mà vẫn không đọc được dữ liệu. Chỉ loại lỗi này mới kích hoạt tạm ngừng đăng nhập
    và yêu cầu nhập lại mật khẩu. Thông báo không chứa mật khẩu."""


class ZteLoiKetNoi(Exception):
    """Không tới được thiết bị, hoặc thiết bị trả thứ không phải trang đăng nhập (mã HTTP lỗi, đang khởi động lại, trả rác).
    Tự hồi phục khi bộ phát sống lại; không phải lý do để tạm ngừng đăng nhập."""


def _json_co_khoa(chuoi: str, khoa: str, *, nghiem: bool = True) -> dict | None:
    """JSON dạng đối tượng mà `khoa` là một khối dữ liệu (đối tượng, hoặc danh sách rỗng).

    - Không phải JSON, không phải đối tượng, hoặc thiếu `khoa` (trang đăng nhập, trang lỗi): trả None — phiên đã mất.
    - Có `khoa` nhưng khối mang kiểu lạ ("loi", null, danh sách có phần tử): bộ phát vẫn trả JSON đúng khoá nên phiên còn tốt,
      đây là ĐỌC HỎNG. Ném ZteLoiKetNoi (nếu `nghiem`), không trả danh sách rỗng giả — nếu không mọi thiết bị theo dõi sẽ
      chuyển «không ở nhà» trong khi bộ phát vẫn sống — và cũng không coi là bị từ chối đăng nhập. Khối không bắt buộc
      (`nghiem=False`) sai kiểu thì coi như thiếu.
    """
    try:
        du = json.loads(chuoi)
    except ValueError:
        return None
    if not isinstance(du, dict) or khoa not in du:
        return None
    khoi = du[khoa]
    if isinstance(khoi, dict) or khoi == []:
        return du
    if nghiem:
        raise ZteLoiKetNoi(f"bộ phát trả khối «{khoa}» sai khuôn ({type(khoi).__name__})")
    return None


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
        except urllib.error.HTTPError as loi:  # phải đứng trước URLError (HTTPError là lớp con)
            loi.close()  # HTTPError giữ socket của phản hồi; không đóng thì rò (ResourceWarning)
            raise ZteLoiKetNoi(f"{self._goc} trả mã HTTP {loi.code}") from loi
        except (urllib.error.URLError, OSError, http.client.HTTPException) as loi:
            raise ZteLoiKetNoi(f"không tới được {self._goc}") from loi

    def dang_nhap(self) -> None:
        """Một lần đăng nhập. Không tự thử lại."""
        LOGGER.debug("bắt đầu đăng nhập")
        self._co_phien = False
        self._jar.clear()  # bắt đầu từ trang đăng nhập sạch, không mang cookie phiên cũ
        m = TOKEN_FORM_RE.search(self._doc("/"))
        if not m:
            raise ZteLoiKetNoi("trang đăng nhập không có _sessionTOKEN (bộ phát đang khởi động lại, hoặc không phải ZTE E2633)")
        token = re.sub(r"<[^>]+>", "", self._doc(DUONG_TOKEN)).strip()
        if not token:
            raise ZteLoiKetNoi("không lấy được token đăng nhập")
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
        LOGGER.debug("đăng nhập xong")

    def dang_xuat(self) -> None:
        """Quên phiên phía máy khách: xoá cookie và cờ phiên, lần đọc sau đăng nhập mới. Gọi lặp không lỗi.

        CHƯA có điểm đăng xuất phía bộ phát nào được kiểm chứng trên E2633 nên KHÔNG gửi yêu cầu nào lên bộ phát
        (không đoán điểm cuối); phiên phía bộ phát tự hết hạn theo thời gian chờ của nó.
        """
        self._co_phien = False
        self._jar.clear()

    def _lay(self, hanh_dong: str, khoa: str, *, nghiem: bool = True) -> dict | None:
        return _json_co_khoa(self._doc(DUONG_DU_LIEU.format(hanh_dong)), khoa, nghiem=nghiem)

    def doc_thiet_bi(self) -> dict[str, Any]:
        """{'clients': [...], 'ap': {...}}. Ném ZteLoiDangNhap / ZteLoiKetNoi khi không đọc được.

        Log DEBUG chỉ ghi mốc, số lượng, loại lỗi và mã HTTP — không bao giờ ghi địa chỉ, tên, MAC, IP, token hay cookie.
        """
        try:
            return self._doc_thiet_bi()
        except (ZteLoiDangNhap, ZteLoiKetNoi) as loi:
            ma = getattr(loi.__cause__, "code", None)
            LOGGER.debug("đọc lỗi: %s%s", type(loi).__name__, f" (mã HTTP {ma})" if ma else "")
            raise

    def _doc_thiet_bi(self) -> dict[str, Any]:
        vua_dang_nhap = not self._co_phien
        if vua_dang_nhap:
            self.dang_nhap()
        du = self._lay("GetALLClients", "clientsData")
        if du is None and not vua_dang_nhap:
            LOGGER.debug("phiên hết hạn, đăng nhập lại một lần")
            self.dang_nhap()
            vua_dang_nhap = True
            du = self._lay("GetALLClients", "clientsData")
        if du is None:
            self._co_phien = False
            raise ZteLoiDangNhap("không đọc được danh sách máy sau khi đăng nhập: kiểm tên và mật khẩu, "
                                 "hoặc tài khoản đang được đăng nhập ở nơi khác")
        try:
            may = phan_tich_thiet_bi(du)
        except DuLieuSaiKhuon as loi:
            raise ZteLoiKetNoi(str(loi)) from loi
        ap = self._lay("GetALLAP", "apData", nghiem=False)  # không bắt buộc: thiếu thì để trống
        LOGGER.debug("đọc xong %d máy", len(may))
        return {"clients": may, "ap": phan_tich_ap(ap or {})}
