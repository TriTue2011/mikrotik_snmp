"""Máy khách API RouterOS CHỈ ĐỌC (tuỳ chọn): tên máy từ DHCP và bộ đếm byte từng thiết bị từ Kid Control.

Chỉ-đọc THEO CẤU TẠO: `goi_doc` chỉ nhận lệnh kết thúc bằng «/print» và từ chối mọi lệnh khác (set, add, reboot, make-static…).
Chỉ nối qua TLS và GHIM vân tay SHA-256 của chứng chỉ router (sai vân tay thì từ chối, không đăng nhập). Mật khẩu không vào thông báo lỗi.
Giao thức câu-từ của RouterOS tự viết bằng thư viện chuẩn, không thêm gói.
"""
from __future__ import annotations

import hashlib
import re
import socket
import ssl
from typing import Any

HET_GIO = 8.0
_PROPLIST_LEASE = "mac-address,host-name,comment,address"
_PROPLIST_WG = "name,interface,comment,allowed-address,current-endpoint-address,rx,tx,last-handshake,disabled"
_PROPLIST_KID = "mac-address,ip-address,bytes-down,bytes-up,rate-down,rate-up"


class ApiLoi(Exception):
    """Lỗi chung."""


class ApiLoiKetNoi(ApiLoi):
    """Không tới được cổng API."""


class ApiLoiDangNhap(ApiLoi):
    """Sai người dùng hoặc mật khẩu."""


class ApiLoiVanTay(ApiLoi):
    """Chứng chỉ của router không khớp vân tay đã ghim."""


