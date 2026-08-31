"""한공회 베타 조회 화면(캡쳐 형식)과 같은 xlsx/csv fixture."""
import csv
import openpyxl

hdr = ["조회일자", "기준일자", "시장구분", "단축코드/종목코드", "한글종목명", "영문종목명", "주기", "종가",
       "2년베타 실질베타", "2년베타 조정베타", "2년베타 포인트수"]
rows = [
    [20260630, 20260626, "코스피", "018260", "삼성에스디에스", "SAMSUNG SDS", "Weekly", 189900, 0.934737, 0.956492, 104],
    [20260630, 20260626, "코스피", 64400,    "LG씨엔에스",     "LG CNS",      "Weekly", 75100,  1.039477, 1.026318, 72],
    [20260630, 20260626, "코스피", "286940", "롯데이노베이트", "LOTTE INNOVATE", "Weekly", 16600, 0.685396, 0.790264, 104],
    [20260630, 20260626, "코스피", "307950", "현대오토에버",   "HyundaiAutoever", "Weekly", 507000, 1.668034, 1.445356, 104],
]
wb = openpyxl.Workbook(); ws = wb.active
ws.append(hdr)
for r in rows:
    ws.append(r)
wb.save(r"tests\fixtures\kicpa_sample.xlsx")
with open(r"tests\fixtures\kicpa_sample.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f); w.writerow(hdr); w.writerows(rows)
with open(r"tests\fixtures\kicpa_sample_cp949.csv", "w", newline="", encoding="cp949") as f:
    w = csv.writer(f); w.writerow(hdr); w.writerows(rows)
html = "<html><head><meta charset='euc-kr'></head><body><table><tr>" + "".join(f"<td>{h}</td>" for h in hdr) + "</tr>"
for r in rows:
    html += "<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>"
html += "</table></body></html>"
open(r"tests\fixtures\kicpa_sample_html.xls", "wb").write(html.encode("euc-kr"))
print("written")
