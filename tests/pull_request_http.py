"""Same-repository pull-request API exercised with real stock Git branches."""
import json
import os
import subprocess


def check(port, session_headers, admin_headers, token, root, request):
    repo = root / 'git-client'
    endpoint = '/v1/repositories/testuser/git-wire/pull-requests'
    env = dict(os.environ, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
               GIT_TERMINAL_PROMPT='0', GIT_AUTHOR_NAME='Fixture',
               GIT_AUTHOR_EMAIL='fixture@example.test', GIT_COMMITTER_NAME='Fixture',
               GIT_COMMITTER_EMAIL='fixture@example.test', GIT_ASKPASS=str(root / 'git-askpass.sh'),
               LUCE_GIT_USERNAME='testuser', LUCE_GIT_TOKEN=token.decode())

    def git(*args):
        result = subprocess.run(['git', '-C', str(repo), *args], env=env,
                                capture_output=True, timeout=90)
        assert result.returncode == 0, (args, result.stderr)
        return result.stdout.strip()

    git('checkout', '-qb', 'review/native-pr')
    (repo / 'review.txt').write_text('same-repository review\n')
    git('add', 'review.txt')
    git('commit', '-qm', 'pull request fixture')
    head = git('rev-parse', 'HEAD').decode()
    git('push', 'origin', 'review/native-pr')
    git('checkout', '-q', 'main')
    base = git('rev-parse', 'HEAD').decode()

    assert request(port, 'GET', endpoint)[0] == 401
    assert request(port, 'GET', endpoint, headers=admin_headers)[0] == 403
    assert request(port, 'GET', '/v1/repositories/testadmin/demo/pull-requests',
                   headers=admin_headers) == (200, b'[]')
    for payload in ({}, [], {'base': 'main', 'head': 'review/native-pr', 'title': 'x'},
                    {'base': 'main', 'head': 'review/native-pr', 'title': 'x', 'body': '', 'fork': 'other/repo'},
                    {'base': 'refs/heads/main', 'head': 'review/native-pr', 'title': 'x', 'body': ''},
                    {'base': 'main', 'head': 'main', 'title': 'x', 'body': ''},
                    {'base': 'main', 'head': 'missing', 'title': 'x', 'body': ''},
                    {'base': 'main', 'head': 'review/native-pr', 'title': 'bad\nheading', 'body': ''}):
        status, _ = request(port, 'POST', endpoint, payload, session_headers)
        assert status in (400, 404), (payload, status)
    payload = {'base': 'main', 'head': 'review/native-pr', 'title': 'Review π',
               'body': 'Line one\nLine "two"'}
    status, body = request(port, 'POST', endpoint, payload, session_headers)
    assert status == 201, (status, body)
    record = json.loads(body)
    assert record == {
        **record, 'number': 1, 'author': 'testuser', 'title': payload['title'],
        'body': payload['body'], 'base': 'main', 'head': 'review/native-pr',
        'base_commit': base, 'head_commit': head, 'merge_commit': '',
        'state': 'open', 'closed_by': ''
    }
    assert isinstance(record['created_at'], int) and record['updated_at'] >= record['created_at']
    assert request(port, 'POST', endpoint, payload, session_headers)[0] == 409
    status, body = request(port, 'GET', endpoint, headers=session_headers)
    assert status == 200 and [entry['number'] for entry in json.loads(body)] == [1]
    item = endpoint + '/1'
    assert json.loads(request(port, 'GET', item, headers=session_headers)[1])['state'] == 'open'
    assert request(port, 'GET', endpoint + '/0', headers=session_headers)[0] == 400
    assert request(port, 'GET', endpoint + '/257', headers=session_headers)[0] == 400
    assert request(port, 'GET', endpoint + '/2', headers=session_headers)[0] == 404
    assert request(port, 'POST', item, {'state': 'unknown'}, session_headers)[0] == 400
    assert request(port, 'POST', item, {'state': 'closed'}, session_headers)[0] == 200
    closed = json.loads(request(port, 'GET', item, headers=session_headers)[1])
    assert closed['state'] == 'closed' and closed['closed_by'] == 'testuser'
    assert request(port, 'POST', item, {'state': 'open'}, session_headers)[0] == 200
    assert request(port, 'POST', item, {'state': 'merged'}, session_headers)[0] == 409
    git('merge', '--ff-only', 'review/native-pr')
    git('push', 'origin', 'main')
    assert request(port, 'POST', item, {'state': 'merged'}, session_headers)[0] == 200
    merged = json.loads(request(port, 'GET', item, headers=session_headers)[1])
    assert merged['state'] == 'merged' and merged['merge_commit'] == head
    assert merged['head_commit'] == head and merged['closed_by'] == 'testuser'
    assert request(port, 'POST', item, {'state': 'open'}, session_headers)[0] == 409
    print('PASS same-repository pull requests: create, list, close, reopen and verified merge', flush=True)
    return merged


def persisted(port, session_headers, expected, request):
    endpoint = '/v1/repositories/testuser/git-wire/pull-requests'
    status, body = request(port, 'GET', endpoint, headers=session_headers)
    assert status == 200
    records = json.loads(body)
    assert len(records) == 1 and records[0] == expected
    assert json.loads(request(port, 'GET', endpoint + '/1', headers=session_headers)[1]) == expected
    print('PASS pull request state survives registry restart', flush=True)
