import os
import psutil
import datetime
import platform

from tkinter import messagebox
from queue import Queue
from extra.check_exists import check_exists

PLATFORM = platform.system().lower()
IS_LINUX = (PLATFORM == 'linux')


def get_date_string(include_time=True):
    now = datetime.datetime.now()
    year = '{:04d}'.format(now.year)
    month = '{:02d}'.format(now.month)
    day = '{:02d}'.format(now.day)
    hour = '{:02d}'.format(now.hour)
    minute = '{:02d}'.format(now.minute)
    if include_time:
        return '{}-{}-{}_{}{}'.format(year, month, day, hour, minute)
    else:
        return '{}-{}-{}'.format(year, month, day)

def is_network(f):
    return f.startswith("//") or f.startswith("/mnt") or f.startswith("\\\\")

class CopyManager():
    def __init__(self, record_fps: float, storage_folder_list: list, tmp_local_folder: str):

        self.file_queue = Queue()  # type: ignore
        self.text_queue = Queue()  # type: ignore

        folder_exists = []

        if record_fps == 0:
            # Assume 30 fps if not specified in config file
            self.record_frame_rate = 30.0
        else:
            self.record_frame_rate = record_fps

        self.MAX_DISPLAY_FRAMES_PER_SECOND = self.record_frame_rate

        final_dest_folder: str | None = None
        self.IS_NETWORK_DRIVE = False

        # Find the first folder that exists in the config file list, and establish that as the folder to use until program quits
        for idx, d in enumerate(storage_folder_list):
            if len(d) > 0 and d != ".":
                if not (d.endswith("/") or d.endswith("\\")):
                    # To ensure that all candidate folders end in slash, we add one here if it is
                    # not already present. Make exception for empty string, which should not have slash
                    # appended, otherwise it will look like system root.
                    d += "/"

            if len(d) == 0:
                # Semicolon at end sometimes causes parser to think there is an empty folder at end. Ignore.
                continue

            if is_network(d) and IS_LINUX:
                # For network folders on linux, simply test if it exists. Don't try to create if not, as that
                # should have already been handled by LINUX_START_SCRIPT, and hence a non-existent folder
                # indicates a mount failure.
                tmp_exists = os.path.isdir(d)
            else:
                # For local folders, or Windows systems, test for existence and also try to create folder
                # (and possible parent folders) if not found.
                tmp_exists = check_exists(d)

            folder_exists.append(tmp_exists)
            if tmp_exists:
                print(f'Found folder {d}, will use it for primary storage\n')
                # Find the first folder that actually exists (or is creatable)
                if final_dest_folder is None:
                    final_dest_folder = storage_folder_list[idx]
                    self.IS_NETWORK_DRIVE = is_network(final_dest_folder)
                    break
            else:
                print(f'Unable to locate folder {d}\n')

        if final_dest_folder is None:
            nl = "\n"
            messagebox.showinfo(
                title="Error",
                message=f"Could not locate or create specified data folders:\n\n{nl.join(storage_folder_list)}\n\nPlease check config file, and make sure drives are connected.\n\nFor now, will use program folder")

            final_dest_folder = './'

        DEFAULT_LOCAL_FOLDER = os.path.join(os.getcwd(), 'tmp_videos')

        if tmp_local_folder is None or tmp_local_folder == "":
            # Default local folder inside program directory
            self.TEMP_LOCAL_DIRECTORY = DEFAULT_LOCAL_FOLDER
        else:
            if not os.path.isdir(tmp_local_folder):
                messagebox.showinfo(title="Warning", message=f"Unable to find local folder {tmp_local_folder}. Will use program folder instead, which may have limited space")
                self.TEMP_LOCAL_DIRECTORY = DEFAULT_LOCAL_FOLDER
            else:
                self.TEMP_LOCAL_DIRECTORY = tmp_local_folder

        if not os.path.isdir(self.TEMP_LOCAL_DIRECTORY):
            # If local directory is not present, create it, along with any necessary parent directories.
            # We do NOT do this to remote directories, at least for now, due to the possibility of mount
            # point failure. A better option instead is to put a sudo mkdir -p into the LINUX_START_SCRIPT
            # string that runs only if mount succeeds.
            os.makedirs(self.TEMP_LOCAL_DIRECTORY, mode=0o775, exist_ok=True)

        self.FINAL_DESTINATION_FOLDER = final_dest_folder
        
        self.filepath_log = os.path.join(final_dest_folder, get_date_string(include_time=False) + "_log.txt")

        try:
            # Create text file for frame timestamps. Note 'a' for appending.
            fid_log = open(self.filepath_log, 'a')
            print("Logging events to file: \'" + self.filepath_log + "\'")
            fid_log.close()
        except:
            print(
                "Unable to create log file: \'" + self.filepath_log + "\'.\n  Please make sure folder exists and you have write permissions for it.")

    def printt_final(self, s):
        # Print log file text to final destination (rather than cached local copy)
        try:
            # Regenerate log filename in case date has changed
            filename_log = os.path.join(self.FINAL_DESTINATION_FOLDER, get_date_string(include_time=False) + "_log.txt")
            fid_log = open(filename_log, 'a')
            fid_log.write(s)
            fid_log.close()
            return True
        except Exception as e:
            print(e)
            return False

    def get_disk_free_space_GB(self, secondary_storage=False):
        if secondary_storage:
            path = self.TEMP_LOCAL_DIRECTORY
        else:
            path = self.FINAL_DESTINATION_FOLDER
        if path == "":
            path = "./"
        if os.path.exists(path):
            bytes_avail = psutil.disk_usage(path).free
            gigabytes_avail = bytes_avail / 1024 / 1024 / 1024
            return gigabytes_avail
        else:
            return -1

    def get_initial_save_directory(self):
        if self.IS_NETWORK_DRIVE:
            # If using network drive, then we first write to local folder
            # If this is the Raspberry Pi SD card, then space will fill up
            # quickly.
            return check_exists(self.TEMP_LOCAL_DIRECTORY)
        else:
            return self.verify_directory()

    def verify_directory(self):
        # get custom version of datetime for folder search/create
        now = datetime.datetime.now()
        year = '{:04d}'.format(now.year)
        month = '{:02d}'.format(now.month)
        day = '{:02d}'.format(now.day)
        date = '{}-{}-{}'.format(year, month, day)

        # Append subfolder with year, month day
        target_path = os.path.join(self.FINAL_DESTINATION_FOLDER, date)

        # Check if we have to make folder and/or set permissions
        if check_exists(target_path):
            return target_path
        else:
            return ''  # Empty string will force saving to current folder
