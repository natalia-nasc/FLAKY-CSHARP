import sys, glob, os, re
import xml.etree.ElementTree as ET
ns = {"t": "http://microsoft.com/schemas/VisualStudio/TeamTest/2010"}
folder = sys.argv[1]; pats = sys.argv[2:]
for f in sorted(glob.glob(os.path.join(folder, "*.trx")), key=lambda p: int(re.findall(r"(\d+)\.trx$", p)[0])):
    root = ET.parse(f).getroot()
    fails = [x.get("testName") for x in root.iterfind(".//t:UnitTestResult", ns)
             if x.get("outcome") == "Failed" and any(p in x.get("testName", "") for p in pats)]
    if fails:
        print(os.path.basename(f))
        for t in fails: print("   ", t[:140])

