import subprocess, tempfile, os, sqlite3, datetime
BLOCKED = ["os.system","shutil.rmtree","rm -rf /",":(){ :|:& };:"]
def is_safe(c: str) -> bool: return not any(b in c for b in BLOCKED)
def log_action(action: str, command: str = "", blocked=False, **kwargs):
    try:
        os.makedirs("supervisor", exist_ok=True)
        conn = sqlite3.connect("supervisor/logs.db")
        conn.execute("CREATE TABLE IF NOT EXISTS logs (time TEXT, action TEXT, command TEXT, blocked TEXT)")
        conn.execute("INSERT INTO logs VALUES (?,?,?,?)",(datetime.datetime.now().isoformat(),action,command,str(blocked)))
        conn.commit(); conn.close()
    except: pass
def run_sandboxed(code: str, filename="test.py"):
    with tempfile.TemporaryDirectory() as tmp:
        p=os.path.join(tmp,filename)
        open(p,"w").write(code)
        try:
            r=subprocess.run(["python",p],capture_output=True,text=True,timeout=10,cwd=tmp)
            return {"stdout":r.stdout,"stderr":r.stderr,"exit_code":r.returncode}
        except subprocess.TimeoutExpired:
            return {"stdout":"","stderr":"Timeout 10s","exit_code":124}