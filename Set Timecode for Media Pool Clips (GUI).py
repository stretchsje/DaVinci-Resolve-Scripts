#!/usr/bin/env python
# DaVinci Resolve Script: Set Timecodes and/or Scene from File Data
# Version 3.3
#
# This script iterates through clips in the Media Pool.
# It provides a GUI to set "Start TC" (timecode) and/or "Scene" (date YYYY-MM-DD) based on:
# 1. Filename (with fallback to creation/modification date)
# 2. File Creation Timestamp
# 3. File Modification Timestamp
# Options include updating all clips or only those with empty/zero values for the selected fields,
# and skipping clips already used in timelines. A summary is displayed at the end.

import tkinter as tk
from tkinter import ttk, messagebox
import os
import datetime
import math
import re # For filename parsing

# --- Configuration (defaults, can be overridden by GUI) ---
EMPTY_TIMECODES = ["00:00:00:00", "00:00:00;00"] # For Start TC
EMPTY_SCENE_VALUES = ["0", "00", "00000000", ""]    # For Scene field, add others if needed

# These will be set by GUI choices
USER_PRIMARY_SOURCE_CHOICE = 'filename'
USER_FALLBACK_SOURCE_CHOICE = 'create'
USER_UPDATE_ONLY_EMPTY = True
USER_SKIP_TIMELINE_CLIPS = True
USER_TARGET_START_TC = True  # New: Whether to update Start TC
USER_TARGET_SCENE = False    # New: Whether to update Scene

# --- DaVinci Resolve Objects (should be available when run in Resolve) ---
try:
    resolve = bmd.scriptapp("Resolve") # Standard way to get Resolve object
except NameError: # If bmd is not defined (e.g. running outside Resolve without full mock setup)
    print("CRITICAL: DaVinci Resolve 'bmd' object not found. This script must be run from Resolve.")
    resolve = None # Ensure resolve is defined to prevent further NameErrors before script exits
except Exception as e:
    print(f"CRITICAL: Could not get DaVinci Resolve object: {e}")
    resolve = None


# --- Filename Parsing Configuration ---
PATTERNS_YMDHMS = [
    (re.compile(r"^(?:PXL_|VID|DJI_|IMG|GH|GX|GOPR|GPMF|G[EH]P)?(\d{4})(\d{2})(\d{2})_?(\d{2})(\d{2})(\d{2})(?:[._-]?)(\d{3})?", re.IGNORECASE), 7),
    (re.compile(r"^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})", re.IGNORECASE), 6),
    (re.compile(r"^(?:signal-)?(\d{4})-(\d{2})-(\d{2})-(\d{2})-(\d{2})-(\d{2})(?:[_-](\d{3}))?", re.IGNORECASE), 7),
]
PATTERNS_YMD_ONLY = [
    (re.compile(r"^(?:IMG-|VID-)?(\d{4})(\d{2})(\d{2})-WA\d+", re.IGNORECASE), 3),
    (re.compile(r"(\d{4})(\d{2})(\d{2})"), 3) # General YYYYMMDD, less specific
]

def parse_datetime_from_filename(filename_str):
    base_name = os.path.splitext(filename_str)[0]
    for pattern, num_groups in PATTERNS_YMDHMS:
        match = pattern.match(base_name)
        if match:
            groups = match.groups()
            try: return datetime.datetime(int(groups[0]), int(groups[1]), int(groups[2]), int(groups[3]), int(groups[4]), int(groups[5]))
            except (ValueError, IndexError): continue
    for pattern, num_groups in PATTERNS_YMD_ONLY:
        match = pattern.search(base_name) # Use search for less specific patterns
        if match:
            groups = match.groups()
            try: return datetime.datetime(int(groups[0]), int(groups[1]), int(groups[2]), 0, 0, 0) # Time defaults to midnight
            except (ValueError, IndexError): continue
    return None

# --- Core Script Logic ---
def get_resolve_objects():
    if not resolve:
        print("Resolve object is not available. Cannot continue.")
        return None, None, None, None
    pm = resolve.GetProjectManager()
    proj = pm.GetCurrentProject()
    if not proj:
        print("No project is currently open.")
        return resolve, pm, None, None
    pool = proj.GetMediaPool()
    if not pool:
        print("Could not access the Media Pool.")
        return resolve, pm, proj, None
    return resolve, pm, proj, pool

def get_timeline_frame_rate(proj):
    try: return float(proj.GetSetting("timelineFrameRate"))
    except: return 24.0 # Sensible default

def format_timecode(h, m, s, f, is_drop):
    sep = ";" if is_drop else ":"
    return f"{int(h):02d}{sep}{int(m):02d}{sep}{int(s):02d}{sep}{int(f):02d}"

