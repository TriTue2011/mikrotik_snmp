# Mạng LAN: MikroTik (SNMP, chỉ đọc) + ZTE E2633 — tích hợp Home Assistant

Một tích hợp cho cả mạng nhà: đọc router **MikroTik** bằng **SNMPv3 chỉ đọc**, và (tuỳ chọn) đọc thêm bộ phát **ZTE E2633** để biết máy nào đang dùng WiFi.
Kết quả là một **cây thiết bị** `Router → Bridge → Cổng → ZTE → Máy` cùng tốc độ thời gian thực, đủ để card
[`mikrotik-topo-lan-card`](https://github.com/TriTue2011/mikrotik-topo-lan-card) tự vẽ sơ đồ mạng.

**Tại sao không dùng tích hợp MikroTik có sẵn?** Tích hợp đó cần tài khoản API có quyền ghi (`write`, `reboot`, `policy`…); ai lấy được mật khẩu trong cấu hình Home Assistant điều khiển được router.
Tích hợp này **không có đường ghi nào trong mã**: SNMP chỉ đọc, và API (nếu bật) chỉ gửi lệnh `…/print`, qua TLS có ghim vân tay chứng chỉ.

## Mục lục
1. [Nó làm gì](#nó-làm-gì) · 2. [Yêu cầu](#yêu-cầu) · 3. [Cài đặt](#cài-đặt) · 4. [Chuẩn bị MikroTik](#chuẩn-bị-mikrotik) ·
5. [Thêm tích hợp](#thêm-tích-hợp-vào-home-assistant) · 6. [Tuỳ chọn](#tuỳ-chọn-nút-bánh-răng) · 7. [Cây thiết bị](#cây-thiết-bị) ·
8. [Thực thể](#thực-thể) · 9. [Dùng với card](#dùng-với-card) · 10. [Bảo mật](#bảo-mật) · 11. [Khắc phục sự cố](#khắc-phục-sự-cố) ·
12. [Bộ phát chỉ cho một phiên](#bộ-phát-chỉ-cho-một-phiên-không-chạy-hai-tích-hợp-zte-cùng-lúc) · 13. [Thu log gỡ lỗi đã che](#cách-thu-log-gỡ-lỗi-đã-che) ·
14. [Trạng thái kiểm chứng](#trạng-thái-kiểm-chứng-nói-thật) · 15. [Thay đổi ở 0.7.2](#thay-đổi-ở-072) · [0.7.1](#thay-đổi-ở-071)

## Nó làm gì
Ba nguồn dữ liệu, **chỉ SNMP là bắt buộc**; hai nguồn còn lại tuỳ chọn và hỏng thì phần còn lại vẫn chạy:

| Nguồn | Bắt buộc | Cho ra |
|---|---|---|
| **MikroTik qua SNMPv3** | có | Tốc độ nhận/gửi từng cổng (Mbit/s, mỗi 5 giây), tổng byte, lỗi, trạng thái link; CPU, RAM, thời gian chạy, nhiệt độ, điện áp; bảng ARP và bảng MAC (máy nào, IP nào, cắm cổng nào) |
| **MikroTik qua API-SSL chỉ đọc** | không | **Tên máy** (ghi chú *Comment* của lease DHCP), **tốc độ từng máy** (Kid Control), **WireGuard** (peer, tốc độ, bắt tay), **cổng thuộc bridge nào** |
| **ZTE E2633 (trang quản trị web)** | không | Máy WiFi: tên, băng tần 2.4G/5G, tín hiệu (dBm), chế độ (802.11ax…), thời gian kết nối |

Giới hạn của thiết bị, không phải của tích hợp: SNMP của RouterOS không có tên máy và không có bộ đếm theo từng máy (nên mới cần API); ZTE E2633 luôn báo tốc độ từng máy bằng 0 (nên tốc độ từng máy lấy từ MikroTik).

## Yêu cầu
- Home Assistant **2024.11** trở lên; RouterOS **7**.
- Thư viện `pysnmp`: Home Assistant đã có nếu từng dùng tích hợp «SNMP». Nếu thiếu, thêm một cảm biến SNMP bất kỳ một lần để Home Assistant tự cài, rồi xoá cảm biến đó.
- Máy Home Assistant tới được router (UDP 161; TCP 8729 nếu dùng API) và tới được ZTE (HTTP/HTTPS) nếu dùng ZTE.

## Cài đặt
**Qua HACS (khuyến nghị):**
1. HACS → ⋮ → **Kho tuỳ chỉnh** → dán `https://github.com/TriTue2011/mikrotik_snmp`, loại **Tích hợp (Integration)** → Thêm.
2. Tìm «Mạng LAN: MikroTik (SNMP) + ZTE E2633» → **Tải xuống** → **khởi động lại Home Assistant**.

**Thủ công:** chép thư mục `custom_components/mikrotik_snmp` của kho này vào `/config/custom_components/`, rồi khởi động lại Home Assistant.

**Cập nhật:** khi có thay đổi mới trên kho, HACS báo cập nhật → Cập nhật → khởi động lại Home Assistant. Số phiên bản nằm ở `manifest.json` (hiện 0.7.1). Kho chưa phát hành bản đóng gói (Releases), nên HACS theo nhánh `main`.

## Chuẩn bị MikroTik
Thay `<IP_HA>` bằng địa chỉ máy chạy Home Assistant (ví dụ `192.168.88.10`). Chạy trong Terminal của WinBox hoặc SSH.
**Mật khẩu** do anh tự đặt: chỉ gồm chữ và số, tối thiểu 12 ký tự, mỗi mật khẩu một chuỗi riêng, tự sinh ngẫu nhiên
(`tr -dc 'A-Za-z0-9' </dev/urandom | head -c 24; echo`). Đừng dùng dấu nháy cong `“ ”` (bàn phím điện thoại hay tự đổi) và đừng dán mật khẩu vào chat hay nơi công khai.

### A. SNMPv3 chỉ đọc (bắt buộc)
```
/snmp community add name=hass security=private read-access=yes write-access=no \
    addresses=<IP_HA>/32 \
    authentication-protocol=SHA1 authentication-password=<MAT_KHAU_XAC_THUC> \
    encryption-protocol=AES encryption-password=<MAT_KHAU_MA_HOA>
/snmp community set [find name=public] disabled=yes
/snmp set enabled=yes
/ip firewall filter add chain=input protocol=udp dst-port=161 src-address=<IP_HA> action=accept \
    comment="SNMP chi tu HA" place-before=<SO_THU_TU_LUAT_CHAN>
```
`<SO_THU_TU_LUAT_CHAN>`: số thứ tự của luật chặn tất cả đầu vào (xem bằng `/ip firewall filter print`). **Luật chấp nhận phải nằm TRƯỚC luật chặn**, nếu không Home Assistant không tới được.
Tên người dùng SNMPv3 trong Home Assistant là tên community: `hass`.

### B. API-SSL chỉ đọc (tuỳ chọn, để có tên máy, tốc độ từng máy, WireGuard, cầu nối bridge)
```
# 1. Tài khoản chỉ có quyền api + read, chỉ đăng nhập được từ máy Home Assistant
/user group add name=ha-doc policy=api,read
/user add name=ha-doc group=ha-doc address=<IP_HA>/32 password=<MAT_KHAU_API>

# 2. Chứng chỉ tự ký cho API-SSL (cổng 8729)
/certificate add name=ha-api common-name=<IP_ROUTER> key-usage=tls-server days-valid=3650
/certificate sign ha-api

# 3. Bật API-SSL chỉ cho Home Assistant, tắt API chữ thường 8728
/ip service set api-ssl certificate=ha-api address=<IP_HA>/32 disabled=no
/ip service set api disabled=yes

# 4. Tường lửa (đặt trước luật chặn tất cả)
/ip firewall filter add chain=input protocol=tcp dst-port=8729 src-address=<IP_HA> action=accept \
    comment="API-SSL chi tu HA" place-before=<SO_THU_TU_LUAT_CHAN>
```
- **Tên máy**: đặt ghi chú cho lease DHCP, ví dụ `/ip dhcp-server lease set [find mac-address=AA:BB:CC:DD:EE:01] comment="Cam phong khach"`.
- **Tốc độ từng máy** cần **Kid Control** bật một lần (chỉ đo, không giới hạn gì):
  `/ip kid-control add name=ca-nha mon=0s-1d tue=0s-1d wed=0s-1d thu=0s-1d fri=0s-1d sat=0s-1d sun=0s-1d`.
  Không bật thì tên máy và WireGuard vẫn có, chỉ mất tốc độ từng máy (`api_trang_thai` = `kid_control_khong_co`).

## Thêm tích hợp vào Home Assistant
Cài đặt → Thiết bị & dịch vụ → **Thêm tích hợp** → «Mạng LAN: MikroTik (SNMP) + ZTE E2633». Các màn hình theo thứ tự:

| Bước | Điền |
|---|---|
| **1. MikroTik qua SNMP** | *Địa chỉ IP* của router; *Cổng SNMP* `161`; *Tên người dùng SNMPv3* `hass`; *Mật khẩu xác thực* và *Mật khẩu mã hoá* (hai chuỗi ở mục A); giao thức giữ mặc định `hmac-sha` và `aes-cfb-128` (khớp `SHA1`/`AES` ở trên); *Tiền tố tên thực thể* (mặc định `mikrotik_router`, **card dùng đúng tiền tố này**); *Chu kỳ đọc* (mặc định 5 giây, từ 2 đến 60) |
| **2. ZTE E2633 (tuỳ chọn)** | IP của ZTE, tên đăng nhập và mật khẩu **quản trị web** của ZTE (E2633 không có tài khoản chỉ đọc). Để trống IP để bỏ qua. Kiểm chứng chứng chỉ HTTPS thường để tắt |
| **3. API chỉ đọc (tuỳ chọn)** | Tên `ha-doc`, mật khẩu `<MAT_KHAU_API>`, cổng `8729`. Để trống tên để bỏ qua. Lần đầu tích hợp **ghim vân tay chứng chỉ** của router (xem [Bảo mật](#bảo-mật)) |
| **4. Chọn cổng** | Các cổng muốn hiện (đổi lại sau trong Tuỳ chọn) |

Mỗi bước kiểm kết nối ngay và báo lỗi rõ trên màn hình (sai mật khẩu, không tới được, vân tay khác…). Mật khẩu SNMP sai về sau thì Home Assistant hiện yêu cầu nhập lại, không cần xoá tích hợp.

## Tuỳ chọn (nút bánh răng)
Cài đặt → Thiết bị & dịch vụ → mục MikroTik → ⚙ **Tuỳ chọn**. Ba màn hình liên tiếp, bấm **Gửi** ở mỗi màn hình (Gửi xong tích hợp tự tải lại):
1. **Chung**: chu kỳ đọc; cổng hiển thị; **Tên thiết bị** — mỗi dòng `MAC = Tên`, ví dụ `AA:BB:CC:DD:EE:01 = Máy in` (dòng bắt đầu bằng `#` là ghi chú). Tên tự đặt ưu tiên hơn mọi nguồn khác.
2. **ZTE**: thêm, đổi hoặc tắt ZTE sau khi đã cài. Để trống mật khẩu = giữ mật khẩu cũ; để trống IP = tắt ZTE.
3. **API**: thêm, đổi hoặc tắt API chỉ đọc (tên `ha-doc`, mật khẩu, cổng 8729). Để trống mật khẩu = giữ cũ.

**Thứ tự ưu tiên tên máy:** tên tự đặt trong Tuỳ chọn › ghi chú (Comment) của lease DHCP › tên do ZTE báo › tên máy tự báo (`host-name`) › IP › MAC.

## Cây thiết bị
Mỗi thiết bị có thiết bị cha (`via_device`), nên **mở trang một thiết bị trong Home Assistant là thấy mục «Thiết bị được kết nối»** liệt kê các thiết bị bên trong:

```
MikroTik ─┬─ BridgeLAN ─┬─ ether2 ── ZTE E2633 ── máy WiFi (5G, −58 dBm, 802.11ax)
          │             │          └─ máy có dây
          │             └─ ether3 ── máy có dây
          ├─ WAN (cổng ra Internet, không thuộc bridge)
          └─ giao diện WireGuard ── peer
```
- **Máy WiFi** (MAC có trong danh sách máy của ZTE) là con của ZTE, kèm tên, băng tần, tín hiệu, chế độ, thời gian kết nối. Cần đã điền bước ZTE **và** ZTE đăng nhập được; nếu không, máy đó nằm dưới cổng mà nó được học.
- **Máy có dây** là con của **cổng** nó được học trên bảng MAC; không biết cổng thì là con của router.
- **ZTE** là con của cổng nó cắm vào (suy từ IP → MAC trong ARP → cổng trong bảng MAC).
- **Cổng thuộc bridge** là con của bridge (lấy từ API chỉ đọc); không có API thì cổng nằm trực tiếp dưới router. Cổng WAN và chính bridge nằm dưới router.
- **Peer WireGuard** là con của giao diện WireGuard của nó; không rõ giao diện thì là con của router.
- Tên thiết bị chỉ là tên máy (ví dụ «Máy in»), **không** kèm tên cổng: vị trí nằm ở thiết bị cha.
- Đổi cấu hình bridge trên router: vào ⚙ Tuỳ chọn bấm Gửi để cây cập nhật ngay; không thì cập nhật ở lần đọc tên kế tiếp (tối đa 1 phút).
- Cây cũng nằm trong cảm biến `sensor.<tiền_tố>_cay_thiet_bi` (thuộc tính `nodes` và `clients`, mỗi máy có `parent`); đó là thứ card đọc.

## Thực thể
`<tt>` là tiền tố đã chọn khi thêm tích hợp (mặc định `mikrotik_router`).

| Thực thể | Ý nghĩa |
|---|---|
| `sensor.<tt>_<loại>_<cổng>_rx` / `_tx` | Tốc độ nhận / gửi của cổng (Mbit/s). `<loại>` là `port`, `bridge` hoặc `ppp` |
| `sensor.<tt>_<loại>_<cổng>_rx_total` / `_tx_total` | Tổng byte nhận / gửi |
| `sensor.<tt>_<loại>_<cổng>_in_errors` / `_out_errors` | Lỗi nhận / gửi |
| `binary_sensor.<tt>_<loại>_<cổng>_connection` | Cổng đang nối hay không |
| `sensor.<tt>_core_cpu_load` `_memory_usage` `_uptime` `_temperature` `_voltage` | CPU %, RAM %, thời gian chạy, nhiệt độ, điện áp (cảm biến nào router không có thì bị bỏ) |
| `sensor.<tt>_cay_thiet_bi` | Cây thiết bị (card đọc) |
| `sensor.<tt>_bang_mac`, `sensor.<tt>_thiet_bi_lan` | Bảng MAC theo cổng; danh sách máy trong LAN (IP, MAC, cổng) |
| `sensor.<tt>_zte_so_may` (+ `_2_4g`, `_5g`), `_zte_bo_phat`, `_zte_trang_thai` | Số máy WiFi; thông tin bộ phát; trạng thái đọc ZTE |
| `sensor.<tt>_api_trang_thai` | Trạng thái API chỉ đọc |
| `sensor.<tt>_wireguard_<peer>_rx` / `_tx` / `_last_handshake`, `binary_sensor.<tt>_wireguard_<peer>_connected` | Peer WireGuard: tốc độ, giây từ lần bắt tay gần nhất, đang kết nối (bắt tay trong 3 phút) |
| Mỗi máy: `device_tracker` + cảm biến | Có mặt; máy WiFi có thêm *Cường độ tín hiệu*, *Băng tần*, *Chế độ WiFi*, *Thời gian kết nối*; có API thì có *Tốc độ nhận (tải về)* và *Tốc độ gửi (tải lên)* |

Giá trị của `sensor.<tt>_zte_trang_thai`: `ok`, `loi_dang_nhap`, `loi_ket_noi`, `tam_ngung`, `chua_doc`.
Giá trị của `sensor.<tt>_api_trang_thai`: `ok`, `kid_control_khong_co`, `loi_dang_nhap`, `loi_van_tay`, `loi_ket_noi`, `tam_ngung`, `chua_doc`.
`tam_ngung` = đang nghỉ 30 phút sau khi bị bộ phát từ chối đăng nhập (để không khoá tài khoản; lỗi mạng thường tự hồi phục, không tạm ngừng).

Nếu tích hợp MikroTik cũ hoặc `zte_e2633` riêng còn cài, mã thực thể có thể trùng (Home Assistant thêm đuôi `_2`): gỡ bản cũ trước, hoặc đặt tiền tố khác.

## Dùng với card
Cài card [`mikrotik-topo-lan-card`](https://github.com/TriTue2011/mikrotik-topo-lan-card) (từ 0.8) rồi thêm:
```yaml
type: custom:mikrotik-topo-lan-card
prefix: mikrotik_router                              # trùng «Tiền tố» khi thêm tích hợp
topo_sensor: sensor.mikrotik_router_cay_thiet_bi     # card tự dựng hộp và nối thiết bị từ cây
```
Thiết bị mới vào mạng thì tự có thực thể và tự nối vào sơ đồ. Chi tiết (đặt tên hộp, hiệu năng, khắc phục) ở README của card.

## Bảo mật
- **Không có đường ghi**: SNMP community `write-access=no`; máy khách SNMP không có lệnh SET (có test); máy khách API chỉ gửi lệnh kết thúc bằng `/print`, mọi lệnh khác bị từ chối **trước khi gửi** (có test).
- **API chỉ qua TLS** (cổng 8729) và **ghim vân tay SHA-256 của chứng chỉ**: lần đầu (khi bấm Gửi ở bước API) tích hợp đọc vân tay và lưu; từ đó chứng chỉ khác thì **không gửi mật khẩu**, báo `loi_van_tay`. Ghim lần đầu nên làm trong mạng nội bộ tin cậy. Đổi chứng chỉ trên router thì vào Tuỳ chọn › API bấm Gửi để ghim lại.
- **Quyền tối thiểu**: tài khoản API chỉ `api,read`, chỉ đăng nhập được từ IP của Home Assistant; SNMP chỉ cho IP của Home Assistant. Hai điều đó phải khớp luật tường lửa mục «Chuẩn bị MikroTik».
- **Chống khoá tài khoản**: sau một lần bị từ chối đăng nhập (ZTE hoặc API) tích hợp nghỉ 30 phút; lỗi mạng thường không kích hoạt tạm ngừng; mỗi lần đọc đăng nhập tối đa một lần; giữ một phiên suốt vòng đời coordinator.
- **Mật khẩu không vào log hay thông báo lỗi.** Chúng được lưu trong cấu hình Home Assistant như mọi tích hợp: bảo vệ máy chủ Home Assistant và bản sao lưu của nó.
- Dữ liệu từ router và ZTE (tên máy…) bị cắt độ dài và loại ký tự điều khiển trước khi dùng.

## Khắc phục sự cố
| Triệu chứng | Nguyên nhân thường gặp | Cách xử lý |
|---|---|---|
| Bước 1 báo «Router từ chối» | Sai tên `hass`, sai một trong hai mật khẩu, hoặc giao thức không khớp | Kiểm `/snmp community print`; giao thức phải là `hmac-sha` + `aes-cfb-128` khi router dùng SHA1/AES |
| Bước 1 báo «không tới được router» | Chưa có luật tường lửa UDP 161, hoặc luật nằm sau luật chặn | `/ip firewall filter print` rồi đưa luật SNMP lên trước luật chặn tất cả |
| Không có cổng nào | Quyền SNMP sai, hoặc thư viện `pysnmp` thiếu | Xem Nhật ký Home Assistant (lọc `mikrotik_snmp`) |
| Mật khẩu bị từ chối dù đúng | Mật khẩu có dấu nháy cong `“ ”` hoặc ký tự lạ | Đặt lại mật khẩu chỉ chữ và số |
| ZTE báo «từ chối đăng nhập» | Sai tên/mật khẩu **hoặc đang có phiên quản trị khác** (trình duyệt đang mở trang ZTE, tích hợp `zte_e2633` riêng, app) | Đóng mọi nơi đang đăng nhập ZTE, tắt `zte_e2633` riêng, chờ vài phút rồi Gửi lại |
| `zte_trang_thai` = `tam_ngung` | Bộ phát vừa TỪ CHỐI đăng nhập (sai mật khẩu hoặc tài khoản bị khoá); lỗi mạng không gây ra trạng thái này | Chờ 30 phút, hoặc ⚙ Tuỳ chọn › ZTE bấm Gửi để thử lại |
| Máy WiFi nằm dưới cổng, không dưới ZTE | ZTE chưa điền hoặc chưa đăng nhập được (`zte_trang_thai` ≠ `ok`); hoặc máy đó cắm dây qua ZTE (ZTE chỉ liệt kê máy WiFi) | Xử lý ZTE như dòng trên; máy cắm dây qua ZTE nằm dưới cổng là đúng |
| `api_trang_thai` = `loi_van_tay` | Chứng chỉ router đã đổi | ⚙ Tuỳ chọn › API bấm Gửi để ghim vân tay mới |
| `api_trang_thai` = `loi_ket_noi` | Chưa mở 8729 cho IP Home Assistant | `/ip service print` (api-ssl bật, `address` đúng), luật tường lửa TCP 8729 |
| `api_trang_thai` = `kid_control_khong_co` | Kid Control chưa bật | Chạy lệnh `/ip kid-control add …` ở mục B |
| Máy không có tên (chỉ IP/MAC) | Lease DHCP chưa có Comment, hoặc máy dùng IP tĩnh không có lease | Đặt Comment cho lease, hoặc dùng *Tên thiết bị* trong Tuỳ chọn |
| Tốc độ từng máy luôn 0 | Kid Control chưa bật, hoặc máy chưa có lưu lượng | Bật Kid Control; ZTE không đo được tốc độ từng máy |
| Không thấy bridge trong cây | Chưa bật API chỉ đọc | Điền bước API (mục B) |
| Thực thể có đuôi `_2` | Tích hợp cũ cùng tiền tố còn tồn tại | Gỡ tích hợp/thực thể cũ, hoặc dùng tiền tố khác |
| Sau cập nhật card vẫn thấy giao diện cũ | Trình duyệt/app giữ bản cũ trong bộ nhớ đệm | Xem README của card, mục «Cập nhật và kiểm phiên bản» |

Muốn xem log chi tiết, thêm vào `configuration.yaml`: `logger: { logs: { custom_components.mikrotik_snmp: debug } }`. Log không chứa mật khẩu.

## Bộ phát chỉ cho một phiên: không chạy hai tích hợp ZTE cùng lúc
Bộ phát ZTE E2633 có thể chỉ cho **MỘT** phiên quản trị hoạt động tại một thời điểm:
- Không chạy cùng lúc tích hợp này với tích hợp ZTE khác (ví dụ tích hợp riêng `zte_e2633`) hoặc ứng dụng điện thoại / trang quản trị trong trình duyệt trên cùng tài khoản.
- Chu kỳ đọc ZTE hiện tại là `CHU_KY_ZTE_GIAY` = 15 giây. Nếu thấy bộ phát khoá hoặc trả «页面过期» (nguyên văn của thiết bị: "trang đã hết hạn"), hãy đóng các phiên quản trị khác; nếu vẫn bị, tăng hằng số `CHU_KY_ZTE_GIAY` trong `custom_components/mikrotik_snmp/const.py` (hiện chưa có ô cấu hình để đổi, phải sửa mã). Không đổi giá trị mặc định nếu không có bằng chứng.

## Cách thu log gỡ lỗi đã che
Khi cần gửi nhật ký để nhờ hỗ trợ hoặc mở issue, hãy làm theo các bước sau để đảm bảo không lộ thông tin mạng nhà:
1. Thêm cấu hình logger vào `configuration.yaml`:
   ```yaml
   logger:
     default: info
     logs:
       custom_components.mikrotik_snmp: debug
   ```
2. Lọc nhật ký và chạy công cụ che tự động kèm theo kho:
   ```bash
   grep mikrotik_snmp config/home-assistant.log | python3 scripts/che_log.py > log_da_che.txt
   ```
3. **Nhắc nhở quan trọng**: Tự mở và đọc lại tệp `log_da_che.txt` trước khi đăng. TUYỆT ĐỐI không đăng nhật ký gốc chưa che, không chụp ảnh màn hình trang quản trị bộ phát hay gửi cookie phiên.

## Trạng thái kiểm chứng (nói thật)
- **Kiểm bằng router và ZTE giả + lõi Home Assistant thật** (`python3 -m unittest discover -s tests -p "test_*.py"`, 141 test): tốc độ từ bộ đếm 64-bit và tràn bộ đếm, router khởi động lại, phân tích bảng giao diện/ARP/bảng MAC, gộp cây, phân loại lỗi kết nối / từ chối đăng nhập ZTE, kiểm soát kích thước thuộc tính recorder (ngăn tràn 16 KB), máy khách API chỉ cho lệnh `print`, ghim vân tay, cổng thuộc bridge.
- **Đã chạy trên một nhà thật** (RouterOS 7, ZTE E2633, Home Assistant): đọc cổng và tốc độ, cây thiết bị, tên máy từ DHCP, máy WiFi dưới ZTE, WireGuard.
- **Chưa kiểm với bộ phát thật và Home Assistant đang chạy thật** cho các thay đổi mới ở phiên bản 0.7.1.
- **Chưa kiểm trên nhiều cấu hình**: định dạng thật của `/interface/bridge/port/print` trên nhiều bản RouterOS; nhiệt độ/điện áp (`MIKROTIK-MIB`) và RAM (`hrStorage`) có thể khác theo bo mạch (thiếu thì cảm biến bị bỏ); các bản firmware ZTE khác E2633.

## Thay đổi ở 0.7.2
- **Icon riêng** cho tích hợp trong Home Assistant (`custom_components/mikrotik_snmp/brand/`): router có hai antenna và sóng WiFi, kèm bản cho nền tối. Home Assistant có hỗ trợ thư mục `brand/` tự nạp (đã thấy trong 2026.10.3; bản cũ hơn chưa kiểm). Không đổi mã.

## Thay đổi ở 0.7.1
- **Điểm 2 — Đọc WiFi hỏng không thành «không có máy»**: Xử lý dữ liệu ZTE sai khuôn (`DuLieuSaiKhuon`): phân tích lỗi đọc do bộ phát trả kiểu lạ hoặc đổi tên trường thành `ZteLoiKetNoi`, giữ danh sách máy WiFi cũ và đánh dấu thực thể WiFi `available = False` (không coi là "không có máy", tránh làm mọi thiết bị theo dõi WiFi chuyển "vắng" hàng loạt). Thiết bị có dây MikroTik vẫn sống và `available = True`.
- **Điểm 3 — Phiên và backoff**: Phân loại lỗi bằng cấu trúc: `ZteLoiDangNhap` chỉ xảy ra khi bộ phát từ chối tài khoản (chỉ loại lỗi này mới tạm ngừng 30 phút); mất mạng, trang khởi động lại không có token, token rỗng, lỗi HTTP ở trang lấy token thành `ZteLoiKetNoi` và hồi phục ngay ở chu kỳ sau khi bộ phát sống lại; bắt `HTTPError` trước `URLError`, đóng socket tránh rò rỉ (`ResourceWarning`); thêm `dang_xuat()` khi gỡ tích hợp để quên phiên phía máy khách; bổ sung debug log không chứa thông tin nhạy cảm.
- **Điểm 4 — Ngăn tràn bộ nhớ recorder (16 KB)**: Khai báo `_unrecorded_attributes` cho `BangMacSensor` (`MATCH_ALL`) và `ThietBiLanSensor` (`clients`) bên cạnh `ZteSoMaySensor` và `CayThietBiSensor` để tránh vượt ngưỡng 16384 byte của recorder khi mạng LAN có nhiều thiết bị.
- **Điểm 5 — Bộ test mức coordinator trên lõi Home Assistant thật**: Thêm `tests/test_dieu_phoi_ha.py` (9 ca test trên lõi Home Assistant thật với mock router và máy chủ ZTE giả) và `tests/test_zte_loi.py` (26 test kiểm tra phân loại lỗi và phục hồi ZTE).
- **Công cụ che log**: Cập nhật `scripts/che_log.py` và `tests/test_che_log.py` cho `mikrotik_snmp`.

## Phát triển
```
python3 -m unittest discover -s tests -p "test_*.py"
```
Mã nằm ở `custom_components/mikrotik_snmp/`: `snmp_client.py` (SNMP), `routeros_api.py` + `nguon_api.py` (API chỉ đọc), `zte_api.py` + `zte_nguon.py` (ZTE), `thu_thap.py` (gộp dữ liệu), `cay.py` (dựng cây), `thiet_bi.py` (cây trong sổ thiết bị), `config_flow.py`.

