"""Test phần logic và thu thập của tích hợp MikroTik SNMP bằng router GIẢ (không cần Home Assistant hay pysnmp)."""
from __future__ import annotations

import asyncio
import pathlib
import sys
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
goi = types.ModuleType("mikrotik_snmp")
goi.__path__ = [str(ROOT / "custom_components" / "mikrotik_snmp")]
sys.modules["mikrotik_snmp"] = goi

from mikrotik_snmp import logic as L  # noqa: E402
from mikrotik_snmp.thu_thap import ThuThap  # noqa: E402


class RouterGia:
    """Máy khách giả: bảng OID → giá trị, bộ đếm tăng theo `buoc` octet mỗi lần hỏi."""

    def __init__(self):
        self.db = {
            L.SYS_DESCR: "RouterOS RB5009", L.SYS_NAME: "MikroTik", L.SYS_UPTIME: 8640000,
            L.MTXR_TEMPERATURE: 452, L.MTXR_VOLTAGE: 240,
            f"{L.IF_NAME}.2": "WAN-ETHER1", f"{L.IF_NAME}.3": "ether2", f"{L.IF_NAME}.6": "BridgeLAN", f"{L.IF_NAME}.1": "lo",
            f"{L.IF_TYPE}.2": 6, f"{L.IF_TYPE}.3": 6, f"{L.IF_TYPE}.6": 209, f"{L.IF_TYPE}.1": 24,
            f"{L.IF_ALIAS}.3": "Switch 1",
            f"{L.HR_PROCESSOR_LOAD}.1": 10, f"{L.HR_PROCESSOR_LOAD}.2": 30,
            f"{L.HR_STORAGE_DESCR}.65536": "main memory", f"{L.HR_STORAGE_DESCR}.131072": "system disk",
            f"{L.HR_STORAGE_SIZE}.65536": 1000, f"{L.HR_STORAGE_USED}.65536": 250,
        }
        for i in (2, 3, 6):
            self.db[f"{L.IF_OPER}.{i}"] = 1
            self.db[f"{L.IF_HIGH_SPEED}.{i}"] = 1000
            self.db[f"{L.IF_HC_IN}.{i}"] = 1_000_000
            self.db[f"{L.IF_HC_OUT}.{i}"] = 2_000_000
        # BRIDGE-MIB: cổng bridge 1 → ifIndex 3 (ether2), cổng 2 → ifIndex 2 (WAN); ARP cho 2 máy
        self.db[f"{L.BASE_PORT_IF}.1"] = 3
        self.db[f"{L.BASE_PORT_IF}.2"] = 2
        self.db[f"{L.FDB_PORT}.170.187.204.221.238.1"] = 1
        self.db[f"{L.FDB_STATUS}.170.187.204.221.238.1"] = 3
        self.db[f"{L.FDB_PORT}.170.187.204.221.238.2"] = 1
        self.db[f"{L.FDB_STATUS}.170.187.204.221.238.2"] = 3
        self.db[f"{L.FDB_PORT}.1.2.3.4.5.6"] = 2          # máy sau WAN
        self.db[f"{L.FDB_STATUS}.1.2.3.4.5.6"] = 3
        self.db[f"{L.FDB_PORT}.9.9.9.9.9.9"] = 1          # MAC của chính router: bị bỏ
        self.db[f"{L.FDB_STATUS}.9.9.9.9.9.9"] = 4
        self.db[f"{L.ARP_MAC}.6.172.16.10.50"] = "aabbccddee01"
        self.db[f"{L.ARP_MAC}.6.172.16.10.9"] = "aabbccddee02"
        self.db[f"{L.ARP_MAC}.6.172.16.10.77"] = "000000000000"   # ARP chưa phân giải: bị bỏ
        self.so_lan_get = 0
        self.oid_moi_lan: list[int] = []

    async def get(self, oids):
        self.so_lan_get += 1
        self.oid_moi_lan.append(len(oids))
        return {o: self.db[o] for o in oids if o in self.db}

    async def walk(self, goc, hex_octet=False):
        return {o: v for o, v in self.db.items() if o.startswith(goc + ".")}


def chay(coro):
    return asyncio.run(coro)


