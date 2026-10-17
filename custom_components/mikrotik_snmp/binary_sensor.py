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


class KetNoiCong(CoordinatorEntity, BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_name = "Kết nối"

    def __init__(self, coordinator, entry: ConfigEntry, chi_so: int) -> None:
        super().__init__(coordinator)
        self._chi_so = chi_so
        gd = coordinator.data["interfaces"][chi_so]
        self._attr_unique_id = f"{entry.entry_id}_{chi_so}_connection"
        self._attr_device_info = thiet_bi_giao_dien(entry, chi_so, gd["name"])
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
