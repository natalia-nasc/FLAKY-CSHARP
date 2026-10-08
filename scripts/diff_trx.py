import sys, xml.etree.ElementTree as ET
ns = {"t": "http://microsoft.com/schemas/VisualStudio/TeamTest/2010"}

def keys(path):
    r = ET.parse(path).getroot()
    cls = {u.get("id"): u.find("t:TestMethod", ns).get("className")
           for u in r.iterfind(".//t:UnitTest", ns)}
    return {f'{cls.get(x.get("testId"), "?")}::{x.get("testName")}'
            for x in r.iterfind(".//t:UnitTestResult", ns)}

a, b = keys(sys.argv[1]), keys(sys.argv[2])
miss = sorted(a - b)
print(f"100x: {len(a)} | manual: {len(b)} | faltando no manual: {len(miss)}")
for k in miss: print(k)

