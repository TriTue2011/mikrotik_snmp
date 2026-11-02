"""Tạo thiết bị con thẳng trong sổ thiết bị (không qua thực thể): gắn thiết bị cha bằng `via_device_id`.

`async_get_or_create(via_device=…)` đã bị Home Assistant đánh dấu lỗi thời; thực thể vẫn dùng `DeviceInfo(via_device=…)` bình thường."""
from __future__ import annotations

from typing import Any


def tao_thiet_bi_con(so_thiet_bi: Any, config_entry_id: str, identifiers: set, cha: tuple[str, str], **thuoc_tinh: Any) -> Any:
    """Tạo/cập nhật thiết bị con. Cha chưa có trong sổ thì vẫn tạo con (chưa gắn cha) thay vì làm hỏng cả bước dựng."""
    cha_tb = so_thiet_bi.async_get_device(identifiers={cha})
    if cha_tb is not None:
        thuoc_tinh["via_device_id"] = cha_tb.id
    return so_thiet_bi.async_get_or_create(config_entry_id=config_entry_id, identifiers=identifiers, **thuoc_tinh)
