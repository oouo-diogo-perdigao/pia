import subprocess


def execute(piaClose):
    subprocess.Popen(['notepad.exe'])
    piaClose()
