"""Trạng thái liên kết của từng cổng (binary_sensor.<tiền_tố>_<loại>_<cổng>_connection)."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .sensor import thiet_bi_giao_dien


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    da_them: set[int] = set()

    @callback
    def _them_moi() -> None:
        moi = []
        for chi_so in (coordinator.data or {}).get("interfaces", {}):
            if chi_so not in da_them:
                da_them.add(chi_so)
                moi.append(KetNoiCong(coordinator, entry, chi_so))
        if moi:
            async_add_entities(moi)

    _them_moi()
    entry.async_on_unload(coordinator.async_add_listener(_them_moi))
    if coordinator.co_api:
        _them_wireguard(entry, coordinator, async_add_entities)


class KetNoiCong(CoordinatorEntity, BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_name = "Kết nối"

    def __init__(self, coordinator, entry: ConfigEntry, chi_so: int) -> None:
        super().__init__(coordinator)
        self._chi_so = chi_so
        gd = coordinator.data["interfaces"][chi_so]
        self._attr_unique_id = f"{entry.entry_id}_{chi_so}_connection"
        self._attr_device_info = thiet_bi_giao_dien(entry, chi_so, gd["name"], coordinator.data)
        self.entity_id = f"binary_sensor.{coordinator.tien_to}_{gd['kind']}_{gd['slug']}_connection"

    @property
    def _gd(self):
        return (self.coordinator.data or {}).get("interfaces", {}).get(self._chi_so)

    @property
    def available(self) -> bool:
        return super().available and self._gd is not None

    @property
    def is_on(self) -> bool | None:
        gd = self._gd
        return gd.get("up") if gd else None


def _them_wireguard(entry: ConfigEntry, coordinator, async_add_entities: AddEntitiesCallback) -> None:
    da_them: set[str] = set()

    @callback
    def _them_moi() -> None:
        moi = []
        for p in (coordinator.data or {}).get("wireguard", []):
            if p["name"] not in da_them:
                da_them.add(p["name"])
                moi.append(WgKetNoi(coordinator, entry, p["name"]))
        if moi:
            async_add_entities(moi)

    _them_moi()
    entry.async_on_unload(coordinator.async_add_listener(_them_moi))


class WgKetNoi(CoordinatorEntity, BinarySensorEntity):
    """binary_sensor.<tiền_tố>_wireguard_<peer>_connected: bắt tay trong 3 phút gần nhất."""

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_name = "Kết nối"

    def __init__(self, coordinator, entry: ConfigEntry, ten: str) -> None:
        super().__init__(coordinator)
        self._ten = ten
        ma = slug(ten)
        self._attr_unique_id = f"{entry.entry_id}_wg_{ma}_connected"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, f"{entry.entry_id}_wg_{ma}")})
        self.entity_id = f"binary_sensor.{coordinator.tien_to}_wireguard_{ma}_connected"

    @property
    def _p(self):
        for p in (self.coordinator.data or {}).get("wireguard", []):
            if p["name"] == self._ten:
                return p
        return None

    @property
    def available(self) -> bool:
        return super().available and self._p is not None

    @property
    def is_on(self) -> bool | None:
        p = self._p
        return p.get("connected") if p else None
