"""
estimate_time.py - Uoc tinh thoi gian crawl con lai tu SO LIEU THAT da crawl duoc (doc data/).

Cach chay (dung lai crawler hay dang chay deu duoc, chi doc file):
    python estimate_time.py
    python estimate_time.py --data-dir data --speeds 35,500,2000,10000

Y tuong:
    thoi gian 1 version  ~=  a + bytes / toc_do
        a        = thoi gian co dinh moi lan goi (3 giay cho gian cach + do tre mang), lay tu so lieu that
        toc_do   = toc do tai that cua may ban (KB/s), cung lay tu so lieu that
    Tong con lai = so version con lai x a  +  (so version con lai x dung luong trung binh) / toc_do

In ra 2 phan: (1) theo toc do do duoc tren may ban, (2) neu toc do tai la X KB/s (vi du Colab).
Toc do tren Colab CHUA do: hay chay 100 bai tren Colab roi chay lai script nay de co so that.
"""
import argparse
import json
import math
import statistics
from pathlib import Path


def fmt(seconds):
    if seconds is None or math.isinf(seconds):
        return "n/a"
    h = seconds / 3600
    if h >= 48:
        return f"{h / 24:.1f} ngay ({h:.0f} gio)"
    if h >= 1:
        return f"{int(h)} gio {int(round((h - int(h)) * 60))} phut"
    return f"{seconds / 60:.0f} phut"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--speeds", default="35,500,2000,10000,30000",
                    help="cac toc do tai (KB/s) de thu, cach nhau dau phay")
    args = ap.parse_args()
    data = Path(args.data_dir)

    n_papers_meta, v_total = 0, 0
    for meta in data.glob("*/meta.json"):
        try:
            v_total += int(json.loads(meta.read_text(encoding="utf-8")).get("n_versions", 1))
            n_papers_meta += 1
        except (ValueError, OSError):
            continue
    if n_papers_meta == 0:
        raise SystemExit(f"Khong thay {data}/*/meta.json. Chay tu thu muc goc cua repo.")

    xs, ys = [], []                                   # bytes, seconds cua tung version da xong
    for st in data.glob("*/v*/status.json"):
        try:
            rec = json.loads(st.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if rec.get("kind") == "not_found" and not rec.get("bytes_downloaded"):
            continue
        if rec.get("bytes_downloaded") is None or rec.get("seconds") is None:
            continue
        xs.append(float(rec["bytes_downloaded"]))
        ys.append(float(rec["seconds"]))
    v_done = len(xs)
    if v_done < 5:
        raise SystemExit(f"Moi co {v_done} version xong, chua du de uoc tinh (can it nhat 5, nen 100 bai).")

    mean_b = statistics.mean(xs)
    med_b = statistics.median(xs)
    se_b = statistics.stdev(xs) / math.sqrt(v_done) if v_done > 1 else 0.0

    a, speed = 3.5, sum(xs) / sum(ys)                 # du phong
    fitted = False
    if v_done >= 20:
        try:
            slope, intercept = statistics.linear_regression(xs, ys)
            if slope > 0:
                a, speed, fitted = max(intercept, 3.0), 1.0 / slope, True
        except statistics.StatisticsError:
            pass

    v_rem = max(v_total - v_done, 0)
    print(f"Bai co meta.json            : {n_papers_meta}")
    print(f"Tong so version (theo meta) : {v_total}  (trung binh {v_total / n_papers_meta:.2f} version/bai)")
    print(f"Version da tai xong         : {v_done}   con lai: {v_rem}")
    print(f"Dung luong tai ve / version : trung binh {mean_b / 1e6:.2f} MB, trung vi {med_b / 1e6:.2f} MB")
    print(f"Do tre co dinh / version (a): {a:.1f} giay" + ("" if fitted else "  (uoc luong tho, it mau)"))
    print(f"Toc do tai do duoc          : {speed / 1024:.0f} KB/s" + ("" if fitted else "  (trung binh gop)"))
    if v_done < 100:
        print(f"LUU Y: moi co {v_done} mau; trung binh dung luong con dao dong manh (sai so ~ +-{se_b / 1e6:.1f} MB).")

    def total(speed_bps, mean_bytes):
        return v_rem * a + v_rem * mean_bytes / speed_bps

    print("\n== (1) Tai toc do do duoc tren may nay ==")
    print(f"   Con lai: {fmt(total(speed, mean_b))}   (khoang {fmt(total(speed, max(mean_b - 2 * se_b, 0)))}"
          f" den {fmt(total(speed, mean_b + 2 * se_b))} neu dung luong TB lech 2 sai so)")

    print("\n== (2) Neu toc do tai la ... (gia dinh, chua do) ==")
    print(f"   {'toc do':>10}   {'thoi gian con lai':<24}  ghi chu")
    floor = v_rem * 3.0
    for s in [float(x) for x in args.speeds.split(",") if x.strip()]:
        t = total(s * 1024, mean_b)
        print(f"   {s:>7.0f} KB/s   {fmt(t):<24}  chi phan tai: {fmt(v_rem * mean_b / (s * 1024))}")
    print(f"\n   San cung (khong tinh tai, chi 3 giay/lan hoi arXiv): {fmt(floor)}")
    print("   Luong Semantic Scholar chay song song nen khong cong them (neu co S2_API_KEY).")


if __name__ == "__main__":
    main()
