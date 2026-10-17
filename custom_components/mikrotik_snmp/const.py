"""Hằng số của tích hợp MikroTik (SNMP, chỉ đọc)."""

DOMAIN = "mikrotik_snmp"

CONF_HOST = "host"
CONF_PORT = "port"
CONF_TEN = "ten"
CONF_AUTH_KEY = "auth_key"
CONF_PRIV_KEY = "priv_key"
CONF_AUTH_PROTOCOL = "auth_protocol"
CONF_PRIV_PROTOCOL = "priv_protocol"
CONF_CHU_KY = "chu_ky"
CONF_TIEN_TO = "tien_to"
CONF_CONG = "cong"
CONF_TEN_MAY = "ten_may"

CONF_ZTE_HOST = "zte_host"
CONF_ZTE_TEN = "zte_ten"
CONF_ZTE_MAT_KHAU = "zte_mat_khau"
CONF_ZTE_SSL = "zte_xac_minh_ssl"

PORT_MAC_DINH = 161
CHU_KY_MAC_DINH = 5
CHU_KY_NHO_NHAT = 2
CHU_KY_LON_NHAT = 60
TIEN_TO_MAC_DINH = "mikrotik_router"
AUTH_MAC_DINH = "hmac-sha"
PRIV_MAC_DINH = "aes-cfb-128"
# Thông tin chậm đổi (trạng thái, lỗi, nhiệt độ…) chỉ hỏi mỗi từng ấy giây; bộ đếm lưu lượng hỏi mỗi chu kỳ.
CHU_KY_CHAM_GIAY = 30
# ZTE (máy WiFi) đọc mỗi từng ấy giây; sau lỗi đăng nhập nghỉ THOI_GIAN_TAM_DUNG giây.
CHU_KY_ZTE_GIAY = 15
THOI_GIAN_TAM_DUNG = 1800
# Bảng ARP và bảng MAC (máy nào, IP nào, cổng nào) đọc mỗi từng ấy giây.
CHU_KY_THIET_BI_GIAY = 15
# Danh sách giao diện chỉ dò lại sau từng ấy giây (giao diện mới xuất hiện).
CHU_KY_DO_LAI_GIAY = 600
# Mỗi lần hỏi chỉ gửi từng ấy OID để không vượt kích thước gói SNMP.
TOI_DA_OID_MOI_LAN = 20
# Chặn vòng lặp vô hạn khi duyệt một bảng.
TOI_DA_BUOC_DUYET = 400

AUTH_PROTOCOLS = ["hmac-md5", "hmac-sha", "hmac128-sha224", "hmac192-sha256", "hmac256-sha384", "hmac384-sha512"]
PRIV_PROTOCOLS = ["des", "3des-ede", "aes-cfb-128", "aes-cfb-192", "aes-cfb-256"]
