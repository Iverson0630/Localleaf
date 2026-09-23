#!/usr/bin/env python3
"""LocalLeaf: an offline LaTeX workspace. Python standard library only."""
import argparse
import base64
import hashlib
import io
import json
import mimetypes
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import webbrowser
import zipfile
from keychain_credential import delete_token, get_token, set_token
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse, quote

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'projects'
API_VERSION = 3
TOKEN = secrets.token_urlsafe(32)
LOCK = threading.RLock()
COMPILE_LOCKS = {}
GIT_LOCKS = {}
MAX_FILE = 20 * 1024 * 1024
MAX_IMPORT = 80 * 1024 * 1024
ENGINES = ('xelatex', 'pdflatex', 'lualatex')

ENGLISH = r'''\documentclass[11pt,a4paper]{article}
\usepackage[margin=1in]{geometry}
\usepackage{amsmath,amssymb,graphicx,booktabs}
\usepackage[colorlinks=true,allcolors=blue]{hyperref}

\title{A New Research Journey}
\author{Your Name \\ Your University}
\date{\today}

\begin{document}
\maketitle

\begin{abstract}
Write a concise summary of your research question, approach,
main findings, and their implications here.
\end{abstract}

\input{sections/introduction}

\section{Methods}
Describe the study design and make your assumptions explicit.
For example, the optimization objective can be written as
\begin{equation}
  \theta^{\star} = \arg\min_{\theta}
  \mathbb{E}_{x \sim p(x)}\left[\mathcal{L}(x;\theta)\right].
  \label{eq:objective}
\end{equation}

\section{Results}
Report your observations and uncertainty. Replace this section
with your experimental results.

\section{Discussion}
Interpret the results, describe limitations, and identify next steps.

\bibliographystyle{plain}
\bibliography{references}
\end{document}
'''
CHINESE = r'''\documentclass[UTF8,a4paper,11pt,fontset=fandol]{ctexart}
\usepackage[margin=2.5cm]{geometry}
\usepackage{amsmath,amssymb,graphicx,booktabs}
\usepackage[colorlinks=true,allcolors=blue]{hyperref}
\title{我的研究论文}
\author{作者姓名 \\ 所在学校}
\date{\today}
\begin{document}
\maketitle
\begin{abstract}
在这里简要介绍研究问题、方法、主要发现与意义。
\end{abstract}
\input{sections/introduction}
\section{研究方法}
描述研究设计、实验条件与评价指标。例如：
\begin{equation}
  \theta^{\star}=\arg\min_{\theta}\mathcal{L}(\theta).
\end{equation}
\section{实验结果}
在这里报告实际观测结果与不确定性。
\section{讨论与结论}
说明结果的意义、研究局限与后续方向。
\bibliographystyle{plain}
\bibliography{references}
\end{document}
'''
BIB = '''@book{lamport1994,
  author = {Leslie Lamport},
  title = {{LaTeX}: A Document Preparation System},
  publisher = {Addison-Wesley},
  year = {1994},
  edition = {2}
}
'''


class Problem(Exception):
    def __init__(self, message, status=400):
        self.message, self.status = message, status


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.save-', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def write_json(path, value):
    atomic(path, json.dumps(value, ensure_ascii=False, indent=2).encode())


def project(pid):
    if (not isinstance(pid, str) or not pid or len(pid) > 120 or pid in ('.', '..')
            or pid.startswith('.') or '/' in pid or '\\' in pid or '\x00' in pid):
        raise Problem('项目不存在', 404)
    p = DATA / pid
    if p.is_symlink() or not (p / '.localleaf.json').is_file():
        raise Problem('项目不存在', 404)
    try:
        record = json.loads((p / '.localleaf.json').read_text())
    except (OSError, ValueError):
        raise Problem('项目不存在', 404)
    local_path = record.get('localPath')
    if local_path:
        root = Path(local_path).expanduser()
        if not root.is_absolute() or not root.is_dir() or root.is_symlink():
            raise Problem('本地项目文件夹不存在或不可用', 404)
        return root.resolve()
    return p


def clean_project_name(name):
    name = re.sub(r'[\\/:\x00-\x1f]+', '-', str(name or '')).strip().strip('.')[:100].strip()
    return name or 'Untitled Paper'


def available_project_id(name, current=None):
    base = clean_project_name(name)
    candidate = base
    number = 2
    while (DATA / candidate).exists() and (current is None or (DATA / candidate) != current):
        suffix = f' ({number})'
        candidate = base[:100 - len(suffix)].rstrip() + suffix
        number += 1
    return candidate


