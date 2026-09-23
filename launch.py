#!/usr/bin/env python3
"""Double-click entry point; reuse a running copy of this workspace."""
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import urllib.request
import webbrowser
import server

url = 'http://127.0.0.1:8787'
workspace = str(Path(__file__).resolve().parent / 'projects')


def stop_stale_server(info):
    candidates = []
    pid = info.get('pid')
    if isinstance(pid, int) and pid > 1:
        candidates.append(pid)
    else:
        lsof = Path('/usr/sbin/lsof')
        if lsof.is_file():
            result = subprocess.run([str(lsof), '-nP', '-t', '-iTCP:8787', '-sTCP:LISTEN'],
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
            candidates.extend(int(value) for value in result.stdout.split() if value.isdigit())
    for candidate in set(candidates):
        if candidate != os.getpid():
            try:
                os.kill(candidate, signal.SIGTERM)
            except ProcessLookupError:
                pass
    for _ in range(30):
        try:
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url, timeout=.1):
                time.sleep(.1)
        except Exception:
            return
    raise RuntimeError('The previous LocalLeaf server did not stop')


try:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url + '/api/bootstrap', timeout=2) as response:
        info = json.load(response)
    if info.get('dataPath') != workspace:
        raise RuntimeError('Port belongs to another workspace')
    if info.get('apiVersion') == server.API_VERSION:
        webbrowser.open(url)
    else:
        stop_stale_server(info)
        server.main()
except Exception:
    server.main()