class DongHo:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class TocDoTest(unittest.TestCase):
    def test_lan_dau_khong_bia_so(self):
        self.assertIsNone(L.tinh_toc_do_mbit(None, (10.0, 5)))

    def test_toc_do_binh_thuong(self):
        # 1.25 MB trong 1 giây = 10 Mbit/s
        self.assertEqual(L.tinh_toc_do_mbit((10.0, 0), (11.0, 1_250_000)), 10.0)

    def test_thoi_gian_khong_duong(self):
        self.assertIsNone(L.tinh_toc_do_mbit((10.0, 0), (10.0, 99)))
        self.assertIsNone(L.tinh_toc_do_mbit((10.0, 0), (9.0, 99)))

    def test_tran_bo_dem_64bit(self):
        gan_dinh = L.HAI_MU_64 - 500_000
        # tràn: 500_000 để chạm đỉnh + 750_000 sau tràn = 1.25 MB → 10 Mbit/s
        self.assertEqual(L.tinh_toc_do_mbit((0.0, gan_dinh), (1.0, 750_000)), 10.0)

    def test_router_khoi_dong_lai_khong_ra_so_khong_lo(self):
        self.assertIsNone(L.tinh_toc_do_mbit((0.0, 9_000_000_000), (1.0, 100)))


class LamSachTest(unittest.TestCase):
    def test_lam_sach_va_slug(self):
        self.assertEqual(L.lam_sach("a\x00b\x1bc\n"), "abc")
        self.assertEqual(len(L.lam_sach("x" * 500)), 64)
        self.assertEqual(L.slug("BridgeLAN"), "bridgelan")
        self.assertEqual(L.slug("WAN-ETHER1"), "wan_ether1")
        self.assertEqual(L.slug("..."), "x")

    def test_thoi_gian_chay(self):
        self.assertEqual(L.thoi_gian_chay(8640000), "1d 00:00:00")
        self.assertEqual(L.thoi_gian_chay(360500), "0d 01:00:05")
        self.assertIsNone(L.thoi_gian_chay("khong-phai-so"))


class ThuThapTest(unittest.TestCase):
    def test_kham_pha_giao_dien_bo_loopback_va_phan_loai(self):
        r = RouterGia()
        tt = ThuThap(r, None, DongHo())
        chay(tt.cap_nhat())
        ten = {g["name"]: g for g in tt.giao_dien.values()}
        self.assertEqual(set(ten), {"WAN-ETHER1", "ether2", "BridgeLAN"})   # «lo» bị loại
        self.assertEqual(ten["BridgeLAN"]["kind"], "bridge")
        self.assertEqual(ten["ether2"]["kind"], "port")
        self.assertEqual(ten["ether2"]["comment"], "Switch 1")

    def test_toc_do_tu_hai_lan_doc(self):
        r, dh = RouterGia(), DongHo()
        tt = ThuThap(r, None, dh)
        d1 = chay(tt.cap_nhat())
        self.assertIsNone(d1["interfaces"][3]["rx_mbps"])           # lần đầu: chưa có tốc độ
        dh.t += 5
        r.db[f"{L.IF_HC_IN}.3"] += 6_250_000                         # 50 Mbit trong 5 s = 10 Mbit/s
        d2 = chay(tt.cap_nhat())
        self.assertEqual(d2["interfaces"][3]["rx_mbps"], 10.0)
        self.assertEqual(d2["interfaces"][3]["tx_mbps"], 0.0)

    def test_chi_hoi_cong_da_chon_va_chia_nhom_oid(self):
        r = RouterGia()
        tt = ThuThap(r, ["ether2"], DongHo())
        d = chay(tt.cap_nhat())
        self.assertEqual(set(d["interfaces"]), {3})
        self.assertLessEqual(max(r.oid_moi_lan), 20)

    def test_thong_tin_he_thong(self):
        d = chay(ThuThap(RouterGia(), None, DongHo()).cap_nhat())
        c = d["core"]
        self.assertEqual(c["cpu"], 20.0)
        self.assertEqual(c["memory"], 25.0)
        self.assertEqual(c["temperature"], 45.2)
        self.assertEqual(c["voltage"], 24.0)
        self.assertEqual(c["uptime"], "1d 00:00:00")
        self.assertEqual(d["interfaces"][2]["up"], True)
        self.assertEqual(d["interfaces"][2]["speed_mbps"], 1000)

    def test_thieu_nhiet_do_va_ram_khong_vo(self):
        r = RouterGia()
        for k in (L.MTXR_TEMPERATURE, L.MTXR_VOLTAGE, f"{L.HR_STORAGE_DESCR}.65536"):
            del r.db[k]
        c = chay(ThuThap(r, None, DongHo()).cap_nhat())["core"]
        self.assertIsNone(c["temperature"])
        self.assertIsNone(c["voltage"])
        self.assertIsNone(c["memory"])

    def test_thong_tin_cham_chi_hoi_theo_chu_ky(self):
        r, dh = RouterGia(), DongHo()
        tt = ThuThap(r, None, dh)
        chay(tt.cap_nhat())
        sau_lan_1 = r.so_lan_get
        dh.t += 5
        chay(tt.cap_nhat())
        so_get_lan_2 = r.so_lan_get - sau_lan_1
        dh.t += 60
        chay(tt.cap_nhat())
        so_get_lan_3 = r.so_lan_get - sau_lan_1 - so_get_lan_2
        self.assertLess(so_get_lan_2, so_get_lan_3)    # lần 3 đủ hạn đọc chậm nên hỏi nhiều hơn

    def test_hai_giao_dien_trung_ten_khong_trung_slug(self):
        ten = {f"{L.IF_NAME}.5": "ether-1", f"{L.IF_NAME}.7": "ether_1"}
        gd = L.phan_tich_giao_dien(ten, {})
        self.assertEqual(len({g["slug"] for g in gd.values()}), 2)


