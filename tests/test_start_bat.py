# -*- coding: utf-8 -*-
"""验证 start.bat 能正确解析并拉起服务"""
import json
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BAT = str(ROOT / "start.bat")
CWD = str(ROOT)

p = subprocess.Popen(["cmd", "/c", BAT], cwd=CWD,
                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
time.sleep(9)

ok = False
try:
    r = urllib.request.urlopen("http://127.0.0.1:3000/api/pages", timeout=8)
    d = json.loads(r.read().decode())
    ok = True
    print(f"[bat 启动成功] 页面数={len(d['pages'])}  车型={d['pack']['id']}  发动机={d['pack']['engine']}")
except Exception as e:
    print("[bat 启动失败]", e)

subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)],
               capture_output=True)
time.sleep(1)
try:
    out = p.stdout.read().decode("utf-8", "replace")
except Exception:
    out = ""
p.wait(timeout=10)

print("\n--- bat 控制台输出 ---")
print(out.strip()[:1500] if out.strip() else "(无输出)")

# 区分三种结果：
#   PASS  —— 服务起来了，接口能通
#   SKIP  —— 本机缺依赖/缺 Python，start.bat 已给出正确指引（环境问题，不是代码问题）
#   FAIL  —— 有 Python 有依赖但服务没起来（这才是真 bug）
if ok:
    verdict = "PASS"
elif "[SETUP]" in out or "dependencies are missing" in out:
    verdict = "SKIP（本机缺依赖；start.bat 已给出安装命令，属环境问题）"
elif "No Python 3.10+" in out:
    verdict = "SKIP（本机没装 Python 3.10+）"
else:
    verdict = "FAIL"
print("\n结论:", verdict)
