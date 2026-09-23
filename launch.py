#!/usr/bin/env python3
"""Double-click entry point; reuse a running copy of this workspace."""
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import time
import urllib.request
import webbrowser
import server

url = 'http://127.0.0.1:8787'
port = 8787
workspace = str(Path(__file__).resolve().parent / 'projects')


def run(command):
    try:
        return subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return ''


def pids_from_proc():
    """Find the listener by reading /proc only — no external tools required.

    /proc/net/tcp lists the listening socket (state 0A) with its inode; the owning process is
    whichever one has that inode among its open file descriptors."""
    inodes = set()
    for name in ('tcp', 'tcp6'):
        try:
            lines = Path('/proc/net', name).read_text().splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            parts = line.split()
            if len(parts) < 10 or parts[3] != '0A':
                continue
            try:
                if int(parts[1].rsplit(':', 1)[1], 16) == port:
                    inodes.add(parts[9])
            except (IndexError, ValueError):
                continue
    if not inodes:
        return set()
    found = set()
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        try:
            for fd in (entry / 'fd').iterdir():
                target = os.readlink(fd)
                if target.startswith('socket:[') and target[8:-1] in inodes:
                    found.add(int(entry.name))
                    break
        except OSError:          # the process exited, or is not ours to inspect
            continue
    return found


def listening_pids():
    """PIDs listening on this port, most portable source first.

    lsof is only a safe bet on macOS (/usr/sbin/lsof); most Linux images ship neither it nor
    anything else in a fixed location, so fall through to ss and finally to /proc."""
    lsof = shutil.which('lsof') or next((p for p in ('/usr/sbin/lsof', '/usr/bin/lsof')
                                         if Path(p).is_file()), None)
    if lsof:
        pids = {int(v) for v in run([lsof, '-nP', '-t', f'-iTCP:{port}', '-sTCP:LISTEN']).split()
                if v.isdigit()}
        if pids:
            return pids
    ss = shutil.which('ss')
    if ss:
        pids = set()
        for line in run([ss, '-ltnp']).splitlines():
            local = line.split()[3:4]
            if local and local[0].rsplit(':', 1)[-1] == str(port):
                pids.update(int(v) for v in re.findall(r'pid=(\d+)', line))
        if pids:
            return pids
    return pids_from_proc()


def serving():
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url, timeout=.2):
            return True
    except Exception:
        return False


def stop_stale_server(info):
    """Stop the server holding the port. Returns True once the port is free.

    A server too old to report its own pid is located through listening_pids(); older releases
    only looked for lsof, so on a machine without it nothing was ever signalled, the wait loop
    below timed out, and the launcher died silently with the port still held."""
    pid = info.get('pid')
    candidates = {pid} if isinstance(pid, int) and pid > 1 else listening_pids()
    candidates.discard(os.getpid())
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for candidate in candidates:
            try:
                os.kill(candidate, sig)
            except (ProcessLookupError, PermissionError):
                pass
        for _ in range(30):
            if not serving():
                return True
            time.sleep(.1)
    return not serving()


def bootstrap():
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url + '/api/bootstrap', timeout=2) as response:
            return json.load(response)
    except Exception:
        return None


info = bootstrap()
if info is None:
    server.main()                                   # nothing is listening: start normally
elif info.get('dataPath') != workspace:
    raise SystemExit(f'Port {port} is serving another workspace: {info.get("dataPath")}')
elif info.get('apiVersion') == server.API_VERSION:
    webbrowser.open(url)                            # current server already running
elif stop_stale_server(info):
    server.main()                                   # replaced an outdated server
else:
    # The old server would not die and still holds the port, so starting would only abort with
    # "address already in use" and -- with Terminal=false -- leave the icon looking inert.
    print(f'Could not stop the server on port {port}; opening the running one instead.')
    webbrowser.open(url)
