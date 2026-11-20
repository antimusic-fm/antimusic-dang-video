#!/usr/bin/env python3
"""Tự đăng video lên YouTube + Instagram theo lịch trong Google Sheet (hoặc file CSV khi chạy thử).

Chỉ đăng dòng có trang_thai = "da-duyet" và gio_dang (giờ Hà Nội) đã tới. Đăng xong ghi "da-dang" + link,
lỗi ghi "loi" + lý do, nên chạy lại không đăng trùng. Chỉ dùng thư viện có sẵn của Python.

Lệnh:
  python3 dang_video.py --xem                   # liệt kê dòng sắp/đến giờ đăng, không đăng
  python3 dang_video.py --dry-run               # đi hết các bước, không gọi API đăng, không ghi Sheet
  python3 dang_video.py                         # chạy thật (GitHub Actions gọi lệnh này 4 lần/giờ)
  python3 dang_video.py --lich lich.csv --video-thu-muc ./video --dry-run   # chạy thử trên máy, không cần Google
  thêm --json để in kết quả dạng JSON. Mã thoát: 0 = ổn, 1 = có dòng lỗi, 2 = thiếu cấu hình.

Biến môi trường (khoá nằm trong GitHub Secrets, KHÔNG ghi vào file):
  GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN   quyền: youtube.upload, drive.readonly, spreadsheets
  SHEET_ID, SHEET_TAB (mặc định "Lich")
  IG_USER_ID, IG_TOKEN, IG_HOST (mặc định graph.facebook.com; dùng graph.instagram.com nếu đăng nhập bằng Instagram)
  YT_CHE_DO (private | unlisted | public; mặc định private cho tuần chạy thử)
  BAO_WEBHOOK (tuỳ chọn: webhook bot Lark để nhắn kết quả)
"""
import argparse, csv, json, os, subprocess, sys, tempfile, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone, timedelta

HN = timezone(timedelta(hours=7))
COT = ["brand", "gio_dang", "kenh", "file_drive_id", "tieu_de", "caption", "hashtag",
       "nhac_ban_quyen", "trang_thai", "link_yt", "link_ig", "ghi_chu"]
IG_VER = "v21.0"


# ---------- HTTP gọn ----------
def goi(url, method="GET", data=None, headers=None, json_body=None, tra_header=False, timeout=600):
    headers = dict(headers or {})
    if json_body is not None:
        data = json.dumps(json_body).encode()
        headers["Content-Type"] = "application/json; charset=UTF-8"
    elif isinstance(data, dict):
        data = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            if tra_header:
                return r.headers, body
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{method} {url.split('?')[0]} -> {e.code}: {e.read()[:400].decode(errors='replace')}")


# ---------- Google ----------
def google_token():
    return goi("https://oauth2.googleapis.com/token", "POST", data={
        "client_id": os.environ["GOOGLE_CLIENT_ID"], "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
        "refresh_token": os.environ["GOOGLE_REFRESH_TOKEN"], "grant_type": "refresh_token"})["access_token"]


class SheetLich:
    def __init__(self, tok):
        self.tok, self.id, self.tab = tok, os.environ["SHEET_ID"], os.environ.get("SHEET_TAB", "Lich")

    def _h(self):
        return {"Authorization": f"Bearer {self.tok}"}

    def doc(self):
        rng = urllib.parse.quote(f"{self.tab}!A1:L")
        v = goi(f"https://sheets.googleapis.com/v4/spreadsheets/{self.id}/values/{rng}", headers=self._h()).get("values", [])
        if not v:
            return []
        dau = [c.strip() for c in v[0]]
        thieu = [c for c in COT if c not in dau]
        if thieu:
            raise SystemExit(f"Sheet thiếu cột: {thieu}. Dòng 1 phải là: {', '.join(COT)}")
        return [dict(zip(dau, r + [""] * (len(dau) - len(r))), _dong=i + 2) for i, r in enumerate(v[1:])]

    def ghi(self, dong, cap_nhat):
        for cot, gt in cap_nhat.items():
            chu = chr(ord("A") + COT.index(cot))
            rng = urllib.parse.quote(f"{self.tab}!{chu}{dong['_dong']}")
            goi(f"https://sheets.googleapis.com/v4/spreadsheets/{self.id}/values/{rng}?valueInputOption=RAW",
                "PUT", headers=self._h(), json_body={"values": [[gt]]})


