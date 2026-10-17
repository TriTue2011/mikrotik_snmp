"""Thêm tích hợp: nhập IP + người dùng SNMPv3 + hai mật khẩu, thử đọc một lần, rồi chọn cổng. Chỉ đọc, không ghi gì lên router."""
from __future__ import annotations

import re
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from . import logic as L
from .const import (
    AUTH_MAC_DINH, AUTH_PROTOCOLS, CHU_KY_LON_NHAT, CHU_KY_MAC_DINH, CHU_KY_NHO_NHAT, CONF_AUTH_KEY, CONF_AUTH_PROTOCOL,
    CONF_CHU_KY, CONF_CONG, CONF_HOST, CONF_PORT, CONF_PRIV_KEY, CONF_PRIV_PROTOCOL, CONF_TEN, CONF_TIEN_TO, DOMAIN,
    CONF_ZTE_HOST, CONF_ZTE_MAT_KHAU, CONF_ZTE_SSL, CONF_ZTE_TEN, PORT_MAC_DINH, PRIV_MAC_DINH, PRIV_PROTOCOLS, TIEN_TO_MAC_DINH,
)
from .snmp_client import SnmpClient, SnmpLoiDangNhap, SnmpLoiKetNoi
from .thu_thap import LoiDuLieu, ThuThap
from .zte_api import ZteE2633, ZteLoiDangNhap, ZteLoiKetNoi

HOST_RE = re.compile(r"^[A-Za-z0-9.-]{1,253}$")
TIEN_TO_RE = re.compile(r"^[a-z0-9_]{1,40}$")
MAT_KHAU = selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD))


def _chon(danh_sach: list[str]) -> selector.SelectSelector:
    return selector.SelectSelector(selector.SelectSelectorConfig(options=danh_sach, mode=selector.SelectSelectorMode.DROPDOWN))


def _schema(mac_dinh: dict[str, Any]) -> vol.Schema:
    return vol.Schema({
        vol.Required(CONF_HOST, default=mac_dinh.get(CONF_HOST, "")): str,
        vol.Required(CONF_PORT, default=mac_dinh.get(CONF_PORT, PORT_MAC_DINH)): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
        vol.Required(CONF_TEN, default=mac_dinh.get(CONF_TEN, "hass")): str,
        vol.Required(CONF_AUTH_KEY): MAT_KHAU,
        vol.Required(CONF_PRIV_KEY): MAT_KHAU,
        vol.Required(CONF_AUTH_PROTOCOL, default=mac_dinh.get(CONF_AUTH_PROTOCOL, AUTH_MAC_DINH)): _chon(AUTH_PROTOCOLS),
        vol.Required(CONF_PRIV_PROTOCOL, default=mac_dinh.get(CONF_PRIV_PROTOCOL, PRIV_MAC_DINH)): _chon(PRIV_PROTOCOLS),
        vol.Required(CONF_TIEN_TO, default=mac_dinh.get(CONF_TIEN_TO, TIEN_TO_MAC_DINH)): str,
        vol.Required(CONF_CHU_KY, default=mac_dinh.get(CONF_CHU_KY, CHU_KY_MAC_DINH)): vol.All(
            vol.Coerce(int), vol.Range(min=CHU_KY_NHO_NHAT, max=CHU_KY_LON_NHAT)),
    })


async def _thu(hass, du: dict[str, Any]) -> list[str]:
    """Đọc thử một lần: trả danh sách tên giao diện. Ném SnmpLoiKetNoi / SnmpLoiDangNhap."""
    mk = SnmpClient(hass, du[CONF_HOST], du[CONF_PORT], du[CONF_TEN], du[CONF_AUTH_KEY], du[CONF_PRIV_KEY],
                    du[CONF_AUTH_PROTOCOL], du[CONF_PRIV_PROTOCOL])
    try:
        await mk.get([L.SYS_DESCR])
        tt = ThuThap(mk)
        await tt.do_lai()
        return sorted(g["name"] for g in tt.giao_dien.values())
    finally:
        mk.dong()


def _cong_schema(danh_sach: list[str], dang_chon: list[str]) -> vol.Schema:
    return vol.Schema({vol.Required(CONF_CONG, default=dang_chon or danh_sach): selector.SelectSelector(
        selector.SelectSelectorConfig(options=danh_sach, multiple=True, mode=selector.SelectSelectorMode.DROPDOWN))})


class MikrotikSnmpConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._du: dict[str, Any] = {}
        self._cong: list[str] = []

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> MikrotikSnmpOptionsFlow:
        return MikrotikSnmpOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        loi: dict[str, str] = {}
        if user_input is not None:
            user_input[CONF_HOST] = user_input[CONF_HOST].strip()
            if not HOST_RE.match(user_input[CONF_HOST]):
                loi["base"] = "host_sai"
            elif not TIEN_TO_RE.match(user_input[CONF_TIEN_TO]):
                loi["base"] = "tien_to_sai"
            else:
                try:
                    self._cong = await _thu(self.hass, user_input)
                except SnmpLoiDangNhap:
                    loi["base"] = "dang_nhap"
                except SnmpLoiKetNoi:
                    loi["base"] = "ket_noi"
                except LoiDuLieu:
                    loi["base"] = "khong_co_cong"
                except Exception:  # noqa: BLE001 - lỗi lạ (ví dụ thiếu pysnmp): báo chung, chi tiết ở nhật ký
                    loi["base"] = "khong_ro"
                else:
                    await self.async_set_unique_id(user_input[CONF_HOST])
                    self._abort_if_unique_id_configured()
                    self._du = user_input
                    return await self.async_step_zte()
        return self.async_show_form(step_id="user", data_schema=_schema(user_input or {}), errors=loi)

    async def async_step_zte(self, user_input: dict[str, Any] | None = None):
        """Bước tuỳ chọn: có bộ phát ZTE E2633 thì đăng nhập thêm để đưa máy WiFi thành con của ZTE. Bỏ trống IP để bỏ qua."""
        loi: dict[str, str] = {}
        if user_input is not None:
            host = (user_input.get(CONF_ZTE_HOST) or "").strip()
            if not host:
                return await self.async_step_cong()
            if not HOST_RE.match(host):
                loi["base"] = "host_sai"
            else:
                may = ZteE2633(host, user_input.get(CONF_ZTE_TEN, ""), user_input.get(CONF_ZTE_MAT_KHAU, ""),
                               xac_minh_ssl=user_input.get(CONF_ZTE_SSL, False))
                try:
                    await self.hass.async_add_executor_job(may.doc_thiet_bi)
                except ZteLoiDangNhap:
                    loi["base"] = "dang_nhap_zte"
                except ZteLoiKetNoi:
                    loi["base"] = "ket_noi_zte"
                except Exception:  # noqa: BLE001
                    loi["base"] = "khong_ro"
                else:
                    self._du.update({CONF_ZTE_HOST: host, CONF_ZTE_TEN: user_input.get(CONF_ZTE_TEN, ""),
                                     CONF_ZTE_MAT_KHAU: user_input.get(CONF_ZTE_MAT_KHAU, ""),
                                     CONF_ZTE_SSL: user_input.get(CONF_ZTE_SSL, False)})
                    return await self.async_step_cong()
        mac_dinh = user_input or {}
        return self.async_show_form(step_id="zte", errors=loi, data_schema=vol.Schema({
            vol.Optional(CONF_ZTE_HOST, default=mac_dinh.get(CONF_ZTE_HOST, "")): str,
            vol.Optional(CONF_ZTE_TEN, default=mac_dinh.get(CONF_ZTE_TEN, "user")): str,
            vol.Optional(CONF_ZTE_MAT_KHAU, default=""): MAT_KHAU,
            vol.Optional(CONF_ZTE_SSL, default=mac_dinh.get(CONF_ZTE_SSL, False)): bool,
        }))

    async def async_step_cong(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            return self.async_create_entry(title=f"MikroTik ({self._du[CONF_HOST]})", data={**self._du, CONF_CONG: user_input[CONF_CONG]})
        return self.async_show_form(step_id="cong", data_schema=_cong_schema(self._cong, []))

    async def async_step_reauth(self, entry_data: dict[str, Any]):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None):
        entry: ConfigEntry = self._get_reauth_entry()
        loi: dict[str, str] = {}
        if user_input is not None:
            du = {**entry.data, CONF_AUTH_KEY: user_input[CONF_AUTH_KEY], CONF_PRIV_KEY: user_input[CONF_PRIV_KEY]}
            try:
                await _thu(self.hass, du)
            except SnmpLoiDangNhap:
                loi["base"] = "dang_nhap"
            except SnmpLoiKetNoi:
                loi["base"] = "ket_noi"
            else:
                return self.async_update_reload_and_abort(entry, data=du, reason="reauth_successful")
        return self.async_show_form(step_id="reauth_confirm", errors=loi, data_schema=vol.Schema(
            {vol.Required(CONF_AUTH_KEY): MAT_KHAU, vol.Required(CONF_PRIV_KEY): MAT_KHAU}))


class MikrotikSnmpOptionsFlow(OptionsFlow):
    """Nút bánh răng: đổi chu kỳ đọc và cổng hiển thị."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        hien_tai = {**self.config_entry.data, **self.config_entry.options}
        coordinator = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id)
        ten_cong = sorted(g["name"] for g in coordinator.thu_thap.giao_dien.values()) if coordinator else hien_tai.get(CONF_CONG, [])
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(step_id="init", data_schema=vol.Schema({
            vol.Required(CONF_CHU_KY, default=hien_tai.get(CONF_CHU_KY, CHU_KY_MAC_DINH)): vol.All(
                vol.Coerce(int), vol.Range(min=CHU_KY_NHO_NHAT, max=CHU_KY_LON_NHAT)),
            vol.Required(CONF_CONG, default=hien_tai.get(CONF_CONG) or ten_cong): selector.SelectSelector(
                selector.SelectSelectorConfig(options=ten_cong, multiple=True, mode=selector.SelectSelectorMode.DROPDOWN)),
        }))
