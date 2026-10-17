# Mạng LAN: MikroTik (SNMP, chỉ đọc) + ZTE E2633 — tích hợp Home Assistant

Một tích hợp cho cả nhà: đọc router **MikroTik qua SNMPv3** (chỉ đọc, không mở cổng API) và, nếu có bộ phát **ZTE E2633**, đăng nhập thêm vào ZTE
để các máy WiFi hiện làm **con của ZTE** kèm thông tin MikroTik không có. Dữ liệu cập nhật vài giây, tên thực thể theo quy ước card
[`mikrotik-topo-lan-card`](https://github.com/TriTue2011/mikrotik-topo-lan-card).

## Cây thiết bị
```
MikroTik (router)
├─ ether2 (SW1)  ─ máy A, máy B …            ← máy có dây: con của cổng nó được học
├─ ether4 (SW2)
│   └─ ZTE E2633 ─ điện thoại (5G, −58 dBm, 802.11ax), laptop …   ← máy WiFi: con của ZTE
│   └─ máy C (có dây qua SW2)
└─ BridgeLAN …
```
Quy tắc: MAC có trong danh sách máy WiFi của ZTE thì là con của ZTE (kèm tên máy, băng tần, tín hiệu, chế độ, thời gian kết nối); MAC còn lại là con
của **cổng** nó được học trên bảng MAC; ZTE là con của cổng mà nó cắm vào (suy từ IP → MAC → cổng). Cây này hiện đúng trong sổ thiết bị của Home Assistant
(mỗi máy là thiết bị con) và trong cảm biến `sensor.<tiền_tố>_cay_thiet_bi` (thuộc tính `nodes`, `clients` có `parent`).

## Có gì
| Từ MikroTik (SNMP) | Từ ZTE (web, tuỳ chọn) |
|---|---|
| Tốc độ nhận/gửi từng cổng, Mbit/s, mỗi 5 giây; tổng byte; lỗi; trạng thái link | Tên máy WiFi, băng tần 2.4G/5G |
| CPU, RAM, thời gian chạy, nhiệt độ, điện áp | Cường độ tín hiệu (dBm), chế độ WiFi (802.11ax…) |
| ARP + bảng MAC: máy nào, IP nào, cắm cổng nào (15 giây/lần) | Thời gian kết nối, mọi trường gốc của bộ phát (thuộc tính) |

**Không có** (SNMP của RouterOS và bộ phát E2633 không cung cấp): tốc độ **từng máy** (ZTE luôn trả 0), tên máy từ DHCP, chi tiết WireGuard,
công tắc điều khiển. Tên máy: dùng tên từ ZTE (máy WiFi) hoặc `device_names` (theo MAC) của card.

## Thiết lập MikroTik (RouterOS 7), SNMPv3 chỉ đọc, chỉ cho máy Home Assistant
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

## ZTE E2633 (tuỳ chọn)
Bước thứ hai của màn hình thêm tích hợp. Cần **tài khoản quản trị web của ZTE** (E2633 không có tài khoản chỉ đọc): tích hợp chỉ đọc danh sách máy,
**không ghi gì**, mỗi lần đọc đăng nhập tối đa một lần, và sau một lần đăng nhập thất bại thì **nghỉ 30 phút** để không khoá tài khoản.
Mật khẩu không vào log. Để trống IP để bỏ qua; khi ZTE lỗi, phần MikroTik vẫn chạy bình thường (trạng thái ở `sensor.<tiền_tố>_zte_trang_thai`).

## Cài đặt
1. HACS → Kho tuỳ chỉnh → `https://github.com/TriTue2011/mikrotik_snmp` → loại *Integration* → tải → khởi động lại Home Assistant.
2. Cài đặt → Thiết bị & dịch vụ → Thêm tích hợp → **Mạng LAN: MikroTik (SNMP) + ZTE E2633**: nhập IP router, người dùng (`hass`), hai mật khẩu;
   (tuỳ chọn) IP và tài khoản ZTE; rồi chọn cổng.
3. Nút bánh răng: đổi chu kỳ đọc (mặc định 5 giây), cổng hiển thị, và **Tên thiết bị** (mỗi dòng `MAC = Tên`; SNMP không có tên máy nên anh tự đặt,
   hoặc lấy tên từ ZTE cho máy WiFi). Tên thiết bị hiển thị dạng `ether3 · Máy in` nên danh sách thiết bị của Home Assistant xếp các máy cùng cổng liền nhau.

Cần thư viện `pysnmp`: Home Assistant đã có nếu từng dùng tích hợp «SNMP». Nếu thiếu, thêm một cảm biến SNMP bất kỳ một lần để Home Assistant cài nó.

## Dùng với card — tự nối thiết bị vào sơ đồ (card từ 0.8.0)
```yaml
type: custom:mikrotik-topo-lan-card
prefix: mikrotik_router
topo_sensor: sensor.mikrotik_router_cay_thiet_bi   # card tự dựng hộp (cổng, ZTE) và đặt từng máy vào hộp của cha nó
port_names: { ether2: SW1, ether4: SW2, bridgelan: BRIDGE LAN }
```
Thiết bị mới xuất hiện trong mạng thì tự có thực thể và tự nối vào sơ đồ, không cần khai gì thêm.

## Cách cũ: khai nguồn tay (không cần `topo_sensor`)
```yaml
type: custom:mikrotik-topo-lan-card
prefix: mikrotik_router                       # trùng «Tiền tố» khi thêm tích hợp
mac_sensor: sensor.mikrotik_router_bang_mac   # card tự biết máy nào sau cổng nào (SW1, SW2…)
access_points:
  - name: ZTE WiFi
    switch: SW2
    ips: [172.16.10.24]
    clients_sensor: sensor.mikrotik_router_zte_so_may     # máy WiFi (thuộc tính `clients`)
    fields:
      - { label: Phần mềm, entity: sensor.mikrotik_router_zte_bo_phat }
sources:
  - node: LAN                                  # mọi thiết bị trong LAN (IP, MAC, cổng)
    entity: sensor.mikrotik_router_thiet_bi_lan
    attribute: clients
```

## Thực thể chính
- Mỗi cổng (`<loại>` là `port`, `bridge` hoặc `ppp`): `sensor.<tiền_tố>_<loại>_<cổng>_rx|tx` (Mbit/s), `…_rx_total|tx_total`, `…_in_errors|out_errors`,
  `binary_sensor.<tiền_tố>_<loại>_<cổng>_connection`.
- Router: `sensor.<tiền_tố>_core_cpu_load|memory_usage|uptime|temperature|voltage`, `_bang_mac`, `_thiet_bi_lan`, `_cay_thiet_bi`.
- ZTE: `sensor.<tiền_tố>_zte_so_may` (+ `_2_4g`, `_5g`), `_zte_bo_phat`, `_zte_trang_thai`.
- Mỗi máy: một thiết bị con với `device_tracker`; máy WiFi có thêm Cường độ tín hiệu, Băng tần, Chế độ WiFi, Thời gian kết nối.

Nếu tích hợp MikroTik cũ hoặc `zte_e2633` còn cài, mã thực thể có thể trùng (Home Assistant thêm đuôi `_2`): gỡ bản cũ trước, hoặc đặt tiền tố khác.

## Trạng thái kiểm chứng (nói thật)
- Logic (tốc độ từ bộ đếm 64-bit, tràn bộ đếm, router khởi động lại, phân tích bảng giao diện/ARP/bảng MAC, **gộp cây MikroTik + ZTE**, chu kỳ và chốt nghỉ của ZTE)
  và máy khách web ZTE kiểm bằng **router/ZTE giả**: `python3 -m unittest discover -s tests -p "test_*.py"` (49 test).
- Phần gọi `pysnmp` (GET đã chạy được trong container Home Assistant; GETNEXT để duyệt bảng, OID bảng ARP/bảng MAC chưa kiểm trên router thật), luồng đăng nhập
  ZTE (đã đọc thành công một lần bằng script độc lập) và giao diện Home Assistant (màn hình cấu hình, cây thiết bị, thực thể) **chưa chạy thử trong Home Assistant thật**.
- OID nhiệt độ/điện áp (`MIKROTIK-MIB`) và RAM (`hrStorage`) có thể khác theo bo mạch: thiếu thì cảm biến bị bỏ.

## Phát triển
`python3 -m unittest discover -s tests -p "test_*.py"`
