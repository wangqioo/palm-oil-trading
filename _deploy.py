import paramiko, os

HOST   = '150.158.146.192'
PORT   = 6002
USER   = 'wq'
PASS   = '152535'
REMOTE = '/home/wq/palm-oil-trading'
LOCAL  = r'D:\ClaudeCode_Work\Work\palm-oil-trading-main'

EXCLUDES = {'.git', '__pycache__', '.pytest_cache', 'logs', 'data',
            '_deploy.py', '.env', 'knowledge_base'}

def should_skip(name):
    if name in EXCLUDES:
        return True
    if name.endswith('.pyc'):
        return True
    return False

def ensure_remote_dir(sftp, path):
    parts = [p for p in path.split('/') if p]
    current = ''
    for part in parts:
        current += '/' + part
        try:
            sftp.stat(current)
        except Exception:
            try:
                sftp.mkdir(current)
            except Exception:
                pass  # 已存在或无权限创建（父目录已有）

def upload_dir(sftp, local_dir, remote_dir):
    ensure_remote_dir(sftp, remote_dir)
    for item in sorted(os.listdir(local_dir)):
        if should_skip(item):
            continue
        lp = os.path.join(local_dir, item)
        rp = remote_dir + '/' + item
        if os.path.isdir(lp):
            upload_dir(sftp, lp, rp)
        else:
            sftp.put(lp, rp)
            print(f'  {rp}')

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
print(f'连接 {HOST}:{PORT} ...')
client.connect(HOST, port=PORT, username=USER, password=PASS, timeout=20)
sftp = client.open_sftp()

print('上传文件...')
upload_dir(sftp, LOCAL, REMOTE)

sftp.close()

print('\n重建 Docker 镜像（server.py 不在挂载卷，需要 build）...')
build_cmd = 'cd /home/wq/palm-oil-trading && docker-compose build 2>&1 && docker-compose up -d 2>&1'
_, stdout, stderr = client.exec_command(build_cmd, timeout=300)
# 流式打印输出
import time
while not stdout.channel.exit_status_ready():
    if stdout.channel.recv_ready():
        chunk = stdout.channel.recv(4096).decode(errors='replace')
        print(chunk, end='', flush=True)
    time.sleep(0.2)
# 读剩余
remaining = stdout.read().decode(errors='replace')
if remaining:
    print(remaining)

client.close()
print('\n部署完成，访问 http://150.158.146.192:6151')
