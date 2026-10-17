"""Thu thập dữ liệu router qua một «máy khách SNMP» (get/walk). Không phụ thuộc Home Assistant: kiểm được bằng máy khách giả.

Giữ trạng thái giữa các lần đọc (bộ đếm trước đó để tính Mbit/s). Bộ đếm lưu lượng hỏi mỗi chu kỳ; thông tin chậm đổi
(trạng thái, lỗi, CPU, bộ nhớ, nhiệt độ) mỗi CHU_KY_CHAM_GIAY; danh sách giao diện dò lại mỗi CHU_KY_DO_LAI_GIAY.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Protocol

from . import logic as L
from .cay import xay_cay
from .const import CHU_KY_CHAM_GIAY, CHU_KY_DO_LAI_GIAY, CHU_KY_THIET_BI_GIAY, CHU_KY_ZTE_GIAY, TOI_DA_OID_MOI_LAN


class MayKhach(Protocol):
    async def get(self, oids: list[str]) -> dict[str, Any]: ...
    async def walk(self, goc: str, hex_octet: bool = False) -> dict[str, Any]: ...


class NguonZte(Protocol):
    host: str

    async def doc(self) -> dict[str, Any]: ...


_TRANG_THAI_LOI = {"ZteLoiDangNhap": "loi_dang_nhap", "ZteLoiKetNoi": "loi_ket_noi", "ZteTamNgung": "tam_ngung"}


class ThuThap:
    def __init__(self, may_khach: MayKhach, cong_chon: list[str] | None = None, dong_ho: Callable[[], float] = time.monotonic,
                 zte: NguonZte | None = None):
        self._mk = may_khach
        self._chon = set(cong_chon or [])      # rỗng = tất cả
        self._dong_ho = dong_ho
        self.giao_dien: dict[int, dict[str, Any]] = {}
        self._chi_so_ram: str | None = None
        self._lan_do = -1e18
        self._lan_cham = -1e18
        self._lan_thiet_bi = -1e18
        self._zte = zte
        self._lan_zte = -1e18
        self._du_lieu_zte: dict[str, Any] | None = (
            {"host": zte.host, "trang_thai": "chua_doc", "ap": {}, "clients": []} if zte else None)
        self._thiet_bi: dict[str, Any] = {"bang_mac": {}, "arp": {}, "clients": [], "co_bang_mac": False}
        self._truoc: dict[tuple[int, str], tuple[float, int]] = {}
        self._cham: dict[int, dict[str, Any]] = {}
        self._loi_he_thong: dict[str, Any] = {}

    def doi_cong_chon(self, cong_chon: list[str] | None) -> None:
        self._chon = set(cong_chon or [])
        self._truoc.clear()

    def _duoc_chon(self) -> list[int]:
        return [i for i, g in self.giao_dien.items() if not self._chon or g["name"] in self._chon]

    async def _hoi(self, oids: list[str]) -> dict[str, Any]:
        ra: dict[str, Any] = {}
        for nhom in L.chia_nhom(oids, TOI_DA_OID_MOI_LAN):
            ra.update(await self._mk.get(nhom))
        return ra

    async def do_lai(self) -> None:
        """Dò danh sách giao diện (tên, loại, ghi chú) và dòng RAM."""
        ten = await self._mk.walk(L.IF_NAME)
        loai = await self._mk.walk(L.IF_TYPE)
        gd = L.phan_tich_giao_dien(ten, loai)
        try:
            ghi_chu = await self._mk.walk(L.IF_ALIAS)
        except Exception:  # noqa: BLE001 - ghi chú không bắt buộc; thiếu thì để trống
            ghi_chu = {}
        for oid, v in ghi_chu.items():
            chi_so = L.hau_to(oid, L.IF_ALIAS)
            if chi_so and chi_so.isdigit() and int(chi_so) in gd:
                gd[int(chi_so)]["comment"] = L.lam_sach(v, 128)
        self.giao_dien = gd
        try:
            self._chi_so_ram = L.tim_chi_so_ram(await self._mk.walk(L.HR_STORAGE_DESCR))
        except Exception:  # noqa: BLE001 - router không có hrStorage: bỏ cảm biến bộ nhớ
            self._chi_so_ram = None
        self._lan_do = self._dong_ho()

    async def _doc_cham(self, chi_so: list[int]) -> None:
        oids: list[str] = []
        for i in chi_so:
            oids += [f"{L.IF_OPER}.{i}", f"{L.IF_IN_ERR}.{i}", f"{L.IF_OUT_ERR}.{i}", f"{L.IF_IN_DISC}.{i}",
                     f"{L.IF_OUT_DISC}.{i}", f"{L.IF_HIGH_SPEED}.{i}"]
        v = await self._hoi(oids)
        for i in chi_so:
            self._cham[i] = {
                "up": L._so(v.get(f"{L.IF_OPER}.{i}")) == 1,
                "oper": L._so(v.get(f"{L.IF_OPER}.{i}")),
                "in_errors": L._so(v.get(f"{L.IF_IN_ERR}.{i}")),
                "out_errors": L._so(v.get(f"{L.IF_OUT_ERR}.{i}")),
                "in_discards": L._so(v.get(f"{L.IF_IN_DISC}.{i}")),
                "out_discards": L._so(v.get(f"{L.IF_OUT_DISC}.{i}")),
                "speed_mbps": L._so(v.get(f"{L.IF_HIGH_SPEED}.{i}")),
            }
        lo = await self._hoi([L.SYS_UPTIME, L.SYS_NAME, L.SYS_DESCR, L.MTXR_TEMPERATURE, L.MTXR_VOLTAGE])
        nhiet, ap = L._so(lo.get(L.MTXR_TEMPERATURE)), L._so(lo.get(L.MTXR_VOLTAGE))
        try:
            cpu = L.cpu_trung_binh(await self._mk.walk(L.HR_PROCESSOR_LOAD))
        except Exception:  # noqa: BLE001
            cpu = None
        ram = None
        if self._chi_so_ram is not None:
            m = await self._hoi([f"{L.HR_STORAGE_SIZE}.{self._chi_so_ram}", f"{L.HR_STORAGE_USED}.{self._chi_so_ram}"])
            ram = L.phan_tram(m.get(f"{L.HR_STORAGE_USED}.{self._chi_so_ram}"), m.get(f"{L.HR_STORAGE_SIZE}.{self._chi_so_ram}"))
        self._loi_he_thong = {
            "uptime": L.thoi_gian_chay(lo.get(L.SYS_UPTIME)),
            "name": L.lam_sach(lo.get(L.SYS_NAME)) or None,
            "descr": L.lam_sach(lo.get(L.SYS_DESCR), 160) or None,
            "temperature": nhiet / 10 if nhiet is not None else None,
            "voltage": ap / 10 if ap is not None else None,
            "cpu": cpu,
            "memory": ram,
        }

    async def _doc_thiet_bi(self) -> None:
        """Bảng ARP + bảng MAC của bridge. Router không có bảng nào thì giữ kết quả cũ (không làm hỏng cả lần cập nhật)."""
        try:
            arp = L.phan_tich_arp(await self._mk.walk(L.ARP_MAC, hex_octet=True))
        except Exception:  # noqa: BLE001
            arp = self._thiet_bi["arp"]
        try:
            cong = await self._mk.walk(L.FDB_PORT)
            if cong:
                bang = L.phan_tich_bang_mac(cong, await self._mk.walk(L.FDB_STATUS),
                                            await self._mk.walk(L.BASE_PORT_IF), self.giao_dien)
            else:
                bang = {}
        except Exception:  # noqa: BLE001
            bang = self._thiet_bi["bang_mac"]
        self._thiet_bi = {"bang_mac": bang, "arp": arp, "clients": L.danh_sach_thiet_bi(arp, bang), "co_bang_mac": bool(bang)}

    async def _doc_zte(self) -> None:
        """Danh sách máy WiFi từ ZTE. Lỗi (không đăng nhập được, nghỉ, mất mạng) thì giữ danh sách cũ và ghi trạng thái."""
        cu = self._du_lieu_zte or {}
        try:
            d = await self._zte.doc()
            self._du_lieu_zte = {"host": self._zte.host, "trang_thai": "ok", "ap": d.get("ap") or {}, "clients": d.get("clients") or []}
        except Exception as loi:  # noqa: BLE001 - mọi lỗi nguồn ZTE chỉ làm mất thông tin WiFi, không làm hỏng phần MikroTik
            self._du_lieu_zte = {**cu, "host": self._zte.host, "trang_thai": _TRANG_THAI_LOI.get(type(loi).__name__, "loi")}

    async def cap_nhat(self) -> dict[str, Any]:
        bay_gio = self._dong_ho()
        if not self.giao_dien or bay_gio - self._lan_do >= CHU_KY_DO_LAI_GIAY:
            await self.do_lai()
        chi_so = self._duoc_chon()
        oids = []
        for i in chi_so:
            oids += [f"{L.IF_HC_IN}.{i}", f"{L.IF_HC_OUT}.{i}"]
        v = await self._hoi(oids)
        t = self._dong_ho()          # thời điểm nhận trả lời: mốc tính tốc độ
        if t - self._lan_cham >= CHU_KY_CHAM_GIAY or not self._cham:
            await self._doc_cham(chi_so)
            self._lan_cham = t
        if t - self._lan_thiet_bi >= CHU_KY_THIET_BI_GIAY:
            await self._doc_thiet_bi()
            self._lan_thiet_bi = t
        if self._zte is not None and t - self._lan_zte >= CHU_KY_ZTE_GIAY:
            await self._doc_zte()
            self._lan_zte = t
        ra: dict[int, dict[str, Any]] = {}
        for i in chi_so:
            g = dict(self.giao_dien[i])
            for huong, goc in (("rx", L.IF_HC_IN), ("tx", L.IF_HC_OUT)):
                so = L._so(v.get(f"{goc}.{i}"))
                g[f"{huong}_mbps"] = None
                if so is not None:
                    g[f"{huong}_octets"] = so
                    g[f"{huong}_mbps"] = L.tinh_toc_do_mbit(self._truoc.get((i, huong)), (t, so))
                    self._truoc[(i, huong)] = (t, so)
            g.update(self._cham.get(i, {}))
            ra[i] = g
        ten_router = self._loi_he_thong.get("name") or "MikroTik"
        cay = xay_cay(ra, self._thiet_bi["bang_mac"], self._thiet_bi["arp"], self._du_lieu_zte, ten_router)
        return {"interfaces": ra, "core": dict(self._loi_he_thong), "devices": dict(self._thiet_bi), "tree": cay,
                "zte": dict(self._du_lieu_zte) if self._du_lieu_zte else None}
