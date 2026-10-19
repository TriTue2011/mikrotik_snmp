"""Nguồn ZTE cho bộ thu thập: bọc máy khách web (đồng bộ) chạy trong luồng phụ, kèm chốt an toàn.

Sau một lần đăng nhập thất bại thì tạm ngừng THOI_GIAN_TAM_DUNG giây (không gõ mật khẩu liên tục, tránh khoá tài khoản quản trị).
"""
from __future__ import annotations

import time
from typing import Any, Awaitable, Callable

from .const import THOI_GIAN_TAM_DUNG
from .zte_api import ZteE2633, ZteLoiDangNhap


class ZteTamNgung(Exception):
    """Đang trong thời gian nghỉ sau lỗi đăng nhập."""


class NguonZte:
    def __init__(self, may: ZteE2633, host: str, chay_nen: Callable[[Callable[[], Any]], Awaitable[Any]],
                 dong_ho: Callable[[], float] = time.monotonic) -> None:
        self._may = may
        self.host = host
        self._chay = chay_nen
        self._dong_ho = dong_ho
        self._tam_dung_den = 0.0

    async def doc(self) -> dict[str, Any]:
        if self._dong_ho() < self._tam_dung_den:
            raise ZteTamNgung()
        try:
            return await self._chay(self._may.doc_thiet_bi)
        except ZteLoiDangNhap:
            self._tam_dung_den = self._dong_ho() + THOI_GIAN_TAM_DUNG
            raise

    def dong(self) -> None:
        """Đóng/quên phiên ZTE phía máy khách."""
        self._may.dang_xuat()
