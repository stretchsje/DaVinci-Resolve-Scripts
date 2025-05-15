#!/usr/bin/env python
# DaVinci Resolve Script: Set Timecodes & Scene from File Data with GUI
# Version 4.1
#
# Features:
# - Set Start TC and/or Scene metadata from filename, creation, or modification date.
# - Sub-second accuracy from filename used for Start TC frames.
# - Option to backup Start TC to 'Slate TC' before overwriting.
# - Mode to restore Start TC from 'Slate TC'.
# - Rules for updating only empty fields, skipping timeline clips (uses "Usage" property).
# - GUI for all options and summary report.
# - Assumes 'resolve' object is globally available.

import tkinter as tk
from tkinter import ttk, messagebox
import os
import datetime
import math
import re

# --- Configuration ---
EMPTY_TIMECODES = ["00:00:00:00", "00:00:00;00"]
DEFAULT_EMPTY_SCENE_VALUES = ["", None, "0000-00-00 00:00:00"] # Common empty/default scene values

# Default GUI choices (can be overridden by user interaction)
USER_OPERATION_MODE = 'set_properties'
USER_PRIMARY_SOURCE_CHOICE = 'filename'
USER_FALLBACK_SOURCE_CHOICE = 'create'
USER_UPDATE_START_TC = True
USER_UPDATE_SCENE = False
USER_BACKUP_START_TC = False
USER_UPDATE_ONLY_EMPTY = True
USER_SKIP_TIMELINE_CLIPS = True
USER_RESTORE_ONLY_EMPTY_TC = True

# --- Filename Parsing (Using user's provided patterns with slight adjustment for ms capture) ---
# Each pattern tuple: (compiled_regex, number_of_groups_including_optional_ms, ms_group_index_if_present_else_None)
# ms_group_index is 0-based index in the `groups` tuple from match.groups()
PATTERNS_YMDHMS = [
    (re.compile(r"^(?:PXL_|VID|DJI_|IMG|GH|GX|GOPR|GPMF|G[EH]P)?(\d{4})(\d{2})(\d{2})_?(\d{2})(\d{2})(\d{2})(?:[._-]?)(\d{1,6})?", re.IGNORECASE), 7, 6),
    (re.compile(r"^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})(?:[._-]?)(\d{1,6})?", re.IGNORECASE), 7, 6), # Added optional ms here too for consistency
    (re.compile(r"^(?:signal-)?(\d{4})-(\d{2})-(\d{2})-(\d{2})-(\d{2})-(\d{2})(?:[_-](\d{1,6}))?", re.IGNORECASE), 7, 6),
]
PATTERNS_YMD_ONLY = [ # These patterns only capture YYYY, MM, DD
    (re.compile(r"^(?:IMG-|VID-)?(\d{4})(\d{2})(\d{2})-WA\d+", re.IGNORECASE), 3, None),
    (re.compile(r"(\d{4})(\d{2})(\d{2})"), 3, None) # General YYYYMMDD search
]

def parse_datetime_from_filename(filename_str):
    base_name = os.path.splitext(filename_str)[0]
    # Try patterns that include HMS first
    for pattern_list in [PATTERNS_YMDHMS]: # Removed PATTERNS_YMDHMS_NO_MS, covered by optional ms
        for pattern, num_expected_groups, ms_group_idx in pattern_list:
            match = pattern.match(base_name) # `match` for anchored patterns
            if not match and pattern.pattern.startswith(r"(\d{4})(\d{2})(\d{2})"): # If it's a generic date search like YYYYMMDD
                match = pattern.search(base_name) # Use `search` for non-anchored general date patterns

            if match:
                groups = match.groups()
                try:
                    year, month, day = int(groups[0]), int(groups[1]), int(groups[2])
                    hour, minute, second = 0, 0, 0 # Defaults if not in pattern
                    microseconds = 0

                    if num_expected_groups >= 6 : # Has H, M, S
                         hour, minute, second = int(groups[3]), int(groups[4]), int(groups[5])

                    if ms_group_idx is not None and len(groups) > ms_group_idx and groups[ms_group_idx]:
                        ms_str = groups[ms_group_idx]
                        microseconds = int((ms_str + "000000")[:6]) # Pad/truncate to 6 microsecond digits
                    return datetime.datetime(year, month, day, hour, minute, second, microseconds)
                except (ValueError, IndexError) as e:
                    # print(f"Debug: ValueError/IndexError during HMS parsing for {pattern.pattern} with groups {groups}: {e}")
                    continue
    
    # Try patterns that only get YMD
    for pattern, num_expected_groups, _ in PATTERNS_YMD_ONLY: # ms_group_idx is None here
        match = pattern.search(base_name) # Search for YMD_ONLY as it might be anywhere
        if match:
            groups = match.groups()
            try:
                year, month, day = int(groups[0]), int(groups[1]), int(groups[2])
                return datetime.datetime(year, month, day, 0, 0, 0, 0) # Time defaults to midnight
            except (ValueError, IndexError) as e:
                # print(f"Debug: ValueError/IndexError during YMD_ONLY parsing for {pattern.pattern} with groups {groups}: {e}")
                continue
    return None


