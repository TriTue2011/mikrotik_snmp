"""Dọn thiết bị mà router không còn thấy nữa.

Lỗi gốc (chủ máy 02/11/2026: «nhiều thiết bị đã xóa nhưng HA vẫn giữ và không xóa»): tích hợp chỉ TẠO thiết bị/thực thể (máy LAN theo MAC, cổng, peer WireGuard, ZTE),
không bao giờ gỡ; riêng máy LAN còn được dựng lại từ sổ thực thể sau mỗi lần khởi động. Máy hết trên router (xoá khỏi DHCP/ARP, peer WireGuard bị xoá, cổng không còn chọn)
nằm lại vĩnh viễn trong sổ thiết bị.

Nguyên tắc: một thiết bị là «vắng» khi KHÔNG còn trong dữ liệu router ở lần cập nhật thành công gần nhất. Vắng liên tục quá ``don_sau_ngay`` ngày thì gỡ khỏi sổ
(gỡ thiết bị kéo theo thực thể của nó); máy chỉ tắt nguồn vài hôm không bị đụng. Mốc «vắng từ lúc nào» lưu bền để sống qua khởi động lại.
Nguồn ZTE/API lỗi thì tích hợp giữ danh sách cũ (không làm máy biến mất) nên mất kết nối tới nguồn không bị hiểu nhầm là máy đã xoá; cập nhật SNMP thất bại thì không xét gì.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Iterable

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, format_mac
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .logic import slug

LOGGER = logging.getLogger(__name__)

NGAY_GIAY = 86400


def khoa_hien_co(entry_id: str, du_lieu: dict[str, Any] | None, co_zte: bool) -> set[str]:
    """Khoá của mọi thiết bị mà dữ liệu router hiện có: ``id:<mã>`` (router, cổng, ZTE, peer WireGuard) và ``mac:<mac>`` (máy LAN)."""
    du_lieu = du_lieu or {}
    ra = {f"id:{entry_id}"}
    ra.update(f"id:{entry_id}_{chi_so}" for chi_so in (du_lieu.get("interfaces") or {}))
    if co_zte:
        ra.add(f"id:{entry_id}_zte")
    ra.update(f"id:{entry_id}_wg_{slug(p['name'])}" for p in (du_lieu.get("wireguard") or []) if p.get("name"))
    ra.update(f"mac:{format_mac(may['mac'])}" for may in ((du_lieu.get("tree") or {}).get("clients") or []) if may.get("mac"))
    return ra


def khoa_cua_thiet_bi(identifiers: Iterable[tuple[str, str]], connections: Iterable[tuple[str, str]]) -> set[str]:
    """Khoá của một thiết bị trong sổ thiết bị (cùng khuôn với ``khoa_hien_co``)."""
    ra = {f"id:{ma}" for kieu, ma in identifiers if kieu == DOMAIN}
    ra.update(f"mac:{format_mac(ma)}" for kieu, ma in connections if kieu == CONNECTION_NETWORK_MAC)
    return ra


def quyet_dinh(thiet_bi: dict[str, set[str]], hien_co: set[str], vang_tu: dict[str, float], bay_gio: float,
               han_giay: float | None, entry_id: str) -> tuple[dict[str, float], list[str]]:
    """Từ ``{mã thiết bị trong sổ: khoá}`` tính (mốc «vắng từ» mới, danh sách mã thiết bị cần gỡ).

    Thiết bị còn trong dữ liệu thì xoá mốc vắng; chưa có mốc thì đặt mốc = bây giờ; vắng từ đủ ``han_giay`` thì cần gỡ (``None`` = không bao giờ gỡ, ``0`` = gỡ ngay mọi thiết bị đang vắng). Router gốc không bao giờ bị gỡ.
    Mốc của thiết bị không còn trong sổ bị bỏ (bản đồ không phình)."""
    moi: dict[str, float] = {}
    can_go: list[str] = []
    for ma, khoa in thiet_bi.items():
        if f"id:{entry_id}" in khoa or khoa & hien_co:
            continue
        tu = vang_tu.get(ma, bay_gio)
        moi[ma] = tu
        if han_giay is not None and bay_gio - tu >= han_giay:
            can_go.append(ma)
    return moi, can_go


class DonDep:
    def __init__(self, hass: HomeAssistant, entry: Any, coordinator: Any, han_ngay: int) -> None:
        self.hass, self.entry, self.coordinator = hass, entry, coordinator
        self.han_ngay = han_ngay
        self._kho = Store[dict[str, float]](hass, 1, f"{DOMAIN}.vang.{entry.entry_id}")
        self._vang: dict[str, float] = {}

    async def tai(self) -> None:
        self._vang = {k: float(v) for k, v in (await self._kho.async_load() or {}).items()}

    def _thiet_bi_cua_entry(self) -> dict[str, set[str]]:
        return {d.id: khoa_cua_thiet_bi(d.identifiers, d.connections)
                for d in dr.async_entries_for_config_entry(dr.async_get(self.hass), self.entry.entry_id)}

    def _hien_co(self) -> set[str]:
        return khoa_hien_co(self.entry.entry_id, self.coordinator.data, self.coordinator.co_zte)

    def cap_nhat(self) -> None:
        """Gọi sau mỗi lần cập nhật: ghi mốc vắng, gỡ thiết bị vắng quá hạn (nếu bật)."""
        if not self.coordinator.last_update_success or not self.coordinator.data:
            return
        han = self.han_ngay * NGAY_GIAY if self.han_ngay > 0 else None      # 0 ngày = tắt tự dọn
        moi, can_go = quyet_dinh(self._thiet_bi_cua_entry(), self._hien_co(), self._vang, time.time(), han, self.entry.entry_id)
        if moi != self._vang:
            self._vang = moi
            self._kho.async_delay_save(lambda: dict(self._vang), 30)
        self._go(can_go)

    def _go(self, ma_thiet_bi: list[str]) -> int:
        so = dr.async_get(self.hass)
        n = 0
        for ma in ma_thiet_bi:
            d = so.async_get(ma)
            if d is None:
                continue
            LOGGER.info("gỡ thiết bị không còn trên router: %s", d.name_by_user or d.name or ma)
            so.async_update_device(ma, remove_config_entry_id=self.entry.entry_id)
            self._vang.pop(ma, None)
            n += 1
        return n

    def don_ngay(self, sau_ngay: float = 0) -> int:
        """Gỡ NGAY thiết bị đã vắng ≥ ``sau_ngay`` ngày (0 = mọi thiết bị đang vắng). Chỉ làm khi dữ liệu đáng tin: cập nhật gần nhất thành công
        và ZTE (nếu có) đã đọc xong, nếu không danh sách máy chưa đầy đủ và máy đang có mặt sẽ bị gỡ nhầm."""
        d = self.coordinator.data
        if not self.coordinator.last_update_success or not d:
            raise HomeAssistantError("Chưa dọn được: lần đọc router gần nhất chưa thành công.")
        zte = d.get("zte")
        if self.coordinator.co_zte and (not zte or zte.get("trang_thai") == "chua_doc"):
            raise HomeAssistantError("Chưa dọn được: ZTE chưa đọc xong danh sách máy WiFi, chờ vài chục giây rồi thử lại.")
        bay_gio = time.time()
        moi, can_go = quyet_dinh(self._thiet_bi_cua_entry(), self._hien_co(), self._vang, bay_gio,
                                 max(0.0, sau_ngay) * NGAY_GIAY, self.entry.entry_id)
        self._vang = moi
        n = self._go(can_go)
        self._kho.async_delay_save(lambda: dict(self._vang), 1)
        return n

    def co_the_go(self, khoa: set[str]) -> bool:
        """Cho người dùng xoá thiết bị này trong giao diện: chỉ khi nó không còn trong dữ liệu router."""
        if f"id:{self.entry.entry_id}" in khoa:
            return False
        return not (khoa & self._hien_co())
