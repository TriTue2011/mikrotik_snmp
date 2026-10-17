"""Gộp dữ liệu MikroTik (cổng, ARP, bảng MAC của bridge) với ZTE (máy WiFi) thành CÂY: Router → Cổng → ZTE → Thiết bị.

Logic thuần, không phụ thuộc Home Assistant. Quy tắc:
- MAC có trong danh sách máy WiFi của ZTE → là con của nút «zte», mang thêm tên máy, băng tần, tín hiệu, chế độ, thời gian kết nối.
- MAC còn lại → là con của cổng nó được học trên bảng MAC; không biết cổng thì là con của router.
- Nút ZTE là con của cổng mà ZTE cắm vào (suy từ IP của ZTE → MAC trong ARP → cổng trong bảng MAC); không suy được thì con của router.
- ZTE không tự là «máy» của chính nó.
Dữ liệu từ router/ZTE là không tin được: đã được làm sạch ở lớp đọc (chuỗi cắt độ dài).
"""
from __future__ import annotations

from typing import Any

ROUTER = "router"
ZTE = "zte"


def _hoa(mac: Any) -> str:
    return str(mac or "").strip().upper().replace("-", ":")


def _cong_cua(bang_mac: dict[str, list[str]]) -> dict[str, str]:
    ra: dict[str, str] = {}
    for cong, ds in bang_mac.items():
        for mac in ds:
            ra.setdefault(_hoa(mac), cong)
    return ra


def _khoa_ip(ip: str):
    try:
        return tuple(int(x) for x in ip.split("."))
    except ValueError:
        return (999,)


def xay_cay(giao_dien: dict[int, dict[str, Any]], bang_mac: dict[str, list[str]], arp: dict[str, str],
            zte: dict[str, Any] | None, ten_router: str, ten_may: dict[str, str] | None = None) -> dict[str, Any]:
    cong_cua = _cong_cua(bang_mac)
    ten_may = {_hoa(m): t for m, t in (ten_may or {}).items()}
    arp = {_hoa(m): ip for m, ip in arp.items()}
    tim_mac_theo_ip = {ip: mac for mac, ip in arp.items()}

    nodes: list[dict[str, Any]] = [{"id": ROUTER, "kind": "router", "name": ten_router, "parent": None}]
    ten_cong = set()
    for chi_so in sorted(giao_dien):
        gd = giao_dien[chi_so]
        ten_cong.add(gd["name"])
        nodes.append({"id": gd["name"], "kind": gd.get("kind", "port"), "name": gd["name"], "parent": ROUTER, "up": gd.get("up")})

    zte_macs: set[str] = set()
    zte_clients: dict[str, dict[str, Any]] = {}
    zte_ip = ""
    if zte:
        ap = zte.get("ap") or {}
        zte_ip = str(zte.get("host") or ap.get("ip") or "")
        # Cổng mà ZTE cắm vào: IP → MAC (ARP) → cổng (bảng MAC); thử cả MAC báo bởi chính ZTE.
        mac_zte = tim_mac_theo_ip.get(zte_ip, "")
        cha = cong_cua.get(mac_zte) or cong_cua.get(_hoa(ap.get("mac"))) or ROUTER
        zte_macs = {m for m in (mac_zte, _hoa(ap.get("mac"))) if m}
        nodes.append({"id": ZTE, "kind": "ap", "name": ap.get("name") or "ZTE E2633", "parent": cha,
                      "ip": zte_ip, "mac": mac_zte or _hoa(ap.get("mac")), "firmware": ap.get("firmware") or "",
                      "trang_thai": zte.get("trang_thai", "")})
        for c in zte.get("clients") or []:
            mac = _hoa(c.get("mac"))
            if mac:
                zte_clients[mac] = c

    cac_mac = set(arp) | set(cong_cua) | set(zte_clients)
    clients: list[dict[str, Any]] = []
    for mac in cac_mac:
        if mac in zte_macs or (zte_ip and arp.get(mac) == zte_ip):
            continue
        w = zte_clients.get(mac)
        ip = arp.get(mac) or (w or {}).get("ip") or ""
        cong = cong_cua.get(mac, "")
        clients.append({
            "mac": mac, "ip": ip, "interface": cong,
            "parent": ZTE if w else (cong if cong in ten_cong else ROUTER),
            "wifi": bool(w), "source": "zte" if w else "mik",
            "name": ten_may.get(mac) or (w or {}).get("name") or "",
            "band": (w or {}).get("band"), "rssi": (w or {}).get("rssi"),
            "mode": (w or {}).get("mode"), "assoc_s": (w or {}).get("assoc_s"),
        })
    thu_tu_cha = {n["id"]: i for i, n in enumerate(nodes)}
    clients.sort(key=lambda c: (thu_tu_cha.get(c["parent"], 999), _khoa_ip(c["ip"]) if c["ip"] else (999,), c["mac"]))
    return {"nodes": nodes, "clients": clients}