def format_scene_date(dt_obj):
    return f"{dt_obj.year:04d}-{dt_obj.month:02d}-{dt_obj.day:02d}"

def is_timecode_empty(tc_str):
    if not tc_str or not tc_str.strip(): return True
    if tc_str in EMPTY_TIMECODES: return True
    parts = tc_str.replace(';', ':').split(':')
    if len(parts) == 4:
        try: return all(int(p) == 0 for p in parts)
        except ValueError: pass
    return False

def is_scene_empty(scene_str):
    if scene_str is None: return True
    if not isinstance(scene_str, str): return False # Treat non-strings as not-empty or unexpected
    scene_str_stripped = scene_str.strip()
    if not scene_str_stripped: return True # Empty string
    if scene_str_stripped in EMPTY_SCENE_VALUES: return True
    if all(char == '0' for char in scene_str_stripped): return True # e.g. "0000-00-00" (if hyphens removed)
    return False

def process_clip(clip, tl_fps, is_df, prim_src, fb_src, upd_empty, skip_tl_clips,
                 update_start_tc, update_scene, stats):
    clip_name = clip.GetName()
    stats['total_scanned'] += 1
    print(f"Processing clip: '{clip_name}'")

    # 1. Check if clip is used in timelines and should be skipped
    if skip_tl_clips:
        try:
            usage_str = clip.GetClipProperty("Usage") # Returns a string like "0", "1", "2"
            if usage_str is not None and int(usage_str) > 0:
                print(f"  Skipping '{clip_name}': Clip is used {usage_str} time(s) in timelines and 'Skip timeline clips' is enabled.")
                stats['skipped_in_timeline'] += 1
                return # Use return without value; stats dict is modified directly
        except Exception as e:
            print(f"  Warning: Could not get or parse usage count for '{clip_name}': {e}. Proceeding cautiously.")
            stats['errors_getting_usage'] += 1

    # 2. Get file path (needed for timestamp sources)
    file_path_dict = clip.GetClipProperty()
    file_path = None
    if isinstance(file_path_dict, dict): file_path = file_path_dict.get("File Path")
    else: file_path = clip.GetClipProperty("File Path")

    if not file_path or not os.path.exists(file_path):
        print(f"  Failed for '{clip_name}': Could not get valid file path ('{file_path}').")
        stats['failed_no_path'] += 1
        return

    # 3. Determine dt_object (datetime from chosen source)
    dt_object = None; source_used = "none"; current_primary_src = prim_src
    if current_primary_src == 'filename':
        stats['filename_attempts'] +=1
        print(f"  Attempting to parse datetime from filename: '{os.path.basename(file_path)}'")
        dt_object = parse_datetime_from_filename(os.path.basename(file_path))
        if dt_object:
            print(f"  Parsed from filename: {dt_object.strftime('%Y-%m-%d %H:%M:%S')}")
            stats['filename_success'] +=1; source_used = "filename"
        else:
            print(f"  Filename parsing failed. Using fallback: '{fb_src}'.")
            stats['filename_failed'] += 1; current_primary_src = fb_src

    if not dt_object: # Try timestamp source (primary or fallback)
        timestamp_type_str = "creation" if current_primary_src == 'create' else "modification"
        if prim_src != 'filename' or source_used == 'none':
            stats[f'{timestamp_type_str}_attempts'] += 1
        try:
            ts_float = os.path.getctime(file_path) if current_primary_src == 'create' else os.path.getmtime(file_path)
            dt_object = datetime.datetime.fromtimestamp(ts_float)
            source_used = current_primary_src
            print(f"  Using file {timestamp_type_str} time: {dt_object.strftime('%Y-%m-%d %H:%M:%S')}")
            if prim_src != 'filename' or (prim_src == 'filename' and source_used != 'filename'):
                stats[f'{timestamp_type_str}_success'] += 1
        except Exception as e:
            print(f"  Error getting {timestamp_type_str} timestamp for '{clip_name}': {e}")
            stats['failed_other'] += 1; return

    if not dt_object:
        print(f"  Failed for '{clip_name}': Could not determine a valid datetime from any source.")
        stats['failed_other'] += 1; return

    # 4. Update selected fields
    action_taken_on_clip = False

    if update_start_tc:
        current_start_tc = clip.GetClipProperty("Start TC")
        if upd_empty and not is_timecode_empty(current_start_tc):
            print(f"  Skipping 'Start TC' for '{clip_name}': Value '{current_start_tc}' not empty.")
            stats['skipped_set_tc'] += 1
        else:
            h, m, s, f = dt_object.hour, dt_object.minute, dt_object.second, 0
            new_tc_str = format_timecode(h, m, s, f, is_df)
            print(f"  Generated 'Start TC': {new_tc_str} (Source: {source_used})")
            if clip.SetClipProperty("Start TC", new_tc_str):
                print(f"  Successfully set 'Start TC'.")
                stats['updated_start_tc_success'] += 1
                stats[f'updated_start_tc_from_{source_used}'] = stats.get(f'updated_start_tc_from_{source_used}', 0) + 1
                action_taken_on_clip = True
            else:
                print(f"  Failed to set 'Start TC'.")
                stats['failed_set_tc'] += 1

    if update_scene:
        current_scene_val = clip.GetClipProperty("Scene")
        if upd_empty and not is_scene_empty(current_scene_val):
            print(f"  Skipping 'Scene' for '{clip_name}': Value '{current_scene_val}' not empty.")
            stats['skipped_set_scene'] += 1
        else:
            new_scene_str = format_scene_date(dt_object)
            print(f"  Generated 'Scene': {new_scene_str} (Source: {source_used})")
            if clip.SetClipProperty("Scene", new_scene_str):
                print(f"  Successfully set 'Scene'.")
                stats['updated_scene_success'] += 1
                stats[f'updated_scene_from_{source_used}'] = stats.get(f'updated_scene_from_{source_used}', 0) + 1
                action_taken_on_clip = True
            else:
                print(f"  Failed to set 'Scene'.")
                stats['failed_set_scene'] += 1

    if action_taken_on_clip:
        stats['clips_with_any_update'] += 1


