"""Cây thiết bị trong sổ thiết bị của Home Assistant: Router → Bridge → Cổng → ZTE → Máy, và Router → WireGuard → Peer (via_device)."""
from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN


def dinh_danh_cha(entry_id: str, nut: str | None, du_lieu: dict[str, Any] | None) -> tuple[str, str]:
    """Định danh thiết bị cha cho nút cây («router», «zte» hoặc tên cổng); không rõ thì về router."""
    if not nut or nut == "router":
        return (DOMAIN, entry_id)
    if nut == "zte":
        return (DOMAIN, f"{entry_id}_zte")
    for chi_so, gd in ((du_lieu or {}).get("interfaces") or {}).items():
        if gd["name"] == nut:
            return (DOMAIN, f"{entry_id}_{chi_so}")
    return (DOMAIN, entry_id)


def thiet_bi_cong(entry_id: str, chi_so: int, ten: str) -> DeviceInfo:
    return DeviceInfo(identifiers={(DOMAIN, f"{entry_id}_{chi_so}")}, name=ten, manufacturer="MikroTik",
                      via_device=(DOMAIN, entry_id))


def cha_cua_giao_dien(entry_id: str, ten: str, du_lieu: dict[str, Any] | None) -> tuple[str, str]:
    """Thiết bị cha của một giao diện: bridge nếu cổng thuộc bridge (theo cây), còn lại là router."""
    nut = next((n for n in ((du_lieu or {}).get("tree") or {}).get("nodes", []) if n["id"] == ten), None)
    return dinh_danh_cha(entry_id, (nut or {}).get("parent"), du_lieu)


def ten_thiet_bi(may: dict[str, Any] | None, mac: str) -> str:
    """Tên thiết bị hiển thị: tên đã đặt, không có thì IP, không có nữa thì MAC. Vị trí (cổng, bridge, ZTE) nằm ở thiết bị cha (via_device)."""
    may = may or {}
    return may.get("name") or may.get("ip") or mac
