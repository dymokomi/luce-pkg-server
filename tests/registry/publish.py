#!/usr/bin/env python3
"""luc against this registry, end to end: `luc login`, `luc publish` of a history too
large for one push (luc pushes it a commit at a time), then `luc latest` and `luc add`
from another project, which downloads and checks the release pack."""
import http.client
import http.server
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

sys.path.insert(0, str(Path(__file__).resolve().parent))
from registry_client import free_port, start, stop  # noqa: E402

FORWARDED = ('/git/', '/v1/', '/health')


def front(registry_port, site):
    """The routing of deploy/Caddyfile: accounts, Git and health go to the registry, and
    everything else is a static file of the site the registry writes."""
    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def forward(self):
            length = int(self.headers.get('Content-Length') or 0)
            body = self.rfile.read(length) if length else None
            connection = http.client.HTTPConnection('127.0.0.1', registry_port, timeout=600)
            try:
                headers = {k: v for k, v in self.headers.items() if k.lower() not in ('host', 'connection')}
                connection.request(self.command, self.path, body, headers)
                response = connection.getresponse()
                payload = response.read()
            finally:
                connection.close()
            self.send_response(response.status)
            for key, value in response.getheaders():
                if key.lower() not in ('content-length', 'transfer-encoding', 'connection'):
                    self.send_header(key, value)
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def static(self):
            path = (site / self.path.split('?')[0].lstrip('/')).resolve()
            if path.is_dir(): path = path / 'index.html'
            if site not in path.parents or not path.is_file():
                self.send_response(404)
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            payload = path.read_bytes()
            self.send_response(200)
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            if self.command != 'HEAD': self.wfile.write(payload)

        def handle_any(self):
            if self.path.startswith(FORWARDED): self.forward()
            else: self.static()

        do_GET = do_POST = do_HEAD = do_DELETE = handle_any

        def log_message(self, *args): pass

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server

registry, fixture, luc = [Path(value).resolve() for value in sys.argv[1:4]]
TOKEN = 'integration-store-token'
PASSWORD = b'fixture-password'


def manifest(name, kind='package', extra=''):
    return (f'#prisma 4.0\ndef package "{name}" {{\n    str owner = "testadmin"\n    str version = "0.1.0"\n'
            f'    str kind = "{kind}"\n    str language = "luce-base"\n'
            f'    str description = "Publish fixture"\n{extra}}}\n')