def iterate_media_pool_folders(folder, tl_fps, is_df, prim_src, fb_src, upd_empty, skip_tl,
                               upd_tc, upd_scene, stats): # Added upd_tc, upd_scene
    if not folder: return
    clips = folder.GetClipList()
    if clips:
        for clip in clips:
            process_clip(clip, tl_fps, is_df, prim_src, fb_src, upd_empty, skip_tl,
                         upd_tc, upd_scene, stats) # Pass new flags
    subfolders = folder.GetSubFolderList()
    if subfolders:
        for subfolder in subfolders:
            iterate_media_pool_folders(subfolder, tl_fps, is_df, prim_src, fb_src, upd_empty, skip_tl,
                                       upd_tc, upd_scene, stats) # Pass new flags

def run_script_logic_with_options(prim_choice, fb_choice, upd_empty_choice, skip_tl_choice,
                                  target_tc_choice, target_scene_choice): # Added target choices
    if not target_tc_choice and not target_scene_choice:
        messagebox.showwarning("No Target Selected", "Please select at least one field (Start TC or Scene) to update.")
        return

    print(f"Options: Primary={prim_choice}, Fallback={fb_choice}, UpdateEmpty={upd_empty_choice}, SkipTimeline={skip_tl_choice}")
    print(f"Targets: Update Start TC={target_tc_choice}, Update Scene={target_scene_choice}")

    res, proj_mgr, proj, pool = get_resolve_objects()
    if not all([res, proj_mgr, proj, pool]):
        messagebox.showerror("Error", "Script cannot run due to missing Resolve objects. Exiting.")
        return

    stats = {
        'total_scanned': 0, 'clips_with_any_update': 0,
        'skipped_set_tc': 0, 'skipped_set_scene': 0, 'skipped_in_timeline':0,
        'failed_no_path': 0, 'failed_other': 0,
        'failed_set_tc': 0, 'failed_set_scene':0, 'errors_getting_usage':0,
        'filename_attempts': 0, 'filename_success': 0, 'filename_failed': 0,
        'creation_attempts': 0, 'creation_success': 0,
        'modification_attempts': 0, 'modification_success': 0,
        'updated_start_tc_success': 0, 'updated_scene_success': 0,
        # Detailed source for TC
        'updated_start_tc_from_filename': 0, 'updated_start_tc_from_create': 0, 'updated_start_tc_from_modify': 0,
        # Detailed source for Scene
        'updated_scene_from_filename': 0, 'updated_scene_from_create': 0, 'updated_scene_from_modify': 0,
    }
    # Initialize all keys to ensure they exist for the summary
    for key in list(stats.keys()): # Iterate over a copy of keys
        if '_from_' in key and key not in stats: stats[key] = 0


    print(f"Starting script for project: {proj.GetName()}")
    tl_fps = get_timeline_frame_rate(proj); is_df = proj.GetSetting("timelineDropFrameTimecode") == "1"
    print(f"Timeline: {tl_fps}fps, DropFrame: {is_df}")

    print("--- Starting Media Pool Scan ---")
    iterate_media_pool_folders(pool.GetRootFolder(), tl_fps, is_df, prim_choice, fb_choice,
                               upd_empty_choice, skip_tl_choice,
                               target_tc_choice, target_scene_choice, stats) # Pass target choices
    print("\n--- Script Finished ---")

    summary_lines = [
        f"Total clips scanned: {stats['total_scanned']}",
        f"Clips with at least one field updated: {stats['clips_with_any_update']}",
    ]
    if target_tc_choice and stats['updated_start_tc_success'] > 0 :
        summary_lines.append(f"  - Start TC fields updated: {stats['updated_start_tc_success']}")
        if stats['updated_start_tc_from_filename'] > 0: summary_lines.append(f"    - From Filename: {stats['updated_start_tc_from_filename']}")
        if stats['updated_start_tc_from_create'] > 0: summary_lines.append(f"    - From Creation Date: {stats['updated_start_tc_from_create']}")
        if stats['updated_start_tc_from_modify'] > 0: summary_lines.append(f"    - From Modification Date: {stats['updated_start_tc_from_modify']}")

    if target_scene_choice and stats['updated_scene_success'] > 0:
        summary_lines.append(f"  - Scene fields updated: {stats['updated_scene_success']}")
        if stats['updated_scene_from_filename'] > 0: summary_lines.append(f"    - From Filename: {stats['updated_scene_from_filename']}")
        if stats['updated_scene_from_create'] > 0: summary_lines.append(f"    - From Creation Date: {stats['updated_scene_from_create']}")
        if stats['updated_scene_from_modify'] > 0: summary_lines.append(f"    - From Modification Date: {stats['updated_scene_from_modify']}")


    if prim_choice == 'filename':
        summary_lines.extend([
            f"Filename parsing: {stats['filename_attempts']} attempts",
            f"  - Succeeded: {stats['filename_success']}",
            f"  - Failed (fallback used): {stats['filename_failed']}",
        ])
    summary_lines.extend([
        f"Clips skipped (field-specific):",
        f"  - Start TC (already set): {stats['skipped_set_tc']}",
        f"  - Scene (already set): {stats['skipped_set_scene']}",
        f"  - Used in timeline (and skipping enabled): {stats['skipped_in_timeline']}",
        f"Clips failed:",
        f"  - No valid file path: {stats['failed_no_path']}",
        f"  - To set Start TC property: {stats['failed_set_tc']}",
        f"  - To set Scene property: {stats['failed_set_scene']}",
        f"  - Other errors (timestamp/usage read): {stats['failed_other'] + stats['errors_getting_usage']}",
    ])
    if stats['clips_with_any_update'] > 0: summary_lines.append("\nNote: You may need to re-sort Media Pool bins by the updated fields.")

    final_summary_message = "\n".join(summary_lines)
    print(final_summary_message)
    messagebox.showinfo("Script Execution Summary", final_summary_message)