# --- Core Logic ---
def get_resolve_objects(): # Assumes 'resolve' is globally available and valid
    if 'resolve' not in globals() or not globals()['resolve']:
        print("CRITICAL ERROR: DaVinci Resolve 'resolve' object not found globally.")
        messagebox.showerror("Error", "Resolve object not found. Run script from Resolve.")
        return None, None, None, None
    # No need to assign to local _resolve if global resolve is used directly
    pm = resolve.GetProjectManager()
    proj = pm.GetCurrentProject()
    if not proj:
        print("ERROR: No project is currently open.")
        messagebox.showerror("Error", "No project open.")
        return resolve, pm, None, None
    pool = proj.GetMediaPool()
    if not pool:
        print("ERROR: Could not access the Media Pool.")
        messagebox.showerror("Error", "Cannot access Media Pool.")
        return resolve, pm, proj, None
    return resolve, pm, proj, pool


def get_timeline_frame_rate(proj):
    try: return float(proj.GetSetting("timelineFrameRate"))
    except: return 24.0 # Default

def format_timecode_str(h, m, s, f, is_drop):
    sep = ";" if is_drop else ":"
    return f"{int(h):02d}{sep}{int(m):02d}{sep}{int(s):02d}{sep}{int(f):02d}"

def is_prop_empty(prop_value, empty_values_list):
    if prop_value is None: return True
    if isinstance(prop_value, str) and not prop_value.strip(): return True
    return prop_value in empty_values_list

