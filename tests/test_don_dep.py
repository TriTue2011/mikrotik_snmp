"""Dọn thiết bị không còn trên router (chủ máy 02/11/2026: «nhiều thiết bị đã xóa nhưng HA vẫn giữ»)."""
from __future__ import annotations

import pathlib
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if "mikrotik_snmp" not in sys.modules:
    goi = types.ModuleType("mikrotik_snmp")
    goi.__path__ = [str(ROOT / "custom_components" / "mikrotik_snmp")]
    sys.modules["mikrotik_snmp"] = goi

from homeassistant.exceptions import HomeAssistantError  # noqa: E402
from mikrotik_snmp import don_dep as D  # noqa: E402
from mikrotik_snmp.const import DOMAIN  # noqa: E402

E = "e1"
NGAY = D.NGAY_GIAY
DU_LIEU = {
    "interfaces": {2: {"name": "ether1"}, 5: {"name": "ether4"}},
    "wireguard": [{"name": "Điện thoại A"}],
    "tree": {"clients": [{"mac": "AA:BB:CC:00:00:01"}]},
}


class KhoaHienCoTest(unittest.TestCase):
    def test_liet_ke_dung_cac_loai_thiet_bi(self):
        k = D.khoa_hien_co(E, DU_LIEU, co_zte=True)
        self.assertEqual(k, {"id:e1", "id:e1_2", "id:e1_5", "id:e1_zte", "id:e1_wg_" + D.slug("Điện thoại A"), "mac:aa:bb:cc:00:00:01"})

    def test_khong_co_zte_thi_khong_liet_ke_zte(self):
        self.assertNotIn("id:e1_zte", D.khoa_hien_co(E, DU_LIEU, co_zte=False))

    def test_du_lieu_rong_chi_con_router(self):
        self.assertEqual(D.khoa_hien_co(E, None, False), {"id:e1"})

    def test_khoa_thiet_bi_khop_khuon_mac_va_bo_qua_tich_hop_khac(self):
        k = D.khoa_cua_thiet_bi({(DOMAIN, "e1_2"), ("khac", "x")}, {("mac", "AA:BB:CC:00:00:01")})
        self.assertEqual(k, {"id:e1_2", "mac:aa:bb:cc:00:00:01"})


class QuyetDinhTest(unittest.TestCase):
    HIEN = {"id:e1", "id:e1_2"}
    SO = {"gốc": {"id:e1"}, "cổng-còn": {"id:e1_2"}, "máy-mất": {"mac:aa:bb:cc:00:00:99"}}

    def test_thiet_bi_con_thi_khong_co_moc_vang(self):
        moi, go = D.quyet_dinh({"a": {"id:e1_2"}}, self.HIEN, {"a": 5.0}, 1000.0, 14 * NGAY, E)
        self.assertEqual((moi, go), ({}, []))                       # trở lại thì xoá mốc vắng

    def test_vua_vang_thi_dat_moc_la_bay_gio_chua_go(self):
        moi, go = D.quyet_dinh(self.SO, self.HIEN, {}, 1000.0, 14 * NGAY, E)
        self.assertEqual((moi, go), ({"máy-mất": 1000.0}, []))

    def test_chua_du_han_thi_giu_nguyen_moc_cu(self):
        moi, go = D.quyet_dinh(self.SO, self.HIEN, {"máy-mất": 1000.0}, 1000.0 + 13 * NGAY, 14 * NGAY, E)
        self.assertEqual((moi, go), ({"máy-mất": 1000.0}, []))

    def test_du_han_thi_go_dung_thiet_bi_vang(self):
        moi, go = D.quyet_dinh(self.SO, self.HIEN, {"máy-mất": 1000.0}, 1000.0 + 14 * NGAY, 14 * NGAY, E)
        self.assertEqual(go, ["máy-mất"])

    def test_tat_tu_dong_thi_khong_bao_gio_go(self):
        _moi, go = D.quyet_dinh(self.SO, self.HIEN, {"máy-mất": 0.0}, 10_000 * NGAY, None, E)
        self.assertEqual(go, [])

    def test_han_0_go_ngay_moi_thiet_bi_dang_vang(self):
        _moi, go = D.quyet_dinh(self.SO, self.HIEN, {}, 1000.0, 0.0, E)
        self.assertEqual(go, ["máy-mất"])

    def test_router_goc_khong_bao_gio_bi_go_ke_ca_khi_du_lieu_rong(self):
        _moi, go = D.quyet_dinh({"gốc": {"id:e1"}}, set(), {}, 1000.0, 0.0, E)
        self.assertEqual(go, [])

    def test_moc_cua_thiet_bi_da_het_trong_so_bi_bo(self):
        moi, _ = D.quyet_dinh({}, self.HIEN, {"da-xoa": 1.0}, 1000.0, 14 * NGAY, E)
        self.assertEqual(moi, {})


