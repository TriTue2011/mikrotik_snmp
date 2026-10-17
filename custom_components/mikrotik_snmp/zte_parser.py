"""Đổi JSON trang quản trị ZTE E2633 (GetALLClients, GetALLAP) thành dữ liệu thiết bị. Không gọi mạng.

Khuôn đã đo từ trang của thiết bị: mỗi máy có MacAddr, IpAddr, HostName, Rssi (dBm), AccessType («1» = 2.4 GHz,
«2» = 5 GHz), WirelessMode, AssocTime (giây), TxRateBps, RxRateBps.
"""
from __future__ import annotations

import re
from typing import Any

BAND = {"1": "2.4G", "2": "5G"}

#: Trường gốc của bộ phát đã được đổi sang tên chuẩn hoá (khoá chuẩn → tên gốc). Mọi trường gốc KHÁC đều được giữ nguyên
#: tên trong «thuoc_tinh_goc» để hiển thị hết, không cần liệt kê thêm khi bộ phát có thêm trường.
TEN_GOC_MAY = {"mac": "MacAddr", "ip": "IpAddr", "name": "HostName", "band": "AccessType", "rssi": "Rssi",
               "mode": "WirelessMode", "assoc_s": "AssocTime", "rx_bps": "RxRateBps", "tx_bps": "TxRateBps",
               "rx_mbps": "RxRateMbps", "tx_mbps": "TxRateMbps"}
TEN_GOC_AP = {"mac": "MacAddr", "ip": "IpAddr", "name": "DeviceName", "firmware": "SoftwareVer",
              "link_speed": "LinkSpeed", "role": "role", "backhaul_rssi": "BhStaRssi"}


def thuoc_tinh_goc(muc: dict, da_dung: dict[str, str]) -> dict[str, str]:
    """Mọi trường gốc (giá trị đơn giản) mà bảng chuẩn hoá chưa dùng, giữ nguyên tên gốc, giá trị cắt gọn."""
    dung = set(da_dung.values())
    return {str(k): str(v).strip()[:64] for k, v in muc.items()
            if k not in dung and not isinstance(v, (dict, list)) and v not in (None, "")}
MAC_RE = re.compile(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")


def _so_nguyen(v: Any, mac_dinh: int | None = None) -> int | None:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return mac_dinh


def _muc(du_lieu: Any) -> list[dict]:
    """Các mục «1», «2», … của một khối, theo thứ tự số. Bỏ khoá khác (ví dụ MGET_INST_NUM) và mục không phải đối tượng."""
    if not isinstance(du_lieu, dict):
        return []
    ra = [(int(k), v) for k, v in du_lieu.items() if str(k).isdigit() and isinstance(v, dict)]
    return [v for _, v in sorted(ra, key=lambda kv: kv[0])]


def phan_tich_thiet_bi(du_lieu: Any) -> list[dict]:
    """JSON GetALLClients → danh sách {mac, ip, name, band, rssi, mode, assoc_s, rx_bps, tx_bps}. Mục có MAC sai khuôn bị bỏ."""
    goc = du_lieu.get("clientsData") if isinstance(du_lieu, dict) else None
    ra: list[dict] = []
    for m in _muc(goc):
        mac = str(m.get("MacAddr", "")).strip().lower()
        if not MAC_RE.match(mac):
            continue
        ra.append({
            "mac": mac,
            "ip": str(m.get("IpAddr", ""))[:45],
            "name": str(m.get("HostName", ""))[:64],
            "band": BAND.get(str(m.get("AccessType", "")).strip(), ""),
            "rssi": _so_nguyen(m.get("Rssi")),
            "mode": str(m.get("WirelessMode", ""))[:16],
            "assoc_s": _so_nguyen(m.get("AssocTime")),
            "rx_bps": _so_nguyen(m.get("RxRateBps"), 0),
            "tx_bps": _so_nguyen(m.get("TxRateBps"), 0),
            "rx_mbps": _so_nguyen(m.get("RxRateMbps")),
            "tx_mbps": _so_nguyen(m.get("TxRateMbps")),
            "goc": thuoc_tinh_goc(m, TEN_GOC_MAY),
        })
    return ra


def phan_tich_ap(du_lieu: Any) -> dict:
    """JSON GetALLAP → thông tin bộ phát (mục đầu tiên), hoặc {} nếu không có."""
    goc = du_lieu.get("apData") if isinstance(du_lieu, dict) else None
    ds = _muc(goc)
    if not ds:
        return {}
    a = ds[0]
    mac = str(a.get("MacAddr", "")).strip().lower()
    return {
        "mac": mac if MAC_RE.match(mac) else "",
        "ip": str(a.get("IpAddr", ""))[:45],
        "name": str(a.get("DeviceName", ""))[:64],
        "firmware": str(a.get("SoftwareVer", ""))[:32],
        "link_speed": _so_nguyen(a.get("LinkSpeed")),
        "role": str(a.get("role", ""))[:16],
        "backhaul_rssi": _so_nguyen(a.get("BhStaRssi")),
        "goc": thuoc_tinh_goc(a, TEN_GOC_AP),
    }


def dem_theo_bang(clients: list[dict], bang: str) -> int:
    """Số máy đang kết nối ở một băng tần («2.4G» hoặc «5G»)."""
    return sum(1 for m in clients if m.get("band") == bang)