def safe_path(root, name):
    if not isinstance(name, str) or not name or '\\' in name or '\x00' in name:
        raise Problem('文件路径无效')
    parts = PurePosixPath(name).parts
    if name.startswith('/') or any(x in ('..', '.') or x.startswith('.') for x in parts):
        raise Problem('请使用项目内的非隐藏文件路径')
    if len(name) > 240 or ':' in name:
        raise Problem('文件路径无效')
    p = root.joinpath(*parts)
    if root.resolve() not in p.resolve().parents or any(root.joinpath(*parts[:i]).is_symlink() for i in range(1, len(parts) + 1)):
        raise Problem('文件必须位于项目内')
    return p


def files(p):
    return sorted(x for x in p.rglob('*') if x.is_file() and not x.is_symlink()
                  and not any(a.startswith('.') for a in x.relative_to(p).parts))


def meta(p):
    resolved = p.resolve()
    for entry in DATA.iterdir():
        config = entry / '.localleaf.json'
        if not config.is_file():
            continue
        try:
            record = json.loads(config.read_text())
            if record.get('localPath') and Path(record['localPath']).expanduser().resolve() == resolved:
                return record
        except (OSError, ValueError, RuntimeError):
            continue
    config = p / '.localleaf.json'
    if config.is_file():
        return json.loads(config.read_text())
    raise Problem('项目设置不存在', 404)


def config_path(p):
    resolved = p.resolve()
    for entry in DATA.iterdir():
        candidate = entry / '.localleaf.json'
        if not candidate.is_file():
            continue
        try:
            record = json.loads(candidate.read_text())
            if record.get('localPath') and Path(record['localPath']).expanduser().resolve() == resolved:
                return candidate
        except (OSError, ValueError, RuntimeError):
            continue
    config = p / '.localleaf.json'
    if config.is_file():
        return config
    raise Problem('项目设置不存在', 404)


def touch(p, **changes):
    m = meta(p)
    m.update(changes, updated=time.time())
    write_json(config_path(p), m)
    return m


def revision(data):
    return hashlib.sha256(data).hexdigest()


def history(p, name, content):
    h = p / '.history'
    h.mkdir(exist_ok=True)
    stamp = f'{time.time_ns()}-{uuid.uuid4().hex[:6]}'
    atomic(h / (stamp + '.data'), content)
    write_json(h / (stamp + '.json'), {'id': stamp, 'path': name, 'time': time.time(), 'size': len(content)})
    for old in sorted(h.glob('*.json'), reverse=True)[200:]:
        old.with_suffix('.data').unlink(missing_ok=True)
        old.unlink()


def new_project(name, template='english', imported=None):
    name = clean_project_name(name)
    if not name:
        raise Problem('请输入项目名称')
    pid = available_project_id(name)
    p = DATA / pid
    p.mkdir(parents=True)
    try:
        if imported is not None:
            for filename, content in imported:
                atomic(safe_path(p, filename), content)
        else:
            atomic(p / 'main.tex', (CHINESE if template == 'chinese' else ENGLISH).encode())
            intro = (r'\section{引言}' + '\n介绍研究背景，明确研究问题和本文贡献。\n'
                     r'可通过 BibTeX 管理参考文献，例如 \cite{lamport1994}。' if template == 'chinese' else
                     r'\section{Introduction}' + '\nIntroduce the problem, summarize related work, and explain\n'
                     r'your contribution. Cite sources using BibTeX, for example \cite{lamport1994}.')
            atomic(p / 'sections/introduction.tex', (intro + '\n').encode())
            atomic(p / 'references.bib', BIB.encode())
        tex = [str(x.relative_to(p)) for x in files(p) if x.suffix == '.tex']
        main = 'main.tex' if 'main.tex' in tex else next((x for x in tex if '\\documentclass' in (p / x).read_text(errors='replace')), tex[0] if tex else '')
        write_json(p / '.localleaf.json', {'id': pid, 'name': name, 'main': main, 'engine': 'xelatex', 'updated': time.time()})
        return meta(p)
    except Exception:
        shutil.rmtree(p)
        raise


def new_local_project(name, local_path):
    name = clean_project_name(name or Path(str(local_path or '')).expanduser().name)
    root = Path(str(local_path or '')).expanduser()
    if not root.is_absolute() or not root.is_dir() or root.is_symlink():
        raise Problem('请选择一个存在的本地文件夹')
    root = root.resolve()
    if root in (DATA.resolve(), ROOT.resolve()) or ROOT.resolve() in root.parents:
        raise Problem('不能把 LocalLeaf 自身目录作为外部项目文件夹')
    for entry in DATA.iterdir():
        config = entry / '.localleaf.json'
        if not config.is_file():
            continue
        try:
            record = json.loads(config.read_text())
            if record.get('localPath') and Path(record['localPath']).expanduser().resolve() == root:
                raise Problem('这个文件夹已经添加为 LocalLeaf 项目', 409)
        except Problem:
            raise
        except (OSError, ValueError, RuntimeError):
            continue
    pid = available_project_id(name)
    tex = [str(x.relative_to(root)) for x in files(root) if x.suffix.lower() == '.tex']
    main = 'main.tex' if 'main.tex' in tex else next(
        (x for x in tex if '\\documentclass' in (root / x).read_text(errors='replace')),
        tex[0] if tex else '')
    record = {'id': pid, 'name': name, 'main': main, 'engine': 'xelatex',
              'updated': time.time(), 'localPath': str(root)}
    registry = DATA / pid
    registry.mkdir(parents=True)
    try:
        write_json(registry / '.localleaf.json', record)
        return record
    except Exception:
        shutil.rmtree(registry, ignore_errors=True)
        raise


