from .utils import check_all
import subprocess


class CloudflareTunnels:
    tunnels = {}

    def __init__(self):
        check_all()
        self.update()
        subprocess.Popen("cloudflared.exe login", shell=True)

    def update(self):
        ok = subprocess.Popen("cloudflared.exe tunnel list", shell=True, stdout=subprocess.PIPE)
        answer = ok.stdout.read().decode('utf-8')
        answer = answer.split("\n")
        answer = answer[2:-1]
        remove = lambda x: x.split()
        answer = list(map(remove, answer))
        for i in answer:
            if i != "":
                self.tunnels[i[0]] = {"name": i[1], "time_created": i[2]}

    def show_all(self):
        self.update()
        return self.tunnels

    def create_tunnel(self, name):
        subprocess.Popen("cloudflared.exe tunnel create " + name, shell=True)
        self.update()

    def delete_tunnel(self, name, force=False):
        if force:
            subprocess.Popen("cloudflared.exe tunnel delete -f" + name, shell=True)
        subprocess.Popen("cloudflared.exe tunnel delete " + name, shell=True)
        self.update()

    @staticmethod
    def add_dns(name, dns):
        subprocess.Popen("cloudflared.exe tunnel route dns " + name + " " + dns, shell=True, stdout=subprocess.PIPE)




