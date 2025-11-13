import os
import sys
import subprocess


def check_os():
    """Check if the system is 32 or 64 bit os"""
    return sys.maxsize > 2 ** 32


def get_install_link():
    """Get the link to the latest release of the program"""
    if check_os():
        return "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-386.exe"
    else:
        return "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"


def install_and_add_to_path():
    """Get file from install link and add it to path"""
    # create a folder in the user's appdata folder and add the file to it and add to path
    os.system("mkdir " + os.getenv("APPDATA") + "\\cloudflared")
    os.chdir(os.getenv("APPDATA") + "\\cloudflared")
    os.system("curl -L " + get_install_link() + " --output cloudflared.exe")
    os.system("setx path \"%path%;" + os.getenv("APPDATA") + "\\cloudflared\"")
    os.system("cloudflared.exe update")


def check_if_installed():
    """Check if the program is installed"""
    if os.path.exists(os.getenv("APPDATA") + "\\cloudflared\\cloudflared.exe"):
        return True
    else:
        return False


def check_if_in_path():
    """Check if the program is in the path"""
    if os.getenv("APPDATA") + "\\cloudflared" in os.getenv("PATH"):
        return True
    else:
        return False


def check_all():
    """Main function to check if the program is installed and in path and update it"""
    if not check_if_installed():
        print("Sorry to inform that cloudflare is not in your system installing it now")
        install_and_add_to_path()

    elif not check_if_in_path():
        path = os.getenv("APPDATA") + "\\cloudflared"
        """setx /M path "%path%;path"""
        os.system("setx path \"%path%;" + path + "\"")
        os.environ['PATH'] = os.environ['PATH'] + os.pathsep + path
        print(
            "Path not set until now this is probably your first run of the program this this is solved by temporary environmental variable and we are updating it")

    os.system("cloudflared.exe update")