def process_clip_set_properties(clip, tl_fps, is_df, choices, stats):
    clip_name = clip.GetName()
    stats['total_scanned'] += 1
    print(f"Processing '{clip_name}' for Set Properties...")

    if choices['skip_timeline_clips']:
        try:
            usage_str = clip.GetClipProperty("Usage") # User's corrected way
            if usage_str is not None and int(usage_str) > 0:
                print(f"  Skipping: Used in timeline ({usage_str} times) and policy is to skip.")
                stats['skipped_in_timeline'] += 1; return
        except Exception as e:
            print(f"  Warning: Error getting 'Usage' for '{clip_name}': {e}. Proceeding cautiously.")
            stats['errors_getting_usage'] += 1

    file_path = clip.GetClipProperty("File Path")
    if not file_path or not os.path.exists(file_path):
        print(f"  Failed: Invalid file path ('{file_path}').")
        stats['failed_no_path'] += 1; return

    dt_object = None; source_used = "none"; effective_src = choices['primary_source']
    if effective_src == 'filename':
        stats['filename_attempts'] += 1
        dt_object = parse_datetime_from_filename(os.path.basename(file_path))
        if dt_object:
            print(f"  Parsed from filename: {dt_object.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}") # Show ms
            stats['filename_success'] +=1; source_used = "filename"
        else:
            print(f"  Filename parsing failed. Using fallback: '{choices['fallback_source']}'.")
            stats['filename_failed'] += 1; effective_src = choices['fallback_source']

    if not dt_object:
        ts_type_str = "creation" if effective_src == 'create' else "modification"
        stats[f'{ts_type_str}_attempts'] +=1
        try:
            ts_float = os.path.getctime(file_path) if effective_src == 'create' else os.path.getmtime(file_path)
            dt_object = datetime.datetime.fromtimestamp(ts_float) # This will have microseconds
            source_used = effective_src
            print(f"  Using file {ts_type_str} time: {dt_object.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}") # Show ms
            stats[f'{ts_type_str}_success'] +=1
        except Exception as e:
            print(f"  Error getting {ts_type_str} timestamp: {e}")
            stats['failed_other'] += 1; return

    if not dt_object:
        print(f"  Failed: Could not determine valid timestamp."); stats['failed_other'] += 1; return

    if choices['update_start_tc']:
        original_start_tc = clip.GetClipProperty("Start TC")
        if choices['update_only_empty'] and not is_prop_empty(original_start_tc, EMPTY_TIMECODES):
            print(f"  Skipping Start TC update: Not empty ('{original_start_tc}') and 'update only empty' selected.")
            stats['skipped_start_tc_set'] +=1
        else:
            if choices['backup_start_tc']:
                if not is_prop_empty(original_start_tc, EMPTY_TIMECODES): # Only backup non-empty TCs
                    if clip.SetClipProperty("Slate TC", original_start_tc):
                        print(f"  Backed up Start TC '{original_start_tc}' to 'Slate TC'.")
                        stats['tc_backup_success'] +=1
                    else:
                        print(f"  Failed to backup Start TC to 'Slate TC'.")
                        stats['tc_backup_failed'] +=1
                else:
                     print(f"  Skipping backup of Start TC: Original is empty/default ('{original_start_tc}').")


            frames = math.floor((dt_object.microsecond / 1000000.0) * tl_fps)
            new_start_tc = format_timecode_str(dt_object.hour, dt_object.minute, dt_object.second, frames, is_df)
            if clip.SetClipProperty("Start TC", new_start_tc):
                print(f"  Set Start TC to '{new_start_tc}' (from {source_used}, frames from ms: {dt_object.microsecond}).")
                stats['start_tc_updated'] += 1
                stats[f'start_tc_from_{source_used}'] +=1
            else:
                print(f"  Failed to set Start TC to '{new_start_tc}'.")
                stats['failed_set_start_tc'] += 1

    if choices['update_scene']:
        original_scene = clip.GetClipProperty("Scene")
        if choices['update_only_empty'] and not is_prop_empty(original_scene, DEFAULT_EMPTY_SCENE_VALUES):
            print(f"  Skipping Scene update: Not empty ('{original_scene}') and 'update only empty' selected.")
            stats['skipped_scene_set'] +=1
        else:
            # For Scene, use YYYY-MM-DD HH:MM:SS. Sub-second for Scene is TBD by Resolve's capabilities for this field.
            # If milliseconds are desired and supported, change format string.
            new_scene_str = dt_object.strftime('%Y-%m-%d %H:%M:%S')
            # To include milliseconds: new_scene_str = dt_object.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            if clip.SetClipProperty("Scene", new_scene_str):
                print(f"  Set Scene to '{new_scene_str}' (from {source_used}).")
                stats['scene_updated'] += 1
                stats[f'scene_from_{source_used}'] +=1
            else:
                print(f"  Failed to set Scene to '{new_scene_str}'.")
                stats['failed_set_scene'] +=1

