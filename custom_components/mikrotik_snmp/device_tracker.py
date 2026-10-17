"""Thực thể theo dõi từng máy trong LAN (có mặt / vắng). Máy là thiết bị con của cổng nó cắm hoặc của ZTE (nếu là máy WiFi)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.device_tracker import ScannerEntity, SourceType
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo, format_mac
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .thiet_bi import dinh_danh_cha


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    da_them: set[str] = set()
    tien_to = f"{entry.entry_id}_"

    # Máy đã từng thấy nhưng lúc này vắng: dựng lại để hiện «không ở nhà», không để mất sau khi khởi động lại.
    cu: list[MayLan] = []
    for muc in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id):
        if muc.domain == "device_tracker" and muc.unique_id.startswith(tien_to):
            mac = muc.unique_id.removeprefix(tien_to).upper()
            if mac not in da_them:
                da_them.add(mac)
                cu.append(MayLan(coordinator, entry, mac))
    if cu:
        async_add_entities(cu)

    @callback
    def _them_moi() -> None:
        moi = []
        for may in ((coordinator.data or {}).get("tree") or {}).get("clients", []):
            if may["mac"] not in da_them:
                da_them.add(may["mac"])
                moi.append(MayLan(coordinator, entry, may["mac"]))
        if moi:
            async_add_entities(moi)

    _them_moi()
    entry.async_on_unload(coordinator.async_add_listener(_them_moi))


class MayLan(CoordinatorEntity, ScannerEntity):
    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, coordinator, entry: ConfigEntry, mac: str) -> None:
        super().__init__(coordinator)
        self._mac = mac
        self._entry_id = entry.entry_id
        self._attr_unique_id = f"{entry.entry_id}_{mac}"
        may = self._may or {}
        self._ten_cuoi = may.get("name") or may.get("ip") or mac
        self._cha = dinh_danh_cha(entry.entry_id, may.get("parent"), coordinator.data)

    @property
    def _may(self) -> dict[str, Any] | None:
        for may in ((self.coordinator.data or {}).get("tree") or {}).get("clients", []):
            if may["mac"] == self._mac:
                return may
        return None

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(connections={(CONNECTION_NETWORK_MAC, format_mac(self._mac))}, name=self._ten_cuoi, via_device=self._cha)

    @callback
    def _handle_coordinator_update(self) -> None:
        may = self._may
        if may is not None:
            moi = dinh_danh_cha(self._entry_id, may.get("parent"), self.coordinator.data)
            if moi != self._cha:                       # máy đổi chỗ (WiFi ↔ có dây, đổi cổng): cập nhật cây thiết bị
                so_thiet_bi = dr.async_get(self.hass)
                dev = so_thiet_bi.async_get_device(connections={(CONNECTION_NETWORK_MAC, format_mac(self._mac))})
                cha = so_thiet_bi.async_get_device(identifiers={moi})
                if dev is not None and cha is not None:
                    so_thiet_bi.async_update_device(dev.id, via_device_id=cha.id)
                self._cha = moi
        super()._handle_coordinator_update()

    @property
    def source_type(self) -> SourceType:
        return SourceType.ROUTER

    @property
    def is_connected(self) -> bool:
        return self._may is not None

    @property
    def mac_address(self) -> str:
        return self._mac

    @property
    def ip_address(self) -> str | None:
        may = self._may
        return (may.get("ip") or None) if may else None

    @property
    def hostname(self) -> str | None:
        may = self._may
        return (may.get("name") or None) if may else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        may = self._may
        if not may:
            return {}
        return {k: may[k] for k in ("parent", "interface", "source", "band", "rssi", "mode", "assoc_s") if may.get(k) not in (None, "")}
