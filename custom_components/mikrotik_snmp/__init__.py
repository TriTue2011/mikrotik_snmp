"""MikroTik qua SNMPv3, CHỈ ĐỌC: tốc độ từng cổng (Mbit/s, cập nhật vài giây), trạng thái, lỗi, CPU, bộ nhớ, nhiệt độ."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    AUTH_MAC_DINH, CHU_KY_MAC_DINH, CONF_AUTH_KEY, CONF_AUTH_PROTOCOL, CONF_CHU_KY, CONF_CONG, CONF_HOST, CONF_PORT,
    CONF_PRIV_KEY, CONF_PRIV_PROTOCOL, CONF_TEN, CONF_TIEN_TO, DOMAIN, PORT_MAC_DINH, PRIV_MAC_DINH, TIEN_TO_MAC_DINH,
)
from .snmp_client import SnmpClient, SnmpLoi, SnmpLoiDangNhap
from .thu_thap import ThuThap

LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]


def cau_hinh_hieu_luc(entry: ConfigEntry) -> dict:
    """Dữ liệu lúc thêm, tuỳ chọn (bánh răng) ghi đè."""
    return {**entry.data, **entry.options}


class MikrotikSnmpCoordinator(DataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        cfg = cau_hinh_hieu_luc(entry)
        super().__init__(hass, LOGGER, name=DOMAIN, update_interval=timedelta(seconds=cfg.get(CONF_CHU_KY, CHU_KY_MAC_DINH)))
        self.tien_to: str = cfg.get(CONF_TIEN_TO, TIEN_TO_MAC_DINH)
        self.host: str = cfg[CONF_HOST]
        self.client = SnmpClient(
            hass, cfg[CONF_HOST], cfg.get(CONF_PORT, PORT_MAC_DINH), cfg[CONF_TEN], cfg[CONF_AUTH_KEY], cfg[CONF_PRIV_KEY],
            cfg.get(CONF_AUTH_PROTOCOL, AUTH_MAC_DINH), cfg.get(CONF_PRIV_PROTOCOL, PRIV_MAC_DINH),
        )
        self.thu_thap = ThuThap(self.client, cfg.get(CONF_CONG) or None)

    async def _async_update_data(self):
        try:
            return await self.thu_thap.cap_nhat()
        except SnmpLoiDangNhap as loi:
            raise ConfigEntryAuthFailed(str(loi)) from loi
        except SnmpLoi as loi:
            raise UpdateFailed(str(loi)) from loi


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = MikrotikSnmpCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    core = (coordinator.data or {}).get("core", {})
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name=f"MikroTik {coordinator.host}",
        manufacturer="MikroTik",
        model=core.get("descr"),
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_khi_tuy_chon_doi))
    return True


async def _khi_tuy_chon_doi(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        coordinator = hass.data[DOMAIN].pop(entry.entry_id, None)
        if coordinator is not None:
            coordinator.client.dong()
    return ok
