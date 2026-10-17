"""Cảm biến: tốc độ nhận/gửi từng cổng (Mbit/s), tổng byte, lỗi, và thông tin router (CPU, RAM, thời gian chạy, nhiệt độ, điện áp).

Mã thực thể đặt theo quy ước của card `mikrotik-topo-lan-card`: sensor.<tiền_tố>_(port|bridge|ppp)_<cổng>_(rx|tx|rx_total|tx_total),
sensor.<tiền_tố>_core_(cpu_load|memory_usage|uptime|temperature|voltage).
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, PERCENTAGE, UnitOfDataRate, UnitOfElectricPotential, UnitOfInformation, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo, format_mac
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .thiet_bi import dinh_danh_cha, ten_thiet_bi


def thiet_bi_giao_dien(entry: ConfigEntry, chi_so: int, ten: str) -> DeviceInfo:
    return DeviceInfo(identifiers={(DOMAIN, f"{entry.entry_id}_{chi_so}")}, name=ten, manufacturer="MikroTik",
                      via_device=(DOMAIN, entry.entry_id))


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    da_them: set[int] = set()

    @callback
    def _them_moi() -> None:
        moi: list[SensorEntity] = []
        for chi_so in (coordinator.data or {}).get("interfaces", {}):
            if chi_so in da_them:
                continue
            da_them.add(chi_so)
            moi += [
                ToCDoSensor(coordinator, entry, chi_so, "rx"), ToCDoSensor(coordinator, entry, chi_so, "tx"),
                TongByteSensor(coordinator, entry, chi_so, "rx"), TongByteSensor(coordinator, entry, chi_so, "tx"),
                LoiSensor(coordinator, entry, chi_so, "in_errors", "Lỗi nhận"), LoiSensor(coordinator, entry, chi_so, "out_errors", "Lỗi gửi"),
            ]
        if moi:
            async_add_entities(moi)

    _them_moi()
    entry.async_on_unload(coordinator.async_add_listener(_them_moi))
    core = (coordinator.data or {}).get("core", {})
    he_thong: list[SensorEntity] = [
        HeThongSensor(coordinator, entry, "cpu_load", "Tải CPU", "cpu", PERCENTAGE, None, "mdi:cpu-64-bit"),
        HeThongSensor(coordinator, entry, "memory_usage", "Bộ nhớ đã dùng", "memory", PERCENTAGE, None, "mdi:memory"),
        HeThongSensor(coordinator, entry, "uptime", "Thời gian chạy", "uptime", None, None, "mdi:timer-outline"),
    ]
    if core.get("temperature") is not None:
        he_thong.append(HeThongSensor(coordinator, entry, "temperature", "Nhiệt độ", "temperature", UnitOfTemperature.CELSIUS,
                                         SensorDeviceClass.TEMPERATURE, None))
    if core.get("voltage") is not None:
        he_thong.append(HeThongSensor(coordinator, entry, "voltage", "Điện áp", "voltage", UnitOfElectricPotential.VOLT,
                                         SensorDeviceClass.VOLTAGE, None))
    he_thong += [BangMacSensor(coordinator, entry), ThietBiLanSensor(coordinator, entry), CayThietBiSensor(coordinator, entry)]
    if coordinator.co_zte:
        he_thong += [ZteSoMaySensor(coordinator, entry, None), ZteSoMaySensor(coordinator, entry, "2.4G"),
                     ZteSoMaySensor(coordinator, entry, "5G"), ZteBoPhatSensor(coordinator, entry), ZteTrangThaiSensor(coordinator, entry)]
    async_add_entities(he_thong)
    _them_cam_bien_wifi(hass, entry, coordinator, async_add_entities)
    if coordinator.co_api:
        _them_cam_bien_toc_do_may(hass, entry, coordinator, async_add_entities)
        async_add_entities([ApiTrangThaiSensor(coordinator, entry)])


class _GiaoDien(CoordinatorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry: ConfigEntry, chi_so: int) -> None:
        super().__init__(coordinator)
        self._chi_so = chi_so
        self._entry = entry
        gd = coordinator.data["interfaces"][chi_so]
        self._ma = f"{coordinator.tien_to}_{gd['kind']}_{gd['slug']}"
        self._attr_device_info = thiet_bi_giao_dien(entry, chi_so, gd["name"])

    @property
    def _gd(self) -> dict[str, Any] | None:
        return (self.coordinator.data or {}).get("interfaces", {}).get(self._chi_so)

    @property
    def available(self) -> bool:
        return super().available and self._gd is not None


class ToCDoSensor(_GiaoDien, SensorEntity):
    _attr_device_class = SensorDeviceClass.DATA_RATE
    _attr_native_unit_of_measurement = UnitOfDataRate.MEGABITS_PER_SECOND
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, entry, chi_so, huong: str) -> None:
        super().__init__(coordinator, entry, chi_so)
        self._huong = huong
        self._attr_name = "Tốc độ nhận" if huong == "rx" else "Tốc độ gửi"
        self._attr_unique_id = f"{entry.entry_id}_{chi_so}_{huong}"
        self.entity_id = f"sensor.{self._ma}_{huong}"

    @property
    def native_value(self) -> float | None:
        gd = self._gd
        return gd.get(f"{self._huong}_mbps") if gd else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        gd = self._gd or {}
        ra = {"name": gd.get("name"), "type": gd.get("if_type"), "running": gd.get("up"), "speed_mbps": gd.get("speed_mbps")}
        if gd.get("comment"):
            ra["comment"] = gd["comment"]
        return {k: v for k, v in ra.items() if v is not None}


class TongByteSensor(_GiaoDien, SensorEntity):
    _attr_device_class = SensorDeviceClass.DATA_SIZE
    _attr_native_unit_of_measurement = UnitOfInformation.BYTES
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = True

    def __init__(self, coordinator, entry, chi_so, huong: str) -> None:
        super().__init__(coordinator, entry, chi_so)
        self._huong = huong
        self._attr_name = "Tổng nhận" if huong == "rx" else "Tổng gửi"
        self._attr_unique_id = f"{entry.entry_id}_{chi_so}_{huong}_total"
        self.entity_id = f"sensor.{self._ma}_{huong}_total"

    @property
    def native_value(self) -> int | None:
        gd = self._gd
        return gd.get(f"{self._huong}_octets") if gd else None


class LoiSensor(_GiaoDien, SensorEntity):
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:alert-circle-outline"

    def __init__(self, coordinator, entry, chi_so, khoa: str, ten: str) -> None:
        super().__init__(coordinator, entry, chi_so)
        self._khoa = khoa
        self._attr_name = ten
        self._attr_unique_id = f"{entry.entry_id}_{chi_so}_{khoa}"
        self.entity_id = f"sensor.{self._ma}_{khoa}"

    @property
    def native_value(self) -> int | None:
        gd = self._gd
        return gd.get(self._khoa) if gd else None


class HeThongSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry, ma: str, ten: str, khoa: str, don_vi, lop, bieu_tuong) -> None:
        super().__init__(coordinator)
        self._khoa = khoa
        self._attr_name = ten
        self._attr_unique_id = f"{entry.entry_id}_core_{ma}"
        self._attr_native_unit_of_measurement = don_vi
        self._attr_device_class = lop
        self._attr_icon = bieu_tuong
        if don_vi is not None:
            self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})
        self.entity_id = f"sensor.{coordinator.tien_to}_core_{ma}"

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("core", {}).get(self._khoa)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        core = (self.coordinator.data or {}).get("core", {})
        return {k: core[k] for k in ("descr", "name") if core.get(k)} if self._khoa == "uptime" else {}


class BangMacSensor(CoordinatorEntity, SensorEntity):
    """Bảng MAC theo cổng cho `mac_sensor` của card: trạng thái là tổng số MAC, thuộc tính là {tên cổng: [MAC…]}."""

    _attr_has_entity_name = True
    _attr_name = "Bảng MAC"
    _attr_icon = "mdi:table-network"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_bang_mac"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})
        self.entity_id = f"sensor.{coordinator.tien_to}_bang_mac"

    @property
    def native_value(self) -> int | None:
        dev = (self.coordinator.data or {}).get("devices", {})
        return sum(len(v) for v in dev.get("bang_mac", {}).values()) if dev.get("co_bang_mac") else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return dict((self.coordinator.data or {}).get("devices", {}).get("bang_mac", {}))


class ThietBiLanSensor(CoordinatorEntity, SensorEntity):
    """Danh sách thiết bị trong LAN (thuộc tính `clients`: mac, ip, interface) cho `sources` của card."""

    _attr_has_entity_name = True
    _attr_name = "Thiết bị trong LAN"
    _attr_icon = "mdi:lan"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_thiet_bi_lan"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})
        self.entity_id = f"sensor.{coordinator.tien_to}_thiet_bi_lan"

    @property
    def native_value(self) -> int | None:
        dev = (self.coordinator.data or {}).get("devices")
        return len(dev["clients"]) if dev else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"clients": list((self.coordinator.data or {}).get("devices", {}).get("clients", []))}


class CayThietBiSensor(CoordinatorEntity, SensorEntity):
    """Cây thiết bị cho card: thuộc tính `nodes` (router, cổng, ZTE kèm cha) và `clients` (mỗi máy có `parent`)."""

    _unrecorded_attributes = frozenset({"nodes", "clients"})   # không ghi vào cơ sở dữ liệu lịch sử
    _attr_has_entity_name = True
    _attr_name = "Cây thiết bị"
    _attr_icon = "mdi:file-tree"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_cay_thiet_bi"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})
        self.entity_id = f"sensor.{coordinator.tien_to}_cay_thiet_bi"

    @property
    def native_value(self) -> int | None:
        cay = (self.coordinator.data or {}).get("tree")
        return len(cay["clients"]) if cay else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        du = self.coordinator.data or {}
        cay = du.get("tree") or {"nodes": [], "clients": []}
        zte = du.get("zte") or {}
        return {"nodes": cay["nodes"], "clients": cay["clients"],
                "zte": {"host": zte.get("host"), "trang_thai": zte.get("trang_thai")} if zte else None}


def _may_wifi(coordinator, mac: str) -> dict[str, Any] | None:
    for may in ((coordinator.data or {}).get("tree") or {}).get("clients", []):
        if may["mac"] == mac and may.get("wifi"):
            return may
    return None


# loại → (tên hiển thị, khoá trong dữ liệu máy, đơn vị, lớp thiết bị, nhóm, biểu tượng): chỉ con của ZTE mới có
LOAI_WIFI = {
    "rssi": ("Cường độ tín hiệu", "rssi", "dBm", SensorDeviceClass.SIGNAL_STRENGTH, None, None),
    "band": ("Băng tần", "band", None, None, None, "mdi:wifi-marker"),
    "mode": ("Chế độ WiFi", "mode", None, None, None, "mdi:wifi-cog"),
    "assoc_s": ("Thời gian kết nối", "assoc_s", UnitOfTime.SECONDS, SensorDeviceClass.DURATION, None, None),
}


def _them_cam_bien_wifi(hass, entry, coordinator, async_add_entities) -> None:
    """Mỗi máy WiFi (con của ZTE) có bốn cảm biến; máy lần đầu thấy là WiFi hoặc đã từng thấy (còn trong sổ thực thể) thì dựng."""
    da_them: set[tuple[str, str]] = set()
    tien_to = f"{entry.entry_id}_"

    def _dung(mac: str, loai: str):
        if loai in LOAI_WIFI and (mac, loai) not in da_them:
            da_them.add((mac, loai))
            return CamBienWifiMay(coordinator, entry, mac, loai)
        return None

    cu = []
    for muc in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id):
        if muc.domain == "sensor" and muc.unique_id.startswith(tien_to):
            hau = muc.unique_id.removeprefix(tien_to)
            mac, _, loai = hau.partition("_")
            if len(mac) == 17 and (cb := _dung(mac.upper(), loai)):
                cu.append(cb)
    if cu:
        async_add_entities(cu)

    @callback
    def _them_moi() -> None:
        moi = []
        for may in ((coordinator.data or {}).get("tree") or {}).get("clients", []):
            if may.get("wifi"):
                for loai in LOAI_WIFI:
                    if (cb := _dung(may["mac"], loai)):
                        moi.append(cb)
        if moi:
            async_add_entities(moi)

    _them_moi()
    entry.async_on_unload(coordinator.async_add_listener(_them_moi))


class CamBienWifiMay(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry: ConfigEntry, mac: str, loai: str) -> None:
        super().__init__(coordinator)
        ten, self._khoa, don_vi, lop, nhom, bieu_tuong = LOAI_WIFI[loai]
        self._mac, self._entry_id = mac, entry.entry_id
        self._attr_name = ten
        self._attr_unique_id = f"{entry.entry_id}_{mac}_{loai}"
        self._attr_native_unit_of_measurement = don_vi
        self._attr_device_class = lop
        self._attr_entity_category = nhom
        self._attr_icon = bieu_tuong
        if don_vi is not None:
            self._attr_state_class = SensorStateClass.MEASUREMENT
        may = _may_wifi(coordinator, mac) or {}
        self._ten_cuoi = ten_thiet_bi(may, coordinator.data, mac)

    @property
    def device_info(self) -> DeviceInfo:
        # Cùng «kết nối MAC» với thực thể theo dõi → cùng MỘT thiết bị con trong sổ thiết bị.
        return DeviceInfo(connections={(CONNECTION_NETWORK_MAC, format_mac(self._mac))}, name=self._ten_cuoi,
                          via_device=dinh_danh_cha(self._entry_id, "zte", self.coordinator.data))

    @property
    def available(self) -> bool:
        return super().available and _may_wifi(self.coordinator, self._mac) is not None

    @property
    def native_value(self):
        may = _may_wifi(self.coordinator, self._mac)
        return may.get(self._khoa) if may else None


class _ZteThietBi(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, f"{entry.entry_id}_zte")})

    @property
    def _zte(self) -> dict[str, Any]:
        return (self.coordinator.data or {}).get("zte") or {}


class ZteSoMaySensor(_ZteThietBi):
    _unrecorded_attributes = frozenset({"clients"})
    _attr_icon = "mdi:wifi"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, entry, bang: str | None) -> None:
        super().__init__(coordinator, entry)
        self._bang = bang
        self._attr_name = "Máy WiFi" if bang is None else f"Máy WiFi {bang}"
        ma = "so_may" if bang is None else f"so_may_{bang.lower().replace('.', '_')}"
        self._attr_unique_id = f"{entry.entry_id}_zte_{ma}"
        self.entity_id = f"sensor.{coordinator.tien_to}_zte_{ma}"

    @property
    def native_value(self) -> int | None:
        if self._zte.get("trang_thai") in (None, "chua_doc"):
            return None
        ds = self._zte.get("clients") or []
        return len(ds) if self._bang is None else sum(1 for m in ds if m.get("band") == self._bang)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Cảm biến tổng: thuộc tính `clients` đúng khuôn mà `access_points[].clients_sensor` của card đọc."""
        if self._bang is not None:
            return {}
        return {"clients": [{"mac": str(m.get("mac", "")).lower(), "ip": m.get("ip", ""), "name": m.get("name", ""),
                             "band": m.get("band", ""), "rssi": m.get("rssi"), "mode": m.get("mode", "")}
                            for m in (self._zte.get("clients") or [])]}


