import os
import subprocess
import platform


PLATFORM = platform.system().lower()
IS_LINUX = (PLATFORM == 'linux')


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
