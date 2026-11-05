import os
import subprocess
import platform
import shutil
import tkinter as tk
from pathlib import Path
from sys import gettrace


PLATFORM = platform.system().lower()
IS_LINUX = (PLATFORM == 'linux')


# This returns true if you ran the program in debug mode from the IDE
DEBUG = gettrace() is not None


def check_exists(target_path):
    # Check if folder exists, and if not, create it and set permissions to 777
    if os.path.isdir(target_path):
        # Path already exists
        if IS_LINUX:
            # check permissions
            m = os.stat(target_path).st_mode & 0o777
            if m != 0o777:
                # Now make read/write/executable by owner, group, and other.
                # This is necessary since these folders are often made by root, but accessed by others.
                # os.chmod(target_path, mode=0o777) # This fails if created by root and we are not root
                proc = subprocess.Popen(['sudo', 'chmod', '777', target_path])
    else:
        # Path doesn't exist, so we make it.
        try:
            os.mkdir(target_path,
                 mode=0o777)  # Note linux umask is usually 755, which limits what permissions non-root can make
        except Exception as ex:
            print(f"Error while attempting to create folder {target_path}")
            print("    Error type is: ", ex.__class__.__name__)
            return ''    # Empty string will force use of current folder

        if IS_LINUX:
            # Make writeable by all users on Linux (we need this because when running as root,
            # we need to make this folder accessible to non-root users also)
            subprocess.Popen(['chmod', '777', target_path])  # This should always work
        print("Folder was not found, but created at: ", target_path)

    return target_path


def copy_file_cross_platform(source_file, destination_path):
    # Copies using plain chunked read/write rather than shutil.copy2. On Linux, shutil uses os.sendfile(),
    # which can fail with [Errno 75] "Value too large for defined data type" on large (>=4GB) files
    # copied to CIFS/SMB network mounts. We copy to a temporary ".part" file and rename on success, so a
    # failed copy never leaves a partial file under the final name.
    tmp_path = None
    try:
        src_path = Path(source_file)
        dst_path = Path(destination_path)

        # Ensure the destination directory exists; create if not
        dst_path.parent.mkdir(exist_ok=True, parents=True)

        if src_path.resolve() == dst_path.resolve():
            return "Source and destination represent the same file."

        tmp_path = str(dst_path) + ".part"
        with open(src_path, 'rb') as fsrc, open(tmp_path, 'wb') as fdst:
            shutil.copyfileobj(fsrc, fdst, length=8 * 1024 * 1024)
            fdst.flush()
            os.fsync(fdst.fileno())

        # Best effort to preserve timestamps; not essential, so ignore failures
        try:
            st = os.stat(src_path)
            os.utime(tmp_path, ns=(st.st_atime_ns, st.st_mtime_ns))
        except Exception:
            pass

        os.replace(tmp_path, dst_path)
        tmp_path = None
        return None

    except PermissionError:
        return "Permission denied."
    except FileNotFoundError:
        return "The source file was not found."
    except Exception as e:
        return f"Copy error: {e}"
    finally:
        # If copy failed, remove the partial file so it doesn't pile up on the network drive
        if tmp_path is not None:
            try:
                os.remove(tmp_path)
            except Exception:
                pass


def browse_data_folder(start_folder):
    p = platform.system()
    if p == "Windows":
        os.startfile(os.path.normpath(start_folder))  # Need normpath to convert forward slahes to backslashes
    elif p == "Linux":
        # Open data folder in the Pi's file manager, PCMan.
        # Must use subprocess.Popen() rather than os.system(), as the latter blocks until the window is closed.
        if os.getuid() == 0:
            # If running as superuser, then we must switch to jhoulab account or else VLC player (and possibly other
            # programs) won't work.

            # But first find what accounts are on this machine besides root
            try:
                acct = os.environ['SUDO_USER']
            except:
                if DEBUG:
                    print('Unable to get environment variable SUDO_USER. Trying to find user account in /home')
                acct_list = os.listdir('/home')
                if len(acct_list) > 0:
                    # This gets the alphabetically first user account. If there is more than one, then issue warning.
                    acct = acct_list[0]
                    if len(acct_list) > 1:
                        tk.messagebox.showinfo("Warning", "More than 1 user account found. Using the first one.")
                else:
                    # Default to jhoulab
                    acct = 'jhoulab'
            # Run file manager after first restoring the original user's XDG_RUNTIME_DIR, which we saved
            # when we called this file from RUN_AS_ROOT.py
            subprocess.Popen(f"sudo XDG_RUNTIME_DIR=$XDG_TMP -i -u {acct} pcmanfm \"{start_folder}\"",
                             shell=True)
        else:
            # Open folder in file manager
            subprocess.Popen(f"pcmanfm \"{start_folder}\"", shell=True)
