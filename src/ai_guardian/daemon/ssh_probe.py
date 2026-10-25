"""Fixed, read-only POSIX/Python 3 probe sent over authenticated SSH stdin.

It runs as the SSH user, never sudo, and never executes paths from metadata.
Its bounded response is private protocol data, not CLI or diagnostic output.
No remote package import is needed (including uv tool installations).
"""

PROBE_SCRIPT = r"""
import json, os, pathlib, stat

def read(path, private=False, owner=False):
    path = pathlib.Path(path).expanduser()
    for parent in set(path.absolute().parents) | set(path.resolve().parents):
        info = parent.stat()
        if info.st_uid not in {0, os.getuid()} or (info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX):
            raise ValueError()
    fd = os.open(str(path), os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid not in ({os.getuid()} if owner else {0, os.getuid()}):
            raise ValueError()
        if info.st_mode & (0o077 if private else 0o022):
            raise ValueError()
        with os.fdopen(fd, 'r', encoding='utf-8') as stream:
            fd = None
            value = stream.read(131073)
        if len(value) > 131072:
            raise ValueError()
        return value
    finally:
        if fd is not None:
            os.close(fd)

def probe():
    home = pathlib.Path.home()
    config_dir = pathlib.Path(os.environ.get('AI_GUARDIAN_CONFIG_DIR') or os.environ.get('AI_GUARDIAN_HOME') or pathlib.Path(os.environ.get('XDG_CONFIG_HOME', home / '.config')) / 'ai-guardian').expanduser()
    state_dir = pathlib.Path(os.environ.get('AI_GUARDIAN_STATE_DIR') or pathlib.Path(os.environ.get('XDG_STATE_HOME', home / '.local/state')) / 'ai-guardian').expanduser()
    config_path = config_dir / 'ai-guardian.json'
    pid_path = state_dir / 'daemon.pid'
    if not config_path.exists():
        return {'status': 'unavailable'}
    if not pid_path.exists():
        return {'status': 'stopped'}
    config = json.loads(read(config_path, owner=True)).get('daemon', {})
    pid = json.loads(read(pid_path, owner=True))
    number = pid.get('pid')
    if type(number) is not int or number < 2:
        raise ValueError()
    try:
        os.kill(number, 0)
    except ProcessLookupError:
        return {'status': 'stopped'}
    if pid.get('rest_scheme', 'http') != 'https':
        return {'status': 'https_required'}
    tls = config.get('rest_tls', {})
    if tls.get('enabled') is not True:
        return {'status': 'unavailable'}
    client = tls.get('client', {})
    certificate = read(tls['cert_file'])
    ca = read(client['ca_file']) if client.get('ca_file') else certificate
    token = config.get('auth_token')
    if token:
        read(config_path, private=True, owner=True)
    else:
        token = read(state_dir / 'daemon.token', private=True, owner=True).strip()
    return {'status': 'ok', 'version': 1, 'host': config.get('rest_host', '127.0.0.1'),
            'port': pid.get('rest_port'), 'name': pid.get('name', 'remote'),
            'server_name': client.get('server_name', ''), 'certificate': certificate,
            'ca_pem': ca, 'token': token}

try:
    result = probe()
except (OSError, ValueError, TypeError, KeyError, AttributeError):
    result = {'status': 'unavailable'}
print(json.dumps(result))
"""