def find_bin(name):
    candidates = list((ROOT / 'runtime').glob('**/bin/*/' + name))
    candidates += [Path('/Library/TeX/texbin') / name]
    found = shutil.which(name)
    if found:
        candidates.append(Path(found))
    return next((str(p) for p in candidates if p.is_file() and os.access(p, os.X_OK)), None)


def environment():
    return {'engines': {n: bool(find_bin(n)) for n in ENGINES},
            'latexmk': bool(find_bin('latexmk')), 'synctex': bool(find_bin('synctex')),
            'git': bool(shutil.which('git') or Path('/usr/bin/git').is_file())}


def compile_project(pid):
    p = project(pid)
    with LOCK:
        guard = COMPILE_LOCKS.setdefault(pid, threading.Lock())
    if not guard.acquire(blocking=False):
        raise Problem('此项目正在编译，请稍候', 409)
    started = time.time()
    work = None
    try:
        with LOCK:
            m = meta(p)
            engine = find_bin(m['engine'])
            maker = find_bin('latexmk')
            if not engine or not maker:
                raise Problem('未找到本地 LaTeX 编译器。请查看 README 中的安装说明。', 503)
            main = safe_path(p, m['main'])
            if not main.is_file() or main.suffix != '.tex':
                raise Problem('请在设置中选择存在的 .tex 主文件')
            build = p / '.build'
            build.mkdir(exist_ok=True)
            work = Path(tempfile.mkdtemp(prefix='compile-', dir=build))
            for f in files(p):
                dest = work / f.relative_to(p)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dest)
        env = os.environ.copy()
        env.update(PATH=str(Path(engine).parent) + os.pathsep + env.get('PATH', ''),
                   openin_any='p', openout_any='p', shell_escape='f', TEXMFOUTPUT=str(work))
        flag = {'xelatex': '-xelatex', 'pdflatex': '-pdf', 'lualatex': '-lualatex'}[m['engine']]
        command = [maker, '-norc', flag, '-interaction=nonstopmode', '-halt-on-error', '-file-line-error',
                   '-synctex=1', '-outdir=out', '-latexoption=-no-shell-escape', './' + m['main']]
        proc = subprocess.Popen(command, cwd=work, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                start_new_session=True)
        try:
            output, _ = proc.communicate(timeout=120)
            log = output.decode('utf-8', errors='replace')
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            output, _ = proc.communicate()
            log = output.decode('utf-8', errors='replace') + '\n编译超过 120 秒，已停止。'
        pdf = work / 'out' / (main.stem + '.pdf')
        synctex = work / 'out' / (main.stem + '.synctex.gz')
        ok = proc.returncode == 0 and pdf.is_file()
        result = {'ok': ok, 'duration': round(time.time() - started, 2), 'time': time.time(),
                  'log': log[-100000:], 'engine': m['engine'], 'main': m['main']}
        with LOCK:
            if ok:
                atomic(build / 'output.pdf', pdf.read_bytes())
                if synctex.is_file():
                    atomic(build / 'output.synctex.gz', synctex.read_bytes())
            result['hasPdf'] = (build / 'output.pdf').is_file()
            result['hasSyncTex'] = (build / 'output.synctex.gz').is_file()
            write_json(build / 'result.json', result)
        return result
    finally:
        if work:
            shutil.rmtree(work, ignore_errors=True)
        guard.release()


