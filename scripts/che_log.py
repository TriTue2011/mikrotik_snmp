#!/usr/bin/env python3
"""Che thông tin riêng trong log Home Assistant trước khi dán vào issue. Chỉ dùng thư viện chuẩn.

Dùng:
    python3 scripts/che_log.py home-assistant.log > log_da_che.txt
    grep mikrotik_snmp home-assistant.log | python3 scripts/che_log.py > log_da_che.txt

Che những gì:
  - địa chỉ MAC, IPv4, IPv6  → thay bằng nhãn cố định trong cả tệp (MAC-1, IP-1, …): vẫn thấy «cùng một máy» mà không lộ máy nào
  - mật khẩu, token, cookie phiên, header Check, giá trị băm 64 ký tự hex → «***»
  - tên máy (HostName / DeviceName) → «TEN-n»; tên miền của bộ phát (trong URL hoặc trường host) → «HOST-n»; user:pass trong URL → «***»
Che theo CẤU TRÚC (khuôn MAC/IP, tên trường nhạy cảm), không dựa danh sách từ khoá của từng nhà cung cấp. Vẫn nên đọc lại kết quả
trước khi đăng: không công cụ nào đảm bảo che hết mọi thứ (ví dụ tên người nằm trong câu chữ tự do).
"""
from __future__ import annotations

import re
import sys

# Giá trị đi sau tên trường: có nháy thì lấy đến nháy đóng đúng cặp (kể cả khoảng trắng, dấu phẩy, nháy khác loại, \\" thoát);
# không nháy thì lấy đến khoảng trắng hoặc dấu & (hoặc đóng ngoặc).
_GIA_TRI_SECRET = r"""(?:(?P<q>["'])(?:\\.|(?!(?P=q))[^\\\r\n])*(?P=q)?|(?:(?:bearer|basic)\s+)?[^\s&"'}\]]+(?:;\s*[^\s&"'}\]]+)*)"""

# Tên trường mà giá trị đi sau nó phải bị che hoàn toàn. Khớp dạng `tên=giá_trị`, `tên: giá_trị`, `"tên": "giá_trị"`, và header.
_TRUONG_BI_MAT = r"(?:pass(?:word)?|mat[_ ]?khau|token|_?sessiontoken|frm_logintoken|cookie|set-cookie|sid|session(?:id)?|check|authorization|secret|api[_-]?key)"
_BI_MAT_RE = re.compile(rf"""(?P<dau>["']?\b{_TRUONG_BI_MAT}["']?\s*[:=]\s*)(?P<gia_tri>{_GIA_TRI_SECRET})""", re.IGNORECASE)
_COOKIE_RE = re.compile(r"(?P<dau>\b(?:set-)?cookie\s*[:=]\s*)(?P<gia_tri>[^\r\n]+)", re.IGNORECASE)
# Tên máy: có nháy thì đến nháy đóng; không nháy thì đến chỗ bắt đầu một «tên=»/«tên:» khác, dấu phân cách hoặc hết dòng.
_TEN_MAY_RE = re.compile(
    r"""(?P<dau>["']?\b(?:HostName|DeviceName)["']?\s*[:=]\s*)"""
    r"""(?:(?P<q>["'])(?:\\.|(?!(?P=q))[^\\\r\n])*(?P=q)?|(?P<bare>[^\r\n"',}&]+?)(?=\s+\w+\s*[=:]|[,}&"'\r\n]|$))""",
    re.IGNORECASE,
)
# URL: che user:pass@ và tên miền (địa chỉ IP để quy tắc IP xử lý).
_URL_RE = re.compile(r"""(?P<scheme>\b[A-Za-z][A-Za-z0-9+.-]*://)(?:(?P<userinfo>[^/\s@'"<>]+)@)?(?P<host>\[[0-9A-Fa-f:.]+\]|[^/\s:?#'"<>@]+)""")
_HOST_KEY_RE = re.compile(r"""(?P<dau>["']?\bhost["']?\s*[:=]\s*["']?)(?P<gia_tri>[^\s"',}&]+)""", re.IGNORECASE)
_LA_IP_RE = re.compile(r"^(?:\d{1,3}(?:\.\d{1,3}){3}|\[.*\]|[0-9A-Fa-f:]+)$")
# Số phiên bản bốn nhóm (1.2.3.4) đứng sau từ khoá này không phải IP.
_SAU_TU_KHOA_PHIEN_BAN = re.compile(r"(?:version|ver|firmware|fw|phiên bản|build|\bv)\s*[:=]?\s*$", re.IGNORECASE)
_MAC_RE = re.compile(r"(?<![0-9A-Fa-f:-])[0-9A-Fa-f]{2}(?:[:-][0-9A-Fa-f]{2}){5}(?![0-9A-Fa-f:-])")
_IPV4_RE = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
# IPv6 thật có đủ 8 nhóm hoặc có «::»; chuỗi như 12:34:56 (giờ) không khớp.
_H = r"[0-9A-Fa-f]{1,4}"
_IPV6_RE = re.compile(
    rf"(?<![0-9A-Fa-f:])(?:(?:{_H}:){{7}}{_H}|(?:{_H}:){{0,7}}{_H}?::(?:{_H}(?::{_H}){{0,6}})?)(?![0-9A-Fa-f:])"
)
_BAM_RE = re.compile(r"\b[0-9A-Fa-f]{64}\b")