class CsvLich:
    def __init__(self, duong):
        self.duong = duong

    def doc(self):
        with open(self.duong, newline="", encoding="utf-8") as f:
            return [dict(r, _dong=i + 2) for i, r in enumerate(csv.DictReader(f))]

    def ghi(self, dong, cap_nhat):
        ds = self.doc()
        for r in ds:
            if r["_dong"] == dong["_dong"]:
                r.update(cap_nhat)
        with open(self.duong, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=COT, extrasaction="ignore")
            w.writeheader()
            w.writerows(ds)


def tai_tu_drive(tok, file_id, ra):
    url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media&supportsAllDrives=true"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
    with urllib.request.urlopen(req, timeout=900) as r, open(ra, "wb") as f:
        while True:
            khoi = r.read(1 << 20)
            if not khoi:
                break
            f.write(khoi)


def dang_youtube(tok, duong, dong, che_do):
    meta = {"snippet": {"title": dong["tieu_de"][:100], "categoryId": "10",
                        "description": (dong["caption"] + "\n\n" + dong["hashtag"]).strip()[:5000]},
            "status": {"privacyStatus": che_do, "selfDeclaredMadeForKids": False}}
    hd, _ = goi("https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
                "POST", headers={"Authorization": f"Bearer {tok}", "X-Upload-Content-Type": "video/*",
                                 "X-Upload-Content-Length": str(os.path.getsize(duong))},
                json_body=meta, tra_header=True)
    with open(duong, "rb") as f:
        kq = goi(hd["Location"], "PUT", data=f.read(), headers={"Content-Type": "video/*"})
    if kq.get("status", {}).get("uploadStatus") == "rejected" or (che_do != "private" and kq.get("status", {}).get("privacyStatus") == "private"):
        # Google khoá riêng tư khi app chưa qua kiểm duyệt: vẫn coi là đã tải, ghi chú để anh bấm công khai
        kq["_bi_khoa_rieng_tu"] = True
    return kq


# ---------- Instagram (Reels, tải thẳng file, không cần link công khai) ----------
def dang_instagram(duong, dong):
    host, uid, tok = os.environ.get("IG_HOST", "graph.facebook.com"), os.environ["IG_USER_ID"], os.environ["IG_TOKEN"]
    goc = f"https://{host}/{IG_VER}"
    cap = (dong["caption"] + "\n\n" + dong["hashtag"]).strip()[:2200]
    c = goi(f"{goc}/{uid}/media", "POST", data={"media_type": "REELS", "upload_type": "resumable",
                                                 "caption": cap, "access_token": tok})
    with open(duong, "rb") as f:
        du_lieu = f.read()
    goi(c["uri"], "POST", data=du_lieu, headers={"Authorization": f"OAuth {tok}", "offset": "0",
                                                 "file_size": str(len(du_lieu))})
    for _ in range(60):  # chờ Meta xử lý video, tối đa ~10 phút
        st = goi(f"{goc}/{c['id']}?fields=status_code,status&access_token={tok}")
        if st.get("status_code") == "FINISHED":
            break
        if st.get("status_code") in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram xử lý video lỗi: {st.get('status')}")
        time.sleep(10)
    else:
        raise RuntimeError("Instagram xử lý video quá 10 phút")
    m = goi(f"{goc}/{uid}/media_publish", "POST", data={"creation_id": c["id"], "access_token": tok})
    return goi(f"{goc}/{m['id']}?fields=permalink&access_token={tok}").get("permalink", m["id"])


# ---------- kiểm video ----------
def kiem_video(duong, kenh):
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                              "stream=width,height:format=duration", "-of", "json", duong],
                             capture_output=True, text=True, timeout=60).stdout
        j = json.loads(out)
        w, h = j["streams"][0]["width"], j["streams"][0]["height"]
    except Exception as e:
        return f"không đọc được video ({e})"
    if "ig" in kenh and not (h > w and abs(w / h - 9 / 16) < 0.05):
        return f"Reels cần khung dọc 9:16, video đang {w}x{h}"
    return ""


def bao(tin):
    url = os.environ.get("BAO_WEBHOOK")
    if url:
        try:
            goi(url, "POST", json_body={"msg_type": "text", "content": {"text": tin}}, timeout=30)
        except Exception as e:
            print("Không nhắn được bot:", e, file=sys.stderr)


