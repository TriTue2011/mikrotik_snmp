"""Nguồn API chỉ-đọc cho bộ thu thập: giữ MỘT phiên TLS bền, chạy trong luồng phụ, kèm chốt an toàn.

Mỗi lần đọc: bộ đếm Kid Control (tốc độ từng máy) mỗi chu kỳ, tên DHCP lâu lâu một lần. Sau lỗi đăng nhập/vân tay thì nghỉ THOI_GIAN_TAM_DUNG giây.
Kid Control chưa bật hoặc lỗi lệnh thì chỉ mất tốc độ từng máy, tên vẫn lấy được.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Awaitable, Callable

from .const import THOI_GIAN_TAM_DUNG
from .routeros_api import ApiLoi, ApiLoiDangNhap, ApiLoiVanTay, Phien, kid_control, mo_phien, ten_tu_dhcp


class ApiTamNgung(Exception):
    """Đang nghỉ sau lỗi đăng nhập/vân tay."""


class NguonApi:
    def __init__(self, host: str, port: int, ten: str, mat_khau: str, van_tay: str,
                 chay_nen: Callable[[Callable[[], Any]], Awaitable[Any]], dong_ho: Callable[[], float] = time.monotonic) -> None:
        self.host = host
        self._port, self._ten, self._mat_khau, self._van_tay = port, ten, mat_khau, van_tay
        self._chay = chay_nen
        self._dong_ho = dong_ho
        self._tam_dung_den = 0.0
        self._phien: Phien | None = None
        self._khoa = threading.Lock()

    def _doc_dong_bo(self, lay_ten: bool, lay_kid: bool) -> dict[str, Any]:
        with self._khoa:
            try:
                if self._phien is None:
                    self._phien = mo_phien(self._host_api(), self._port, self._ten, self._mat_khau, self._van_tay)
                ra: dict[str, Any] = {}
                if lay_ten:
                    ra["ten"] = ten_tu_dhcp(self._phien)
                if lay_kid:
                    try:
                        ra["kid"] = kid_control(self._phien)
                    except ApiLoi:
                        ra["kid"] = None            # Kid Control chưa bật / lệnh bị từ chối: chỉ mất tốc độ từng máy
                        self.dong()                 # phiên có thể hỏng: lần sau nối lại
                return ra
            except Exception:
                self.dong()
                raise

    def _host_api(self) -> str:
        return self.host

    async def doc(self, lay_ten: bool, lay_kid: bool) -> dict[str, Any]:
        if self._dong_ho() < self._tam_dung_den:
            raise ApiTamNgung()
        try:
            return await self._chay(lambda: self._doc_dong_bo(lay_ten, lay_kid))
        except (ApiLoiDangNhap, ApiLoiVanTay):
            self._tam_dung_den = self._dong_ho() + THOI_GIAN_TAM_DUNG
            raise

    def dong(self) -> None:
        if self._phien is not None:
            self._phien.dong()
            self._phien = None
