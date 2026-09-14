import subprocess

program1 = subprocess.Popen(["python3", "./Program1-new.py"])
program2 = subprocess.Popen(["python3", "./Program2.py"])

program1.wait()
program2.wait()