# MikroTik (SNMP, chỉ đọc) — tích hợp Home Assistant

Đọc router MikroTik qua **SNMPv3** và đưa vào Home Assistant: **tốc độ nhận/gửi từng cổng (Mbit/s, cập nhật mỗi vài giây)**, trạng thái cổng,
lỗi/gói loại bỏ, CPU, bộ nhớ, thời gian chạy, nhiệt độ, điện áp. **Không mở cổng API** của router và **không có lệnh ghi nào**: máy khách chỉ gửi
`GET`/`GETNEXT` (có test kiểm không có `set`).

Tên thực thể đặt theo quy ước của card [`mikrotik-topo-lan-card`](https://github.com/TriTue2011/mikrotik-topo-lan-card), nên card tự nhận,
không cần cấu hình thêm khi tiền tố là `mikrotik_router`.

## Cái có và cái KHÔNG có (so với tích hợp «MikroTik Extended» dùng API)
| Có (qua SNMP) | KHÔNG có (SNMP của RouterOS không cung cấp) |
|---|---|
| Tốc độ từng cổng, tổng byte, lỗi, trạng thái link | Tốc độ **từng máy** (kid-control/accounting) |
| CPU, RAM, thời gian chạy, nhiệt độ, điện áp | Tên máy từ DHCP (chỉ có qua API) |
| Cổng ảo (bridge, PPPoE) | Chi tiết WireGuard (peer, handshake) |
| **Máy nào, IP nào, cắm cổng nào** (ARP + bảng MAC của bridge, 15 giây/lần) | |
| | Công tắc bật/tắt cổng, luật tường lửa, nút khởi động lại, cập nhật |

## Thiết lập router (RouterOS 7), SNMPv3 chỉ đọc, chỉ cho máy Home Assistant
```
/snmp community add name=hass security=private read-access=yes write-access=no \
    addresses=<IP_HOME_ASSISTANT>/32 \
    authentication-protocol=SHA1 authentication-password=<MAT_KHAU_1> \
    encryption-protocol=AES encryption-password=<MAT_KHAU_2>
/snmp community set [find name=public] disabled=yes
/snmp set enabled=yes
/ip firewall filter add chain=input protocol=udp dst-port=161 src-address=<IP_HOME_ASSISTANT> action=accept \
    comment="SNMP chi tu HA" place-before=[find comment="INPUT: DROP ALL OTHER"]
```
Luật tường lửa phải đứng **trước** luật chặn tất cả. Mật khẩu chỉ gồm chữ và số, tối thiểu 12 ký tự, hai chuỗi khác nhau, tự sinh ngẫu nhiên.
Không dùng nháy kép cong `“ ”` (bàn phím điện thoại hay tự đổi): thư viện SNMP không mã hoá được.

## Cài đặt
1. HACS → Kho tuỳ chỉnh → `https://github.com/TriTue2011/mikrotik_snmp` → loại *Integration* → tải → khởi động lại Home Assistant.
2. Cài đặt → Thiết bị & dịch vụ → Thêm tích hợp → **MikroTik (SNMP, chỉ đọc)**: nhập IP, người dùng (`hass`), hai mật khẩu, rồi chọn cổng.
3. Nút bánh răng: đổi chu kỳ đọc (mặc định 5 giây) và cổng hiển thị.

Cần thư viện `pysnmp`: Home Assistant đã có nếu từng dùng tích hợp «SNMP». Thiếu thì thêm một cảm biến SNMP bất kỳ một lần để Home Assistant cài nó.

## Dùng với card (không cần tích hợp MikroTik cũ)
```yaml
type: custom:mikrotik-topo-lan-card
prefix: mikrotik_router          # trùng «Tiền tố» khi thêm tích hợp
mac_sensor: sensor.mikrotik_router_bang_mac      # card tự biết máy nào sau cổng nào (switch SW1/SW2…)
sources:
  - node: LAN                    # tên không trùng hộp nào: thiết bị vào LAN, rồi được xếp theo cổng
    entity: sensor.mikrotik_router_thiet_bi_lan
    attribute: clients
```
Tên máy không có trong SNMP: dùng `device_names` (theo MAC) của card, hoặc tên từ cảm biến ZTE.

## Thực thể
Với mỗi cổng (`<loại>` là `port`, `bridge` hoặc `ppp`; `<cổng>` là tên cổng viết thường, ví dụ `ether2`, `bridgelan`):
`sensor.<tiền_tố>_<loại>_<cổng>_rx|tx` (Mbit/s), `…_rx_total|tx_total` (byte), `…_in_errors|out_errors`,
`binary_sensor.<tiền_tố>_<loại>_<cổng>_connection`. Của router: `sensor.<tiền_tố>_core_cpu_load|memory_usage|uptime|temperature|voltage`, `sensor.<tiền_tố>_bang_mac` (thuộc tính `{cổng: [MAC…]}` cho `mac_sensor` của card), `sensor.<tiền_tố>_thiet_bi_lan` (thuộc tính `clients`: `mac`, `ip`, `interface`).
Nếu tích hợp MikroTik cũ còn cài, mã thực thể trùng nhau và Home Assistant thêm đuôi `_2`: gỡ tích hợp cũ trước, hoặc đặt tiền tố khác.

## Trạng thái kiểm chứng (nói thật)
- Logic (tính tốc độ từ bộ đếm 64-bit, tràn bộ đếm, router khởi động lại, phân tích bảng giao diện, chia nhóm OID) kiểm bằng **router giả**:
  `python3 -m unittest discover -s tests -p "test_*.py"`.
- Phần gọi `pysnmp` (GET đã chạy được trong container Home Assistant; GETNEXT để duyệt bảng và OID bảng ARP/bảng MAC của bridge **chưa kiểm trên router thật**) và phần giao diện Home Assistant
  (màn hình cấu hình, thực thể) **chưa chạy thử trong Home Assistant thật**.
- OID nhiệt độ/điện áp (`MIKROTIK-MIB`) và RAM (`hrStorage`) có thể khác theo bo mạch: thiếu thì cảm biến bị bỏ, không báo lỗi.

## Phát triển
```
python3 -m unittest discover -s tests -p "test_*.py"
```
