# One 5.5-hour shift: pull the private dataset, start OmniRoute + FreeLLMAPI, run the three generators,
# push new content back every 20 minutes. Prints nothing but short status lines (this repo's logs are public).
import os, sys, time, shutil, threading, subprocess
from huggingface_hub import snapshot_download, upload_folder

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
log = open(H + '/run.log', 'a')
subprocess.Popen('omniroute', shell=True, cwd=H, stdout=log, stderr=log)
subprocess.Popen('npm run dev -w server', shell=True, cwd=H + '/freellmapi', stdout=log, stderr=log)
time.sleep(90)
print('servers started', flush=True)


def loop(key, args):
    env = dict(os.environ, LLM_API_KEY=open(f'{T}/{key}').read().strip(), NO_PROXY='localhost,127.0.0.1')
    while time.time() < END - 900:
        subprocess.run(['python3', T + '/generate.py', *args], cwd=B, env=env, stdout=log, stderr=log, timeout=END - time.time())
        time.sleep(30)


jobs = [('omniroute_key.txt', ['--roles-file', T + '/omni_roles_top.txt', '--skip-file', T + '/omni_skip_roles.txt', '--limit', '6', '--workers', '3']),
        ('omniroute_key.txt', ['--roles-file', T + '/omni_roles_b.txt', '--skip-file', T + '/omni_skip_roles.txt', '--limit', '8', '--workers', '4']),
        ('freellm_key.txt', ['--base-url', 'http://127.0.0.1:3001/v1', '--model', 'auto', '--roles-file', T + '/freellm_roles.txt',
                             '--skip-file', T + '/freellm_skip.txt', '--limit', '100', '--workers', '4'])]
for key, args in jobs: threading.Thread(target=loop, args=(key, args), daemon=True).start()


def push():
    try:
        if os.path.isdir(C + '/.cache'): shutil.copytree(C + '/.cache', B + '/cache', dirs_exist_ok=True)
        for src, dst in [(C, 'bank/content'), (B + '/cache', 'bank/cache')]:
            if os.path.isdir(src): upload_folder(repo_id=REPO, repo_type='dataset', token=TOK, folder_path=src, path_in_repo=dst,
                                                 ignore_patterns=['.cache/*'], commit_message='cloud sync')
        n = len([f for f in os.listdir(C) if f.endswith('.txt')])
        print(f'synced, {n} level files in cloud content', flush=True)
    except Exception as e:
        print('sync failed:', type(e).__name__, flush=True)


while time.time() < END:
    time.sleep(min(1200, max(1, END - time.time()))); push()
sys.exit(0)
