# One 5.5-hour shift: pull the private dataset, start OmniRoute + FreeLLMAPI, run the three generators,
# push new content back every 20 minutes. When no role is left to write, the shift reviews every level instead
# (a second model scores each question, under 8/10 is rewritten). Prints nothing but short status lines (this repo's logs are public).
import os, sys, glob, json, time, shutil, threading, subprocess
from huggingface_hub import snapshot_download, upload_folder, upload_file

H = os.path.expanduser('~'); REPO = os.environ['DATASET']; TOK = os.environ['HF_TOKEN']; END = time.time() + 5.4 * 3600
D = snapshot_download(REPO, repo_type='dataset', token=TOK, local_dir=H + '/pack')
B = D + '/bank'; T = B + '/tools'; C = B + '/content'
os.makedirs(C, exist_ok=True)
if os.path.isdir(B + '/cache'): shutil.copytree(B + '/cache', C + '/.cache', dirs_exist_ok=True)   # half-done levels from the last shift
for s, d in [('omniroute/storage.sqlite', '.omniroute/storage.sqlite'), ('omniroute/.env', '.omniroute/.env'),
             ('freellm/freeapi.db', 'freellmapi/server/data/freeapi.db'), ('freellm/.env', 'freellmapi/.env')]:
    os.makedirs(os.path.dirname(f'{H}/{d}'), exist_ok=True); shutil.copy(f'{D}/{s}', f'{H}/{d}')
for s in ['omni_skip_roles.txt', 'freellm_skip.txt']:   # roles finished or half-done on the laptop stay there
    with open(f'{T}/{s}', 'a', encoding='utf-8') as f: f.write('\n' + open(D + '/done_roles.txt', encoding='utf-8').read() + '\n')
PART = int(os.environ.get('PART', 0))                   # two shifts run at once: part 1 writes roles from the other end
if PART:
    for s in ['omni_roles_top.txt', 'omni_roles_b.txt', 'freellm_roles.txt']:
        rs = open(f'{T}/{s}', encoding='utf-8').read().split(chr(10)); open(f'{T}/{s}', 'w', encoding='utf-8').write(chr(10).join(rs[::-1]))
MEMO = T + '/exhaustive_reviewed.json'                   # review scores of both parts, merged so neither redoes the other's work
memo = {}
for m in glob.glob(T + '/exhaustive_reviewed*.json'): memo.update(json.load(open(m)))
json.dump(memo, open(MEMO, 'w'))
sys.path.insert(0, T); from apply import parse
with open(T + '/all_roles.txt', 'w', encoding='utf-8') as f:
    f.write(chr(10).join(sorted({parse(f'{C}/{x}')[0] for x in os.listdir(C) if x.endswith('.txt')})[PART::2]))   # each part reviews half the roles
T0 = time.time()                                         # only files written or rewritten in this shift are uploaded
log = open(H + '/run.log', 'a')
subprocess.Popen('omniroute', shell=True, cwd=H, stdout=log, stderr=log)
subprocess.Popen('npm run dev -w server', shell=True, cwd=H + '/freellmapi', stdout=log, stderr=log)
time.sleep(90)
print('servers started', flush=True)


idle = set()                                             # generator loops that found no role left to write


def run(env, args):
    subprocess.run(['python3', T + '/generate.py', *args], cwd=B, env=env, stdout=log, stderr=log, timeout=max(1, END - time.time()))


def loop(i, key, args):
    env = dict(os.environ, LLM_API_KEY=open(f'{T}/{key}').read().strip(), NO_PROXY='localhost,127.0.0.1')
    while time.time() < END - 900:
        t = time.time()
        if len(idle) == len(jobs) and i == 0:          # every role written: one loop reviews, so files are never edited twice at once
            run(env, ['--review', '--roles-file', T + '/all_roles.txt', '--workers', '6'])
        elif len(idle) < len(jobs):
            run(env, args)
            if time.time() - t < 120: idle.add(i); print('nothing left to write on loop', i, flush=True)
        time.sleep(30)


jobs = [('omniroute_key.txt', ['--roles-file', T + '/omni_roles_top.txt', '--skip-file', T + '/omni_skip_roles.txt', '--limit', '6', '--workers', '3']),
        ('omniroute_key.txt', ['--roles-file', T + '/omni_roles_b.txt', '--skip-file', T + '/omni_skip_roles.txt', '--limit', '8', '--workers', '4']),
        ('freellm_key.txt', ['--base-url', 'http://127.0.0.1:3001/v1', '--model', 'auto', '--roles-file', T + '/freellm_roles.txt',
                             '--skip-file', T + '/freellm_skip.txt', '--limit', '100', '--workers', '4'])]
for i, (key, args) in enumerate(jobs): threading.Thread(target=loop, args=(i, key, args), daemon=True).start()


def push():
    try:
        if os.path.isdir(C + '/.cache'): shutil.copytree(C + '/.cache', B + '/cache', dirs_exist_ok=True)
        new = [f for f in os.listdir(C) if f.endswith('.txt') and os.path.getmtime(f'{C}/{f}') > T0]
        if os.path.exists(MEMO): upload_file(path_or_fileobj=MEMO, path_in_repo=f'bank/tools/exhaustive_reviewed.{PART}.json', repo_id=REPO, repo_type='dataset', token=TOK)
        if new: upload_folder(repo_id=REPO, repo_type='dataset', token=TOK, folder_path=C, path_in_repo='bank/content',
                              allow_patterns=new, commit_message='cloud sync')
        if os.path.isdir(B + '/cache'): upload_folder(repo_id=REPO, repo_type='dataset', token=TOK, folder_path=B + '/cache',
                                                      path_in_repo='bank/cache', commit_message='cloud sync')
        print(f'synced, {len(new)} new or reviewed level files this shift', flush=True)
    except Exception as e:
        print('sync failed:', type(e).__name__, flush=True)


while time.time() < END:
    time.sleep(min(1200, max(1, END - time.time()))); push()
sys.exit(0)