def den_gio(dong, bay_gio):
    try:
        return datetime.strptime(dong["gio_dang"].strip(), "%Y-%m-%d %H:%M").replace(tzinfo=HN) <= bay_gio
    except ValueError:
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lich", help="file CSV thay cho Google Sheet (chạy thử)")
    ap.add_argument("--video-thu-muc", help="thư mục chứa video, tên file = file_drive_id (chạy thử)")
    ap.add_argument("--dry-run", action="store_true", help="không đăng, không ghi lịch")
    ap.add_argument("--xem", action="store_true", help="chỉ liệt kê dòng đến giờ")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    bay_gio = datetime.now(HN)
    tok = None
    if a.lich:
        lich = CsvLich(a.lich)
    else:
        thieu = [k for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN", "SHEET_ID") if not os.environ.get(k)]
        if thieu:
            print(f"Thiếu cấu hình: {thieu}. Thêm vào GitHub Secrets (xem HUONG-DAN.md).", file=sys.stderr)
            sys.exit(2)
        tok = google_token()
        lich = SheetLich(tok)

    ket_qua, co_loi = [], False
    for d in lich.doc():
        if d.get("trang_thai", "").strip() != "da-duyet":
            continue
        dg = den_gio(d, bay_gio)
        if dg is None:
            ket_qua.append({"dong": d["_dong"], "ket_qua": "loi", "ly_do": f"giờ sai mẫu '{d['gio_dang']}' (cần YYYY-MM-DD HH:MM)"})
            co_loi = True
            if not (a.dry_run or a.xem):
                lich.ghi(d, {"trang_thai": "loi", "ghi_chu": "giờ sai mẫu YYYY-MM-DD HH:MM"})
            continue
        if not dg:
            continue
        kenh = [k.strip() for k in d["kenh"].lower().replace("+", ",").split(",") if k.strip()]
        muc = {"dong": d["_dong"], "brand": d["brand"], "tieu_de": d["tieu_de"], "kenh": kenh}
        if a.xem:
            ket_qua.append(dict(muc, ket_qua="den-gio"))
            continue
        with tempfile.TemporaryDirectory() as tmp:
            try:
                if a.video_thu_muc:
                    duong = os.path.join(a.video_thu_muc, d["file_drive_id"])
                else:
                    duong = os.path.join(tmp, "video.mp4")
                    tai_tu_drive(tok, d["file_drive_id"], duong)
                loi = kiem_video(duong, kenh)
                if loi:
                    raise RuntimeError(loi)
                cap = {}
                if a.dry_run:
                    muc.update(ket_qua="thu-ok", ly_do="đi hết bước kiểm, chưa đăng (dry-run)")
                    ket_qua.append(muc)
                    continue
                ghi_chu = []
                if "yt" in kenh and not d.get("link_yt"):
                    kq = dang_youtube(tok, duong, d, os.environ.get("YT_CHE_DO", "private"))
                    cap["link_yt"] = f"https://youtu.be/{kq['id']}"
                    lich.ghi(d, {"link_yt": cap["link_yt"]})  # ghi ngay để lỗi IG sau đó không làm đăng YT lần 2
                    if kq.get("_bi_khoa_rieng_tu"):
                        ghi_chu.append("YouTube giữ riêng tư (app chưa qua duyệt Google): bấm công khai trong Studio")
                if "ig" in kenh and not d.get("link_ig"):
                    cap["link_ig"] = dang_instagram(duong, d)
                cap.update(trang_thai="da-dang", ghi_chu="; ".join(ghi_chu))
                lich.ghi(d, cap)
                muc.update(ket_qua="da-dang", **cap)
                bao(f"Đã đăng [{d['brand']}] {d['tieu_de']}\n{cap.get('link_yt', '')}\n{cap.get('link_ig', '')}".strip())
            except Exception as e:
                co_loi = True
                muc.update(ket_qua="loi", ly_do=str(e)[:300])
                if not a.dry_run:
                    lich.ghi(d, {"trang_thai": "loi", "ghi_chu": str(e)[:300]})
                    bao(f"LỖI đăng [{d['brand']}] {d['tieu_de']}: {str(e)[:200]}")
        ket_qua.append(muc)

    if a.json:
        print(json.dumps(ket_qua, ensure_ascii=False, indent=1))
    else:
        if not ket_qua:
            print("Không có dòng nào đến giờ đăng.")
        for k in ket_qua:
            print(f"dòng {k['dong']}: {k['ket_qua']} · {k.get('brand', '')} · {k.get('tieu_de', '')} {k.get('ly_do', '')}")
    sys.exit(1 if co_loi else 0)


if __name__ == "__main__":
    main()
