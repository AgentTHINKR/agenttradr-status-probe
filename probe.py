"""External uptime probe for agenttradr.com (R104b). Runs on GitHub's servers every 10 minutes (uptime.yml).

Fails the run (red in Actions, and GitHub emails the repo owner) and sends a Pushover when:
  - https://agenttradr.com/api/v1/health does not answer 200 with "status": "healthy", or
  - https://agenttradr.com/api/v1/public/status does not answer 200, or its "overall" is "down".
Each URL gets 3 tries, 20 s apart, so one blip doesn't alert.
De-duplication without state: it reads this workflow's earlier runs. Pushover on the first failed run, again after
1 h, 3 h and 6 h of failing, and once when it recovers.
Env: PUSHOVER_APP_TOKEN, PUSHOVER_USER_KEY (repo secrets), GH_TOKEN + GITHUB_REPOSITORY + WORKFLOW (runs list),
TEST=true sends one TEST Pushover and exits.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

CHECKS = [
    ('health', 'https://agenttradr.com/api/v1/health', lambda d: d.get('status') == 'healthy'),
    ('public status', 'https://agenttradr.com/api/v1/public/status', lambda d: d.get('overall') in ('ok', 'delayed')),
]
REALERT_AFTER = (6, 18, 36)  # consecutive failed runs (10 min apart): 1 h, 3 h, 6 h
UA = {'User-Agent': 'agenttradr-external-probe/1 (+R104b)'}


def probe(url, good):
    last = ''
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
                body = r.read(200000)
                data = json.loads(body or b'{}')
                if r.status == 200 and good(data):
                    return True, f'{r.status}'
                last = f"HTTP {r.status}, {json.dumps(data)[:160]}"
        except urllib.error.HTTPError as e:
            last = f'HTTP {e.code}'
        except (OSError, ValueError) as e:
            last = f'{e.__class__.__name__}: {str(e)[:120]}'
        if attempt < 2:
            time.sleep(20)
    return False, last


def pushover(title, message, priority=1):
    tok, user = os.environ.get('PUSHOVER_APP_TOKEN'), os.environ.get('PUSHOVER_USER_KEY')
    if not tok or not user:
        print('no Pushover secrets set', file=sys.stderr)
        return None
    data = urllib.parse.urlencode({'token': tok, 'user': user, 'title': title[:250], 'message': message[:1024],
                                   'priority': str(priority)}).encode()
    try:
        with urllib.request.urlopen('https://api.pushover.net/1/messages.json', data=data, timeout=20) as r:
            body = json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = json.loads(e.read() or b'{}')
    print(f"pushover status={body.get('status')} request={body.get('request')} errors={body.get('errors')}")
    return body.get('request')


def previous_conclusions():
    """Conclusions of this workflow's earlier completed scheduled runs, newest first."""
    repo, wf, tok = os.environ.get('GITHUB_REPOSITORY'), os.environ.get('WORKFLOW', 'uptime.yml'), os.environ.get('GH_TOKEN')
    if not repo or not tok:
        return []
    url = f'https://api.github.com/repos/{repo}/actions/workflows/{wf}/runs?event=schedule&status=completed&per_page=40'
    req = urllib.request.Request(url, headers={'Authorization': f'Bearer {tok}', 'Accept': 'application/vnd.github+json', **UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            runs = json.loads(r.read()).get('workflow_runs', [])
    except (OSError, ValueError) as e:
        print(f'could not read earlier runs: {e}', file=sys.stderr)
        return []
    me = os.environ.get('GITHUB_RUN_ID')
    return [x.get('conclusion') for x in runs if str(x.get('id')) != me and x.get('conclusion') in ('success', 'failure')]


def main():
    if os.environ.get('TEST') == 'true':
        pushover('TEST: agenttradr.com external probe', 'Test from the GitHub Actions uptime probe (R104b). No action needed.', 0)
        return 0
    failures = []
    for name, url, good in CHECKS:
        ok, detail = probe(url, good)
        print(f"{name}: {'ok' if ok else 'FAIL'} {detail}")
        if not ok:
            failures.append(f'{name} ({url}): {detail}')
    prev = previous_conclusions()
    streak = 0
    for c in prev:
        if c != 'failure':
            break
        streak += 1
    if failures:
        n = streak + 1  # this run included
        if n == 1 or n in REALERT_AFTER:
            pushover(f'agenttradr.com DOWN (external probe, {n * 10} min)',
                     '\n'.join(failures) + '\nSeen from GitHub Actions, outside prod and home. Runbook: docs/ops/R104b-alerts.md', 1)
        else:
            print(f'failing for {n} runs; Pushover already sent')
        return 1
    if streak:
        pushover('agenttradr.com back up (external probe)', f'Both checks pass again after about {streak * 10} min.', 0)
    return 0


if __name__ == '__main__':
    sys.exit(main())
