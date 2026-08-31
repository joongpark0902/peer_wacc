"""KIND 다운로드 응답을 흉내낸 EUC-KR HTML fixture를 만든다."""
rows = [
    ("해치텍", "코스닥", "0155E0", "반도체 제조업", "지자기센서, 온/습도센서", "2026-08-25", "12월", "최성민", "http://www.haechitech.com", "충청북도"),
    ("삼성전자", "유가", "005930", "통신 및 방송 장비 제조업", "반도체, 휴대폰, 가전", "1975-06-11", "12월", "한종희", "http://www.samsung.com", "경기도"),
    ("성광벤드", "유가", "014620", "기타 금속 가공제품 제조업", "관이음쇠(피팅), 플랜지", "1997-11-14", "12월", "안갑원", "http://www.skbend.co.kr", "부산광역시"),
    ("키움제6호스팩", "코스닥", "413600", "금융 지원 서비스업", "기업 인수합병", "2022-04-07", "12월", "신가형", "", "서울특별시"),
    ("셀트리온", "유가", "068270", "기초 의약물질 및 생물학적 제제 제조업", "바이오시밀러, 케미컬의약품", "2018-02-09", "12월", "서정진", "http://www.celltrion.com", "인천광역시"),
    ("한국파마", "코스닥", "032300", "의약품 제조업", "완제의약품(정신신경계, 소화기계)", "2020-08-10", "3월", "박은희", "http://www.hanpharm.co.kr", "경기도"),
]
hdr = ["회사명", "시장구분", "종목코드", "업종", "주요제품", "상장일", "결산월", "대표자명", "홈페이지", "지역"]
html = "<html><head><meta http-equiv='Content-Type' content='text/html; charset=euc-kr'></head><body><table>"
html += "<tr>" + "".join(f"<th>{h}</th>" for h in hdr) + "</tr>"
for r in rows:
    html += "<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>"
html += "</table></body></html>"
open(r"tests\fixtures\kind_sample.html", "wb").write(html.encode("euc-kr"))
print("written")