def synctex_edit(pid, page, x, y):
    """Resolve a PDF point (big points from top-left) to a project source line."""
    p = project(pid)
    build = p / '.build'
    pdf = build / 'output.pdf'
    mapping = build / 'output.synctex.gz'
    command = find_bin('synctex')
    if not command or not pdf.is_file() or not mapping.is_file():
        raise Problem('此 PDF 没有源码位置映射，请重新编译。', 404)
    try:
        page = int(page)
        x, y = float(x), float(y)
    except (TypeError, ValueError):
        raise Problem('PDF 位置无效')
    if page < 1 or page > 10000 or not (0 <= x <= 10000 and 0 <= y <= 10000):
        raise Problem('PDF 位置超出范围')
    proc = subprocess.run(
        [command, 'edit', '-o', f'{page}:{x:.3f}:{y:.3f}:{pdf.name}', '-d', str(build)],
        cwd=build, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=8)
    output = proc.stdout.decode('utf-8', errors='replace')
    source = re.search(r'(?m)^Input:(.+)$', output)
    line = re.search(r'(?m)^Line:([0-9]+)$', output)
    column = re.search(r'(?m)^Column:(-?[0-9]+)$', output)
    if proc.returncode or not source or not line:
        raise Problem('此处附近没有可定位的 LaTeX 源码。', 404)
    source_path = Path(source.group(1).strip())
    parts = source_path.parts
    compile_index = next((i for i, part in enumerate(parts) if part.startswith('compile-')), None)
    if compile_index is not None:
        relative = PurePosixPath(*parts[compile_index + 1:]).as_posix()
    elif source_path.is_absolute():
        try:
            relative = source_path.relative_to(p).as_posix()
        except ValueError:
            raise Problem('该位置来自外部 LaTeX 宏包，无法在项目中打开。', 404)
    else:
        relative = source_path.as_posix().removeprefix('./')
    target = safe_path(p, relative)
    if not target.is_file():
        raise Problem('映射的源码文件已移动，请重新编译。', 409)
    return {'path': relative, 'line': int(line.group(1)),
            'column': max(0, int(column.group(1))) if column else 0}


def git_bin():
    command = shutil.which('git')
    if command:
        return command
    if Path('/usr/bin/git').is_file():
        return '/usr/bin/git'
    raise Problem('这台 Mac 没有安装 Git。请先安装 Xcode Command Line Tools。', 503)


def git_run(p, *args, timeout=90, check=True):
    env = os.environ.copy()
    env.update(GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='Never', LC_ALL='C')
    proc = subprocess.run([git_bin(), *args], cwd=p, env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, timeout=timeout)
    output = proc.stdout.decode('utf-8', errors='replace').strip()
    if check and proc.returncode:
        lowered = output.lower()
        if 'authentication failed' in lowered or 'could not read password' in lowered:
            raise Problem('Overleaf 认证失败，请检查 Git authentication token。', 401)
        if 'repository not found' in lowered or 'not found' in lowered:
            raise Problem('找不到 Overleaf 项目，请检查 Git 地址和项目权限。', 404)
        if 'could not resolve host' in lowered or 'failed to connect' in lowered:
            raise Problem('目前无法连接 Overleaf，请检查网络后重试。', 503)
        detail = next((line.strip() for line in reversed(output.splitlines()) if line.strip()), '未知错误')
        raise Problem('Git 同步失败：' + detail[:500], 409)
    return proc.returncode, output


def normalize_overleaf_url(value):
    value = str(value or '').strip()
    matches = re.findall(r'https://(?:git@)?git\.overleaf\.com/[A-Za-z0-9_-]+', value)
    if matches:
        value = matches[0]
    parsed = urlparse(value)
    if (parsed.scheme != 'https' or parsed.hostname != 'git.overleaf.com' or parsed.port is not None
            or parsed.password is not None or parsed.username not in (None, 'git')
            or parsed.query or parsed.fragment or not re.fullmatch(r'/[A-Za-z0-9_-]+/?', parsed.path)):
        raise Problem('请输入 Overleaf 项目中“集成 → Git”提供的地址，例如 https://git.overleaf.com/项目ID')
    project_id = parsed.path.strip('/')
    return f'https://git@git.overleaf.com/{project_id}'


def git_credential(p, token, action='approve'):
    if isinstance(token, str):
        token = token.strip()
        if token.startswith('olp\\_'):
            token = 'olp_' + token[5:]
    if action == 'approve' and (not isinstance(token, str) or not token or len(token) > 1000):
        raise Problem('请输入有效的 Overleaf Git authentication token')
    try:
        if action == 'approve':
            set_token(token)
        elif action == 'reject':
            delete_token()
    except RuntimeError:
        raise Problem('无法把 Overleaf 令牌保存到 macOS 钥匙串。', 500)


def has_git_credential():
    try:
        return bool(get_token())
    except RuntimeError:
        return False


def write_git_exclude(p):
    exclude = p / '.git/info/exclude'
    current = exclude.read_text(errors='replace') if exclude.is_file() else ''
    marker = '# LocalLeaf private files'
    if marker not in current:
        addition = '\n' + marker + '\n.localleaf.json\n.build/\n.history/\n.DS_Store\n'
        atomic(exclude, (current.rstrip() + addition).encode())


def git_remote(p):
    if not (p / '.git').is_dir():
        return None
    code, output = git_run(p, 'remote', 'get-url', 'overleaf', check=False)
    return output.strip() if code == 0 else None


def overleaf_branch(p):
    code, value = git_run(p, 'config', '--get', 'localleaf.overleafBranch', check=False)
    if code == 0 and re.fullmatch(r'[A-Za-z0-9._/-]+', value) and not value.startswith(('.', '/')):
        return value
    return 'master'


