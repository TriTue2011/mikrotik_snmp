"""Phần logic THUẦN của tích hợp (không phụ thuộc Home Assistant hay pysnmp): OID, tính tốc độ từ bộ đếm, phân tích bảng.

Mọi hàm ở đây kiểm được bằng test thường. Dữ liệu từ router (tên cổng, mô tả) là KHÔNG TIN ĐƯỢC: cắt độ dài, bỏ ký tự điều khiển.
"""
from __future__ import annotations

import re
from typing import Any

# ── OID chuẩn (IF-MIB, SNMPv2-MIB, HOST-RESOURCES-MIB) ──
SYS_DESCR = "1.3.6.1.2.1.1.1.0"
SYS_UPTIME = "1.3.6.1.2.1.1.3.0"          # centi-giây
SYS_NAME = "1.3.6.1.2.1.1.5.0"
IF_NAME = "1.3.6.1.2.1.31.1.1.1.1"
IF_ALIAS = "1.3.6.1.2.1.31.1.1.1.18"      # ghi chú (comment) của giao diện
IF_TYPE = "1.3.6.1.2.1.2.2.1.3"
IF_OPER = "1.3.6.1.2.1.2.2.1.8"           # 1 = up
IF_HC_IN = "1.3.6.1.2.1.31.1.1.1.6"       # octet, 64-bit
IF_HC_OUT = "1.3.6.1.2.1.31.1.1.1.10"
IF_IN_ERR = "1.3.6.1.2.1.2.2.1.14"
IF_OUT_ERR = "1.3.6.1.2.1.2.2.1.20"
IF_IN_DISC = "1.3.6.1.2.1.2.2.1.13"
IF_OUT_DISC = "1.3.6.1.2.1.2.2.1.19"
IF_HIGH_SPEED = "1.3.6.1.2.1.31.1.1.1.15"  # Mbit/s
HR_PROCESSOR_LOAD = "1.3.6.1.2.1.25.3.3.1.2"
HR_STORAGE_DESCR = "1.3.6.1.2.1.25.2.3.1.3"
HR_STORAGE_UNITS = "1.3.6.1.2.1.25.2.3.1.4"
HR_STORAGE_SIZE = "1.3.6.1.2.1.25.2.3.1.5"
HR_STORAGE_USED = "1.3.6.1.2.1.25.2.3.1.6"
# MIKROTIK-MIB (mtxrHealth): không phải mọi bo mạch đều có; thiếu thì bỏ qua.
MTXR_VOLTAGE = "1.3.6.1.4.1.14988.1.1.3.8.0"       # 0,1 V
MTXR_TEMPERATURE = "1.3.6.1.4.1.14988.1.1.3.10.0"  # 0,1 °C

IF_TYPE_BRIDGE = 209
IF_TYPE_PPP = 23
IF_TYPE_LOOPBACK = 24
LOAI_GIAO_DIEN = {6: "ether", 209: "bridge", 23: "ppp", 24: "loopback", 53: "virtual", 131: "tunnel", 135: "vlan", 136: "vlan"}

_BO_KY_TU_DIEU_KHIEN = re.compile(r"[\x00-\x1f\x7f]")
_KHONG_PHAI_SLUG = re.compile(r"[^a-z0-9]+")
HAI_MU_64 = 2 ** 64


def lam_sach(chuoi: Any, toi_da: int = 64) -> str:
    """Chuỗi từ router: bỏ ký tự điều khiển, cắt độ dài."""
    return _BO_KY_TU_DIEU_KHIEN.sub("", str(chuoi if chuoi is not None else "")).strip()[:toi_da]


def slug(chuoi: Any) -> str:
    """Tên → mã dùng trong entity_id (chữ thường, số, gạch dưới). Rỗng thì «x»."""
    return _KHONG_PHAI_SLUG.sub("_", lam_sach(chuoi).lower()).strip("_") or "x"


def hau_to(oid: str, goc: str) -> str | None:
    """Phần đuôi của oid sau tiền tố `goc` (ví dụ chỉ số giao diện); không thuộc `goc` thì None."""
    tien_to = goc + "."
    return oid[len(tien_to):] if oid.startswith(tien_to) else None


