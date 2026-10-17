"""Cảm biến: tốc độ nhận/gửi từng cổng (Mbit/s), tổng byte, lỗi, và thông tin router (CPU, RAM, thời gian chạy, nhiệt độ, điện áp).

Mã thực thể đặt theo quy ước của card `mikrotik-topo-lan-card`: sensor.<tiền_tố>_(port|bridge|ppp)_<cổng>_(rx|tx|rx_total|tx_total),
sensor.<tiền_tố>_core_(cpu_load|memory_usage|uptime|temperature|voltage).
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, PERCENTAGE, UnitOfDataRate, UnitOfElectricPotential, UnitOfInformation, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


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
    he_thong += [BangMacSensor(coordinator, entry), ThietBiLanSensor(coordinator, entry)]
    async_add_entities(he_thong)


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