def project_summary(p):
    record = meta(p)
    actual = project(record['id'])
    summary = dict(record, localProject=bool(record.get('localPath')), path=str(actual))
    if git_remote(actual):
        summary.update(overleafGit=True, gitBranch=overleaf_branch(actual))
    else:
        summary.update(overleafGit=False)
    return summary


def git_status(pid):
    p = project(pid)
    remote = git_remote(p)
    if not remote:
        return {'configured': False, 'available': bool(shutil.which('git') or Path('/usr/bin/git').is_file()),
                'savedToken': has_git_credential()}
    _, dirty_output = git_run(p, 'status', '--porcelain', '--untracked-files=normal', check=False)
    ahead = behind = 0
    branch = overleaf_branch(p)
    fetch_code, fetch_output = git_run(p, 'fetch', '--quiet', 'overleaf', branch, check=False)
    code, counts = git_run(p, 'rev-list', '--left-right', '--count', f'HEAD...overleaf/{branch}', check=False)
    if code == 0 and re.fullmatch(r'\d+\s+\d+', counts):
        ahead, behind = map(int, counts.split())
    _, last = git_run(p, 'log', '-1', '--format=%ct', check=False)
    result = {'configured': True, 'available': True, 'savedToken': has_git_credential(),
            'remote': remote, 'branch': branch, 'dirty': bool(dirty_output),
            'ahead': ahead, 'behind': behind, 'needsPull': behind > 0,
            'lastCommit': int(last) if last.isdigit() else None}
    if fetch_code:
        result['remoteCheckError'] = next((line for line in reversed(fetch_output.splitlines()) if line.strip()), 'Unable to check the remote repository')
    return result


def _sync_project(p):
    branch = overleaf_branch(p)
    git_run(p, 'add', '-A', '--', '.')
    _, staged = git_run(p, 'diff', '--cached', '--name-only', check=False)
    committed = bool(staged)
    if committed:
        stamp = time.strftime('%Y-%m-%d %H:%M:%S')
        git_run(p, 'commit', '-m', 'Sync from LocalLeaf ' + stamp)
    git_run(p, 'fetch', 'overleaf', branch)
    code, output = git_run(p, 'rebase', f'overleaf/{branch}', check=False)
    if code:
        git_run(p, 'rebase', '--abort', check=False)
        raise Problem('Overleaf 和本地修改发生冲突。已保留本地版本，没有推送；请先手动处理 Git 冲突。', 409)
    git_run(p, 'push', 'overleaf', f'HEAD:{branch}')
    touch(p)
    result = git_status(meta(p)['id'])
    result.update({'ok': True, 'committed': committed, 'message': '已与 Overleaf 同步'})
    return result


def sync_project(pid):
    p = project(pid)
    with LOCK:
        guard = GIT_LOCKS.setdefault(pid, threading.Lock())
    if not guard.acquire(blocking=False):
        raise Problem('此项目正在同步，请稍候', 409)
    try:
        if not git_remote(p):
            raise Problem('请先连接 Overleaf Git 项目', 409)
        return _sync_project(p)
    finally:
        guard.release()


