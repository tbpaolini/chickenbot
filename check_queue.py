from paramiko.client import SSHClient, AutoAddPolicy
import pickle
from pathlib import Path

key = Path(__file__).parents[1] / "Tiago-VM.pem"
ssh = SSHClient()
ssh.set_missing_host_key_policy(AutoAddPolicy)
ssh.connect(
    hostname = "18.116.45.173",
    port = 22,
    username = "ec2-user",
    key_filename = str(key),
)

stdin, stdout, stderr = ssh.exec_command("tail chickenbot/chickenbot_log.txt")
print(stdout.read().decode("utf-8"))

sftp = ssh.open_sftp()
sftp.chdir("chickenbot")
temp_file = sftp.file("temp.bin", "rb")
responses = pickle.load(temp_file)
temp_file.close()
sftp.close()
ssh.close()

for count, line in enumerate(reversed(responses), start=1):
    print(f"{count}. {line}")
input()