class ThietBiLanTest(unittest.TestCase):
    def test_mac_tu_hex_va_hau_to(self):
        self.assertEqual(L.mac_tu_hex("aabbccddee01"), "AA:BB:CC:DD:EE:01")
        self.assertEqual(L.mac_tu_hex("0xaabbccddee01"), "AA:BB:CC:DD:EE:01")
        self.assertIsNone(L.mac_tu_hex("khong-phai-mac"))
        self.assertEqual(L.mac_tu_hau_to("170.187.204.221.238.1"), "AA:BB:CC:DD:EE:01")
        self.assertIsNone(L.mac_tu_hau_to("1.2.3"))
        self.assertIsNone(L.mac_tu_hau_to("300.1.1.1.1.1"))

    def test_bang_mac_theo_cong_bo_mac_cua_router(self):
        d = chay(ThuThap(RouterGia(), None, DongHo()).cap_nhat())["devices"]
        self.assertEqual(d["bang_mac"], {"WAN-ETHER1": ["01:02:03:04:05:06"], "ether2": ["AA:BB:CC:DD:EE:01", "AA:BB:CC:DD:EE:02"]})
        self.assertNotIn("09:09:09:09:09:09", [m for ds in d["bang_mac"].values() for m in ds])

    def test_arp_va_danh_sach_thiet_bi(self):
        d = chay(ThuThap(RouterGia(), None, DongHo()).cap_nhat())["devices"]
        self.assertEqual(d["arp"], {"AA:BB:CC:DD:EE:01": "172.16.10.50", "AA:BB:CC:DD:EE:02": "172.16.10.9"})
        ds = d["clients"]
        # sắp theo IP; máy chỉ có trong bảng MAC (không ARP) vẫn có, ip rỗng, xếp cuối
        self.assertEqual([c["ip"] for c in ds], ["172.16.10.9", "172.16.10.50", ""])
        self.assertEqual(ds[0], {"mac": "AA:BB:CC:DD:EE:02", "ip": "172.16.10.9", "interface": "ether2"})
        self.assertEqual(ds[2]["interface"], "WAN-ETHER1")

    def test_router_khong_co_bang_mac_khong_vo(self):
        r = RouterGia()
        for k in [k for k in r.db if k.startswith(L.FDB_PORT) or k.startswith(L.ARP_MAC)]:
            del r.db[k]
        d = chay(ThuThap(r, None, DongHo()).cap_nhat())
        self.assertEqual(d["devices"]["clients"], [])
        self.assertFalse(d["devices"]["co_bang_mac"])
        self.assertIn(3, d["interfaces"])      # phần tốc độ cổng vẫn chạy

    def test_loi_khi_doc_bang_giu_ket_qua_cu(self):
        r, dh = RouterGia(), DongHo()
        tt = ThuThap(r, None, dh)
        chay(tt.cap_nhat())
        goc_walk = r.walk

        async def hong(goc, hex_octet=False):
            if goc in (L.FDB_PORT, L.ARP_MAC):
                raise RuntimeError("router khong tra loi")
            return await goc_walk(goc, hex_octet)
        r.walk = hong
        dh.t += 20
        d = chay(tt.cap_nhat())
        self.assertEqual(len(d["devices"]["clients"]), 3)      # giữ danh sách cũ, không mất thiết bị


