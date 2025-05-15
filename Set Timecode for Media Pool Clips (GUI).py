#!/usr/bin/env python
# DaVinci Resolve Script: Set Timecodes from File Timestamp or Filename with GUI
# Version 3.1
#
# This script iterates through clips in the Media Pool.
# It provides a GUI to set "Start TC" based on:
# 1. Filename (with fallback to creation/modification date)
# 2. File Creation Timestamp
# 3. File Modification Timestamp
# It also allows updating all clips or only those with empty/zero timecodes,
# and an option to skip clips already used in timelines (recommended).
# A summary of actions is displayed at the end.

import tkinter as tk
from tkinter import ttk, messagebox
import os
import datetime
import math
import re # For filename parsing

# --- Configuration (defaults, can be overridden by GUI) ---
EMPTY_TIMECODES = ["00:00:00:00", "00:00:00;00"]
# These will be set by GUI choices
USER_PRIMARY_SOURCE_CHOICE = 'filename'  # 'filename', 'create', 'modify'
USER_FALLBACK_SOURCE_CHOICE = 'create'   # 'create', 'modify' (used if filename parse fails)
USER_UPDATE_ONLY_EMPTY = True            # True to update only empty, False to update all
USER_SKIP_TIMELINE_CLIPS = True          # True to skip clips used in timelines (recommended)