def process_clip_restore_tc(clip, choices, stats):
    clip_name = clip.GetName()
    stats['total_scanned'] += 1
    print(f"Processing '{clip_name}' for Restore Start TC...")

    if choices['skip_timeline_clips']:
        try:
            usage_str = clip.GetClipProperty("Usage")
            if usage_str is not None and int(usage_str) > 0:
                print(f"  Skipping: Used in timeline ({usage_str} times) and policy is to skip.")
                stats['skipped_in_timeline'] += 1; return
        except Exception as e:
            print(f"  Warning: Error getting 'Usage' for '{clip_name}': {e}.") # No cautious proceeding, just warn
            stats['errors_getting_usage'] += 1

    slate_tc = clip.GetClipProperty("Slate TC")
    # Check if slate_tc is a valid timecode string (basic check, could be more robust)
    if is_prop_empty(slate_tc, []) or not re.match(r"^\d{2}[:;]\d{2}[:;]\d{2}[:;]\d{2}$", slate_tc):
        print(f"  Skipping restore: 'Slate TC' is empty or not a valid TC format ('{slate_tc}').")
        stats['restore_skipped_no_slate_tc'] +=1; return

    current_start_tc = clip.GetClipProperty("Start TC")
    if choices['restore_only_empty_tc'] and not is_prop_empty(current_start_tc, EMPTY_TIMECODES):
        print(f"  Skipping restore: Current Start TC ('{current_start_tc}') not empty and 'restore only empty' selected.")
        stats['restore_skipped_tc_not_empty'] +=1; return

    if clip.SetClipProperty("Start TC", slate_tc):
        print(f"  Restored Start TC to '{slate_tc}' from 'Slate TC'.")
        stats['tc_restored'] += 1
    else:
        print(f"  Failed to restore Start TC from 'Slate TC'.")
        stats['failed_tc_restore'] += 1

def iterate_media_pool(choices, stats):
    _, _, proj, pool = get_resolve_objects()
    if not proj or not pool:
        # Error already shown by get_resolve_objects
        return

    tl_fps = get_timeline_frame_rate(proj)
    is_df = proj.GetSetting("timelineDropFrameTimecode") == "1"

    print(f"Project: {proj.GetName()}, FPS: {tl_fps}, DropFrame: {is_df}")
    print(f"Operation Mode: {choices['operation_mode']}")
    if choices['operation_mode'] == 'set_properties':
        print(f" Primary Source: {choices['primary_source']}, Fallback: {choices['fallback_source']}")
        print(f" Update Start TC: {choices['update_start_tc']}, Update Scene: {choices['update_scene']}")
        if choices['update_start_tc']: print(f" Backup Start TC: {choices['backup_start_tc']}")
    elif choices['operation_mode'] == 'restore_tc':
        print(f" Restore only if Start TC empty: {choices['restore_only_empty_tc']}")
    print(f" Update common rules -> Only if empty fields: {choices['update_only_empty']}; Skip timeline clips: {choices['skip_timeline_clips']}")
    print("--- Starting Media Pool Scan ---")

    def process_folder(folder):
        clips = folder.GetClipList()
        if clips:
            for clip_idx, clip_obj in enumerate(clips): # Use enumerate for better logging if needed
                if choices['operation_mode'] == 'set_properties':
                    process_clip_set_properties(clip_obj, tl_fps, is_df, choices, stats)
                elif choices['operation_mode'] == 'restore_tc':
                    process_clip_restore_tc(clip_obj, choices, stats)
        subfolders = folder.GetSubFolderList()
        if subfolders:
            for subfolder_idx, subfolder_obj in enumerate(subfolders):
                process_folder(subfolder_obj)
    process_folder(pool.GetRootFolder())
    print("\n--- Scan Finished ---")