def _che_gia_tri(m: re.Match) -> str:
    """Giữ phần tên trường (và cặp nháy nếu có), thay giá trị bằng ***."""
    q = m.groupdict().get("q")
    return m["dau"] + (f"{q}***{q}" if q else "***")


class Che:
    """Che một dòng một; giữ bảng nhãn để cùng một MAC/IP luôn ra cùng một nhãn trong cả tệp."""

    def __init__(self) -> None:
        self._nhan: dict[tuple[str, str], str] = {}

    def _gan(self, loai: str, goc: str) -> str:
        khoa = (loai, goc.lower())
        if khoa not in self._nhan:
            self._nhan[khoa] = f"{loai}-{sum(1 for k in self._nhan if k[0] == loai) + 1}"
        return self._nhan[khoa]

    def _ip4(self, m: re.Match) -> str:
        if not all(int(p) <= 255 for p in m.group(0).split(".")):
            return m.group(0)
        if _SAU_TU_KHOA_PHIEN_BAN.search(m.string[max(0, m.start() - 16):m.start()]):
            return m.group(0)
        return self._gan("IP", m.group(0))

    def _url(self, m: re.Match) -> str:
        host = m["host"] if _LA_IP_RE.match(m["host"]) else self._gan("HOST", m["host"])
        return m["scheme"] + ("***@" if m["userinfo"] else "") + host

    def dong(self, dong: str) -> str:
        # Bí mật trước hết, để MAC/IP bên trong giá trị cookie… không bị đổi nhãn rồi lọt qua.
        dong = _URL_RE.sub(self._url, dong)
        dong = _COOKIE_RE.sub(lambda m: m["dau"] + "***", dong)
        dong = _BI_MAT_RE.sub(_che_gia_tri, dong)
        dong = _BAM_RE.sub("***", dong)
        dong = _HOST_KEY_RE.sub(lambda m: m["dau"] + (m["gia_tri"] if _LA_IP_RE.match(m["gia_tri"]) else self._gan("HOST", m["gia_tri"])), dong)
        dong = _TEN_MAY_RE.sub(lambda m: m["dau"] + (f"{m['q']}{self._gan('TEN', m.group(0)[len(m['dau']):].strip(chr(34) + chr(39)))}{m['q']}" if m["q"] else self._gan("TEN", m["bare"].strip())), dong)
        dong = _MAC_RE.sub(lambda m: self._gan("MAC", m.group(0).replace("-", ":")), dong)
        dong = _IPV6_RE.sub(lambda m: self._gan("IP", m.group(0)), dong)
        dong = _IPV4_RE.sub(self._ip4, dong)
        return dong

    def van_ban(self, van_ban: str) -> str:
        return "".join(self.dong(d) for d in van_ban.splitlines(keepends=True))


def main(argv: list[str]) -> int:
    che = Che()
    if len(argv) > 2 or (len(argv) == 2 and argv[1] in ("-h", "--help")):
        print(__doc__, file=sys.stderr)
        return 2
    nguon = open(argv[1], encoding="utf-8", errors="replace") if len(argv) == 2 else sys.stdin
    with nguon:
        for dong in nguon:
            sys.stdout.write(che.dong(dong))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