# --- GUI Setup ---
def show_options_gui():
    root = tk.Tk()
    root.title("Timecode & Scene Setter V3.3")
    try: root.attributes('-topmost', True)
    except tk.TclError: print("Note: Could not set window 'topmost'.")

    prim_src_var = tk.StringVar(value=USER_PRIMARY_SOURCE_CHOICE)
    fb_src_var = tk.StringVar(value=USER_FALLBACK_SOURCE_CHOICE)
    upd_empty_var = tk.BooleanVar(value=USER_UPDATE_ONLY_EMPTY)
    skip_tl_var = tk.BooleanVar(value=USER_SKIP_TIMELINE_CLIPS)
    target_tc_var = tk.BooleanVar(value=USER_TARGET_START_TC) # New
    target_scene_var = tk.BooleanVar(value=USER_TARGET_SCENE)  # New

    main_frm = ttk.Frame(root, padding="10"); main_frm.grid(sticky=(tk.W,tk.E,tk.N,tk.S))
    current_row = 0

    prim_frm = ttk.LabelFrame(main_frm, text="Primary Date/Time Source", padding="10")
    prim_frm.grid(row=current_row, column=0, padx=5, pady=5, sticky=(tk.W, tk.E)); current_row += 1
    ttk.Radiobutton(prim_frm, text="From Filename", variable=prim_src_var, value="filename").pack(anchor=tk.W)
    ttk.Radiobutton(prim_frm, text="From File Creation Date", variable=prim_src_var, value="create").pack(anchor=tk.W)
    ttk.Radiobutton(prim_frm, text="From File Modification Date", variable=prim_src_var, value="modify").pack(anchor=tk.W)

    fb_frm = ttk.LabelFrame(main_frm, text="Fallback (if Filename Fails)", padding="10")
    fb_frm.grid(row=current_row, column=0, padx=5, pady=5, sticky=(tk.W, tk.E)); current_row += 1
    rb_fb_cr = ttk.Radiobutton(fb_frm, text="File Creation Date", variable=fb_src_var, value="create")
    rb_fb_cr.pack(anchor=tk.W)
    rb_fb_md = ttk.Radiobutton(fb_frm, text="File Modification Date", variable=fb_src_var, value="modify")
    rb_fb_md.pack(anchor=tk.W)

    def toggle_fb_state(*args):
        state = tk.NORMAL if prim_src_var.get() == "filename" else tk.DISABLED
        for child in fb_frm.winfo_children(): child.configure(state=state)
    prim_src_var.trace_add("write", toggle_fb_state); toggle_fb_state()

    # New Target Fields Frame
    target_frm = ttk.LabelFrame(main_frm, text="Fields to Update", padding="10")
    target_frm.grid(row=current_row, column=0, padx=5, pady=5, sticky=(tk.W, tk.E)); current_row += 1
    ttk.Checkbutton(target_frm, text="Start Timecode (Start TC)", variable=target_tc_var).pack(anchor=tk.W)
    ttk.Checkbutton(target_frm, text="Scene (as YYYY-MM-DD)", variable=target_scene_var).pack(anchor=tk.W)


    upd_frm = ttk.LabelFrame(main_frm, text="Update Behavior Options", padding="10")
    upd_frm.grid(row=current_row, column=0, padx=5, pady=5, sticky=(tk.W, tk.E)); current_row += 1
    ttk.Checkbutton(upd_frm, text="Update only if field is zero/empty", variable=upd_empty_var).pack(anchor=tk.W)
    ttk.Checkbutton(upd_frm, text="Skip clips used in timelines (Recommended)", variable=skip_tl_var).pack(anchor=tk.W)

    btn_frm = ttk.Frame(main_frm, padding="10"); btn_frm.grid(row=current_row, column=0, sticky=(tk.W, tk.E)); current_row += 1
    res = {"cancelled": True}
    def on_run():
        if not target_tc_var.get() and not target_scene_var.get():
            messagebox.showwarning("No Target Field", "Please select at least one field to update (Start TC or Scene).")
            return

        res.update({"primary": prim_src_var.get(), "fallback": fb_src_var.get(),
                    "update_empty": upd_empty_var.get(), "skip_timeline": skip_tl_var.get(),
                    "target_tc": target_tc_var.get(), "target_scene": target_scene_var.get(), # Add new choices
                    "cancelled": False})
        root.destroy()
    def on_cancel(): res["cancelled"] = True; root.destroy()

    ttk.Button(btn_frm, text="Run Script", command=on_run, width=12).pack(side=tk.RIGHT, padx=(5,0))
    ttk.Button(btn_frm, text="Cancel", command=on_cancel, width=12).pack(side=tk.RIGHT, padx=(0,5))

    root.bind('<Return>', lambda e: on_run()); root.bind('<Escape>', lambda e: on_cancel())
    root.protocol("WM_DELETE_WINDOW", on_cancel)
    root.update_idletasks()
    w = max(430, root.winfo_width()); h = root.winfo_height()
    x = (root.winfo_screenwidth()//2)-(w//2); y = (root.winfo_screenheight()//2)-(h//2)
    root.geometry(f'{w}x{h}+{x}+{y}'); root.minsize(w,h)
    root.mainloop()
    return res

# --- Main Script Execution ---
if __name__ == "__main__":
    # This check is essential if running directly without Resolve's environment fully loaded
    if resolve is None:
        print("Resolve object not initialized. Script cannot run.")
        # Optionally show a Tkinter error message if GUI components are available
        try:
            root = tk.Tk()
            root.withdraw() # Hide main Tk window for messagebox
            messagebox.showerror("Resolve Error", "DaVinci Resolve script object not found. This script must be run from within DaVinci Resolve.")
            root.destroy()
        except tk.TclError: # In case Tkinter can't even initialize
            pass
    else:
        choices = show_options_gui()
        if choices["cancelled"]:
            print("Script cancelled by user.")
        elif choices.get("primary"): # Check if essential choices were made (not cancelled early)
            print("GUI options collected. Proceeding...")
            run_script_logic_with_options(
                choices["primary"], choices["fallback"],
                choices["update_empty"], choices["skip_timeline"],
                choices["target_tc"], choices["target_scene"] # Pass new choices
            )
        print("Script execution finished or was cancelled.")