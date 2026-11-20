#!/usr/bin/env python3
"""Lấy khoá Google (refresh token) cho dang_video.py. Chạy 1 lần trên Mac, khoá KHÔNG in ra chat.

  python3 lay_khoa_google.py <file client_secret_xxx.json tải từ Google Cloud>

Mở link in ra bằng trình duyệt ĐANG ĐĂNG NHẬP tài khoản Google sở hữu kênh YouTube Antimusic, bấm Cho phép.
Khoá lưu vào ~/.config/tu-dong-dang-video/google.json (chỉ anh đọc được). Script in tên kênh để kiểm đúng kênh.
"""
import json, os, sys, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

CONG = 8799
QUYEN = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly",
         "https://www.googleapis.com/auth/drive.readonly", "https://www.googleapis.com/auth/spreadsheets"]
RA = os.path.expanduser("~/.config/tu-dong-dang-video/google.json")


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    c = json.load(open(sys.argv[1]))
    c = c.get("installed") or c.get("web")
    redirect = f"http://127.0.0.1:{CONG}/"
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": c["client_id"], "redirect_uri": redirect, "response_type": "code",
        "scope": " ".join(QUYEN), "access_type": "offline", "prompt": "consent"})
    ma = {}

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            ma.update({k: v[0] for k, v in q.items()})
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.end_headers()
            self.wfile.write("Xong. Quay lại Claude, đóng tab này được.".encode())

        def log_message(self, *a):
            pass

    print("Mở link này, chọn tài khoản Google của kênh YouTube Antimusic, bấm Cho phép:\n\n" + url + "\n", flush=True)
    sv = HTTPServer(("127.0.0.1", CONG), H)
    while "code" not in ma and "error" not in ma:
        sv.handle_request()
    if "error" in ma:
        sys.exit(f"Google báo: {ma['error']} (anh bấm Huỷ hoặc thiếu quyền). Chạy lại lệnh.")
    tk = json.loads(urllib.request.urlopen("https://oauth2.googleapis.com/token", urllib.parse.urlencode({
        "code": ma["code"], "client_id": c["client_id"], "client_secret": c["client_secret"],
        "redirect_uri": redirect, "grant_type": "authorization_code"}).encode()).read())
    if "refresh_token" not in tk:
        sys.exit("Không nhận được refresh token. Vào myaccount.google.com/permissions gỡ app rồi chạy lại.")
    req = urllib.request.Request("https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true",
                                 headers={"Authorization": f"Bearer {tk['access_token']}"})
    kenh = [i["snippet"]["title"] for i in json.loads(urllib.request.urlopen(req).read()).get("items", [])]
    os.makedirs(os.path.dirname(RA), exist_ok=True)
    with open(os.open(RA, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        json.dump({"GOOGLE_CLIENT_ID": c["client_id"], "GOOGLE_CLIENT_SECRET": c["client_secret"],
                   "GOOGLE_REFRESH_TOKEN": tk["refresh_token"]}, f, indent=1)
    print(f"ĐÃ LƯU khoá vào {RA}")
    print("Kênh YouTube của tài khoản này:", ", ".join(kenh) or "KHÔNG CÓ KÊNH (sai tài khoản? chạy lại, chọn tài khoản khác)")


if __name__ == "__main__":
    main()