with tempfile.TemporaryDirectory(prefix='registry-publish-', dir='/tmp') as temporary:
    root = Path(temporary)
    database = root / 'registry.db'
    subprocess.check_output([str(fixture), str(database)], text=True, timeout=30)
    port = free_port()
    (root / 'site').mkdir()
    proxy = front(port, (root / 'site').resolve())
    origin = f'http://127.0.0.1:{proxy.server_port}'
    environment = dict(os.environ, LUCE_REGISTRY_STORE_TOKEN=TOKEN, LUCE_REGISTRY_ORIGIN='https://pkg.luciaos.com',
                       LUCE_REGISTRY_SITE=str(root / 'site'))
    # luc as a user runs it: its own home, this registry, and `luc` on PATH for the Git
    # credential helper `luc publish` configures
    client = dict(os.environ, LUC_HOME=str(root / 'luc-home'), LUC_REGISTRY=origin,
                  PATH=f'{luc.parent}{os.pathsep}{os.environ["PATH"]}',
                  GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT='0',
                  GIT_AUTHOR_NAME='Fixture', GIT_AUTHOR_EMAIL='fixture@example.test',
                  GIT_COMMITTER_NAME='Fixture', GIT_COMMITTER_EMAIL='fixture@example.test')
    assert luc.name == 'luc', 'the credential helper runs `luc`: pass the binary under that name'

    def run(args, cwd=root, stdin=b'', success=True):
        result = subprocess.run([str(luc), *args], cwd=cwd, input=stdin, env=client, capture_output=True, timeout=900)
        assert (result.returncode == 0) == success, (args, result.stdout, result.stderr)
        assert PASSWORD not in result.stdout + result.stderr
        return result

    def git(work, *args):
        subprocess.run(['git', '-C', str(work), *args], env=client, check=True, capture_output=True, timeout=600)

    with (root / 'registry.log').open('w+') as log:
        process = start(registry, database, port, environment, log)
        try:
            assert b'Logged in as testadmin' in run(['login', 'testadmin'], stdin=PASSWORD + b'\n').stdout

            # Three commits of 24 MiB that does not compress: more than one push may carry.
            work = root / 'greeter'
            (work / 'src').mkdir(parents=True)
            (work / 'package.prisma').write_text(manifest('greeter'))
            (work / 'src/greeter.lucb').write_text('## Greets.\npub func greeting() -> str:\n    return "hello"\n')
            git(work, 'init', '-q', '-b', 'main', '--object-format=sha1')
            for index in range(3):
                (work / 'data.bin').write_bytes(os.urandom(24 * 1048576))
                git(work, 'add', '.')
                git(work, 'commit', '-qm', f'step {index}')
            published = run(['publish', '-m', 'First release'], cwd=work).stdout
            assert b'published testadmin/greeter 0.1.0' in published, published
            assert (root / 'site/testadmin/greeter/0.1.0.pack').is_file()
            print('PASS luc publish releases a history larger than one push', flush=True)

            # The same version again is refused before anything is pushed.
            assert b'already tagged' in run(['publish', '-m', 'Again'], cwd=work, success=False).stderr

            assert run(['latest', 'testadmin/greeter']).stdout.strip() == b'0.1.0'
            consumer = root / 'consumer'
            (consumer / 'src').mkdir(parents=True)
            (consumer / 'package.prisma').write_text(manifest('consumer', 'tool', '    str entry = "src/main.lucb"\n'))
            (consumer / 'src/main.lucb').write_text('pub func main(arguments: str[]) -> i32:\n    return 0\n')
            added = run(['add', 'testadmin/greeter'], cwd=consumer).stdout
            assert b'added dependency testadmin/greeter (newest release, 0.1.0)' in added, added
            written = (consumer / 'package.prisma').read_text()
            dependency = written[written.index('def dependency "greeter"'):]
            assert 'str version' not in dependency[:dependency.index('}')], written
            fetched = list(consumer.rglob('greeter.lucb'))
            assert fetched and fetched[0].read_text().endswith('return "hello"\n'), fetched
            print('PASS another project finds the release, adds it with no version and downloads it', flush=True)

            # A package whose dependency names no version publishes, and its page says newest.
            git(consumer, 'init', '-q', '-b', 'main', '--object-format=sha1')
            (consumer / '.gitignore').write_text('.luc/\nbuild/\n')
            git(consumer, 'add', '.')
            git(consumer, 'commit', '-qm', 'consumer')
            published = run(['publish', '-m', 'First release'], cwd=consumer).stdout
            assert b'published testadmin/consumer 0.1.0' in published, published
            page = (root / 'site/testadmin/consumer/index.html').read_text()
            assert '<td>newest</td>' in page, page
            print('PASS a dependency with no version publishes; its page says newest', flush=True)

            # `name@requirement` holds a project back: the requirement is written as given.
            held = root / 'held'
            (held / 'src').mkdir(parents=True)
            (held / 'package.prisma').write_text(manifest('held', 'tool', '    str entry = "src/main.lucb"\n'))
            (held / 'src/main.lucb').write_text('pub func main(arguments: str[]) -> i32:\n    return 0\n')
            added = run(['add', 'testadmin/greeter@^0.1.0'], cwd=held).stdout
            assert b'added dependency testadmin/greeter ^0.1.0' in added, added
            assert 'str version = "^0.1.0"' in (held / 'package.prisma').read_text()
            print('PASS luc add name@^version writes that requirement', flush=True)
        finally:
            proxy.shutdown()
            stop(process)