def _ma_do_dai(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    if n < 0x4000:
        return (n | 0x8000).to_bytes(2, "big")
    if n < 0x200000:
        return (n | 0xC00000).to_bytes(3, "big")
    if n < 0x10000000:
        return (n | 0xE0000000).to_bytes(4, "big")
    return b"\xf0" + n.to_bytes(4, "big")


def van_tay_cua(der: bytes) -> str:
    return hashlib.sha256(der).hexdigest()


def van_tay_khop(da_ghim: str, hien_tai: str) -> bool:
    return bool(da_ghim) and bool(hien_tai) and da_ghim.strip().lower() == hien_tai.strip().lower()


def lay_van_tay(host: str, port: int, het_gio: float = HET_GIO) -> str:
    """Vân tay SHA-256 chứng chỉ hiện tại của cổng API-SSL (dùng lúc cấu hình để ghim)."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with socket.create_connection((host, port), timeout=het_gio) as s, ctx.wrap_socket(s) as t:
            return van_tay_cua(t.getpeercert(binary_form=True) or b"")
    except OSError as e:
        raise ApiLoiKetNoi(f"không tới được {host}:{port}") from e


class Phien:
    def __init__(self, sock: Any):
        self._s = sock

    def _doc(self, n: int) -> bytes:
        b = b""
        while len(b) < n:
            c = self._s.recv(n - len(b))
            if not c:
                raise ApiLoi("router đóng kết nối giữa chừng")
            b += c
        return b

    def _do_dai(self) -> int:
        c = self._doc(1)[0]
        if c < 0x80:
            return c
        if c < 0xC0:
            return ((c & 0x3F) << 8) | self._doc(1)[0]
        if c < 0xE0:
            return ((c & 0x1F) << 16) | int.from_bytes(self._doc(2), "big")
        if c < 0xF0:
            return ((c & 0x0F) << 24) | int.from_bytes(self._doc(3), "big")
        return int.from_bytes(self._doc(4), "big")

    def _cau(self) -> list[str]:
        tu: list[str] = []
        while (n := self._do_dai()) != 0:
            tu.append(self._doc(n).decode("utf-8", errors="replace"))
        return tu

    def _gui_va_nhan(self, tu: list[str]) -> list[dict[str, str]]:
        for w in tu:
            b = w.encode("utf-8")
            self._s.sendall(_ma_do_dai(len(b)) + b)
        self._s.sendall(b"\x00")
        ra: list[dict[str, str]] = []
        while True:
            cau = self._cau()
            if not cau:
                continue
            d: dict[str, str] = {}
            for w in cau[1:]:
                k, _, v = w[1:].partition("=")
                d[k] = v
            if cau[0] == "!re":
                ra.append(d)
            elif cau[0] == "!done":
                return ra
            elif cau[0] in ("!trap", "!fatal"):
                if cau[0] == "!trap":
                    while (c := self._cau()) and c[0] != "!done":
                        pass
                raise ApiLoi(f"router từ chối lệnh: {str(d.get('message') or '')[:80]}")

    def dang_nhap(self, ten: str, mat_khau: str) -> None:
        try:
            self._gui_va_nhan(["/login", f"=name={ten}", f"=password={mat_khau}"])
        except ApiLoi as e:
            raise ApiLoiDangNhap("router từ chối đăng nhập (kiểm tên và mật khẩu)") from e   # không kèm mật khẩu hay lời router

    def goi_doc(self, lenh: str, proplist: str = "") -> list[dict[str, str]]:
        """CHỈ lệnh «…/print» (đọc). Lệnh khác bị từ chối TRƯỚC khi gửi."""
        if not lenh.startswith("/") or not lenh.endswith("/print") or any(c in lenh for c in " ;=\n\r\x00"):
            raise ApiLoi("chỉ cho phép lệnh đọc (…/print)")
        tu = [lenh] + ([f"=.proplist={proplist}"] if proplist else [])
        return self._gui_va_nhan(tu)

    def dong(self) -> None:
        try:
            self._s.close()
        except OSError:
            pass


def mo_phien(host: str, port: int, ten: str, mat_khau: str, van_tay: str, het_gio: float = HET_GIO) -> Phien:
    """Nối TLS (kiểm vân tay đã ghim) rồi đăng nhập. Sai vân tay → ApiLoiVanTay, KHÔNG gửi mật khẩu."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        s = socket.create_connection((host, port), timeout=het_gio)
        t = ctx.wrap_socket(s)
    except OSError as e:
        raise ApiLoiKetNoi(f"không tới được {host}:{port}") from e
    if not van_tay_khop(van_tay, van_tay_cua(t.getpeercert(binary_form=True) or b"")):
        try:
            t.close()
        except OSError:
            pass
        raise ApiLoiVanTay("chứng chỉ của router khác vân tay đã ghim (đổi chứng chỉ? cấu hình lại để ghim vân tay mới)")
    p = Phien(t)
    try:
        p.dang_nhap(ten, mat_khau)
    except Exception:
        p.dong()
        raise
    return p


def _so(v: Any) -> int | None:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


_BPS = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*([kKmMgG]?)\s*(?:bps|b/s)?\s*$")
_HE_SO = {"": 1, "k": 1e3, "m": 1e6, "g": 1e9}


def _bps(v: Any) -> int | None:
    """Tốc độ bit/giây từ số thô («19600») hoặc chuỗi có đơn vị («19.6kbps», «1.2 Mbps»); lạ thì None."""
    m = _BPS.match(str(v if v is not None else ""))
    return round(float(m.group(1)) * _HE_SO[m.group(2).lower()]) if m else None


def ten_tu_dhcp(p: Phien) -> dict[str, dict[str, str]]:
    """{MAC HOA: {comment, host_name}} từ danh sách DHCP lease. Lease không có MAC bị bỏ; chuỗi cắt độ dài."""
    ra: dict[str, dict[str, str]] = {}
    for ls in p.goi_doc("/ip/dhcp-server/lease/print", _PROPLIST_LEASE):
        mac = str(ls.get("mac-address", "")).strip().upper()
        if len(mac) == 17:
            ra[mac] = {"comment": str(ls.get("comment", "")).strip()[:40], "host_name": str(ls.get("host-name", "")).strip()[:40]}
    return ra


def kid_control(p: Phien) -> dict[str, dict[str, int | None]]:
    """{MAC HOA: {bytes_down, bytes_up, rate_down, rate_up}} từ Kid Control. «down» = tải về thiết bị (rx của thiết bị)."""
    ra: dict[str, dict[str, int | None]] = {}
    for d in p.goi_doc("/ip/kid-control/device/print", _PROPLIST_KID):
        mac = str(d.get("mac-address", "")).strip().upper()
        if len(mac) == 17:
            ra[mac] = {"bytes_down": _so(d.get("bytes-down")), "bytes_up": _so(d.get("bytes-up")),
                       "rate_down": _bps(d.get("rate-down")), "rate_up": _bps(d.get("rate-up"))}
    return ra


_THOI_GIAN = re.compile(r"(\d+)\s*([wdhms])")
_HE_GIAY = {"w": 604800, "d": 86400, "h": 3600, "m": 60, "s": 1}


def thoi_gian_giay(v: Any) -> int | None:
    """«1m33s», «00:01:33», «2h5m», «1w2d» → giây; rỗng, «never» hay lạ → None."""
    chu = str(v if v is not None else "").strip().lower()
    if not chu or chu == "never":
        return None
    m = re.fullmatch(r"(\d+):(\d{2}):(\d{2})", chu)
    if m:
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
    phan = _THOI_GIAN.findall(chu)
    if not phan or "".join(f"{n}{u}" for n, u in phan) != chu.replace(" ", ""):
        return None
    return sum(int(n) * _HE_GIAY[u] for n, u in phan)


def wireguard_peers(p: Phien) -> list[dict[str, Any]]:
    """Các peer WireGuard: tên, giao diện, ghi chú, địa chỉ cho phép, địa chỉ đầu bên kia, byte nhận/gửi, lần bắt tay gần nhất (giây trước)."""
    ra: list[dict[str, Any]] = []
    for d in p.goi_doc("/interface/wireguard/peers/print", _PROPLIST_WG):
        ten = str(d.get("name", "")).strip()[:40]
        if not ten:
            continue
        ra.append({
            "name": ten, "interface": str(d.get("interface", "")).strip()[:40], "comment": str(d.get("comment", "")).strip()[:40],
            "allowed_address": str(d.get("allowed-address", "")).strip()[:80], "endpoint": str(d.get("current-endpoint-address", "")).strip()[:64],
            "rx_bytes": _so(d.get("rx")), "tx_bytes": _so(d.get("tx")), "last_handshake_s": thoi_gian_giay(d.get("last-handshake")),
            "disabled": str(d.get("disabled", "")).strip().lower() in ("true", "yes"),
        })
    return ra
