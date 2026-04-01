import os
import psutil
import datetime

from tkinter import messagebox
from queue import Queue
from extra.check_exists import check_exists

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
    def __init__(self, RECORD_FRAME_RATE: float, DATA_FOLDER_LIST: list, TMP_LOCAL_FOLDER: str):

        self.file_queue = Queue()  # type: ignore
        self.text_queue = Queue()  # type: ignore

        folder_exists = []

        if RECORD_FRAME_RATE == 0:
            # Assume 30 fps if not specified in config file
            self.record_frame_rate = 30.0
        else:
            self.record_frame_rate = RECORD_FRAME_RATE

        self.MAX_DISPLAY_FRAMES_PER_SECOND = self.record_frame_rate

        FOLDER_THIS_SESSION: str | None = None
        self.IS_NETWORK_DRIVE = False

        # Find the first folder that exists in the config file list, and establish that as the folder to use until program quits
        for idx, d in enumerate(DATA_FOLDER_LIST):
            if len(d) > 0 and d != ".":
                if not (d.endswith("/") or d.endswith("\\")):
                    # To ensure that all candidate folders end in slash, we add one here if it is
                    # not already present. Make exception for empty string, which should not have slash
                    # appended, otherwise it will look like system root.
                    d += "/"

            if len(d) == 0:
                # Semicolon at end sometimes causes parser to think there is an empty folder at end. Ignore.
                continue

            tmp_exists = os.path.isdir(d)
            folder_exists.append(tmp_exists)
            if tmp_exists:
                print(f'Found folder {d}, will use it for primary storage\n')
                # Find the first folder that actually exists (or is creatable)
                if FOLDER_THIS_SESSION is None:
                    FOLDER_THIS_SESSION = DATA_FOLDER_LIST[idx]
                    self.IS_NETWORK_DRIVE = is_network(FOLDER_THIS_SESSION)
                    break
            else:
                print(f'Unable to locate folder {d}\n')

        if FOLDER_THIS_SESSION is None:
            nl = "\n"
            messagebox.showinfo(
                title="Error",
                message=f"Could not locate or create specified data folders:\n\n{nl.join(DATA_FOLDER_LIST)}\n\nPlease check config file, and make sure drives are connected.\n\nFor now, will use program folder")

            FOLDER_THIS_SESSION = './'

        if TMP_LOCAL_FOLDER is None or TMP_LOCAL_FOLDER == "":
            self.TEMP_LOCAL_DIRECTORY = './tmp_videos'
        else:
            if not os.path.isdir(TMP_LOCAL_FOLDER):
                messagebox.showinfo(title="Warning", message=f"Unable to find local folder {TMP_LOCAL_FOLDER}, will use program folder instead, which may have limited space")
                self.TEMP_LOCAL_DIRECTORY = "./tmp_videos"
            else:
                self.TEMP_LOCAL_DIRECTORY = TMP_LOCAL_FOLDER

        self.FOLDER_THIS_SESSION = FOLDER_THIS_SESSION
        
        return
        
        self.filename_log = os.path.join(FOLDER_THIS_SESSION, get_date_string(include_time=False) + "_log.txt")

        try:
            # Create text file for frame timestamps. Note 'a' for appending.
            fid_log = open(self.filename_log, 'a')
            print("Logging events to file: \'" + self.filename_log + "\'")
            fid_log.close()
        except:
            fid_log = None
            print(
                "Unable to create log file: \'" + self.filename_log + "\'.\n  Please make sure folder exists and you have write permissions for it.")

    def printt_final(self, s):
        return True
        # Print log file text to final destination (rather than cached local copy)
        try:
            # Regenerate log filename in case date has changed
            filename_log = os.path.join(self.FOLDER_THIS_SESSION, get_date_string(include_time=False) + "_log.txt")
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
            path = self.FOLDER_THIS_SESSION
        if path == "":
            path = "./"
        if os.path.exists(path):
            bytes_avail = psutil.disk_usage(path).free
            gigabytes_avail = bytes_avail / 1024 / 1024 / 1024
            return gigabytes_avail
        else:
            return None

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
        target_path = os.path.join(self.FOLDER_THIS_SESSION, date)

        # Check if we have to make folder and/or set permissions
        if check_exists(target_path):
            return target_path
        else:
            return ''  # Empty string will force saving to current folder
