from datetime import datetime
import os
DEBUG=os.getenv("YGGDRASIL_DEBUG","true").lower() in {"1","true","yes","on"}
def log(event,message,**data):
 ts=datetime.now().strftime("%H:%M:%S"); extra=" "+" ".join(f"{k}={v}" for k,v in data.items()) if data else ""; print(f"[{ts}] [{event}] {message}{extra}")
def debug(message,**data):
 if DEBUG: log("DEBUG",message,**data)
def ok(message,**data): log("OK",message,**data)
def warn(message,**data): log("WARN",message,**data)