class ZteBoPhatSensor(_ZteThietBi):
    _attr_name = "Bộ phát"
    _attr_icon = "mdi:router-wireless"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_zte_bo_phat"
        self.entity_id = f"sensor.{coordinator.tien_to}_zte_bo_phat"

    @property
    def native_value(self) -> str | None:
        ap = self._zte.get("ap") or {}
        return ap.get("firmware") or ap.get("name") or None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        ap = self._zte.get("ap") or {}
        ra = {k: v for k, v in ap.items() if k != "goc" and v not in (None, "")}
        ra.update(ap.get("goc") or {})
        return ra


class ZteTrangThaiSensor(_ZteThietBi):
    _attr_name = "Trạng thái đọc"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:lan-check"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_zte_trang_thai"
        self.entity_id = f"sensor.{coordinator.tien_to}_zte_trang_thai"

    @property
    def native_value(self) -> str | None:
        return self._zte.get("trang_thai")


class ApiTrangThaiSensor(CoordinatorEntity, SensorEntity):
    """Trạng thái đọc API chỉ-đọc: ok, kid_control_khong_co, loi_dang_nhap, loi_van_tay, loi_ket_noi, tam_ngung, loi."""

    _attr_has_entity_name = True
    _attr_name = "API trạng thái"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:api"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_api_trang_thai"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})
        self.entity_id = f"sensor.{coordinator.tien_to}_api_trang_thai"

    @property
    def native_value(self) -> str | None:
        return ((self.coordinator.data or {}).get("api") or {}).get("trang_thai")


