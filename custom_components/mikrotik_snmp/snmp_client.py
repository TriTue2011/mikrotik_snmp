"""Máy khách SNMPv3 CHỈ ĐỌC bằng pysnmp (đã có sẵn trong Home Assistant qua tích hợp «snmp»).

Chỉ có GET và GETNEXT. Không có đường ghi. Khoá không bao giờ vào log hay thông báo lỗi.
Dùng đúng cách gọi đã chạy được trong container Home Assistant: UsmUserData, UdpTransportTarget.create, get_cmd, next_cmd.
"""
from __future__ import annotations

from typing import Any

from .const import TOI_DA_BUOC_DUYET
from .logic import hau_to


class SnmpLoi(Exception):
    """Lỗi chung."""


class SnmpLoiKetNoi(SnmpLoi):
    """Không tới được router / hết thời gian chờ."""


class SnmpLoiDangNhap(SnmpLoi):
    """Sai người dùng hoặc mật khẩu / giao thức."""


_KET_NOI = ("timeout", "no snmp response", "unreachable", "refused", "network")


def _phan_loai(loi: Any) -> SnmpLoi:
    chu = str(loi).lower()
    if any(k in chu for k in _KET_NOI):
        return SnmpLoiKetNoi(str(loi)[:120])
    return SnmpLoiDangNhap(str(loi)[:120])


def _gia_tri(v: Any) -> Any:
    if type(v).__name__ in ("NoSuchObject", "NoSuchInstance", "EndOfMibView"):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return v.prettyPrint() if hasattr(v, "prettyPrint") else str(v)


class SnmpClient:
    def __init__(self, hass: Any, host: str, port: int, ten: str, auth_key: str, priv_key: str,
                 auth_protocol: str, priv_protocol: str):
        self._hass = hass
        self._host, self._port, self._ten = host, port, ten
        self._auth_key, self._priv_key = auth_key, priv_key
        self._auth_p, self._priv_p = auth_protocol, priv_protocol
        self._engine: Any = None
        self._muc_tieu: Any = None

    async def _chuan_bi(self) -> tuple[Any, Any, Any]:
        from pysnmp.hlapi.v3arch import asyncio as h  # nhập muộn: chỉ cần khi thật sự hỏi
        if self._engine is None:
            try:
                self._engine = await self._hass.async_add_executor_job(h.SnmpEngine)
            except Exception:  # noqa: BLE001 - tạo ngay trong vòng lặp nếu luồng phụ không dùng được
                self._engine = h.SnmpEngine()
        if self._muc_tieu is None:
            self._muc_tieu = await h.UdpTransportTarget.create((self._host, self._port), timeout=3, retries=1)
        auth = {
            "hmac-md5": "usmHMACMD5AuthProtocol", "hmac-sha": "usmHMACSHAAuthProtocol",
            "hmac128-sha224": "usmHMAC128SHA224AuthProtocol", "hmac192-sha256": "usmHMAC192SHA256AuthProtocol",
            "hmac256-sha384": "usmHMAC256SHA384AuthProtocol", "hmac384-sha512": "usmHMAC384SHA512AuthProtocol",
        }.get(self._auth_p, "usmHMACSHAAuthProtocol")
        priv = {
            "des": "usmDESPrivProtocol", "3des-ede": "usm3DESEDEPrivProtocol", "aes-cfb-128": "usmAesCfb128Protocol",
            "aes-cfb-192": "usmAesCfb192Protocol", "aes-cfb-256": "usmAesCfb256Protocol",
        }.get(self._priv_p, "usmAesCfb128Protocol")
        du = h.UsmUserData(self._ten, self._auth_key, self._priv_key,
                           authProtocol=getattr(h, auth), privProtocol=getattr(h, priv))
        return h, du, self._muc_tieu

    async def get(self, oids: list[str]) -> dict[str, Any]:
        h, du, muc_tieu = await self._chuan_bi()
        ket = await h.get_cmd(self._engine, du, muc_tieu, h.ContextData(), *[h.ObjectType(h.ObjectIdentity(o)) for o in oids])
        loi, trang_thai, _chi_so, var = ket
        if loi:
            raise _phan_loai(loi)
        if trang_thai:
            raise SnmpLoi(f"router báo lỗi SNMP: {trang_thai.prettyPrint()[:60]}")
        ra: dict[str, Any] = {}
        for ten, gia_tri in var:
            v = _gia_tri(gia_tri)
            if v is not None:
                ra[str(ten.prettyPrint() if hasattr(ten, "prettyPrint") else ten).lstrip(".")] = v
        return ra

    async def walk(self, goc: str) -> dict[str, Any]:
        """Duyệt cây con bằng GETNEXT lặp (có giới hạn bước)."""
        h, du, muc_tieu = await self._chuan_bi()
        ra: dict[str, Any] = {}
        hien_tai = goc
        for _ in range(TOI_DA_BUOC_DUYET):
            loi, trang_thai, _ci, var = await h.next_cmd(
                self._engine, du, muc_tieu, h.ContextData(), h.ObjectType(h.ObjectIdentity(hien_tai)))
            if loi:
                raise _phan_loai(loi)
            if trang_thai or not var:
                break
            ten, gia_tri = var[0]
            oid = str(ten.prettyPrint() if hasattr(ten, "prettyPrint") else ten).lstrip(".")
            if hau_to(oid, goc) is None:
                break
            v = _gia_tri(gia_tri)
            if v is None:
                break
            ra[oid] = v
            hien_tai = oid
        return ra

    def dong(self) -> None:
        if self._engine is not None:
            try:
                self._engine.close_dispatcher()
            except Exception:  # noqa: BLE001 - đóng muộn không đáng báo
                pass
            self._engine = None
