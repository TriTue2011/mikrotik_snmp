"""Mức coordinator và thực thể trên Home Assistant THẬT (lớp lõi của HA), máy chủ ZTE giả cục bộ.

Cần gói `homeassistant` (Python 3.13+); thiếu thì cả file được bỏ qua.
Máy chủ giả KHÔNG chứng minh ZTE thật xử lý giống vậy.
"""
from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock

ROOT = pathlib.Path(__file__).resolve().parents[1]

try:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.const import MATCH_ALL
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.json import json_bytes

    from custom_components.mikrotik_snmp import MikrotikSnmpCoordinator, async_unload_entry
    from custom_components.mikrotik_snmp.const import (
        CONF_AUTH_KEY, CONF_HOST, CONF_PRIV_KEY, CONF_TEN,
        CONF_ZTE_HOST, CONF_ZTE_MAT_KHAU, CONF_ZTE_TEN, DOMAIN,
        CHU_KY_ZTE_GIAY,
    )
    from custom_components.mikrotik_snmp.device_tracker import MayLan
    from custom_components.mikrotik_snmp.sensor import (
        BangMacSensor, CamBienWifiMay, CayThietBiSensor, ThietBiLanSensor,
        ZteBoPhatSensor, ZteSoMaySensor, ZteTrangThaiSensor,
    )
    CO_HA = True
except ImportError:
    CO_HA = False

from tests.test_mikrotik_snmp import DongHo, RouterGia
from tests.test_zte_api import MK
from tests.test_zte_loi import clients_lon, dung_may_chu

MAC_WIFI = "02:00:00:00:00:01"       # máy WiFi đầu tiên trong fixture
MAC_CO_DAY = "AA:BB:CC:DD:EE:01"     # máy có dây trong RouterGia
GIOI_HAN_RECORDER = 16384           # homeassistant.components.recorder.db_schema.MAX_STATE_ATTRS_BYTES