def tinh_toc_do_mbit(truoc: tuple[float, int] | None, nay: tuple[float, int]) -> float | None:
    """Tốc độ Mbit/s từ hai lần đọc bộ đếm octet 64-bit: (thời điểm giây, giá trị).

    - Lần đầu (chưa có `truoc`) hoặc khoảng thời gian không dương → None (không bịa số).
    - Bộ đếm tăng bình thường → (hiệu × 8) / thời gian.
    - Bộ đếm GIẢM: nếu lần trước ở sát đỉnh 64-bit thì là tràn thật → tính vòng; còn lại coi là router khởi động lại → None.
    """
    if truoc is None:
        return None
    t0, v0 = truoc
    t1, v1 = nay
    dt = t1 - t0
    if dt <= 0:
        return None
    if v1 >= v0:
        delta = v1 - v0
    elif v0 > HAI_MU_64 * 3 // 4:
        delta = (HAI_MU_64 - v0) + v1
    else:
        return None
    return round(delta * 8 / dt / 1_000_000, 3)


def phan_tich_giao_dien(ten: dict[str, Any], loai: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """Bảng giao diện từ hai lần duyệt: {oid ifName: tên}, {oid ifType: số}. Trả {ifIndex: {name, kind, if_type, slug}}.
    Bỏ giao diện loopback. Hai giao diện trùng tên rút gọn thì thêm đuôi chỉ số để không trùng entity_id."""
    ra: dict[int, dict[str, Any]] = {}
    da_dung: dict[str, int] = {}
    for oid, gia_tri in ten.items():
        chi_so = hau_to(oid, IF_NAME)
        if chi_so is None or not chi_so.isdigit():
            continue
        loai_so = _so(loai.get(f"{IF_TYPE}.{chi_so}"))
        if loai_so == IF_TYPE_LOOPBACK:
            continue
        ten_cong = lam_sach(gia_tri) or f"if{chi_so}"
        ma = slug(ten_cong)
        if ma in da_dung:
            ma = f"{ma}_{chi_so}"
        da_dung[ma] = int(chi_so)
        if loai_so == IF_TYPE_BRIDGE:
            kind = "bridge"
        elif loai_so == IF_TYPE_PPP:
            kind = "ppp"
        else:
            kind = "port"
        ra[int(chi_so)] = {"name": ten_cong, "kind": kind, "if_type": LOAI_GIAO_DIEN.get(loai_so or 0, "other"), "slug": ma}
    return ra


def _so(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def chia_nhom(oid_list: list[str], toi_da: int) -> list[list[str]]:
    return [oid_list[i:i + toi_da] for i in range(0, len(oid_list), toi_da)]


def cpu_trung_binh(gia_tri: dict[str, Any]) -> float | None:
    """Tải CPU trung bình (%) từ hrProcessorLoad của mọi nhân."""
    so = [n for n in (_so(v) for v in gia_tri.values()) if n is not None and 0 <= n <= 100]
    return round(sum(so) / len(so), 1) if so else None


def bo_nho_phan_tram(mo_ta: dict[str, Any], don_vi: dict[str, Any], kich_thuoc: dict[str, Any], da_dung: dict[str, Any]) -> float | None:
    """% RAM đã dùng: dòng hrStorage có mô tả chứa «main memory» (RouterOS) hoặc «ram»; không có thì None."""
    for oid, mo in mo_ta.items():
        chi_so = hau_to(oid, HR_STORAGE_DESCR)
        nhan = lam_sach(mo).lower()
        if chi_so is None or not ("main memory" in nhan or nhan in ("ram", "physical memory")):
            continue
        tong = _so(kich_thuoc.get(f"{HR_STORAGE_SIZE}.{chi_so}"))
        dung = _so(da_dung.get(f"{HR_STORAGE_USED}.{chi_so}"))
        if tong and dung is not None and tong > 0:
            return round(100 * dung / tong, 1)
    return None


def thoi_gian_chay(centi_giay: Any) -> str | None:
    """sysUpTime (1/100 giây) → «5d 03:12:05»."""
    n = _so(centi_giay)
    if n is None or n < 0:
        return None
    giay = n // 100
    ngay, du = divmod(giay, 86400)
    gio, du = divmod(du, 3600)
    phut, giay = divmod(du, 60)
    return f"{ngay}d {gio:02d}:{phut:02d}:{giay:02d}"


def tim_chi_so_ram(mo_ta: dict[str, Any]) -> str | None:
    """Chỉ số dòng hrStorage là RAM chính («main memory»/«ram»); không thấy thì None."""
    for oid, mo in mo_ta.items():
        chi_so = hau_to(oid, HR_STORAGE_DESCR)
        nhan = lam_sach(mo).lower()
        if chi_so is not None and ("main memory" in nhan or nhan in ("ram", "physical memory")):
            return chi_so
    return None


def phan_tram(dung: Any, tong: Any) -> float | None:
    d, t = _so(dung), _so(tong)
    return round(100 * d / t, 1) if d is not None and t and t > 0 else None
