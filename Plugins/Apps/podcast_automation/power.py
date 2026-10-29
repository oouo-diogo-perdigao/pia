"""Explicitly requested power actions, without forced application termination."""
import subprocess
import sys

def shutdown():
    command=['shutdown','/s','/t','60'] if sys.platform=='win32' else ['shutdown','-h','+1']
    options={'creationflags':subprocess.CREATE_NO_WINDOW} if sys.platform=='win32' else {}
    subprocess.run(command,check=True,capture_output=True,timeout=10,**options)

def cancel():
    command=['shutdown','/a'] if sys.platform=='win32' else ['shutdown','-c']
    options={'creationflags':subprocess.CREATE_NO_WINDOW} if sys.platform=='win32' else {}
    subprocess.run(command,check=True,capture_output=True,timeout=10,**options)