def _may_cua(coordinator, mac: str) -> dict[str, Any] | None:
    for may in ((coordinator.data or {}).get("tree") or {}).get("clients", []):
        if may["mac"] == mac:
            return may
    return None


def _them_cam_bien_toc_do_may(hass, entry, coordinator, async_add_entities) -> None:
    """Tốc độ nhận (tải về) / gửi (tải lên) cho MỌI thiết bị, từ Kid Control. Máy lần đầu thấy hoặc đã từng thấy (sổ thực thể) thì dựng."""
    da_them: set[tuple[str, str]] = set()
    tien_to = f"{entry.entry_id}_"

    def _dung(mac: str, huong: str):
        if huong in ("rx", "tx") and (mac, huong) not in da_them:
            da_them.add((mac, huong))
            return CamBienTocDoMay(coordinator, entry, mac, huong)
        return None

    cu = []
    for muc in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id):
        if muc.domain == "sensor" and muc.unique_id.startswith(tien_to):
            mac, _, huong = muc.unique_id.removeprefix(tien_to).partition("_")
            if len(mac) == 17 and (cb := _dung(mac.upper(), huong)):
                cu.append(cb)
    if cu:
        async_add_entities(cu)

    @callback
    def _them_moi() -> None:
        moi = []
        for may in ((coordinator.data or {}).get("tree") or {}).get("clients", []):
            for huong in ("rx", "tx"):
                if (cb := _dung(may["mac"], huong)):
                    moi.append(cb)
        if moi:
            async_add_entities(moi)

    _them_moi()
    entry.async_on_unload(coordinator.async_add_listener(_them_moi))


