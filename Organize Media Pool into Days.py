from datetime import datetime, timedelta
import os

if resolve is None:
    print("Unable to connect to DaVinci Resolve. Ensure Resolve is running.")
    exit()

project_manager = resolve.GetProjectManager()
project = project_manager.GetCurrentProject()
if project is None:
    print("No current project. Please open a project and run the script again.")
    exit()

media_pool = project.GetMediaPool()
if media_pool is None:
    print("Unable to access the media pool.")
    exit()

root_folder = media_pool.GetRootFolder()
if root_folder is None or not hasattr(root_folder, 'AddSubFolder'):
    print("Unable to access the media pool's root folder or required methods.")
    exit()

def get_ordinal_suffix(day):
    """Returns the ordinal suffix for a day (e.g., 1st, 2nd, 3rd, 4th)."""
    if 11 <= day <= 13:
        return "th"
    elif day % 10 == 1:
        return "st"
    elif day % 10 == 2:
        return "nd"
    elif day % 10 == 3:
        return "rd"
    else:
        return "th"

def get_or_create_folder(parent, name):
    """Gets an existing folder or creates a new one under the parent."""
    sub_folders = parent.GetSubFolderList()
    for f in sub_folders:
        if f.GetName() == name:
            return f
    return media_pool.AddSubFolder(parent, name)

def get_all_clips(folder):
    """Recursively collects all clips in a folder and its sub-folders."""
    clips = folder.GetClipList()
    sub_folders = folder.GetSubFolderList()
    for sub in sub_folders:
        clips += get_all_clips(sub)
    return clips

# Initialize Resolve objects
project_manager = resolve.GetProjectManager()
project = project_manager.GetCurrentProject()
media_pool = project.GetMediaPool()
root_folder = media_pool.GetRootFolder()

# Set up bin structure under Master
videos_folder = get_or_create_folder(root_folder, "Videos")
pictures_folder = get_or_create_folder(root_folder, "Pictures")
music_folder = get_or_create_folder(root_folder, "Music")

# Define file extension categories
video_extensions = ['.mp4', '.mov', '.avi', '.mxf', '.mts', '.mkv', '.webm', '.wav', '.lrf', 'srt'] #LRF and SRT are DJI metadata and should stay together, WAV files often accompany DJI microphone files
image_extensions = ['.jpg', '.jpeg', '.png', '.bmp', '.tif', '.tiff', '.gif']
audio_extensions = ['.mp3', '.flac']

# Collect all clips in the media pool
all_clips = get_all_clips(root_folder)

# Process each clip
for clip in all_clips:
    file_path = clip.GetClipProperty("File Path")
    if not file_path:
        continue
    ext = os.path.splitext(file_path)[1].lower()

    if ext in video_extensions:
        date_str = clip.GetClipProperty("Date Created")
        if not date_str:
            continue
        try:
            # Parse creation date with the correct format
            dt = datetime.strptime(date_str, "%a %b %d %Y %H:%M:%S")
            # Adjust date if before 3 AM
            if dt.hour < 3:
                dt = dt - timedelta(days=1)
            bin_date = dt.date()
            # Format date as "Monday, May 12th"
            bin_name = bin_date.strftime("%A, %B ") + str(bin_date.day) + get_ordinal_suffix(bin_date.day)
            date_folder = get_or_create_folder(videos_folder, bin_name)
            media_pool.MoveClips([clip], date_folder)
        except ValueError:
            print(f"Invalid date format for clip {file_path}: {date_str}")
    elif ext in image_extensions:
        media_pool.MoveClips([clip], pictures_folder)
    elif ext in audio_extensions:
        media_pool.MoveClips([clip], music_folder)
    # Other file types remain in their current bins