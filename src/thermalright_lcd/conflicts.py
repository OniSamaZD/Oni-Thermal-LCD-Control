import subprocess,json
from .subprocess_utils import hidden_subprocess_kwargs

NAMES={"TRCC","USBLCD","USBLCDNEW"}
def thermalright_processes():
    cmd="Get-Process -ErrorAction SilentlyContinue | Where-Object {$_.ProcessName -in @('TRCC','USBLCD','USBLCDNEW')} | Select-Object ProcessName,Id,Path | ConvertTo-Json"
    p=subprocess.run(["powershell","-NoProfile","-Command",cmd],capture_output=True,text=True,**hidden_subprocess_kwargs())
    if not p.stdout.strip():return []
    data=json.loads(p.stdout);return data if isinstance(data,list) else [data]