def run_script_with_choices(choices):
    stats_keys = [
        'total_scanned', 'skipped_in_timeline', 'errors_getting_usage', 'failed_no_path',
        'filename_attempts', 'filename_success', 'filename_failed',
        'creation_attempts', 'creation_success', 'modification_attempts', 'modification_success',
        'failed_other', 'start_tc_updated', 'scene_updated', 'tc_backup_success', 'tc_backup_failed',
        'skipped_start_tc_set', 'skipped_scene_set', 'failed_set_start_tc', 'failed_set_scene',
        'tc_restored', 'restore_skipped_no_slate_tc', 'restore_skipped_tc_not_empty', 'failed_tc_restore']
    # Add source-specific update counts dynamically
    for prop in ['start_tc', 'scene']:
        for src in ['filename', 'create', 'modify']:
            stats_keys.append(f'{prop}_from_{src}')
    stats = {key: 0 for key in stats_keys}

    iterate_media_pool(choices, stats)

    summary_lines = [f"Total clips scanned: {stats['total_scanned']}"]
    if choices['operation_mode'] == 'set_properties':
        if stats['start_tc_updated'] > 0:
            summary_lines.append(f"Start TC updated: {stats['start_tc_updated']} (File: {stats['start_tc_from_filename']}, Create: {stats['start_tc_from_create']}, Modify: {stats['start_tc_from_modify']})")
        if stats['scene_updated'] > 0:
            summary_lines.append(f"Scene updated: {stats['scene_updated']} (File: {stats['scene_from_filename']}, Create: {stats['scene_from_create']}, Modify: {stats['scene_from_modify']})")
        if choices['update_start_tc'] and choices['backup_start_tc']:
             summary_lines.append(f"Start TC backups to 'Slate TC': {stats['tc_backup_success']} (Failed: {stats['tc_backup_failed']})")
        if choices['primary_source'] == 'filename':
            summary_lines.extend([
                f"Filename parsing: {stats['filename_attempts']} attempts, {stats['filename_success']} succeeded, {stats['filename_failed']} used fallback."
            ])
    elif choices['operation_mode'] == 'restore_tc':
        summary_lines.append(f"Start TC restored from 'Slate TC': {stats['tc_restored']}")
        if stats['restore_skipped_no_slate_tc']: summary_lines.append(f"  Skipped (no/invalid Slate TC): {stats['restore_skipped_no_slate_tc']}")
        if stats['restore_skipped_tc_not_empty']: summary_lines.append(f"  Skipped (Start TC not empty): {stats['restore_skipped_tc_not_empty']}")

    summary_lines.extend([
        f"Skipped (in timeline): {stats['skipped_in_timeline']}",
        f"Skipped (Start TC already set): {stats['skipped_start_tc_set']}",
        f"Skipped (Scene already set): {stats['skipped_scene_set']}",
        f"Failed (no path): {stats['failed_no_path']}",
        f"Failed (set Start TC): {stats['failed_set_start_tc']}",
        f"Failed (set Scene): {stats['failed_set_scene']}",
        f"Failed (restore TC): {stats['failed_tc_restore']}",
        f"Failed (other errors): {stats['failed_other']}",
    ])
    if stats['errors_getting_usage'] > 0:
        summary_lines.append(f"Timeline usage check issues: {stats['errors_getting_usage']}")
    if sum(stats[k] for k in ['start_tc_updated', 'scene_updated', 'tc_restored']) > 0 :
        summary_lines.append("\nNote: You may need to re-sort Media Pool bins by the updated property.")

    # Filter out lines showing "0" unless it's essential like "total_scanned" or a failure count.
    filtered_summary_lines = []
    for line in summary_lines:
        is_essential = "scanned" in line.lower() or "fail" in line.lower() or "error" in line.lower() or "issue" in line.lower()
        # Check if the line reports a zero count for a non-essential item
        reports_zero = any(val in line for val in [": 0", "(0)"]) and not any(val in line for val in ["(Failed: 0)"]) # Keep "Failed: 0"

        if is_essential or not reports_zero or (reports_zero and "Failed: 0" in line) : # Keep "Failed: 0"
             filtered_summary_lines.append(line)


    final_summary = "\n".join(filtered_summary_lines)
    print(final_summary)
    messagebox.showinfo("Script Execution Summary", final_summary)