@unittest.skipUnless(CO_HA, "không có Home Assistant")
class DieuPhoiHaTest(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.may = dung_may_chu()
        cls.clients_goc = dict(cls.may.clients_json)
        cls.ap_goc = dict(cls.may.ap_json)

    @classmethod
    def tearDownClass(cls):
        cls.may.shutdown()
        cls.may.server_close()

    async def asyncSetUp(self):
        self.may.che_do = ""
        self.may.het_phien_luot = 0
        self.may.dem_dang_nhap = 0
        self.may.ten = "user"
        self.may.clients_json = self.clients_goc
        self.may.ap_json = self.ap_goc

        self._thu_muc = tempfile.TemporaryDirectory()
        self.hass = HomeAssistant(self._thu_muc.name)
        self.entry = ConfigEntry(
            version=1, minor_version=1, domain=DOMAIN, title="thu", source="user", unique_id=None,
            discovery_keys={}, subentries_data=None, options={},
            data={
                CONF_HOST: "192.168.88.1", CONF_TEN: "tk", CONF_AUTH_KEY: "k", CONF_PRIV_KEY: "k",
                CONF_ZTE_HOST: f"127.0.0.1:{self.may.server_port}", CONF_ZTE_TEN: "user", CONF_ZTE_MAT_KHAU: MK,
            },
        )
        self.cc = MikrotikSnmpCoordinator(self.hass, self.entry)
        self.cc.thu_thap._mk = RouterGia()
        self.dh = DongHo()
        self.cc.thu_thap._dong_ho = self.dh
        if self.cc.thu_thap._zte:
            self.cc.thu_thap._zte._dong_ho = self.dh
            self.cc.thu_thap._zte._may._goc = f"http://127.0.0.1:{self.may.server_port}"

    async def asyncTearDown(self):
        await self.hass.async_stop(force=True)
        self._thu_muc.cleanup()

    # ── Ca 1: Đọc hỏng khi phiên hết hạn ─────────────────────────────────────────────────────────────
    async def test_doc_hong_thi_coordinator_song_va_thiet_bi_wifi_unavailable(self):
        """Đọc hỏng: coordinator.last_update_success vẫn True, thực thể WiFi unavailable nhưng không 'vắng'."""
        self.dh.t += CHU_KY_ZTE_GIAY
        await self.cc.async_refresh()
        self.assertTrue(self.cc.last_update_success)

        tracker_wifi = MayLan(self.cc, self.entry, MAC_WIFI)
        cb_so_may = ZteSoMaySensor(self.cc, self.entry, None)
        cb_wifi = CamBienWifiMay(self.cc, self.entry, MAC_WIFI, "rssi")
        cb_trang_thai = ZteTrangThaiSensor(self.cc, self.entry)

        self.assertTrue(tracker_wifi.available)
        self.assertTrue(tracker_wifi.is_connected)
        self.assertTrue(cb_so_may.available)
        self.assertTrue(cb_wifi.available)
        self.assertTrue(cb_trang_thai.available)
        self.assertEqual(cb_trang_thai.native_value, "ok")

        for che_do in ("rot", "rac", "boot"):
            with self.subTest(che_do=che_do):
                self.may.che_do = che_do
                self.may.het_phien_luot = 1
                self.dh.t += CHU_KY_ZTE_GIAY
                await self.cc.async_refresh()

                self.assertTrue(self.cc.last_update_success, "phần MikroTik vẫn chạy")
                self.assertNotEqual(self.cc.data["zte"]["trang_thai"], "ok")
                self.assertTrue(self.cc.data["zte"]["clients"], "danh sách cũ trong zte.clients còn nguyên")
                self.assertTrue(any(c["mac"] == MAC_WIFI for c in self.cc.data["tree"]["clients"]), "máy cũ trong tree còn")

                self.assertFalse(tracker_wifi.available, "máy WiFi phải unavailable")
                self.assertTrue(tracker_wifi.is_connected, "máy WiFi KHÔNG được thành 'vắng'")
                self.assertFalse(cb_so_may.available, "ZteSoMaySensor phải unavailable")
                self.assertFalse(cb_wifi.available, "CamBienWifiMay phải unavailable")
                self.assertTrue(cb_trang_thai.available, "ZteTrangThaiSensor PHẢI luôn available")

    # ── Ca 2: Thiết bị có dây vẫn available và connected khi ZTE hỏng ────────────────────────────────
    async def test_thiet_bi_co_day_van_available_va_connected_khi_zte_hong(self):
        self.dh.t += CHU_KY_ZTE_GIAY
        await self.cc.async_refresh()

        tracker_day = MayLan(self.cc, self.entry, MAC_CO_DAY)
        self.assertTrue(tracker_day.available)
        self.assertTrue(tracker_day.is_connected)

        # Cho ZTE hỏng
        self.may.che_do = "rot"
        self.may.het_phien_luot = 1
        self.dh.t += CHU_KY_ZTE_GIAY
        await self.cc.async_refresh()

        self.assertTrue(tracker_day.available, "thiết bị có dây vẫn available khi ZTE hỏng")
        self.assertTrue(tracker_day.is_connected, "thiết bị có dây vẫn is_connected khi ZTE hỏng")

    # ── Ca 3: Phiên hết hạn đăng nhập lại đúng một lần ───────────────────────────────────────────────
    async def test_phien_het_han_dang_nhap_lai_dung_mot_lan(self):
        self.dh.t += CHU_KY_ZTE_GIAY
        await self.cc.async_refresh()
        self.assertEqual(self.may.dem_dang_nhap, 1)

        self.may.het_phien_luot = 1
        self.dh.t += CHU_KY_ZTE_GIAY
        await self.cc.async_refresh()
        self.assertEqual(self.cc.data["zte"]["trang_thai"], "ok")
        self.assertEqual(self.may.dem_dang_nhap, 2)

    # ── Ca 4: Mất mạng/trang lạ không đặt backoff dài ────────────────────────────────────────────────
    async def test_mat_mang_khong_dat_backoff_va_hoi_phuc_ngay(self):
        self.dh.t += CHU_KY_ZTE_GIAY
        await self.cc.async_refresh()

        for che_do in ("rot", "boot"):
            self.may.che_do = che_do
            self.may.het_phien_luot = 1
            self.dh.t += CHU_KY_ZTE_GIAY
            await self.cc.async_refresh()
            self.assertNotEqual(self.cc.data["zte"]["trang_thai"], "ok")

        self.may.che_do = ""
        truoc = self.may.dem_dang_nhap
        # Tiến đồng hồ chỉ >= chu kỳ ZTE (15 giây), KHÔNG tiến 1800 giây
        self.dh.t += CHU_KY_ZTE_GIAY
        await self.cc.async_refresh()
        self.assertEqual(self.cc.data["zte"]["trang_thai"], "ok", "phải hồi phục ngay mà không đợi 1800s")
        self.assertGreater(self.may.dem_dang_nhap, truoc)

    # ── Ca 5: Bị từ chối thì backoff rồi hết hạn hồi phục ────────────────────────────────────────────
    async def test_bi_tu_choi_dang_nhap_thi_backoff_roi_het_han_hoi_phuc(self):
        self.dh.t += CHU_KY_ZTE_GIAY
        await self.cc.async_refresh()

        self.may.ten = "nguoi-khac"
        self.may.het_phien_luot = 1
        self.dh.t += CHU_KY_ZTE_GIAY
        await self.cc.async_refresh()
        self.assertEqual(self.cc.data["zte"]["trang_thai"], "loi_dang_nhap")
        dem1 = self.may.dem_dang_nhap

        # Tiến ít hơn 1800 giây: đang tạm ngừng, không gửi POST
        self.may.ten = "user"
        self.dh.t += 60
        await self.cc.async_refresh()
        self.assertEqual(self.cc.data["zte"]["trang_thai"], "tam_ngung")
        self.assertEqual(self.may.dem_dang_nhap, dem1, "không được gửi POST khi đang tạm ngừng")

        # Tiến đủ 1800+ giây: hồi phục
        self.dh.t += 1801
        await self.cc.async_refresh()
        self.assertEqual(self.cc.data["zte"]["trang_thai"], "ok")
        self.assertGreater(self.may.dem_dang_nhap, dem1)

    # ── Ca 6: Đối chứng: máy thật sự rời WiFi thì chuyển vắng ────────────────────────────────────────
    async def test_doi_chung_may_wifi_that_su_roi_mang_chuyen_vang(self):
        self.dh.t += CHU_KY_ZTE_GIAY
        await self.cc.async_refresh()
        tracker = MayLan(self.cc, self.entry, MAC_WIFI)
        self.assertTrue(tracker.is_connected)

        # Xoá MAC_WIFI khỏi clients_json của bộ phát
        moi = {k: v for k, v in self.clients_goc["clientsData"].items()
               if not (isinstance(v, dict) and str(v.get("MacAddr", "")).lower() == MAC_WIFI)}
        self.may.clients_json = {"clientsData": moi}
        self.dh.t += CHU_KY_ZTE_GIAY
        await self.cc.async_refresh()

        self.assertEqual(self.cc.data["zte"]["trang_thai"], "ok")
        self.assertTrue(tracker.available, "máy vẫn available")
        self.assertFalse(tracker.is_connected, "máy thật sự rời WiFi phải is_connected = False")

    # ── Ca 7: Gỡ tích hợp quên phiên ────────────────────────────────────────────────────────────────
    async def test_go_tich_hop_dong_phien(self):
        self.dh.t += CHU_KY_ZTE_GIAY
        await self.cc.async_refresh()
        self.assertEqual(self.may.dem_dang_nhap, 1)

        self.hass.data[DOMAIN] = {self.entry.entry_id: self.cc}
        self.hass.config_entries = MagicMock()
        self.hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)

        self.assertTrue(await async_unload_entry(self.hass, self.entry))
        # Sau khi gỡ, client ZTE đã dang_xuat() nên lần đọc sau phải đăng nhập mới
        self.dh.t += CHU_KY_ZTE_GIAY
        await self.cc.async_refresh()
        self.assertEqual(self.may.dem_dang_nhap, 2, "lần đọc sau phải đăng nhập mới")

    # ── Ca 8: Kiểm recorder thuộc tính lớn (Điểm 4) ─────────────────────────────────────────────────
    async def test_recorder_thuoc_tinh_khong_vuot_16kb_voi_150_may(self):
        self.may.clients_json = clients_lon(150)
        self.dh.t += CHU_KY_ZTE_GIAY
        await self.cc.async_refresh()

        # ZteSoMaySensor
        cb_so_may = ZteSoMaySensor(self.cc, self.entry, None)
        attr_so_may = cb_so_may.extra_state_attributes
        self.assertIn("clients", cb_so_may._unrecorded_attributes)
        # Đối chứng: thuộc tính đầy đủ vượt 16 KB
        self.assertGreater(len(json_bytes(attr_so_may)), GIOI_HAN_RECORDER)
        duoc_ghi_so_may = {k: v for k, v in attr_so_may.items() if k not in cb_so_may._unrecorded_attributes}
        self.assertLess(len(json_bytes(duoc_ghi_so_may)), GIOI_HAN_RECORDER // 2)

        # CayThietBiSensor
        cb_cay = CayThietBiSensor(self.cc, self.entry)
        attr_cay = cb_cay.extra_state_attributes
        self.assertTrue({"nodes", "clients"}.issubset(cb_cay._unrecorded_attributes))
        self.assertGreater(len(json_bytes(attr_cay)), GIOI_HAN_RECORDER)
        duoc_ghi_cay = {k: v for k, v in attr_cay.items() if k not in cb_cay._unrecorded_attributes}
        self.assertLess(len(json_bytes(duoc_ghi_cay)), GIOI_HAN_RECORDER // 2)

        # BangMacSensor
        cb_bang_mac = BangMacSensor(self.cc, self.entry)
        self.assertIn(MATCH_ALL, cb_bang_mac._unrecorded_attributes)

        # ThietBiLanSensor
        cb_lan = ThietBiLanSensor(self.cc, self.entry)
        self.assertIn("clients", cb_lan._unrecorded_attributes)

    async def test_recorder_clients_giu_dung_cac_truong(self):
        self.dh.t += CHU_KY_ZTE_GIAY
        await self.cc.async_refresh()
        may = ZteSoMaySensor(self.cc, self.entry, None).extra_state_attributes["clients"][0]
        self.assertEqual(set(may), {"mac", "ip", "name", "band", "rssi", "mode"})
        cay = CayThietBiSensor(self.cc, self.entry).extra_state_attributes
        self.assertIn("nodes", cay)
        self.assertIn("clients", cay)


if __name__ == "__main__":
    unittest.main()