def setup_git(pid, remote_url, token, mode='pull'):
    p = project(pid)
    remote_url = normalize_overleaf_url(remote_url)
    if mode not in ('pull', 'upload'):
        raise Problem('请选择有效的首次同步方式')
    with LOCK:
        guard = GIT_LOCKS.setdefault(pid, threading.Lock())
    if not guard.acquire(blocking=False):
        raise Problem('此项目正在同步，请稍候', 409)
    created = not (p / '.git').exists()
    supplied_token = isinstance(token, str) and bool(token.strip())
    try:
        if created:
            git_run(p, 'init', '-b', 'master')
        elif not (p / '.git').is_dir():
            raise Problem('项目中的 .git 结构不受支持')
        git_run(p, 'config', 'user.name', 'LocalLeaf')
        git_run(p, 'config', 'user.email', 'localleaf@localhost')
        helper = ROOT / 'keychain_credential.py'
        git_run(p, 'config', 'credential.helper', f'!/usr/bin/python3 {helper}')
        git_run(p, 'config', 'core.fileMode', 'false')
        write_git_exclude(p)
        if git_remote(p):
            git_run(p, 'remote', 'set-url', 'overleaf', remote_url)
        else:
            git_run(p, 'remote', 'add', 'overleaf', remote_url)
        if supplied_token:
            git_credential(p, token)
        elif not has_git_credential():
            raise Problem('尚未保存 Overleaf Token，请输入新生成的 authentication token。', 401)
        _, remote_head = git_run(p, 'ls-remote', '--symref', 'overleaf', 'HEAD')
        match = re.search(r'(?m)^ref: refs/heads/([^\s]+)\s+HEAD$', remote_head)
        branch = match.group(1) if match else 'master'
        if not re.fullmatch(r'[A-Za-z0-9._/-]+', branch) or branch.startswith(('.', '/')):
            raise Problem('Overleaf 返回了无效的默认分支名称。', 409)
        git_run(p, 'config', 'localleaf.overleafBranch', branch)
        git_run(p, 'fetch', 'overleaf', branch)
        remote_ref = f'overleaf/{branch}'
        code, _ = git_run(p, 'rev-parse', '--verify', 'HEAD', check=False)
        if code:
            _, remote_files = git_run(p, 'ls-tree', '-r', '--name-only', remote_ref)
            protected = ('.localleaf.json', '.build/', '.history/', '.git/')
            if any(name == '.localleaf.json' or name.startswith(protected[1:]) for name in remote_files.splitlines()):
                raise Problem('Overleaf 项目包含 LocalLeaf 的内部保留路径，无法安全连接。', 409)
            if mode == 'pull':
                for source in files(p):
                    relative = source.relative_to(p).as_posix()
                    history(p, relative, source.read_bytes())
                    source.unlink()
                git_run(p, 'reset', '--hard', remote_ref)
                touch(p)
                result = git_status(pid)
                result.update({'ok': True, 'committed': False,
                               'message': '已连接并拉取 Overleaf 最新版本'})
                return result
            with tempfile.TemporaryDirectory(prefix='localleaf-git-') as snapshot_name:
                snapshot = Path(snapshot_name)
                for source in files(p):
                    destination = snapshot / source.relative_to(p)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
                git_run(p, 'reset', '--mixed', remote_ref)
                git_run(p, 'checkout', remote_ref, '--', '.')
                for source in snapshot.rglob('*'):
                    if source.is_file():
                        destination = p / source.relative_to(snapshot)
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source, destination)
        return _sync_project(p)
    except Exception as error:
        if supplied_token and isinstance(error, Problem) and error.status == 401:
            try:
                git_credential(p, '', 'reject')
            except Exception:
                pass
        if created:
            shutil.rmtree(p / '.git', ignore_errors=True)
        raise
    finally:
        guard.release()


def import_git_project(name, remote_url, token):
    with LOCK:
        created = new_project(name)
    p = project(created['id'])
    try:
        setup_git(created['id'], remote_url, token, 'pull')
        return meta(p)
    except Exception:
        shutil.rmtree(p, ignore_errors=True)
        raise


def unpack(encoded):
    try:
        raw = base64.b64decode(encoded, validate=True)
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except Exception:
        raise Problem('无法读取 ZIP 文件')
    with archive:
        entries = [i for i in archive.infolist() if not i.is_dir() and not i.filename.startswith('__MACOSX/')]
        if len(entries) > 2000 or sum(i.file_size for i in entries) > MAX_IMPORT:
            raise Problem('ZIP 最多包含 2000 个文件，解压后总大小不超过 80 MB')
        out = []
        names = set()
        for i in entries:
            if i.file_size > MAX_FILE or ((i.external_attr >> 16) & 0o170000) == 0o120000:
                raise Problem('ZIP 含过大的文件或符号链接')
            if any(x.startswith('.') and x != '..' for x in PurePosixPath(i.filename).parts):
                continue
            safe_path(DATA / 'validation', i.filename)
            if i.filename in names:
                raise Problem('ZIP 包含重复文件名')
            names.add(i.filename)
            out.append((i.filename, archive.read(i)))
        # Strip a common wrapper directory used by exported projects.
        if out and all('/' in n for n, _ in out):
            prefixes = {n.split('/')[0] for n, _ in out}
            if len(prefixes) == 1:
                out = [(n.split('/', 1)[1], d) for n, d in out]
        if not out:
            raise Problem('ZIP 中没有可导入文件')
        return out


