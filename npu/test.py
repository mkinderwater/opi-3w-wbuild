#!/usr/bin/env python3
"""Run direct VIPLite NPU inference and compare two cases against CPU references."""
import argparse,datetime,hashlib,json,math,os,platform,stat,subprocess,sys,uuid
from pathlib import Path
RUNTIME=Path('/opt/opi-3w-wbuild-npu')

def assess(payload,golden):
    if payload.get('schema')!=1 or payload.get('cid')!=0x1000003b or payload.get('devices')!=1:raise ValueError('Wrong NPU hardware identity')
    if payload.get('input_format')!=2:raise ValueError('Unexpected input format')
    runs=payload.get('runs')
    if not isinstance(runs,list) or len(runs)!=6:raise ValueError('Expected six alternating NPU inferences')
    errors=[]
    for i,result in enumerate(runs):
        if result.get('case_index')!=i%2:raise ValueError('Missing/incorrect input alternation')
        scores=result.get('scores');expected=golden['cases'][i%2]
        if not isinstance(scores,list) or len(scores)!=10 or any(type(x) not in (int,float) or not math.isfinite(x) for x in scores):raise ValueError('Malformed output tensor')
        if not 0.9<=sum(scores)<=1.1 or min(scores)<-0.01 or max(scores)>1.01:raise ValueError('Invalid output probability range/sum')
        error=max(abs(x-y) for x,y in zip(scores,expected['scores']))
        if error>golden['absolute_tolerance'] or max(range(10),key=scores.__getitem__)!=expected['class_index']:raise ValueError('NPU output differs from independent CPU reference: '+expected['name'])
        if type(result.get('hardware_cycles')) is not int or result['hardware_cycles']<=0:raise ValueError('No positive NPU hardware cycle count')
        elapsed=result.get('milliseconds')
        if type(elapsed) not in (int,float) or not math.isfinite(elapsed) or elapsed<0:raise ValueError('Invalid timing')
        errors.append(error)
    return dict(inferences=6,cases=2,max_absolute_error=max(errors),absolute_tolerance=golden['absolute_tolerance'])

def integrity(root):
    m=json.loads((root/'manifest.json').read_text())
    for name,expected in m['files'].items():
        p=root/name
        if p.is_symlink() or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=expected:raise ValueError('NPU asset integrity mismatch: '+name)
    if 'bin/npu-probe' not in m['files']:raise ValueError('NPU probe is not in the manifest')
    return m

def command(report,*args,timeout=30,env=None):
    try:
        p=subprocess.run(args,capture_output=True,text=True,timeout=timeout,env=env)
        result=dict(argv=list(args),code=p.returncode,stdout=p.stdout,stderr=p.stderr)
    except subprocess.TimeoutExpired as e:
        result=dict(argv=list(args),code=124,stdout=(e.stdout or b'').decode(errors='replace') if isinstance(e.stdout,bytes) else e.stdout or '',stderr='Timed out')
    report['commands'].append(result);return result

def execute(root=RUNTIME):
    report=dict(schema=1,status='FAIL',npu_inference_validated=False,commands=[],kernel=platform.release(),timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat())
    try:
        if os.geteuid()!=0:raise ValueError('Run as root')
        m=integrity(root)
        if platform.machine()!='aarch64' or platform.release()!=m['kernel_abi']:raise ValueError('Need AArch64 kernel '+m['kernel_abi'])
        device=Path('/dev/vipcore')
        if not device.exists():
            for module in ['sunxi_npu','vipcore']:
                info=command(report,'modinfo','-F','vermagic',module)
                if info['code']==0 and info['stdout'].split()[:1]==[platform.release()]:
                    command(report,'modprobe',module);command(report,'udevadm','settle','--timeout=5')
                    if device.exists():break
        if not device.exists() or not stat.S_ISCHR(device.stat().st_mode):raise ValueError('NPU character device /dev/vipcore is unavailable')
        report['driver_versions']={p.parent.name:p.read_text().strip() for p in Path('/sys/module').glob('*/version') if any(x in p.parent.name.lower() for x in ['vip','npu'])}
        golden=json.loads((root/'golden.json').read_text())
        env=dict(os.environ,LD_LIBRARY_PATH=str(root/'lib'));env.pop('LD_PRELOAD',None);env.pop('LD_AUDIT',None)
        result=command(report,str(root/'bin/npu-probe'),str(root/'model/lenet-a733.nb'),str(root/'model/sdk-zero.u8'),str(root/'model/synthetic-seven.u8'),timeout=60,env=env)
        if result['code']!=0:raise ValueError('VIPLite probe failed; see commands in this report')
        lines=[line[len('NPU_RESULT='):] for line in result['stdout'].splitlines() if line.startswith('NPU_RESULT=')]
        if len(lines)!=1:raise ValueError('Missing or ambiguous NPU result')
        payload=json.loads(lines[0]);report['validation']=assess(payload,golden);report['hardware_result']=payload
        report.update(status='PASS',npu_inference_validated=True)
    except Exception as e:report['error']=type(e).__name__+': '+str(e)
    if os.geteuid()==0:
        log=command(report,'dmesg','--color=never')
        log['stdout']='\n'.join(line for line in log['stdout'].splitlines() if any(key in line.lower() for key in ('vipcore','sunxi_npu','npu','cma','out of memory')))
    return report

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--json',action='store_true');a=p.parse_args()
    report=execute()
    if os.geteuid()==0:
        folder=Path('/var/log/opi-3w-wbuild');folder.mkdir(parents=True,exist_ok=True)
        output=folder/('npu-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]+'.json')
        report['report_path']=str(output);output.write_text(json.dumps(report,indent=2)+'\n');output.chmod(0o600)
    if a.json:print(json.dumps(report))
    else:
        print('NPU inference: '+report['status'])
        print('Two LeNet inputs; six alternating hardware inferences; independent CPU reference comparison.')
        if report.get('error'):print(report['error'])
        if report.get('validation'):print(json.dumps(report['validation']))
        if report.get('report_path'):print('Report: '+report['report_path'])
    return 0 if report['npu_inference_validated'] else 1
if __name__=='__main__':raise SystemExit(main())