class ZteGia:
    host = "172.16.10.24"

    def __init__(self):
        self.loi: Exception | None = None
        self.so_lan = 0

    async def doc(self):
        self.so_lan += 1
        if self.loi:
            raise self.loi
        return {"ap": {"mac": "02:11:22:33:44:55", "ip": "172.16.10.24", "name": "ZTE:ZXHN E2633", "firmware": "V1.0.4"},
                "clients": [{"mac": "aa:bb:cc:dd:ee:01", "ip": "172.16.10.50", "name": "Honor", "band": "5G", "rssi": -58,
                             "mode": "802.11ax", "assoc_s": 100}]}


class GopZteTest(unittest.TestCase):
    def test_may_wifi_duoi_zte_va_chu_ky_zte(self):
        r, z, dh = RouterGia(), ZteGia(), DongHo()
        r.db[f"{L.ARP_MAC}.6.172.16.10.24"] = "aabbccddee02"      # ARP của chính ZTE
        tt = ThuThap(r, None, dh, zte=z)
        d = chay(tt.cap_nhat())
        may = {c["mac"]: c for c in d["tree"]["clients"]}
        self.assertEqual(may["AA:BB:CC:DD:EE:01"]["parent"], "zte")
        self.assertEqual(may["AA:BB:CC:DD:EE:01"]["rssi"], -58)
        self.assertEqual(d["zte"]["trang_thai"], "ok")
        dh.t += 5
        chay(tt.cap_nhat())
        self.assertEqual(z.so_lan, 1)               # chưa tới hạn đọc ZTE (15 giây)
        dh.t += 20
        chay(tt.cap_nhat())
        self.assertEqual(z.so_lan, 2)

    def test_zte_loi_giu_danh_sach_cu_va_ghi_trang_thai(self):
        class ZteLoiDangNhap(Exception):
            pass
        r, z, dh = RouterGia(), ZteGia(), DongHo()
        tt = ThuThap(r, None, dh, zte=z)
        chay(tt.cap_nhat())
        z.loi = ZteLoiDangNhap("sai mat khau")
        dh.t += 20
        d = chay(tt.cap_nhat())
        self.assertEqual(d["zte"]["trang_thai"], "loi_dang_nhap")
        self.assertEqual(len(d["zte"]["clients"]), 1)              # giữ lần đọc tốt gần nhất
        self.assertIn("interfaces", d)                              # phần MikroTik vẫn chạy
        self.assertEqual({c["mac"]: c for c in d["tree"]["clients"]}["AA:BB:CC:DD:EE:01"]["parent"], "zte")

    def test_khong_khai_zte_thi_khong_co_nut_zte(self):
        d = chay(ThuThap(RouterGia(), None, DongHo()).cap_nhat())
        self.assertIsNone(d["zte"])
        self.assertNotIn("zte", {n["id"] for n in d["tree"]["nodes"]})


class NguonZteBaoVeTest(unittest.TestCase):
    def test_nghi_30_phut_sau_loi_dang_nhap(self):
        from mikrotik_snmp.zte_nguon import NguonZte, ZteTamNgung
        from mikrotik_snmp.zte_api import ZteLoiDangNhap

        class May:
            so = 0

            def doc_thiet_bi(self):
                May.so += 1
                raise ZteLoiDangNhap("sai")

        async def chay_nen(f):
            return f()
        dh = DongHo()
        n = NguonZte(May(), "172.16.10.24", chay_nen, dh)
        with self.assertRaises(ZteLoiDangNhap):
            chay(n.doc())
        for _ in range(3):
            with self.assertRaises(ZteTamNgung):
                chay(n.doc())
        self.assertEqual(May.so, 1)                               # không gõ mật khẩu lại trong lúc nghỉ
        dh.t += 1801
        with self.assertRaises(ZteLoiDangNhap):
            chay(n.doc())
        self.assertEqual(May.so, 2)


