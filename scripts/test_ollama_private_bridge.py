"""Linux-only real restricted SSH -> Unix socket -> application image proof.

Disposable synthetic account/keys/gateway. No real model, production connection,
paid AI, app workers, DB or Telegram. Must run as root on a disposable CI runner.
"""
import http.server
import json
import os
import pwd
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time

MODEL = 'gemma4:12b'
DIGEST = '6114515d63c17436a7c0417d82820ac65ad643e2806c5a3c89cb62846436ed0b'


def run(*args, check=True, **kwargs):
    result = subprocess.run(args, check=False, capture_output=True, text=True, timeout=30, **kwargs)
    if check and result.returncode:
        # Disposable fixtures only; never print a key or model/user content.
        raise RuntimeError('isolated command failed: '+str(args[0])+': '+result.stderr[-1200:])
    return result


def main(image):
    assert sys.platform == 'linux' and os.geteuid() == 0, 'disposable Linux/root required'
    sshd = shutil.which('sshd') or '/usr/sbin/sshd'
    user = 'inference-test-' + str(os.getpid())
    group = 'inference-group-' + str(os.getpid())
    processes=[];added_group=False;added_user=False
    class Gateway(http.server.BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def respond(self,value):
            raw=json.dumps(value).encode();self.send_response(200)
            self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        def do_GET(self):
            self.respond(dict(protocol=1,ready=True,model=MODEL,digest=DIGEST,capacity=1))
        def do_POST(self):
            data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            assert data['model']==MODEL and data['digest']==DIGEST
            self.respond(dict(done=True,done_reason='stop',model=MODEL,model_digest=DIGEST,
                message={'content':'{"ok":true}'},prompt_eval_count=5,eval_count=3))
    gateway=http.server.ThreadingHTTPServer(('127.0.0.1',0),Gateway)
    thread=threading.Thread(target=gateway.serve_forever,daemon=True);thread.start()
    try:
        run('groupadd','-g','20001',group);added_group=True
        with tempfile.TemporaryDirectory(prefix='inference-bridge-') as temp:
            root=Path(temp);root.chmod(0o755)
            relay=root/'relay';relay.mkdir();os.chown(relay,0,20001);relay.chmod(0o770)
            home=root/'home';home.mkdir();home.chmod(0o755)
            run('useradd','-M','-d',str(home),'-g',group,'-s','/usr/sbin/nologin','-p','x',user);added_user=True
            # Same owner/mode as the production provisioning contract.
            os.chown(relay,pwd.getpwnam(user).pw_uid,20001);relay.chmod(0o750)
            for name in ('host','client'):
                run('ssh-keygen','-q','-t','ed25519','-N','','-f',str(root/name))
            # StrictModes stops at the account home. Do not put authorized_keys
            # outside home under world-writable /tmp and weaken StrictModes.
            auth=home/'authorized_keys';auth.write_text('restrict,port-forwarding '+(root/'client.pub').read_text())
            auth.chmod(0o644)
            with socket.socket() as probe:
                probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
            conf=root/'sshd.conf'
            # Exact reviewed Match policy, applied to a synthetic user only.
            reviewed=(Path(__file__).resolve().parents[1]/'deploy/ollama-sshd.conf').read_text()
            conf.write_text(f'Port {port}\nListenAddress 127.0.0.1\nHostKey {root}/host\n'
                f'PidFile {root}/sshd.pid\nAuthorizedKeysFile {auth}\nAllowUsers {user}\n'
                'UsePAM no\nStrictModes yes\n' + reviewed.replace('Match User ai-inference','Match User '+user))
            Path('/run/sshd').mkdir(exist_ok=True)
            run(sshd,'-t','-f',str(conf))
            effective=run(sshd,'-T','-f',str(conf),'-C',f'user={user},host=localhost,addr=127.0.0.1').stdout
            for condition in ('allowtcpforwarding remote','permitlisten none','permitopen none','allowstreamlocalforwarding remote','maxsessions 0',
                'passwordauthentication no','allowagentforwarding no','permittty no'):
                assert condition in effective,condition
            daemon=subprocess.Popen([sshd,'-D','-e','-f',str(conf)],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True)
            processes.append(daemon)
            hosts=root/'known_hosts';hosts.write_text(f'[127.0.0.1]:{port} '+(root/'host.pub').read_text())
            ssh=['ssh','-p',str(port),'-i',str(root/'client'),'-o','BatchMode=yes','-o','StrictHostKeyChecking=yes',
                 '-o','UserKnownHostsFile='+str(hosts),'-o','ConnectTimeout=3','-o','ExitOnForwardFailure=yes']
            time.sleep(.3)
            tunnel=subprocess.Popen(ssh+['-NT','-R',f'{relay}/relay.sock:127.0.0.1:{gateway.server_port}',user+'@127.0.0.1'],
                stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True)
            processes.append(tunnel)
            for _ in range(100):
                if (relay/'relay.sock').exists():break
                if tunnel.poll() is not None:
                    daemon.terminate();daemon.wait(5)
                    raise AssertionError('restricted fixture tunnel exited: '+tunnel.stderr.read()[-1000:]
                        +' daemon: '+daemon.stderr.read()[-2500:])
                time.sleep(.05)
            sock=relay/'relay.sock';assert sock.exists() and sock.stat().st_mode & 0o777==0o660
            assert run(*ssh,user+'@127.0.0.1','true',check=False).returncode!=0,'shell unexpectedly allowed'
            denied=run(*ssh,'-NT','-R','127.0.0.1:17173:127.0.0.1:11434',user+'@127.0.0.1',check=False)
            assert denied.returncode!=0,'TCP forward unexpectedly allowed'
            code="import ai_routing as r;assert r.ready();v,b=r.local_completion([{'role':'user','content':'fixture'}],{'type':'object'},16);assert v=={'ok':True};print('restricted private bridge PASS')"
            run('docker','run','--rm','--network','none','--group-add','20001',
                '-v',str(relay)+':/run/ollama:ro','-e','AI_INFERENCE_MODE=ollama_first',
                '--entrypoint','python',image,'-c',code)
            tunnel.terminate();tunnel.wait(5)
            code="import ai_routing as r;assert not r.ready();print('disconnect readiness fails closed PASS')"
            run('docker','run','--rm','--network','none','--group-add','20001','-v',str(relay)+':/run/ollama:ro',
                '-e','AI_INFERENCE_MODE=ollama_first','--entrypoint','python',image,'-c',code)
            print('PASS: real SSH Unix relay, denied shell/TCP, actual network-none app image, disconnect; synthetic inference only')
    finally:
        for process in reversed(processes):
            if process.poll() is None:process.terminate();process.wait(5)
        gateway.shutdown();thread.join(2);gateway.server_close()
        if added_user:run('userdel',user)
        if added_group:run('groupdel',group)


if __name__=='__main__':main(sys.argv[1])
