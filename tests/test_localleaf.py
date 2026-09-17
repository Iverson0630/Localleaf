import base64
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import urllib.parse
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


def zip_data(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        for name, content in entries:
            z.writestr(name, content)
    return base64.b64encode(buf.getvalue()).decode()


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='localleaf-test-')
        self.original = server.DATA
        server.DATA = Path(self.tmp.name).resolve()

    def tearDown(self):
        server.DATA = self.original
        self.tmp.cleanup()

    def test_zip_round_trip_wrapper_and_traversal(self):
        entries = server.unpack(zip_data([('paper/main.tex', server.ENGLISH), ('paper/refs.bib', server.BIB)]))
        self.assertEqual([n for n, _ in entries], ['main.tex', 'refs.bib'])
        for bad in ['../outside.tex', '/tmp/outside.tex', 'dir/../../outside.tex', 'dir\\evil.tex']:
            with self.subTest(bad=bad), self.assertRaises(server.Problem):
                server.unpack(zip_data([(bad, 'bad')]))
        with self.assertRaises(server.Problem):
            server.unpack(zip_data([('big.tex', 'x' * (server.MAX_FILE + 1))]))

    def test_project_directories_use_readable_names(self):
        first = server.new_project('Paper: Walking/Study')
        second = server.new_project('Paper: Walking/Study')
        self.assertEqual(first['id'], 'Paper- Walking-Study')
        self.assertEqual(second['id'], 'Paper- Walking-Study (2)')
        self.assertTrue((server.DATA / first['id'] / '.localleaf.json').is_file())
        self.assertEqual(server.normalize_overleaf_url('https://git.overleaf.com/abc123'),
                         'https://git@git.overleaf.com/abc123')
        self.assertEqual(server.normalize_overleaf_url(
            'git clone [https://git@git.overleaf.com/abc123](https://git@git.overleaf.com/abc123)'),
            'https://git@git.overleaf.com/abc123')
        with self.assertRaises(server.Problem):
            server.normalize_overleaf_url('file:///tmp/repository')

    def test_git_sync_uses_master_and_excludes_private_files(self):
        git = server.git_bin()
        remote = Path(self.tmp.name) / 'remote.git'
        seed = Path(self.tmp.name) / 'seed'
        subprocess.run([git, 'init', '--bare', '--initial-branch=main', str(remote)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        seed.mkdir()
        subprocess.run([git, 'init', '-b', 'main'], cwd=seed, check=True, stdout=subprocess.DEVNULL)
        subprocess.run([git, 'config', 'user.name', 'Test'], cwd=seed, check=True)
        subprocess.run([git, 'config', 'user.email', 'test@example.invalid'], cwd=seed, check=True)
        (seed / 'remote-note.tex').write_text('remote version\n')
        subprocess.run([git, 'add', '.'], cwd=seed, check=True)
        subprocess.run([git, 'commit', '-m', 'remote'], cwd=seed, check=True, stdout=subprocess.DEVNULL)
        subprocess.run([git, 'remote', 'add', 'origin', str(remote)], cwd=seed, check=True)
        subprocess.run([git, 'push', 'origin', 'main'], cwd=seed, check=True, stdout=subprocess.DEVNULL)

        m = server.new_project('Readable Git Paper')
        p = server.project(m['id'])
        server.git_run(p, 'init', '-b', 'master')
        server.git_run(p, 'config', 'user.name', 'LocalLeaf')
        server.git_run(p, 'config', 'user.email', 'localleaf@localhost')
        server.write_git_exclude(p)
        server.git_run(p, 'remote', 'add', 'overleaf', str(remote))
        server.git_run(p, 'config', 'localleaf.overleafBranch', 'main')
        server.git_run(p, 'fetch', 'overleaf', 'main')
        server.git_run(p, 'reset', '--hard', 'overleaf/main')
        (p / 'local-note.tex').write_text('local version\n')
        result = server.sync_project(m['id'])
        self.assertTrue(result['ok'])
        self.assertTrue(result['configured'])
        self.assertEqual(result['branch'], 'main')
        self.assertFalse(result['dirty'])
        summary = server.project_summary(p)
        self.assertTrue(summary['overleafGit'])
        self.assertEqual(summary['gitBranch'], 'main')
        _, tracked = server.git_run(p, 'ls-files')
        self.assertIn('local-note.tex', tracked)
        self.assertNotIn('.localleaf.json', tracked)
        self.assertNotIn('.build', tracked)

    def test_symlink_cannot_escape_project(self):
        m = server.new_project('links')
        p = server.project(m['id'])
        (p / 'link').symlink_to('/private/tmp')
        with self.assertRaises(server.Problem):
            server.safe_path(p, 'link/outside.tex')

    def test_multifile_english_bibtex_and_failed_build(self):
        m = server.new_project('English')
        p = server.project(m['id'])
        result = server.compile_project(m['id'])
        self.assertTrue(result['ok'], result['log'][-5000:])
        self.assertIn('bibtex', result['log'])
        self.assertNotIn('There were undefined references', result['log'].split('Run number 3')[-1])
        pdf = (p / '.build/output.pdf').read_bytes()
        self.assertTrue(pdf.startswith(b'%PDF-'))
        mapping = (p / '.build/output.synctex.gz').read_bytes()
        self.assertTrue(mapping.startswith(b'\x1f\x8b'))
        hit = None
        for y in range(60, 760, 50):
            for x in range(50, 570, 60):
                try:
                    hit = server.synctex_edit(m['id'], 1, x, y)
                    break
                except server.Problem:
                    pass
            if hit:
                break
        self.assertIsNotNone(hit, 'No SyncTeX source location found on page 1')
        self.assertTrue((p / hit['path']).is_file())
        self.assertGreater(hit['line'], 0)
        server.atomic(p / 'main.tex', b'\\documentclass{article}\n\\begin{document}\n\\undefinedcommand\n\\end{document}')
        failed = server.compile_project(m['id'])
        self.assertFalse(failed['ok'])
        self.assertTrue(failed['hasPdf'])
        self.assertTrue(failed['hasSyncTex'])
        self.assertEqual(pdf, (p / '.build/output.pdf').read_bytes())
        self.assertEqual(mapping, (p / '.build/output.synctex.gz').read_bytes())

    def test_chinese_xelatex(self):
        m = server.new_project('中文', 'chinese')
        result = server.compile_project(m['id'])
        self.assertTrue(result['ok'], result['log'][-5000:])
        self.assertNotIn('Missing character:', result['log'])

    def test_pdflatex_and_nested_main(self):
        m = server.new_project('PDF')
        p = server.project(m['id'])
        (p / 'source').mkdir()
        (p / 'main.tex').rename(p / 'source/paper.tex')
        server.touch(p, main='source/paper.tex', engine='pdflatex')
        result = server.compile_project(m['id'])
        self.assertTrue(result['ok'], result['log'][-5000:])

    def test_lualatex(self):
        m = server.new_project('Lua')
        p = server.project(m['id'])
        server.touch(p, engine='lualatex')
        result = server.compile_project(m['id'])
        self.assertTrue(result['ok'], result['log'][-5000:])

    def test_biber(self):
        m = server.new_project('Biber')
        p = server.project(m['id'])
        server.atomic(p / 'main.tex', r'''\documentclass{article}
\usepackage[backend=biber]{biblatex}
\addbibresource{references.bib}
\begin{document}
Example \cite{lamport1994}.
\printbibliography
\end{document}
'''.encode())
        result = server.compile_project(m['id'])
        self.assertTrue(result['ok'], result['log'][-6000:])
        self.assertIn("rule 'biber", result['log'])


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='localleaf-http-')
        cls.original = server.DATA
        server.DATA = Path(cls.tmp.name).resolve()
        cls.http = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = 'http://127.0.0.1:' + str(cls.http.server_port)
        cls.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.thread.join()
        server.DATA = cls.original
        cls.tmp.cleanup()

    def request(self, route, data=None, headers=None):
        h = {'X-LocalLeaf-Token': server.TOKEN, 'Content-Type': 'application/json'}
        h.update(headers or {})
        route = urllib.parse.quote(route, safe='/?=&%')
        req = urllib.request.Request(self.url + route, data=json.dumps(data).encode() if data is not None else None, headers=h)
        try:
            response = self.opener.open(req)
        except urllib.error.HTTPError as e:
            response = e
        with response:
            body = response.read()
            return response.status, json.loads(body) if response.headers['Content-Type'].startswith('application/json') else body

    def create(self):
        status, m = self.request('/api/create', {'name': 'HTTP test'})
        self.assertEqual(status, 200)
        return m['id']

    def test_autosave_conflict_and_history_restore(self):
        pid = self.create()
        _, old = self.request(f'/api/file?id={pid}&path=main.tex')
        status, saved = self.request('/api/save', {'id':pid,'path':'main.tex','content':'new content','revision':old['revision']})
        self.assertEqual(status, 200)
        status, _ = self.request('/api/save', {'id':pid,'path':'main.tex','content':'stale overwrite','revision':old['revision']})
        self.assertEqual(status, 409)
        _, current = self.request(f'/api/file?id={pid}&path=main.tex')
        self.assertEqual(current['content'], 'new content')
        _, history = self.request(f'/api/history?id={pid}')
        self.assertEqual(history[0]['path'], 'main.tex')
        status, _ = self.request('/api/restore', {'id':pid,'historyId':history[0]['id']})
        self.assertEqual(status, 200)
        _, restored = self.request(f'/api/file?id={pid}&path=main.tex')
        self.assertEqual(restored['content'], old['content'])

    def test_new_rename_delete_restore_and_stale_delete(self):
        pid = self.create()
        self.assertEqual(self.request('/api/new-file', {'id':pid,'path':'notes/a.tex','content':'hello'})[0], 200)
        self.assertEqual(self.request('/api/new-file', {'id':pid,'path':'notes/a.tex'})[0], 409)
        self.assertEqual(self.request('/api/rename', {'id':pid,'path':'notes/a.tex','newPath':'notes/b.tex'})[0], 200)
        _, data = self.request(f'/api/file?id={pid}&path=notes/b.tex')
        self.assertEqual(self.request('/api/delete', {'id':pid,'path':'notes/b.tex'})[0], 200)
        self.assertEqual(self.request('/api/save', {'id':pid,'path':'notes/b.tex','content':'stale','revision':data['revision']})[0], 409)
        _, h = self.request(f'/api/history?id={pid}')
        self.assertEqual(self.request('/api/restore', {'id':pid,'historyId':h[0]['id']})[0], 200)
        self.assertEqual(self.request('/api/delete', {'id':pid,'path':'main.tex'})[0], 400)

    def test_security_boundaries(self):
        pid = self.create()
        self.assertEqual(self.request('/api/create', {'name':'forbidden'}, {'X-LocalLeaf-Token':'wrong'})[0], 403)
        self.assertEqual(self.request('/api/create', {'name':'forbidden'}, {'Origin':'https://other.example'})[0], 403)
        self.assertEqual(self.request('/api/bootstrap', headers={'Host':'evil.example'})[0], 403)
        self.assertEqual(self.request('/api/new-file', {'id':pid,'path':'../escape.tex'})[0], 400)
        self.assertEqual(self.request('/api/file?id='+pid+'&path=.localleaf.json')[0], 400)

    def test_import_export_upload_and_settings(self):
        pid = self.create()
        data = b'\x89PNG\x00binary'
        self.assertEqual(self.request('/api/upload', {'id':pid,'path':'figures/image.png','data':base64.b64encode(data).decode()})[0], 200)
        self.assertEqual(self.request(f'/api/raw?id={pid}&path=figures/image.png')[1], data)
        self.assertTrue(self.request(f'/api/file?id={pid}&path=figures/image.png')[1]['binary'])
        status, renamed = self.request('/api/settings', {'id':pid,'name':'Renamed','main':'main.tex','engine':'pdflatex'})
        self.assertEqual(status, 200)
        pid = renamed['id']
        status, archive = self.request(f'/api/export?id={pid}')
        self.assertEqual(status, 200)
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            self.assertIn('main.tex', z.namelist())
            self.assertIn('figures/image.png', z.namelist())
            self.assertNotIn('.localleaf.json', z.namelist())
        status, imported = self.request('/api/import', {'name':'Imported','data':base64.b64encode(archive).decode()})
        self.assertEqual(status, 200)
        _, content = self.request(f'/api/file?id={imported["id"]}&path=main.tex')
        self.assertEqual(content['content'], server.ENGLISH)

    def test_static_assets_are_local(self):
        for path in ['/', '/static/app.js', '/static/app.css', '/static/pdf-viewer.css', '/static/git-sync.css',
                     '/static/pdf-viewer.mjs', '/static/vendor/pdf.min.mjs',
                     '/static/vendor/pdf.worker.min.mjs', '/static/vendor/codemirror.js',
                     '/static/vendor/stex.js']:
            with self.subTest(path=path):
                status, body = self.request(path)
                self.assertEqual(status, 200)
                self.assertGreater(len(body), 100)


if __name__ == '__main__':
    unittest.main()
