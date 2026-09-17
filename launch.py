#!/usr/bin/env python3
"""Double-click entry point; reuse a running copy of this workspace."""
import json
from pathlib import Path
import urllib.request
import webbrowser
import server

url = 'http://127.0.0.1:8787'
try:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url + '/api/bootstrap', timeout=2) as response:
        info = json.load(response)
    if info.get('dataPath') == str(Path(__file__).resolve().parent / 'projects'):
        webbrowser.open(url)
    else:
        raise RuntimeError('Port belongs to another workspace')
except Exception:
    server.main()