# --- GUI Setup ---
def show_options_gui():
    root = tk.Tk()
    root.title("Timecode & Scene Utility V4.1")
    try: root.attributes('-topmost', True)
    except tk.TclError: pass

    op_mode_var = tk.StringVar(value=USER_OPERATION_MODE)
    prim_src_var = tk.StringVar(value=USER_PRIMARY_SOURCE_CHOICE)
    fb_src_var = tk.StringVar(value=USER_FALLBACK_SOURCE_CHOICE)
    upd_start_tc_var = tk.BooleanVar(value=USER_UPDATE_START_TC)
    upd_scene_var = tk.BooleanVar(value=USER_UPDATE_SCENE)
    backup_tc_var = tk.BooleanVar(value=USER_BACKUP_START_TC)
    upd_empty_var = tk.BooleanVar(value=USER_UPDATE_ONLY_EMPTY)
    skip_tl_var = tk.BooleanVar(value=USER_SKIP_TIMELINE_CLIPS)
    restore_only_empty_var = tk.BooleanVar(value=USER_RESTORE_ONLY_EMPTY_TC)

    main_frame = ttk.Frame(root, padding="10")
    main_frame.grid(row=0, column=0, sticky="nsew")
    root.columnconfigure(0, weight=1); root.rowconfigure(0, weight=1)

    mode_frame = ttk.LabelFrame(main_frame, text="Operation Mode", padding="10")
    mode_frame.grid(row=0, column=0, columnspan=2, sticky="ew", padx=5, pady=5)
    rb_set_props = ttk.Radiobutton(mode_frame, text="Set Date/Time Properties (Start TC and/or Scene)", variable=op_mode_var, value="set_properties")
    rb_set_props.pack(anchor="w", pady=2)
    rb_restore_tc = ttk.Radiobutton(mode_frame, text="Restore Start TC from 'Slate TC'", variable=op_mode_var, value="restore_tc")
    rb_restore_tc.pack(anchor="w", pady=2)

    set_props_frame = ttk.LabelFrame(main_frame, text="Set Date/Time Options", padding="10")
    set_props_frame.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
    restore_frame = ttk.LabelFrame(main_frame, text="Restore Options", padding="10")
    restore_frame.grid(row=1, column=1, sticky="nsew", padx=5, pady=5)

    # --- Widgets for "Set Properties" Frame ---
    target_frame = ttk.LabelFrame(set_props_frame, text="Properties to Update", padding="5")
    target_frame.pack(fill="x", expand=True, pady=(0,5), padx=2)
    cb_upd_start_tc = ttk.Checkbutton(target_frame, text="Start TC", variable=upd_start_tc_var)
    cb_upd_start_tc.pack(anchor="w")
    cb_backup_tc = ttk.Checkbutton(target_frame, text="  Backup original Start TC to 'Slate TC'", variable=backup_tc_var)
    cb_backup_tc.pack(anchor="w", padx=(15,0))
    cb_upd_scene = ttk.Checkbutton(target_frame, text="Scene", variable=upd_scene_var)
    cb_upd_scene.pack(anchor="w")

    src_frame = ttk.LabelFrame(set_props_frame, text="Data Source", padding="5")
    src_frame.pack(fill="x", expand=True, pady=5, padx=2)
    ttk.Radiobutton(src_frame, text="From Filename", variable=prim_src_var, value="filename").pack(anchor="w")
    ttk.Radiobutton(src_frame, text="From File Creation Date", variable=prim_src_var, value="create").pack(anchor="w")
    ttk.Radiobutton(src_frame, text="From File Modification Date", variable=prim_src_var, value="modify").pack(anchor="w")

    fb_frame = ttk.LabelFrame(set_props_frame, text="Fallback (if Filename Fails)", padding="5")
    fb_frame.pack(fill="x", expand=True, pady=5, padx=2)
    ttk.Radiobutton(fb_frame, text="File Creation Date", variable=fb_src_var, value="create").pack(anchor="w")
    ttk.Radiobutton(fb_frame, text="File Modification Date", variable=fb_src_var, value="modify").pack(anchor="w")

    # --- Widgets for "Restore Options" Frame ---
    ttk.Checkbutton(restore_frame, text="Restore only if Start TC is zero/empty", variable=restore_only_empty_var).pack(anchor="w")

    common_behavior_frame = ttk.LabelFrame(main_frame, text="Common Update Rules", padding="10")
    common_behavior_frame.grid(row=2, column=0, columnspan=2, sticky="ew", padx=5, pady=5)
    ttk.Checkbutton(common_behavior_frame, text="Apply updates only if target field is empty", variable=upd_empty_var).pack(anchor="w")
    ttk.Checkbutton(common_behavior_frame, text="Skip clips used in timelines (Recommended)", variable=skip_tl_var).pack(anchor="w")

    # --- GUI State Management Function ---
    interactive_widgets_in_set_props = []
    for frame in [target_frame, src_frame, fb_frame]: # fb_frame needs special logic below
        for widget in frame.winfo_children():
            if widget != cb_backup_tc and frame != fb_frame : # cb_backup_tc & fb_frame handled separately
                 interactive_widgets_in_set_props.append(widget)

    interactive_widgets_in_fb_frame = [w for w in fb_frame.winfo_children()]
    interactive_widgets_in_restore = [w for w in restore_frame.winfo_children()]


    def manage_gui_state(*args):
        current_mode = op_mode_var.get()
        is_set_mode = current_mode == "set_properties"
        is_restore_mode = current_mode == "restore_tc"

        # Enable/disable widgets in "Set Date/Time Options" frame
        set_options_state = tk.NORMAL if is_set_mode else tk.DISABLED
        for widget in interactive_widgets_in_set_props:
            widget.configure(state=set_options_state)
        cb_upd_start_tc.configure(state=set_options_state) # Ensure these specific ones are handled
        cb_upd_scene.configure(state=set_options_state)


        # Backup checkbox state
        can_backup = is_set_mode and upd_start_tc_var.get()
        cb_backup_tc.configure(state=tk.NORMAL if can_backup else tk.DISABLED)
        if not can_backup: backup_tc_var.set(False)

        # Fallback frame state
        can_fallback = is_set_mode and (prim_src_var.get() == "filename")
        fallback_state = tk.NORMAL if can_fallback else tk.DISABLED
        for widget in interactive_widgets_in_fb_frame:
            widget.configure(state=fallback_state)

        # Enable/disable widgets in "Restore Options" frame
        restore_options_state = tk.NORMAL if is_restore_mode else tk.DISABLED
        for widget in interactive_widgets_in_restore:
            widget.configure(state=restore_options_state)

    op_mode_var.trace_add("write", manage_gui_state)
    prim_src_var.trace_add("write", manage_gui_state)
    upd_start_tc_var.trace_add("write", manage_gui_state)
    manage_gui_state()

    btn_frame = ttk.Frame(main_frame, padding="10")
    btn_frame.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10,0))
    gui_result_data = {"cancelled": True}
    def on_run():
        gui_result_data.update({
            "operation_mode": op_mode_var.get(),
            "primary_source": prim_src_var.get(), "fallback_source": fb_src_var.get(),
            "update_start_tc": upd_start_tc_var.get(), "update_scene": upd_scene_var.get(),
            "backup_start_tc": backup_tc_var.get(),
            "update_only_empty": upd_empty_var.get(), "skip_timeline_clips": skip_tl_var.get(),
            "restore_only_empty_tc": restore_only_empty_var.get(),
            "cancelled": False
        })
        root.destroy()
    def on_cancel(): gui_result_data["cancelled"] = True; root.destroy()

    ttk.Button(btn_frame, text="Run Script", command=on_run, width=15).pack(side=tk.RIGHT, padx=5)
    ttk.Button(btn_frame, text="Cancel", command=on_cancel, width=15).pack(side=tk.RIGHT)
    root.bind('<Return>', lambda e: on_run()); root.bind('<Escape>', lambda e: on_cancel())
    root.protocol("WM_DELETE_WINDOW", on_cancel)

    root.update_idletasks()
    min_w = 500 # Adjusted min width for more complex GUI
    w = max(min_w, root.winfo_width()); h = root.winfo_height()
    x = (root.winfo_screenwidth()//2)-(w//2); y = (root.winfo_screenheight()//2)-(h//2)
    root.geometry(f'{w}x{h}+{x}+{y}'); root.minsize(w,h)
    root.mainloop()
    return gui_result_data

# --- Main Script Execution ---
if __name__ == "__main__":
    # This script assumes 'resolve' is already defined in the global scope
    # when run from DaVinci Resolve's scripting console or via the Scripts menu.
    if 'resolve' not in globals():
        print("CRITICAL: 'resolve' object not found. This script must be run from within DaVinci Resolve.")
        # Optionally, could pop up a Tkinter error message here too if GUI elements are already imported
        # For now, console print is the main feedback if this pre-condition fails.
    else:
        choices = show_options_gui()
        if not choices["cancelled"]:
            print("GUI options collected. Proceeding with script...")
            run_script_with_choices(choices)
        else:
            print("Script cancelled by user.")
    print("Script execution finished or was cancelled.")