def _dong_bo(co_zte=False, zte=None, thanh_cong=True, du_lieu=DU_LIEU):
    cd = SimpleNamespace(last_update_success=thanh_cong, data={**du_lieu, "zte": zte} if du_lieu else du_lieu, co_zte=co_zte)
    entry = SimpleNamespace(entry_id=E)
    hass = MagicMock()
    with patch.object(D.Store, "__init__", lambda self, *a, **k: None):
        don = D.DonDep(hass, entry, cd, 14)
    don._kho = MagicMock()
    return don, hass


def _so_thiet_bi(cac_thiet_bi):
    so = MagicMock()
    so.async_get.side_effect = lambda ma: cac_thiet_bi.get(ma)
    return so


class DonNgayTest(unittest.TestCase):
    def _chay(self, don, hass, thiet_bi):
        d = {ma: SimpleNamespace(id=ma, identifiers=ids, connections=cn, name=ma, name_by_user=None) for ma, (ids, cn) in thiet_bi.items()}
        so = _so_thiet_bi(d)
        with patch.object(D.dr, "async_get", return_value=so), \
                patch.object(D.dr, "async_entries_for_config_entry", return_value=list(d.values())):
            return don.don_ngay(0), so

    THIET_BI = {
        "goc": ({(DOMAIN, "e1")}, set()),
        "cong": ({(DOMAIN, "e1_2")}, set()),
        "may-con": (set(), {("mac", "AA:BB:CC:00:00:01")}),
        "may-mat": (set(), {("mac", "AA:BB:CC:00:00:99")}),
        "wg-mat": ({(DOMAIN, "e1_wg_da_xoa")}, set()),
    }

    def test_go_dung_cac_thiet_bi_vang_va_giu_cac_thiet_bi_con(self):
        don, hass = _dong_bo()
        n, so = self._chay(don, hass, self.THIET_BI)
        self.assertEqual(n, 2)
        da_go = sorted(c.args[0] for c in so.async_update_device.call_args_list)
        self.assertEqual(da_go, ["may-mat", "wg-mat"])
        for c in so.async_update_device.call_args_list:
            self.assertEqual(c.kwargs, {"remove_config_entry_id": E})

    def test_cap_nhat_lan_cuoi_that_bai_thi_tu_choi_khong_go_gi(self):
        don, hass = _dong_bo(thanh_cong=False)
        with self.assertRaises(HomeAssistantError):
            self._chay(don, hass, self.THIET_BI)

    def test_zte_chua_doc_xong_thi_tu_choi_vi_danh_sach_may_wifi_chua_day_du(self):
        don, hass = _dong_bo(co_zte=True, zte={"trang_thai": "chua_doc"})
        with self.assertRaises(HomeAssistantError):
            self._chay(don, hass, self.THIET_BI)

    def test_zte_da_doc_xong_thi_don_binh_thuong(self):
        don, hass = _dong_bo(co_zte=True, zte={"trang_thai": "ok"})
        n, _ = self._chay(don, hass, self.THIET_BI)
        self.assertEqual(n, 2)

    def test_cap_nhat_tu_dong_chi_ghi_moc_khi_chua_du_han(self):
        don, hass = _dong_bo()
        d = {ma: SimpleNamespace(id=ma, identifiers=ids, connections=cn, name=ma, name_by_user=None) for ma, (ids, cn) in self.THIET_BI.items()}
        so = _so_thiet_bi(d)
        with patch.object(D.dr, "async_get", return_value=so), patch.object(D.dr, "async_entries_for_config_entry", return_value=list(d.values())):
            don.cap_nhat()
        so.async_update_device.assert_not_called()
        self.assertEqual(set(don._vang), {"may-mat", "wg-mat"})

    def test_co_the_go_tu_giao_dien_chi_khi_thiet_bi_khong_con(self):
        don, _ = _dong_bo()
        self.assertFalse(don.co_the_go({"id:e1"}))                       # router gốc
        self.assertFalse(don.co_the_go({"mac:aa:bb:cc:00:00:01"}))       # máy đang có mặt
        self.assertTrue(don.co_the_go({"mac:aa:bb:cc:00:00:99"}))        # máy đã mất


if __name__ == "__main__":
    unittest.main()
