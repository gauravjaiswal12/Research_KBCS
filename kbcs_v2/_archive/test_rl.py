import paramiko
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('localhost', port=2222, username='p4', password='p4', timeout=5)

VENV_PY = '/home/p4/src/p4dev-python-venv/bin/python3'

# Test 1: system python numpy
stdin, stdout, stderr = ssh.exec_command('python3 -c "import numpy; print(numpy.__version__)" 2>&1')
print('System numpy:', stdout.read().decode('utf-8', errors='replace').strip())

# Test 2: venv python numpy
stdin, stdout, stderr = ssh.exec_command(VENV_PY + ' -c "import numpy; print(numpy.__version__)" 2>&1')
print('Venv numpy:', stdout.read().decode('utf-8', errors='replace').strip())

# Test 3: run RL with venv python
stdin, stdout, stderr = ssh.exec_command(
    'cd /home/p4/kbcs_v2 && ' + VENV_PY + 
    ' controller/rl_controller.py --flows 1,2,3,4 --duration 4 --switches 9090 2>&1'
)
time.sleep(7)
out = stdout.read().decode('utf-8', errors='replace')
print('RL with venv:')
print(out[:2000])

ssh.close()
