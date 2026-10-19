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
    CONF_API_MAT_KHAU, CONF_API_PORT, CONF_API_TEN, CONF_API_VAN_TAY, API_PORT_MAC_DINH,
    CONF_PRIV_KEY, CONF_PRIV_PROTOCOL, CONF_TEN, CONF_TEN_MAY, CONF_TIEN_TO, CONF_ZTE_HOST, CONF_ZTE_MAT_KHAU, CONF_ZTE_SSL, CONF_ZTE_TEN, DOMAIN,
    PORT_MAC_DINH, PRIV_MAC_DINH, TIEN_TO_MAC_DINH,
)
from .snmp_client import SnmpClient, SnmpLoi, SnmpLoiDangNhap
from .thiet_bi import cha_cua_giao_dien, dinh_danh_cha
from .logic import phan_tich_ten_may
from .thu_thap import LoiDuLieu, ThuThap
from .zte_api import ZteE2633
from .nguon_api import NguonApi
from .zte_nguon import NguonZte

LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.DEVICE_TRACKER]


def cau_hinh_hieu_luc(entry: ConfigEntry) -> dict:
    """Dữ liệu lúc thêm, tuỳ chọn (bánh răng) ghi đè."""
    return {**entry.data, **entry.options}


class MikrotikSnmpCoordinator(DataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        cfg = cau_hinh_hieu_luc(entry)
        super().__init__(hass, LOGGER, name=DOMAIN, update_interval=timedelta(seconds=cfg.get(CONF_CHU_KY, CHU_KY_MAC_DINH)), config_entry=entry)
        self.tien_to: str = cfg.get(CONF_TIEN_TO, TIEN_TO_MAC_DINH)
        self.host: str = cfg[CONF_HOST]
        self.client = SnmpClient(
            hass, cfg[CONF_HOST], cfg.get(CONF_PORT, PORT_MAC_DINH), cfg[CONF_TEN], cfg[CONF_AUTH_KEY], cfg[CONF_PRIV_KEY],
            cfg.get(CONF_AUTH_PROTOCOL, AUTH_MAC_DINH), cfg.get(CONF_PRIV_PROTOCOL, PRIV_MAC_DINH),
        )
        zte = None
        self.co_zte = bool(cfg.get(CONF_ZTE_HOST))
        if self.co_zte:
            zte = NguonZte(ZteE2633(cfg[CONF_ZTE_HOST], cfg.get(CONF_ZTE_TEN, ""), cfg.get(CONF_ZTE_MAT_KHAU, ""),
                                    xac_minh_ssl=cfg.get(CONF_ZTE_SSL, False)),
                           cfg[CONF_ZTE_HOST], hass.async_add_executor_job)
        self._zte = zte
        api = None
        self.co_api = bool(cfg.get(CONF_API_TEN))
        if self.co_api:
            api = NguonApi(cfg[CONF_HOST], cfg.get(CONF_API_PORT, API_PORT_MAC_DINH), cfg[CONF_API_TEN], cfg.get(CONF_API_MAT_KHAU, ""),
                           cfg.get(CONF_API_VAN_TAY, ""), hass.async_add_executor_job)
        self._api = api
        self.thu_thap = ThuThap(self.client, cfg.get(CONF_CONG) or None, zte=zte, ten_may=phan_tich_ten_may(cfg.get(CONF_TEN_MAY, "")), api=api)

    async def _async_update_data(self):
        try:
            return await self.thu_thap.cap_nhat()
        except SnmpLoiDangNhap as loi:
            raise ConfigEntryAuthFailed(str(loi)) from loi
        except (SnmpLoi, LoiDuLieu) as loi:
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
    # Dựng sẵn thiết bị giao diện và ZTE để thực thể con gắn via_device được: bridge (con của router) trước, rồi cổng (con của bridge
    # hoặc router), rồi ZTE là con của cổng.
    so_thiet_bi = dr.async_get(hass)
    du_lieu = coordinator.data or {}
    goc = (DOMAIN, entry.entry_id)
    cha_cua = {chi_so: cha_cua_giao_dien(entry.entry_id, gd["name"], du_lieu) for chi_so, gd in (du_lieu.get("interfaces") or {}).items()}
    for chi_so in sorted(cha_cua, key=lambda c: cha_cua[c] != goc):
        so_thiet_bi.async_get_or_create(config_entry_id=entry.entry_id, identifiers={(DOMAIN, f"{entry.entry_id}_{chi_so}")},
                               name=du_lieu["interfaces"][chi_so]["name"], manufacturer="MikroTik", via_device=cha_cua[chi_so])
    if coordinator.co_zte:
        nut_zte = next((n for n in (du_lieu.get("tree") or {}).get("nodes", []) if n["id"] == "zte"), {})
        ap = (du_lieu.get("zte") or {}).get("ap") or {}
        so_thiet_bi.async_get_or_create(config_entry_id=entry.entry_id, identifiers={(DOMAIN, f"{entry.entry_id}_zte")},
                               name=nut_zte.get("name") or "ZTE E2633", manufacturer="ZTE", model="E2633",
                               sw_version=ap.get("firmware") or None,
                               via_device=dinh_danh_cha(entry.entry_id, nut_zte.get("parent"), du_lieu))
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
            if coordinator._api is not None:
                coordinator._api.dong()
            if coordinator._zte is not None:
                coordinator._zte.dong()
    return ok