class CauTrucGopTest(unittest.TestCase):
    """Cấu trúc của bản gộp (không cần Home Assistant)."""

    def _nguon(self, ten):
        return (ROOT / "custom_components" / "mikrotik_snmp" / ten).read_text(encoding="utf-8")

    def test_co_nen_tang_device_tracker_va_cay(self):
        self.assertIn("Platform.DEVICE_TRACKER", self._nguon("__init__.py"))
        sensor = self._nguon("sensor.py")
        self.assertIn('f"sensor.{coordinator.tien_to}_cay_thiet_bi"', sensor)
        self.assertIn("_unrecorded_attributes", sensor)           # thuộc tính lớn không ghi vào cơ sở dữ liệu lịch sử

    def test_zte_la_tuy_chon(self):
        self.assertIn("co_zte", self._nguon("__init__.py"))
        self.assertIn("if coordinator.co_zte:", self._nguon("sensor.py"))

    def test_may_con_gan_dung_cha(self):
        tracker = self._nguon("device_tracker.py")
        self.assertIn("via_device=self._cha", tracker)
        self.assertIn("dinh_danh_cha", tracker)

    def test_tuy_chon_co_buoc_zte_de_them_sau(self):
        """Thêm/đổi/tắt ZTE sau khi cài (không phải xoá rồi thêm lại): bước `zte` trong OptionsFlow, mật khẩu trống = giữ cũ."""
        nguon = self._nguon("config_flow.py")
        self.assertIn("async def async_step_zte", nguon[nguon.index("class MikrotikSnmpOptionsFlow"):])
        self.assertIn('hien_tai.get(CONF_ZTE_MAT_KHAU, "")', nguon)
        import json
        vi = json.loads(self._nguon("translations/vi.json"))
        self.assertIn("zte", vi["options"]["step"])
        self.assertIn("dang_nhap_zte", vi["options"]["error"])

    def test_mat_khau_zte_khong_vao_log(self):
        for ten in ("zte_api.py", "zte_nguon.py", "config_flow.py", "__init__.py"):
            for dong in self._nguon(ten).splitlines():
                if "LOGGER." in dong or "print(" in dong:
                    self.assertNotIn("mat_khau", dong)


class CauTrucTest(unittest.TestCase):
    def test_moi_khoa_python_bien_dich_duoc(self):
        for f in (ROOT / "custom_components" / "mikrotik_snmp").glob("*.py"):
            compile(f.read_text(encoding="utf-8"), str(f), "exec")

    def test_khong_co_lenh_ghi_snmp(self):
        """Chỉ đọc theo CẤU TẠO: máy khách không được có hàm/ lệnh SET."""
        nguon = (ROOT / "custom_components" / "mikrotik_snmp" / "snmp_client.py").read_text(encoding="utf-8")
        for cam in ("set_cmd", "bulk_set", "SetRequest", "async def set"):
            self.assertNotIn(cam, nguon)


class QuyUocThucTheTest(unittest.TestCase):
    """Mã thực thể phải khớp quy ước card `mikrotik-topo-lan-card` đọc (không cần Home Assistant)."""

    def _nguon(self, ten):
        return (ROOT / "custom_components" / "mikrotik_snmp" / ten).read_text(encoding="utf-8")

    def test_ma_thuc_the_theo_quy_uoc_card(self):
        sensor = self._nguon("sensor.py")
        for mau in ('f"sensor.{self._ma}_{huong}"', 'f"sensor.{self._ma}_{huong}_total"', 'f"sensor.{coordinator.tien_to}_core_{ma}"'):
            self.assertIn(mau, sensor)
        self.assertIn("binary_sensor.{coordinator.tien_to}_{gd['kind']}_{gd['slug']}_connection", self._nguon("binary_sensor.py"))

    def test_don_vi_toc_do_la_mbit_s(self):
        self.assertIn("UnitOfDataRate.MEGABITS_PER_SECOND", self._nguon("sensor.py"))

    def test_dich_vi_va_en_cung_khoa(self):
        import json

        def khoa(d, tien_to=""):
            ra = set()
            for k, v in d.items():
                ra |= khoa(v, f"{tien_to}{k}.") if isinstance(v, dict) else {f"{tien_to}{k}"}
            return ra
        thu_muc = ROOT / "custom_components" / "mikrotik_snmp"
        vi = json.loads((thu_muc / "translations" / "vi.json").read_text(encoding="utf-8"))
        en = json.loads((thu_muc / "translations" / "en.json").read_text(encoding="utf-8"))
        self.assertEqual(khoa(vi), khoa(en))
        self.assertIn("options.step.init.data.cong", khoa(vi))

    def test_khoa_khong_vao_log(self):
        """Không có lệnh log/in nào chứa khoá hoặc mật khẩu."""
        for ten in ("snmp_client.py", "__init__.py", "config_flow.py"):
            for dong in self._nguon(ten).splitlines():
                if "LOGGER." in dong or "print(" in dong:
                    self.assertNotIn("auth_key", dong)
                    self.assertNotIn("priv_key", dong)


if __name__ == "__main__":
    unittest.main()
