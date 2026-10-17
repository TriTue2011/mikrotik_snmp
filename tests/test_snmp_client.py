"""Test máy khách SNMP bằng một `pysnmp` GIẢ trả tên OID dạng CHỮ như bản thật («SNMPv2-SMI::mib-2.31.1.1.1.6.3»).

Lỗi đã gặp trên Home Assistant thật: khoá lấy bằng prettyPrint() nên không khớp OID dạng số → danh sách cổng rỗng.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if "mikrotik_snmp" not in sys.modules:
    goi = types.ModuleType("mikrotik_snmp")
    goi.__path__ = [str(ROOT / "custom_components" / "mikrotik_snmp")]
    sys.modules["mikrotik_snmp"] = goi

TIEN_TO_MIB2 = "1.3.6.1.2.1."


class FakeOid:
    def __init__(self, so):
        self._so = so

    def __str__(self):
        return self._so

    def prettyPrint(self):
        return self._so


class TenCu:
    """Tên OID kiểu bản cũ: chỉ có getOid() camelCase."""

    def __init__(self, so):
        self._so = so

    def prettyPrint(self):
        return "SNMPv2-SMI::mib-2." + self._so[len(TIEN_TO_MIB2):]

    def getOid(self):
        return FakeOid(self._so)


class TenMoi(TenCu):
    def get_oid(self):
        return FakeOid(self._so)


class TenChiChu:
    """Không có get_oid/getOid: chỉ còn đường dự phòng tách từ chữ."""

    def __init__(self, so):
        self._so = so

    def prettyPrint(self):
        return "SNMPv2-SMI::mib-2." + self._so[len(TIEN_TO_MIB2):]


class GiaTri:
    def __init__(self, v, octet=False):
        self.v, self.octet = v, octet

    def __int__(self):
        if isinstance(self.v, int):
            return self.v
        raise ValueError

    def prettyPrint(self):
        return str(self.v)

    def asOctets(self):
        return bytes.fromhex(self.v) if self.octet else str(self.v).encode()


class Hass:
    async def async_add_executor_job(self, f, *a):
        return f(*a)


def cai_pysnmp_gia(db, lop_ten):
    mod = types.ModuleType("pysnmp.hlapi.v3arch.asyncio")
    mod.SnmpEngine = lambda: types.SimpleNamespace(close_dispatcher=lambda: None)
    mod.UsmUserData = lambda *a, **k: ("usm", a, k)
    mod.ContextData = lambda: None

    class Dich:
        @staticmethod
        async def create(diachi, timeout=None, retries=None):
            return ("dich", diachi)
    mod.UdpTransportTarget = Dich
    mod.ObjectIdentity = lambda oid: oid
    mod.ObjectType = lambda ten: ten
    for ten in ("usmHMACMD5AuthProtocol", "usmHMACSHAAuthProtocol", "usmHMAC128SHA224AuthProtocol", "usmHMAC192SHA256AuthProtocol",
                "usmHMAC256SHA384AuthProtocol", "usmHMAC384SHA512AuthProtocol", "usmDESPrivProtocol", "usm3DESEDEPrivProtocol",
                "usmAesCfb128Protocol", "usmAesCfb192Protocol", "usmAesCfb256Protocol"):
        setattr(mod, ten, ten)

    def so_sanh(oid):
        return tuple(int(x) for x in oid.split("."))

    async def get_cmd(eng, du, tg, ctx, *oids):
        return None, 0, 0, [(lop_ten(o), db[o]) for o in oids if o in db]

    async def next_cmd(eng, du, tg, ctx, oid):
        sau = sorted((o for o in db if so_sanh(o) > so_sanh(oid)), key=so_sanh)
        return None, 0, 0, ([(lop_ten(sau[0]), db[sau[0]])] if sau else [])

    mod.get_cmd, mod.next_cmd = get_cmd, next_cmd
    for ten in ("pysnmp", "pysnmp.hlapi", "pysnmp.hlapi.v3arch"):
        sys.modules.setdefault(ten, types.ModuleType(ten))
    sys.modules["pysnmp.hlapi.v3arch"].asyncio = mod
    sys.modules["pysnmp.hlapi.v3arch.asyncio"] = mod


def chay(c):
    return asyncio.run(c)


DB = {
    "1.3.6.1.2.1.31.1.1.1.1.2": GiaTri("WAN-ETHER1"),
    "1.3.6.1.2.1.31.1.1.1.1.3": GiaTri("ether2"),
    "1.3.6.1.2.1.31.1.1.1.6.3": GiaTri(1877166545454),
    "1.3.6.1.2.1.4.22.1.2.6.172.16.10.50": GiaTri("aabbccddee01", octet=True),
    "1.3.6.1.2.1.31.1.1.1.18.3": GiaTri("Switch 1"),
}


class MayKhachTest(unittest.TestCase):
    def _mk(self, lop_ten):
        cai_pysnmp_gia(DB, lop_ten)
        from mikrotik_snmp.snmp_client import SnmpClient
        return SnmpClient(Hass(), "172.16.10.1", 161, "hass", "a", "p", "hmac-sha", "aes-cfb-128")

    def test_get_tra_khoa_dang_so_du_ten_ve_dang_chu(self):
        for lop in (TenMoi, TenCu, TenChiChu):
            with self.subTest(lop=lop.__name__):
                r = chay(self._mk(lop).get(["1.3.6.1.2.1.31.1.1.1.6.3"]))
                self.assertEqual(r, {"1.3.6.1.2.1.31.1.1.1.6.3": 1877166545454})

    def test_walk_duyet_dung_bang_ifname(self):
        for lop in (TenMoi, TenCu, TenChiChu):
            with self.subTest(lop=lop.__name__):
                r = chay(self._mk(lop).walk("1.3.6.1.2.1.31.1.1.1.1"))
                self.assertEqual(r, {"1.3.6.1.2.1.31.1.1.1.1.2": "WAN-ETHER1", "1.3.6.1.2.1.31.1.1.1.1.3": "ether2"})

    def test_walk_dung_o_het_cay_con(self):
        r = chay(self._mk(TenMoi).walk("1.3.6.1.2.1.31.1.1.1.6"))
        self.assertEqual(list(r), ["1.3.6.1.2.1.31.1.1.1.6.3"])        # không lấn sang ...18 hay ...1

    def test_walk_mac_dang_hex(self):
        r = chay(self._mk(TenMoi).walk("1.3.6.1.2.1.4.22.1.2", hex_octet=True))
        self.assertEqual(list(r.values()), ["aabbccddee01"])

    def test_duyet_bang_ket_hop_voi_logic_ra_giao_dien(self):
        """Đầu-cuối nhỏ: máy khách giả (tên dạng chữ) + ThuThap thật → ra danh sách cổng."""
        from mikrotik_snmp.thu_thap import ThuThap
        mk = self._mk(TenMoi)
        tt = ThuThap(mk)
        chay(tt.do_lai())
        self.assertEqual(sorted(g["name"] for g in tt.giao_dien.values()), ["WAN-ETHER1", "ether2"])


class CanhBaoTest(unittest.TestCase):
    def test_walk_ten_khong_chuyen_duoc_sang_so_thi_bao_loi_ro(self):
        cai_pysnmp_gia(DB, lambda oid: TenKhongDung(oid))
        from mikrotik_snmp.snmp_client import SnmpClient, SnmpLoi
        mk = SnmpClient(Hass(), "172.16.10.1", 161, "hass", "a", "p", "hmac-sha", "aes-cfb-128")
        with self.assertRaises(SnmpLoi) as ctx:
            chay(mk.walk("1.3.6.1.2.1.31.1.1.1.1"))
        self.assertIn("OID dạng số", str(ctx.exception))

    def test_do_lai_khong_ra_cong_nao_thi_bao_loi_du_lieu(self):
        from mikrotik_snmp.thu_thap import LoiDuLieu, ThuThap

        class Rong:
            async def get(self, oids):
                return {}

            async def walk(self, goc, hex_octet=False):
                return {}
        with self.assertRaises(LoiDuLieu):
            chay(ThuThap(Rong()).cap_nhat())


class TenKhongDung:
    """Tên OID không có get_oid và in kiểu lạ (IF-MIB::…): không thể quy ra số."""

    def __init__(self, so):
        pass

    def prettyPrint(self):
        return "IF-MIB::ifName.2"


if __name__ == "__main__":
    unittest.main()
