"""Median wall and CPU time of the per-tool hooks (`sisi watch`), against a bare interpreter start. Run it when the
machine is quiet; under load every process start is slow and the baseline line shows by how much."""
import subprocess, tempfile, os, json, time, statistics, sys
T=tempfile.mkdtemp(); proj=os.path.join(T,"p"); os.makedirs(proj); subprocess.run(["git","init","-q"],cwd=proj)
env=dict(os.environ,SISI_STATE=T+"/s",SISI_DATA=T+"/d",SISI_LIB=T+"/l",SISI_TOOL="claude-code")
B="bin/sisi"
import resource
def one(args,inp=""):
    r0=resource.getrusage(resource.RUSAGE_CHILDREN)
    t=time.perf_counter(); subprocess.run(args,input=inp,text=True,capture_output=True,env=env); w=(time.perf_counter()-t)*1000
    r1=resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu=((r1.ru_utime-r0.ru_utime)+(r1.ru_stime-r0.ru_stime))*1000
    return (w,cpu)
def payload(ev,tool,inp,extra=None):
    d={"session_id":"tm","cwd":proj,"hook_event_name":ev,"tool_name":tool,"tool_input":inp}; d.update(extra or {}); return json.dumps(d)
os.makedirs(T+"/d",exist_ok=True); open(T+"/d/config.json","w").write(json.dumps({"orchestrate":{"direct_calls":100000,"direct_chars":10**12}}))
one([sys.executable,B,"prompt","--tool","claude-code"],json.dumps({"session_id":"tm","cwd":proj,"prompt":"x"*30}))
N=int(sys.argv[1]) if len(sys.argv)>1 else 40
def med(f):
    xs=[f() for _ in range(N)]; return statistics.median(x[0] for x in xs), statistics.median(x[1] for x in xs)
base=med(lambda: one([sys.executable,"-c","import json,re,os,time"]))
print("baseline python start (json,re,os,time imported): wall %.1f ms, cpu %.1f ms  load %.1f"%(base[0],base[1],os.getloadavg()[0]))
cases={"before Read":("PreToolUse","Read",{"file_path":"/x"},None),
 "after Read (500 chars)":("PostToolUse","Read",{"file_path":"/x"},{"tool_response":"x"*500}),
 "before Bash ls":("PreToolUse","Bash",{"command":"ls"},None),
 "after Bash ls":("PostToolUse","Bash",{"command":"ls"},{"tool_response":{"stdout":"a","exit_code":0}}),
 "before Edit":("PreToolUse","Edit",{"file_path":"/x"},None),
 "after Edit":("PostToolUse","Edit",{"file_path":"/x"},{"tool_response":"ok"}),
 # the contract guard on a project file: a document change (never refused) and a source change with no unit (refused)
 "before Edit README (in project)":("PreToolUse","Edit",{"file_path":proj+"/README.md"},None),
 "before Edit src (refused, no unit)":("PreToolUse","Edit",{"file_path":proj+"/src/app.py"},None)}
for name,(ev,tool,inp,ex) in cases.items():
    m=med(lambda: one([sys.executable,B,"watch","--tool","claude-code"],payload(ev,tool,inp,ex)))
    print("%-26s median wall %6.1f ms  cpu %5.1f ms   (cpu over a bare python start: %.1f ms)"%(name,m[0],m[1],m[1]-base[1]))