# --- Filename Parsing Configuration ---
PATTERNS_YMDHMS = [
    (re.compile(r"^(?:PXL_|VID|DJI_|IMG|GH|GX|GOPR|GPMF|G[EH]P)?(\d{4})(\d{2})(\d{2})_?(\d{2})(\d{2})(\d{2})(?:[._-]?)(\d{3})?", re.IGNORECASE), 7),
    (re.compile(r"^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})", re.IGNORECASE), 6),
    (re.compile(r"^(?:signal-)?(\d{4})-(\d{2})-(\d{2})-(\d{2})-(\d{2})-(\d{2})(?:[_-](\d{3}))?", re.IGNORECASE), 7),
]
PATTERNS_YMD_ONLY = [
    (re.compile(r"^(?:IMG-|VID-)?(\d{4})(\d{2})(\d{2})-WA\d+", re.IGNORECASE), 3),
    (re.compile(r"(\d{4})(\d{2})(\d{2})"), 3)
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
        match = pattern.search(base_name)
        if match:
            groups = match.groups()
            try: return datetime.datetime(int(groups[0]), int(groups[1]), int(groups[2]), 0, 0, 0)
            except (ValueError, IndexError): continue
    return None

# --- Core Script Logic ---
def get_resolve_objects():
    if not resolve: return None, None, None, None
    pm = resolve.GetProjectManager(); proj = pm.GetCurrentProject()
    if not proj: return resolve, pm, None, None
    pool = proj.GetMediaPool()
    if not pool: return resolve, pm, proj, None
    return resolve, pm, proj, pool

def get_timeline_frame_rate(proj):
    try: return float(proj.GetSetting("timelineFrameRate"))
    except: return 24.0

def format_timecode(h, m, s, f, is_drop):
    sep = ";" if is_drop else ":"
    return f"{int(h):02d}{sep}{int(m):02d}{sep}{int(s):02d}{sep}{int(f):02d}"

def is_timecode_empty(tc_str):
    if not tc_str or not tc_str.strip(): return True
    if tc_str in EMPTY_TIMECODES: return True
    parts = tc_str.replace(';', ':').split(':')
    if len(parts) == 4:
        try: return all(int(p) == 0 for p in parts)
        except ValueError: pass
    return False

def process_clip(clip, tl_fps, is_df, prim_src, fb_src, upd_empty, skip_tl_clips, stats):
    clip_name = clip.GetName()
    start_tc_prop = clip.GetClipProperty("Start TC")
    stats['total_scanned'] += 1
    print(f"Processing clip: '{clip_name}' - Current Start TC: '{start_tc_prop}'")

    # 1. Check if clip is used in timelines and should be skipped
    if skip_tl_clips:
        try:
            usage_count = clip.GetClipProperty("Usage")
            if int(usage_count) != 0: #Resolve returns a string this allows a number just in case
                print(f"  Skipping '{clip_name}': Clip is used {usage_count} time(s) in timelines and 'Skip timeline clips' is enabled.")
                stats['skipped_in_timeline'] += 1
                return "SKIPPED_IN_TIMELINE"
        except Exception as e:
            print(f"  Warning: Could not get usage count for '{clip_name}': {e}. Proceeding cautiously.")
            stats['errors_getting_usage'] = stats.get('errors_getting_usage',0) + 1


    # 2. Check if timecode is already set and should be skipped
    if upd_empty and not is_timecode_empty(start_tc_prop):
        print(f"  Skipping '{clip_name}': Timecode '{start_tc_prop}' is not empty and 'Update only empty' is selected.")
        stats['skipped_set'] += 1
        return "SKIPPED_SET"

    # 3. Get file path
    file_path_dict = clip.GetClipProperty()
    file_path = None
    if isinstance(file_path_dict, dict): file_path = file_path_dict.get("File Path")
    else: file_path = clip.GetClipProperty("File Path")

    if not file_path or not os.path.exists(file_path):
        print(f"  Failed for '{clip_name}': Could not get valid file path ('{file_path}').")
        stats['failed_no_path'] += 1
        return "FAILED_NO_PATH"

    dt_object = None; source_used = "none"; current_primary_src = prim_src

    # 4. Try Primary Source: Filename
    if current_primary_src == 'filename':
        stats['filename_attempts'] +=1
        print(f"  Attempting to parse datetime from filename: '{os.path.basename(file_path)}'") # Log basename
        dt_object = parse_datetime_from_filename(os.path.basename(file_path)) # Use basename for parsing
        if dt_object:
            print(f"  Successfully parsed from filename: {dt_object.strftime('%Y-%m-%d %H:%M:%S')}")
            stats['filename_success'] +=1; source_used = "filename"
        else:
            print(f"  Filename parsing failed for '{clip_name}'. Using fallback: '{fb_src}'.")
            stats['filename_failed'] += 1; current_primary_src = fb_src # Switch to fallback

    # 5. Try Creation/Modification Date (either as primary or effective fallback)
    if not dt_object:
        timestamp_type_str = "creation" if current_primary_src == 'create' else "modification"
        # Avoid double-counting attempts if filename was the initial primary
        if prim_src != 'filename' or source_used == 'none': # only count if it's direct or actual fallback attempt
            stats[f'{timestamp_type_str}_attempts'] = stats.get(f'{timestamp_type_str}_attempts',0) + 1

        try:
            ts_float = os.path.getctime(file_path) if current_primary_src == 'create' else os.path.getmtime(file_path)
            dt_object = datetime.datetime.fromtimestamp(ts_float)
            source_used = current_primary_src
            print(f"  Using file {timestamp_type_str} time: {dt_object.strftime('%Y-%m-%d %H:%M:%S')}")
            if prim_src != 'filename' or (prim_src == 'filename' and source_used != 'filename') : # only count success if direct or actual fallback
                stats[f'{timestamp_type_str}_success'] = stats.get(f'{timestamp_type_str}_success',0) +1
        except Exception as e:
            print(f"  Error getting {timestamp_type_str} timestamp for '{clip_name}': {e}")
            stats['failed_other'] += 1; return "FAILED_OTHER"

    if not dt_object:
        print(f"  Failed for '{clip_name}': Could not determine a valid timestamp from any source.")
        stats['failed_other'] += 1; return "FAILED_OTHER"

    # 6. Generate and set timecode
    h, m, s, f = dt_object.hour, dt_object.minute, dt_object.second, 0
    new_tc_str = format_timecode(h, m, s, f, is_df)
    print(f"  Generated new timecode for '{clip_name}': {new_tc_str} (Source: {source_used})")

    if clip.SetClipProperty("Start TC", new_tc_str):
        print(f"  Successfully set Start TC for '{clip_name}'.")
        stats['updated_success'] += 1
        stats[f'updated_from_{source_used}'] = stats.get(f'updated_from_{source_used}', 0) + 1
        return f"UPDATED_{source_used.upper()}"
    else:
        print(f"  Failed to set Start TC for '{clip_name}'.")
        stats['failed_set_tc'] +=1; return "FAILED_SET_TC"

def iterate_media_pool_folders(folder, tl_fps, is_df, prim_src, fb_src, upd_empty, skip_tl, stats):
    if not folder: return
    clips = folder.GetClipList()
    if clips:
        for clip in clips:
            process_clip(clip, tl_fps, is_df, prim_src, fb_src, upd_empty, skip_tl, stats)
    subfolders = folder.GetSubFolderList()
    if subfolders:
        for subfolder in subfolders:
            iterate_media_pool_folders(subfolder, tl_fps, is_df, prim_src, fb_src, upd_empty, skip_tl, stats)

def run_script_logic_with_options(prim_choice, fb_choice, upd_empty_choice, skip_tl_choice):
    print(f"Options: Primary={prim_choice}, Fallback={fb_choice}, UpdateEmpty={upd_empty_choice}, SkipTimeline={skip_tl_choice}")
    res, proj_mgr, proj, pool = get_resolve_objects()
    if not all([res, proj_mgr, proj, pool]):
        messagebox.showerror("Error", "Script cannot run due to missing Resolve objects. Exiting.")
        return

    stats = {
        'total_scanned': 0, 'updated_success': 0, 'skipped_set': 0, 'skipped_in_timeline':0,
        'failed_no_path': 0, 'failed_other': 0, 'failed_set_tc': 0, 'errors_getting_usage':0,
        'filename_attempts': 0, 'filename_success': 0, 'filename_failed': 0,
        'creation_attempts': 0, 'creation_success': 0,
        'modification_attempts': 0, 'modification_success': 0,
        'updated_from_filename': 0, 'updated_from_create': 0, 'updated_from_modify': 0
    }

    print(f"Starting script for project: {proj.GetName()}")
    tl_fps = get_timeline_frame_rate(proj); is_df = proj.GetSetting("timelineDropFrameTimecode") == "1"
    print(f"Timeline: {tl_fps}fps, DropFrame: {is_df}")
    print(f"Primary: '{prim_choice}', Fallback: '{fb_choice}', UpdateEmpty: {upd_empty_choice}, SkipTimeline: {skip_tl_choice}")

    print("--- Starting Media Pool Scan ---")
    iterate_media_pool_folders(pool.GetRootFolder(), tl_fps, is_df, prim_choice, fb_choice, upd_empty_choice, skip_tl_choice, stats)
    print("\n--- Script Finished ---")

    summary_lines = [
        f"Total clips scanned: {stats['total_scanned']}",
        f"Clips updated successfully: {stats['updated_success']}",
    ]
    if stats['updated_success'] > 0:
        if stats['updated_from_filename'] > 0: summary_lines.append(f"  - From Filename: {stats['updated_from_filename']}")
        if stats['updated_from_create'] > 0: summary_lines.append(f"  - From Creation Date: {stats['updated_from_create']}")
        if stats['updated_from_modify'] > 0: summary_lines.append(f"  - From Modification Date: {stats['updated_from_modify']}")
    if prim_choice == 'filename':
        summary_lines.extend([
            f"Filename parsing: {stats['filename_attempts']} attempts",
            f"  - Succeeded: {stats['filename_success']}",
            f"  - Failed (fallback used): {stats['filename_failed']}",
        ])
    summary_lines.extend([
        f"Clips skipped:",
        f"  - Already set (and not forcing update): {stats['skipped_set']}",
        f"  - Used in a timeline (and skipping enabled): {stats['skipped_in_timeline']}",
        f"Clips failed:",
        f"  - No valid file path: {stats['failed_no_path']}",
        f"  - Failed to set TC property: {stats['failed_set_tc']}",
        f"  - Other errors (timestamp/usage read): {stats['failed_other'] + stats['errors_getting_usage']}",
    ])
    if stats['updated_success'] > 0: summary_lines.append("\nNote: You may need to re-sort Media Pool bins.")

    final_summary_message = "\n".join(summary_lines)
    print(final_summary_message)
    messagebox.showinfo("Script Execution Summary", final_summary_message)

# --- GUI Setup ---
def show_options_gui():
    root = tk.Tk()
    root.title("Timecode Setter Options V3.1")
    try: root.attributes('-topmost', True)
    except tk.TclError: print("Note: Could not set window 'topmost'.")

    prim_src_var = tk.StringVar(value=USER_PRIMARY_SOURCE_CHOICE)
    fb_src_var = tk.StringVar(value=USER_FALLBACK_SOURCE_CHOICE)
    upd_empty_var = tk.BooleanVar(value=USER_UPDATE_ONLY_EMPTY)
    skip_tl_var = tk.BooleanVar(value=USER_SKIP_TIMELINE_CLIPS) # New GUI variable

    main_frm = ttk.Frame(root, padding="10"); main_frm.grid(sticky=(tk.W,tk.E,tk.N,tk.S))

    prim_frm = ttk.LabelFrame(main_frm, text="Primary Timecode Source", padding="10")
    prim_frm.grid(row=0, column=0, padx=5, pady=5, sticky=(tk.W, tk.E))
    ttk.Radiobutton(prim_frm, text="From Filename", variable=prim_src_var, value="filename").pack(anchor=tk.W)
    ttk.Radiobutton(prim_frm, text="From File Creation Date", variable=prim_src_var, value="create").pack(anchor=tk.W)
    ttk.Radiobutton(prim_frm, text="From File Modification Date", variable=prim_src_var, value="modify").pack(anchor=tk.W)

    fb_frm = ttk.LabelFrame(main_frm, text="Fallback (if Filename Fails)", padding="10")
    fb_frm.grid(row=1, column=0, padx=5, pady=5, sticky=(tk.W, tk.E))
    rb_fb_cr = ttk.Radiobutton(fb_frm, text="File Creation Date", variable=fb_src_var, value="create")
    rb_fb_cr.pack(anchor=tk.W)
    rb_fb_md = ttk.Radiobutton(fb_frm, text="File Modification Date", variable=fb_src_var, value="modify")
    rb_fb_md.pack(anchor=tk.W)

    def toggle_fb_state(*args):
        state = tk.NORMAL if prim_src_var.get() == "filename" else tk.DISABLED
        for child in fb_frm.winfo_children(): child.configure(state=state)
    prim_src_var.trace_add("write", toggle_fb_state); toggle_fb_state()

    upd_frm = ttk.LabelFrame(main_frm, text="Update Behavior", padding="10")
    upd_frm.grid(row=2, column=0, padx=5, pady=5, sticky=(tk.W, tk.E))
    ttk.Checkbutton(upd_frm, text="Update only if TC is zero/empty", variable=upd_empty_var).pack(anchor=tk.W)
    # New Checkbox for skipping timeline clips
    ttk.Checkbutton(upd_frm, text="Skip clips used in timelines (Recommended)", variable=skip_tl_var).pack(anchor=tk.W)


    btn_frm = ttk.Frame(main_frm, padding="10"); btn_frm.grid(row=3, column=0, sticky=(tk.W, tk.E))
    res = {"cancelled": True}
    def on_run():
        res.update({"primary": prim_src_var.get(), "fallback": fb_src_var.get(),
                    "update_empty": upd_empty_var.get(), "skip_timeline": skip_tl_var.get(), # Add new choice
                    "cancelled": False})
        root.destroy()
    def on_cancel(): res["cancelled"] = True; root.destroy()

    ttk.Button(btn_frm, text="Run Script", command=on_run, width=12).pack(side=tk.RIGHT, padx=(5,0))
    ttk.Button(btn_frm, text="Cancel", command=on_cancel, width=12).pack(side=tk.RIGHT, padx=(0,5))

    root.bind('<Return>', lambda e: on_run()); root.bind('<Escape>', lambda e: on_cancel())
    root.protocol("WM_DELETE_WINDOW", on_cancel)
    root.update_idletasks()
    w = max(420, root.winfo_width()); h = root.winfo_height()
    x = (root.winfo_screenwidth()//2)-(w//2); y = (root.winfo_screenheight()//2)-(h//2)
    root.geometry(f'{w}x{h}+{x}+{y}'); root.minsize(w,h)
    root.mainloop()
    return res

# --- Main Script Execution ---
if __name__ == "__main__":
    choices = show_options_gui()
    if choices["cancelled"]:
        print("Script cancelled by user.")
    else:
        print("GUI options collected. Proceeding...")
        run_script_logic_with_options(
            choices["primary"], choices["fallback"],
            choices["update_empty"], choices["skip_timeline"] # Pass new choice
        )
    print("Script execution finished or was cancelled.")