class Handler(BaseHTTPRequestHandler):
    server_version = 'LocalLeaf/1.0'

    def log_message(self, fmt, *args):
        pass

    def reply(self, value, status=200, mime='application/json; charset=utf-8', headers=None):
        content = json.dumps(value, ensure_ascii=False).encode() if mime.startswith('application/json') else value
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(content)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'SAMEORIGIN')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; frame-src 'self' blob:; object-src 'self' blob:; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'self'")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(content)

    def check_host(self):
        host = self.headers.get('Host', '')
        allowed = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
        if host not in allowed:
            raise Problem('只允许本机访问', 403)

    def do_GET(self):
        try:
            self.check_host()
            parsed = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            route = parsed.path
            if route == '/api/bootstrap':
                with LOCK:
                    projects = [project_summary(p) for p in DATA.iterdir() if p.is_dir() and not p.is_symlink() and (p / '.localleaf.json').exists()]
                return self.reply({'token': TOKEN, 'apiVersion': API_VERSION, 'pid': os.getpid(),
                                   'projects': sorted(projects, key=lambda x: -x['updated']),
                                   'environment': environment(), 'dataPath': str(DATA)})
            if route == '/api/project':
                with LOCK:
                    p = project(q.get('id'))
                    result = p / '.build/result.json'
                    record = meta(p)
                    info = dict(record, localProject=bool(record.get('localPath')), path=str(p))
                    return self.reply({'project': info, 'files': [{'path': str(f.relative_to(p)), 'size': f.stat().st_size,
                                                                  'updated': f.stat().st_mtime} for f in files(p)],
                                       'build': json.loads(result.read_text()) if result.exists() else None})
            if route == '/api/git-status':
                return self.reply(git_status(q.get('id')))
            if route in ('/api/file', '/api/raw'):
                with LOCK:
                    p = safe_path(project(q.get('id')), q.get('path'))
                    if not p.is_file():
                        raise Problem('文件不存在', 404)
                    data = p.read_bytes()
                if route == '/api/raw':
                    mime = mimetypes.guess_type(p.name)[0] or 'application/octet-stream'
                    if mime not in ('application/pdf', 'image/png', 'image/jpeg', 'image/gif', 'image/webp'):
                        mime = 'application/octet-stream'
                    return self.reply(data, mime=mime)
                try:
                    if b'\x00' in data:
                        raise UnicodeDecodeError('utf8', b'\x00', 0, 1, 'binary')
                    content = data.decode('utf-8')
                except UnicodeDecodeError:
                    return self.reply({'binary': True, 'size': len(data)})
                return self.reply({'content': content, 'revision': revision(data)})
            if route == '/api/pdf':
                p = project(q.get('id')) / '.build/output.pdf'
                if not p.is_file():
                    raise Problem('请先编译论文', 404)
                return self.reply(p.read_bytes(), mime='application/pdf', headers={'Content-Disposition': ('attachment' if q.get('download') else 'inline') + '; filename="paper.pdf"'})
            if route == '/api/synctex':
                return self.reply(synctex_edit(q.get('id'), q.get('page'), q.get('x'), q.get('y')))
            if route == '/api/history':
                p = project(q.get('id'))
                with LOCK:
                    rows = [json.loads(x.read_text()) for x in sorted((p / '.history').glob('*.json'), reverse=True)]
                return self.reply(rows)
            if route == '/api/export':
                p = project(q.get('id'))
                stream = io.BytesIO()
                with LOCK, zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as z:
                    for f in files(p):
                        z.write(f, str(f.relative_to(p)))
                return self.reply(stream.getvalue(), mime='application/zip', headers={'Content-Disposition': 'attachment; filename="project.zip"'})
            if route == '/':
                return self.reply((ROOT / 'static/index.html').read_bytes(), mime='text/html; charset=utf-8')
            if route.startswith('/static/'):
                f = safe_path(ROOT / 'static', route[len('/static/'):])
                if not f.is_file():
                    raise Problem('文件不存在', 404)
                return self.reply(f.read_bytes(), mime=mimetypes.guess_type(f.name)[0] or 'application/octet-stream')
            raise Problem('页面不存在', 404)
        except Problem as e:
            self.reply({'error': e.message}, e.status)
        except (OSError, ValueError) as e:
            self.reply({'error': '读取失败：' + str(e)}, 500)

    def do_POST(self):
        try:
            self.check_host()
            if self.headers.get('X-LocalLeaf-Token') != TOKEN:
                raise Problem('会话已过期，请刷新页面', 403)
            origin = self.headers.get('Origin')
            if origin and origin not in (f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'):
                raise Problem('不允许跨站请求', 403)
            length = int(self.headers.get('Content-Length', '0'))
            if length > MAX_IMPORT * 1.4 or length < 0:
                raise Problem('请求过大', 413)
            b = json.loads(self.rfile.read(length))
            if not isinstance(b, dict):
                raise Problem('请求必须为 JSON 对象')
            route = urlparse(self.path).path
            if route == '/api/compile':
                return self.reply(compile_project(b.get('id')))
            if route == '/api/git-setup':
                return self.reply(setup_git(b.get('id'), b.get('remote'), b.get('token'), b.get('mode', 'pull')))
            if route == '/api/git-sync':
                return self.reply(sync_project(b.get('id')))
            if route == '/api/git-import':
                return self.reply(import_git_project(b.get('name'), b.get('remote'), b.get('token')))
            if route == '/api/pick-local-folder':
                if not sys.platform.startswith('darwin'):
                    raise Problem('本地文件夹选择器目前只支持 macOS', 501)
                script = 'POSIX path of (choose folder with prompt "Choose a LocalLeaf project folder")'
                result = subprocess.run(['osascript', '-e', script], stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, timeout=120)
                if result.returncode:
                    raise Problem('已取消文件夹选择', 409)
                path = result.stdout.decode('utf-8', errors='replace').strip()
                if not path:
                    raise Problem('未选择文件夹')
                return self.reply({'path': path})
            with LOCK:
                if route == '/api/create':
                    return self.reply(new_project(b.get('name', ''), b.get('template', 'english')))
                if route == '/api/import':
                    return self.reply(new_project(b.get('name', 'Imported project'), imported=unpack(b.get('data', ''))))
                if route == '/api/local-import':
                    return self.reply(new_local_project(b.get('name', ''), b.get('path', '')))
                p = project(b.get('id'))
                if route == '/api/save':
                    f = safe_path(p, b.get('path'))
                    content = b.get('content', '').encode('utf-8')
                    if len(content) > MAX_FILE:
                        raise Problem('文件不能超过 20 MB')
                    old = f.read_bytes() if f.is_file() else None
                    if (old is not None and b.get('revision') != revision(old)) or (old is None and b.get('revision') is not None):
                        raise Problem('文件已在其他窗口或本地修改。当前编辑内容已保留，请先下载当前编辑副本，再重新打开文件。', 409)
                    if old != content:
                        if old is not None:
                            history(p, b['path'], old)
                        atomic(f, content)
                        touch(p)
                    return self.reply({'revision': revision(content)})
                if route == '/api/new-file':
                    f = safe_path(p, b.get('path'))
                    if f.exists():
                        raise Problem('文件已存在', 409)
                    atomic(f, b.get('content', '').encode())
                    touch(p)
                    return self.reply({'ok': True})
                if route == '/api/upload':
                    f = safe_path(p, b.get('path'))
                    if f.exists():
                        raise Problem('同名文件已存在，请重命名后上传', 409)
                    content = base64.b64decode(b.get('data', ''), validate=True)
                    if len(content) > MAX_FILE:
                        raise Problem('文件不能超过 20 MB')
                    atomic(f, content)
                    touch(p)
                    return self.reply({'ok': True})
                if route == '/api/rename':
                    src, dst = safe_path(p, b.get('path')), safe_path(p, b.get('newPath'))
                    if not src.is_file():
                        raise Problem('文件不存在', 404)
                    if dst.exists():
                        raise Problem('目标文件已存在', 409)
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    src.rename(dst)
                    m = meta(p)
                    touch(p, main=b['newPath'] if m['main'] == b['path'] else m['main'])
                    return self.reply({'ok': True})
                if route == '/api/delete':
                    f = safe_path(p, b.get('path'))
                    if not f.is_file():
                        raise Problem('文件不存在', 404)
                    if meta(p)['main'] == b['path']:
                        raise Problem('请先在设置中更换主文件，再删除此文件')
                    history(p, b['path'], f.read_bytes())
                    f.unlink()
                    touch(p)
                    return self.reply({'ok': True})
                if route == '/api/settings':
                    main = safe_path(p, b.get('main'))
                    if not main.is_file() or main.suffix != '.tex' or b.get('engine') not in ENGINES:
                        raise Problem('请选择有效的主文件和编译器')
                    name = str(b.get('name', '')).strip()[:100]
                    if not name:
                        raise Problem('请输入项目名称')
                    registry = config_path(p).parent
                    new_id = available_project_id(name, current=registry)
                    updated = touch(p, id=new_id, name=name, main=b['main'], engine=b['engine'])
                    if new_id != registry.name:
                        registry.rename(DATA / new_id)
                    return self.reply(updated)
                if route == '/api/restore':
                    hid = b.get('historyId', '')
                    if not re.fullmatch(r'\d+-[a-f0-9]{6}', hid):
                        raise Problem('版本不存在', 404)
                    h = p / '.history' / (hid + '.json')
                    if not h.is_file():
                        raise Problem('版本不存在', 404)
                    entry = json.loads(h.read_text())
                    content = h.with_suffix('.data').read_bytes()
                    dst = safe_path(p, entry['path'])
                    if dst.is_file():
                        history(p, entry['path'], dst.read_bytes())
                    atomic(dst, content)
                    touch(p)
                    return self.reply({'path': entry['path']})
                raise Problem('操作不存在', 404)
        except Problem as e:
            self.reply({'error': e.message}, e.status)
        except (ValueError, KeyError, OSError, zipfile.BadZipFile) as e:
            self.reply({'error': '操作失败：' + str(e)}, 400)


def main():
    global DATA
    parser = argparse.ArgumentParser(description='LocalLeaf offline LaTeX editor')
    parser.add_argument('--port', type=int, default=8787)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--data-dir', type=Path)
    args = parser.parse_args()
    if args.data_dir:
        DATA = args.data_dir.resolve()
    DATA.mkdir(parents=True, exist_ok=True)
    if not any(DATA.glob('*/.localleaf.json')):
        new_project('My Research Paper')
    try:
        server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    except OSError as e:
        parser.exit(1, f'无法启动端口 {args.port}: {e}\n可使用 --port 8788 更换端口。\n')
    url = f'http://127.0.0.1:{server.server_port}'
    print(f'LocalLeaf is running at {url}\nProjects: {DATA}\nPress Ctrl+C to stop.', flush=True)
    if not args.no_browser:
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