class CamBienTocDoMay(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.DATA_RATE
    _attr_native_unit_of_measurement = UnitOfDataRate.MEGABITS_PER_SECOND
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, entry: ConfigEntry, mac: str, huong: str) -> None:
        super().__init__(coordinator)
        self._mac, self._huong, self._entry_id = mac, huong, entry.entry_id
        self._attr_name = "Tốc độ nhận (tải về)" if huong == "rx" else "Tốc độ gửi (tải lên)"
        self._attr_unique_id = f"{entry.entry_id}_{mac}_{huong}"
        self._attr_icon = "mdi:download-network" if huong == "rx" else "mdi:upload-network"
        self._ten_cuoi = ten_thiet_bi(_may_cua(coordinator, mac), coordinator.data, mac)

    @property
    def device_info(self) -> DeviceInfo:
        may = _may_cua(self.coordinator, self._mac) or {}
        return DeviceInfo(connections={(CONNECTION_NETWORK_MAC, format_mac(self._mac))}, name=self._ten_cuoi,
                          via_device=dinh_danh_cha(self._entry_id, may.get("parent"), self.coordinator.data))

    @property
    def available(self) -> bool:
        return super().available and _may_cua(self.coordinator, self._mac) is not None

    @property
    def native_value(self) -> float | None:
        may = _may_cua(self.coordinator, self._mac)
        return may.get(f"{self._huong}_mbps") if may else None
