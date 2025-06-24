from datetime import datetime, timedelta
import os
import collections

# --- DaVinci Resolve Connection and Project Setup ---
try:
    resolve
except NameError:
    print("Unable to connect to DaVinci Resolve. This script must be run from the Resolve console.")
    exit()

project_manager = resolve.GetProjectManager()
project = project_manager.GetCurrentProject()
if not project:
    print("No current project. Please open a project and run the script again.")
    exit()

media_pool = project.GetMediaPool()
root_folder = media_pool.GetRootFolder()
if not media_pool or not root_folder:
    print("Unable to access the media pool or its root folder.")
    exit()


# --- Helper Functions ---

def get_or_create_folder(parent, name):
    """Gets an existing folder or creates a new one under the parent."""
    # Resolve's API doesn't have a direct "get child by name" method.
    for f in parent.GetSubFolderList():
        if f.GetName() == name:
            return f
    try:
        return media_pool.AddSubFolder(parent, name)
    except Exception as e:
        print(f"Error creating folder '{name}': {e}")
        return None

def get_all_clips(folder):
    """Recursively collects all clips in a folder and its sub-folders."""
    clips = list(folder.GetClipList()) # Ensure it's a mutable list
    for sub in folder.GetSubFolderList():
        clips.extend(get_all_clips(sub))
    return clips

# --- Main Script Logic ---

print("Starting media organization script...")

# 1. Setup Bin Structure and Define File Extensions
videos_folder = get_or_create_folder(root_folder, "Videos")
pictures_folder = get_or_create_folder(root_folder, "Pictures")
music_folder = get_or_create_folder(root_folder, "Music")

video_extensions = ['.mp4', '.mov', '.avi', '.mxf', '.mts', '.mkv', '.webm', '.wav', '.lrf', '.srt']
image_extensions = ['.jpg', '.jpeg', '.png', '.bmp', '.tif', '.tiff', '.gif']
audio_extensions = ['.mp3', '.flac']

# 2. First Pass: Collate all clips by date
all_clips = get_all_clips(root_folder)
video_clips_by_date = collections.defaultdict(list)
other_media_to_move = []

print(f"Analyzing {len(all_clips)} clips...")

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
            # Parse the creation date string provided by Resolve
            dt = datetime.strptime(date_str, "%a %b %d %Y %H:%M:%S")
            
            # If a clip was shot between midnight and 3 AM, assign it to the previous day
            if dt.hour < 3:
                dt -= timedelta(days=1)
                
            bin_date = dt.date()
            video_clips_by_date[bin_date].append(clip)
        except (ValueError, TypeError):
            print(f"Could not parse date for clip '{clip.GetName()}': '{date_str}'")
    elif ext in image_extensions or ext in audio_extensions:
        other_media_to_move.append((clip, ext))

# 3. Second Pass: Determine grouping for video dates
GROUPING_THRESHOLD = 20
MAX_GROUP_SPAN_DAYS = 7
sorted_dates = sorted(video_clips_by_date.keys())
grouped_dates = []
i = 0

while i < len(sorted_dates):
    current_date = sorted_dates[i]
    num_clips = len(video_clips_by_date[current_date])

    # If clip count is over the threshold, it's its own group
    if num_clips > GROUPING_THRESHOLD:
        grouped_dates.append([current_date])
        i += 1
        continue

    # This is a "small" day, so start a potential group
    small_group = [current_date]
    j = i + 1
    while j < len(sorted_dates):
        next_date = sorted_dates[j]
        
        # Check if the next day meets all grouping criteria
        is_consecutive = (next_date - small_group[-1]).days == 1
        is_small = len(video_clips_by_date[next_date]) <= GROUPING_THRESHOLD
        span_ok = (next_date - small_group[0]).days < MAX_GROUP_SPAN_DAYS

        if is_consecutive and is_small and span_ok:
            small_group.append(next_date)
            j += 1
        else:
            # Stop grouping if criteria are not met
            break
            
    grouped_dates.append(small_group)
    i = j # Move the main index to the end of the processed group

# 4. Third Pass: Create folders and move video clips
print("Creating folders and moving video clips...")
for group in grouped_dates:
    if not group: continue
    
    start_date = group[0]
    end_date = group[-1]
    
    if len(group) == 1:
        # Format for a single day: "06/02 (Tuesday)"
        bin_name = start_date.strftime("%m/%d (%A)")
    else:
        # Format for a date range: "06/02 - 06/05"
        bin_name = f"{start_date.strftime('%m/%d')} - {end_date.strftime('%m/%d')}"
        
    date_folder = get_or_create_folder(videos_folder, bin_name)
    if not date_folder:
        print(f"Skipping clips for folder '{bin_name}' due to creation error.")
        continue

    clips_to_move = []
    for date_in_group in group:
        clips_to_move.extend(video_clips_by_date[date_in_group])
    
    if clips_to_move:
        media_pool.MoveClips(clips_to_move, date_folder)

# 5. Final Pass: Move other media types
print("Moving pictures and music files...")
for clip, ext in other_media_to_move:
    if ext in image_extensions:
        media_pool.MoveClips([clip], pictures_folder)
    elif ext in audio_extensions:
        media_pool.MoveClips([clip], music_folder)

print("Script finished successfully.")