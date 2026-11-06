#!/usr/bin/python3
"""Offline first boot provisioning. CONFIG.TXT is data, never executable code."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import uuid
import sys
sys.path.insert(0,"/usr/local/lib/opi-3w-wbuild")
from boot_status import atomic, write_status


class SetupError(RuntimeError):
    """A controlled diagnostic message that contains no configuration values."""



def run(*args, **kwargs):
    return subprocess.run(args, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60, **kwargs)


def parse(text):
    values = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith('#'): continue
        key, sep, value = line.partition('=')
        key = key.strip()
        if not sep or key not in {'SSID','PSK','COUNTRY','HIDDEN','TIMEZONE','ROOT_PASSWORD'}:
            raise ValueError('Unknown or malformed configuration key')
        if key in values: raise ValueError('Duplicate configuration key')
        values[key] = value
    ssid = values.get('SSID', '')
    psk = values.get('PSK', '')
    password = values.get('ROOT_PASSWORD', '')
    if not 1 <= len(ssid.encode()) <= 32: raise ValueError('SSID must be 1-32 bytes')
    if not (8 <= len(psk) <= 63 and psk.isascii() and all(32 <= ord(c) <= 126 for c in psk)):
        raise ValueError('PSK must contain 8-63 printable ASCII characters')
    if not 8 <= len(password) <= 64 or any(c in password for c in '\n\r\x00:'):
        raise ValueError('ROOT_PASSWORD must contain 8-64 valid characters')
    if not re.fullmatch('[A-Z]{2}', values.get('COUNTRY','')): raise ValueError('COUNTRY needs two uppercase letters')
    if values.get('HIDDEN') not in ('true','false'): raise ValueError('HIDDEN must be true or false')
    zone = values.get('TIMEZONE','')
    if not re.fullmatch(r'[A-Za-z0-9_+/-]+', zone) or '..' in zone or zone.startswith('/'):
        raise ValueError('Invalid TIMEZONE')
    if not (Path('/usr/share/zoneinfo') / zone).is_file(): raise ValueError('Unknown TIMEZONE')
    return values

def profile(values, connection_uuid):
    # Byte-list SSID encoding avoids interpreting arbitrary SSIDs as keyfile syntax.
    ssid = ';'.join(str(b) for b in values['SSID'].encode()) + ';'
    key = hashlib.pbkdf2_hmac('sha1', values['PSK'].encode(), values['SSID'].encode(), 4096, 32).hex()
    return ('[connection]\nid=opi-3w-wbuild\nuuid=' + connection_uuid + '\ntype=wifi\nautoconnect=true\nautoconnect-priority=100\n'
            '[wifi]\nmode=infrastructure\nssid=' + ssid + '\nhidden=' + values['HIDDEN'] + '\n'
            '[wifi-security]\nkey-mgmt=wpa-psk\npsk=' + key + '\n'
            '[ipv4]\nmethod=auto\n[ipv6]\nmethod=auto\n')


def scrub(text):
    return '\n'.join(line.partition('=')[0] + '=' if line.partition('=')[0].strip() in ('PSK','ROOT_PASSWORD') else line for line in text.splitlines()) + '\n'


def setup(root=Path('/'), execute=run, mounted=os.path.ismount):
    state = root / 'var/lib/opi-3w-wbuild'
    config = root / 'config/CONFIG.TXT'
    phase = 'SETUP_STARTED'
    def mark(name, detail=''):
        nonlocal phase
        phase = name
        write_status(name, detail, root, mounted)
    try:
        mark(phase)
        if (state / 'configured').exists():
            if config.exists(): atomic(config,scrub(config.read_text()))
            mark('PREVIOUSLY_CONFIGURED', 'Linux started; stored NetworkManager profile will reconnect')
            (state/'last-error').unlink(missing_ok=True)
            return
        mark('READING_CONFIG')
        values = parse(config.read_text())
        machine = (root / 'etc/machine-id').read_text().strip()
        if not re.fullmatch('[0-9a-f]{32}', machine): raise RuntimeError('Invalid machine ID')
        hostname = 'opi-3w-wbuild-' + machine[:8]
        mark('SETTING_CREDENTIALS')
        execute('chpasswd', input='root:' + values['ROOT_PASSWORD'] + '\n')
        execute('hostnamectl', 'set-hostname', hostname)
        execute('timedatectl', 'set-timezone', values['TIMEZONE'])
        # Keep vendor host entries, but make the local hostname resolvable.
        hosts = root / 'etc/hosts'
        original = hosts.read_text() if hosts.exists() else '127.0.0.1 localhost\n'
        original = '\n'.join(line for line in original.splitlines() if '# opi-3w-wbuild-hostname' not in line)
        atomic(hosts, original+'\n127.0.1.1 '+hostname+' # opi-3w-wbuild-hostname\n', 0o644)
        ssh_config = root / 'etc/ssh/sshd_config.d/00-opi-3w-wbuild.conf'
        atomic(ssh_config, 'PermitRootLogin yes\nPasswordAuthentication yes\n', 0o644)
        execute('ssh-keygen', '-A')
        (root / 'run/sshd').mkdir(mode=0o755,parents=True,exist_ok=True)
        execute('/usr/sbin/sshd', '-t')
        settings = execute('/usr/sbin/sshd', '-T').stdout.splitlines()
        if 'permitrootlogin yes' not in settings or 'passwordauthentication yes' not in settings:
            raise RuntimeError('Donor SSH configuration overrides provisioning')
        atomic(state/'ssh-ready','complete\n')
        execute('systemctl', 'restart', 'ssh.service')
        execute('systemctl', 'is-active', '--quiet', 'ssh.service')
        mark('SSH_READY', 'Credentials committed; Wi-Fi setup follows')
        mark('WAITING_FOR_WIFI_DEVICE')
        execute('systemctl', 'start', 'NetworkManager.service')
        devices = execute('nmcli','--wait','30','-t','-f','DEVICE,TYPE','device','status').stdout.splitlines()
        interfaces = [line.rsplit(':',1)[0] for line in devices if line.endswith(':wifi')]
        if not interfaces: raise SetupError('NetworkManager detected no Wi-Fi device')
        interface = interfaces[0]
        if not re.fullmatch('[A-Za-z0-9_.-]+',interface): raise RuntimeError('Invalid interface name')
        atomic(state/'wifi-interface',interface+'\n')
        # A regulatory-setting failure must not prevent credentials/SSH setup.
        try: execute('iw','reg','set',values['COUNTRY'])
        except (OSError,subprocess.SubprocessError): mark('REGDOMAIN_WARNING','Could not apply requested regulatory domain')
        uuid_file = state/'connection-uuid'
        connection_uuid = uuid_file.read_text().strip() if uuid_file.exists() else str(uuid.uuid4())
        connection_uuid = str(uuid.UUID(connection_uuid))
        atomic(uuid_file,connection_uuid+'\n')
        connection = root / 'etc/NetworkManager/system-connections/opi-3w-wbuild.nmconnection'
        atomic(connection,profile(values,connection_uuid))
        mark('WIFI_PROFILE_READY')
        execute('nmcli','connection','load',str(connection) if root != Path('/') else '/etc/NetworkManager/system-connections/opi-3w-wbuild.nmconnection')
        mark('WAITING_FOR_DHCP')
        execute('nmcli','--wait','45','connection','up','uuid',connection_uuid,'ifname',interface)
        result = execute('ip','-j','-4','address','show','dev',interface)
        addresses = json.loads(result.stdout)
        assigned = [a['local'] for item in addresses for a in item.get('addr_info',[]) if a.get('scope')=='global']
        if not assigned: raise SetupError('Wi-Fi has no IPv4 address')
        # Commit before scrubbing; retry can finish scrubbing after a power loss.
        atomic(state/'configured','complete\n')
        atomic(config,scrub(config.read_text()))
        (state/'last-error').unlink(missing_ok=True)
        mark('CONFIGURED', 'IPv4='+','.join(assigned)+'; SSH ready')
    except Exception as error:
        # Never include command output, arguments or config values in diagnostics.
        message = 'Setup failed at '+phase+' ('+type(error).__name__+')'
        if isinstance(error,SetupError): message += ': '+str(error)
        atomic(state/'last-error',message+'\n')
        try: write_status('SETUP_FAILED',message,root,mounted)
        except Exception: pass
        print(message,flush=True)
        raise


def main():
    if len(sys.argv)==2 and sys.argv[1]=='--boot-status':
        write_status('LINUX_STARTED','Root filesystem and configuration partition mounted')
    else:
        setup()


if __name__ == '__main__':
    try: main()
    except Exception: raise SystemExit(1)
