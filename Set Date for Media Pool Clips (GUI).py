import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import re
from datetime import datetime, timedelta, timezone
import os
import platform
import stat
import statistics

# --- DaVinci Resolve Connection and Project Setup ---
try:
    resolve
except NameError:
    print("Unable to connect to DaVinci Resolve. This script must be run from the Resolve console.")
    exit()

projectManager = resolve.GetProjectManager()
project = projectManager.GetCurrentProject()
mediaPool = project.GetMediaPool()

# --- Main Application Class ---
class TimecodeToolApp(tk.Tk):
    def __init__(self, resolve_app):
        super().__init__()
        self.resolve = resolve_app
        self.project = self.resolve.GetProjectManager().GetCurrentProject()
        self.media_pool = self.project.GetMediaPool() if self.project else None

        self.title("Resolve Timecode & Date Utility")
        # Adjusted window size for a two-column layout
        self.geometry("1550x850")

        self.style = ttk.Style(self)
        self.style.theme_use('clam')
        self.configure(bg='#2E2E2E')

        # --- Style Configuration ---
        self.style.configure('.', background='#2E2E2E', foreground='#E0E0E0', fieldbackground='#3C3C3C', bordercolor="#555555")
        self.style.configure('TLabel', font=('Segoe UI', 10))
        self.style.configure('TButton', font=('Segoe UI', 10, 'bold'), padding=6, background='#555555', foreground='#FFFFFF')
        self.style.map('TButton', background=[('active', '#6A6A6A')])
        self.style.configure('TCheckbutton', font=('Segoe UI', 10), indicatorrelief=tk.FLAT)
        self.style.configure('TRadiobutton', font=('Segoe UI', 10))
        self.style.configure('TCombobox', font=('Segoe UI', 10), fieldbackground='#3C3C3C')
        self.style.configure('TEntry', font=('Segoe UI', 10), fieldbackground='#3C3C3C')
        self.style.configure('TFrame', background='#2E2E2E')
        self.style.configure('Header.TLabel', font=('Segoe UI', 14, 'bold'), foreground='#00A1DE')

        # Fix for hover/active state making text unreadable with a more contrasting color
        active_bg = '#4A4A4A'
        self.style.map('TCheckbutton',
            background=[('active', active_bg)],
            indicatorbackground=[('active', active_bg)],
            foreground=[('active', '#FFFFFF')])
        self.style.map('TRadiobutton',
            background=[('active', active_bg)],
            indicatorbackground=[('active', active_bg)],
            foreground=[('active', '#FFFFFF')])

        self.filename_prefixes = ["All"]
        self.clips_to_process = []
        self._create_widgets()
        self._populate_prefix_dropdown()
        self._on_source_option_change() # Set initial state of widgets

    def _create_widgets(self):
        main_frame = ttk.Frame(self, padding="15")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Configure grid for two columns
        main_frame.columnconfigure(0, weight=1, minsize=400) # Left column for controls
        main_frame.columnconfigure(1, weight=2) # Right column for log
        main_frame.rowconfigure(1, weight=1)

        # --- Title ---
        ttk.Label(main_frame, text="Timecode & Date Utility", style='Header.TLabel').grid(row=0, column=0, columnspan=2, pady=(0, 20), sticky='w')

        # --- LEFT COLUMN FRAME ---
        left_column_frame = ttk.Frame(main_frame)
        left_column_frame.grid(row=1, column=0, sticky='nsew', padx=(0, 10))
        
        # --- Frame 1: Filtering & Source ---
        filter_frame = ttk.LabelFrame(left_column_frame, text="1. Filtering & Source Options", padding="10")
        filter_frame.pack(fill=tk.X, expand=False, pady=(0, 10))
        filter_frame.columnconfigure(1, weight=1)

        # File Prefix Filter
        ttk.Label(filter_frame, text="Filter by Filename Prefix:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.prefix_var = tk.StringVar(value="All")
        self.prefix_combo = ttk.Combobox(filter_frame, textvariable=self.prefix_var, values=self.filename_prefixes, state="readonly")
        self.prefix_combo.grid(row=0, column=1, padx=5, pady=5, sticky="ew")

        # Wildcard Filter
        ttk.Label(filter_frame, text="Or use Wildcard Filter:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.wildcard_var = tk.StringVar()
        self.wildcard_entry = ttk.Entry(filter_frame, textvariable=self.wildcard_var)
        self.wildcard_entry.grid(row=1, column=1, padx=5, pady=5, sticky="ew")
        
        # --- Frame 2: Date Source Priority ---
        source_frame = ttk.LabelFrame(left_column_frame, text="2. Date Source Priority", padding="10")
        source_frame.pack(fill=tk.X, expand=False, pady=10)

        self.source_logic_var = tk.StringVar(value="priority")
        
        # Priority Logic Radiobutton
        self.priority_radio = ttk.Radiobutton(source_frame, text="Use Priority Logic:", variable=self.source_logic_var, value="priority", command=self._on_source_option_change)
        self.priority_radio.grid(row=0, column=0, sticky='w', pady=5)

        self.parse_filename_var = tk.BooleanVar(value=True)
        self.parse_filename_check = ttk.Checkbutton(source_frame, text="Attempt to parse date from filename first", variable=self.parse_filename_var)
        self.parse_filename_check.grid(row=1, column=0, columnspan=2, sticky='w', padx=20)
        
        self.fallback_label = ttk.Label(source_frame, text="If filename parsing fails, use:")
        self.fallback_label.grid(row=2, column=0, padx=25, pady=(5,0), sticky="w")
        self.fallback_date_var = tk.StringVar(value="create")
        self.create_date_radio = ttk.Radiobutton(source_frame, text="File Creation Date", variable=self.fallback_date_var, value="create")
        self.create_date_radio.grid(row=3, column=0, padx=40, pady=2, sticky='w')
        self.modify_date_radio = ttk.Radiobutton(source_frame, text="File Modification Date", variable=self.fallback_date_var, value="modify")
        self.modify_date_radio.grid(row=4, column=0, padx=40, pady=2, sticky='w')

        # Earliest Date Logic Radiobutton
        self.earliest_radio = ttk.Radiobutton(source_frame, text="Use the earliest available date from any source", variable=self.source_logic_var, value="earliest", command=self._on_source_option_change)
        self.earliest_radio.grid(row=5, column=0, sticky='w', pady=(10,5))


        # --- Frame 3: Advanced Options ---
        adv_frame = ttk.LabelFrame(left_column_frame, text="3. Advanced Options", padding="10")
        adv_frame.pack(fill=tk.X, expand=False, pady=10)
        adv_frame.columnconfigure(1, weight=1)

        self.skip_in_timeline_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(adv_frame, text="Skip clips already used in a timeline", variable=self.skip_in_timeline_var).grid(row=0, column=0, columnspan=2, sticky='w', pady=2)
        
        self.only_if_null_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(adv_frame, text="Only update if 'Start TC' is null (e.g., 00:00:00:00)", variable=self.only_if_null_var).grid(row=1, column=0, columnspan=2, sticky='w', pady=2)

        self.backup_tc_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(adv_frame, text="Backup original 'Start TC' to 'Slate TC'", variable=self.backup_tc_var).grid(row=2, column=0, columnspan=2, sticky='w', pady=2)
        
        # Timezone Adjustment
        ttk.Label(adv_frame, text="Timezone Hour Adjustment:").grid(row=3, column=0, padx=5, pady=(10, 5), sticky="w")
        self.tz_offset_var = tk.DoubleVar(value=0.0)
        self.tz_offset_spinbox = tk.Spinbox(adv_frame, from_=-24.0, to=24.0, increment=0.5, textvariable=self.tz_offset_var, width=6, font=('Segoe UI', 10), bg='#3C3C3C', fg='#E0E0E0', buttonbackground='#555555')
        self.tz_offset_spinbox.grid(row=3, column=1, padx=5, pady=(10,5), sticky="w")


        # --- RIGHT COLUMN FRAME ---
        right_column_frame = ttk.Frame(main_frame)
        right_column_frame.grid(row=1, column=1, sticky='nsew', padx=(10, 0))
        right_column_frame.rowconfigure(1, weight=1)
        right_column_frame.columnconfigure(0, weight=1)
        
        # --- Frame 4: Actions ---
        action_frame = ttk.Frame(right_column_frame)
        action_frame.grid(row=0, column=0, sticky='ew', pady=(0,10))
        
        self.scan_button = ttk.Button(action_frame, text="Scan & Analyze Discrepancies", command=self.scan_and_analyze)
        self.scan_button.pack(side=tk.LEFT, padx=(0,5), fill=tk.X, expand=True)

        self.run_button = ttk.Button(action_frame, text="Apply Changes to Clips", command=self.apply_changes)
        self.run_button.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        
        self.restore_button = ttk.Button(action_frame, text="Restore 'Start TC' from 'Slate TC'", command=self.restore_from_backup)
        self.restore_button.pack(side=tk.LEFT, padx=(5,0), fill=tk.X, expand=True)

        # --- Frame 5: Output Log ---
        log_frame = ttk.LabelFrame(right_column_frame, text="Log & Summary", padding="10")
        log_frame.grid(row=1, column=0, sticky="nsew")
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)

        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, height=15, bg='#1E1E1E', fg='#D4D4D4', font=('Consolas', 9))
        self.log_text.grid(row=0, column=0, sticky='nsew')


    def _on_source_option_change(self):
        """Enable/disable widgets based on the source logic selection."""
        if self.source_logic_var.get() == "priority":
            self.parse_filename_check.config(state=tk.NORMAL)
            self.fallback_label.config(state=tk.NORMAL)
            self.create_date_radio.config(state=tk.NORMAL)
            self.modify_date_radio.config(state=tk.NORMAL)
        else: # "earliest"
            self.parse_filename_check.config(state=tk.DISABLED)
            self.fallback_label.config(state=tk.DISABLED)
            self.create_date_radio.config(state=tk.DISABLED)
            self.modify_date_radio.config(state=tk.DISABLED)

    def _log(self, message):
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.update_idletasks()

    def _populate_prefix_dropdown(self):
        """Scans the media pool to find unique filename prefixes."""
        if not self.media_pool:
            self._log("Error: Could not access Media Pool.")
            return
        
        prefixes = set()
        root_folder = self.media_pool.GetRootFolder()
        clips = self._get_all_clips(root_folder)
        
        for clip in clips:
            name = clip.GetName()
            if len(name) >= 3:
                match = re.match(r'([a-zA-Z_]+)', name)
                if match:
                    prefixes.add(match.group(1).rstrip('_'))
                elif name[0].isdigit():
                    prefixes.add(name[:4])
                else:
                     prefixes.add(name[:3])

        self.filename_prefixes = ["All"] + sorted(list(prefixes))
        self.prefix_combo['values'] = self.filename_prefixes
        self._log(f"Found {len(prefixes)} unique filename prefixes.")

    def _get_all_clips(self, folder):
        """Recursively gets all clips from a folder and its subfolders."""
        clips = []
        if hasattr(folder, "GetClipList"):
             clips.extend(folder.GetClipList())
        if hasattr(folder, "GetSubFolderList"):
            for subfolder in folder.GetSubFolderList():
                clips.extend(self._get_all_clips(subfolder))
        return clips
        
    def _filter_clips(self, by_prefix=None):
        """Filters clips based on the user's selection in the GUI."""
        if not self.media_pool:
            self._log("Error: Could not access Media Pool. Cannot filter clips.")
            return []

        root_folder = self.media_pool.GetRootFolder()
        all_clips = self._get_all_clips(root_folder)
        
        prefix = by_prefix if by_prefix else self.prefix_var.get()
        wildcard = self.wildcard_var.get().strip()
        
        # If a prefix is passed directly, ignore wildcard
        use_wildcard = not bool(by_prefix) 
        
        filtered_clips = []
        for clip in all_clips:
            name = clip.GetName()
            if use_wildcard and wildcard:
                pattern = wildcard.replace('.', r'\.').replace('*', '.*').replace('?', '.')
                if re.match(pattern, name, re.IGNORECASE):
                    filtered_clips.append(clip)
            elif prefix == "All" or name.startswith(prefix):
                filtered_clips.append(clip)
        
        if by_prefix: # If filtering for analysis, we don't need the other checks
            return filtered_clips

        final_list = []
        for clip in filtered_clips:
            if self.skip_in_timeline_var.get():
                usage_str = clip.GetClipProperty("Usage")
                if usage_str and int(usage_str) > 0:
                    continue
            if self.only_if_null_var.get():
                start_tc = clip.GetClipProperty("Start TC")
                if start_tc and start_tc.strip() and start_tc != "00:00:00:00":
                    continue
            final_list.append(clip)

        self._log(f"Found {len(all_clips)} total clips. Filtered down to {len(final_list)} clips for processing.")
        return final_list
        
    def _parse_datetime_from_filename(self, filename):
        """Tries various regex patterns to extract datetime from a filename."""
        patterns = [
            r'(\d{8})[_-]?(\d{6})(?!\d)',
            r'(\d{8})_?(\d{6})(\d{3})',
            r'(\d{4})-(\d{2})-(\d{2})-(\d{2})-(\d{2})-(\d{2})-(\d{3})'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, filename)
            if match:
                try:
                    parts = match.groups()
                    if len(parts) == 2:
                        dt_str = ''.join(parts)
                        return datetime.strptime(dt_str, '%Y%m%d%H%M%S')
                    elif len(parts) == 3:
                        dt_str = ''.join(parts)
                        return datetime.strptime(dt_str, '%Y%m%d%H%M%S%f')
                    elif len(parts) == 7:
                        dt_str = f"{''.join(parts)}"
                        return datetime.strptime(dt_str, '%Y%m%d%H%M%S%f')
                except ValueError:
                    continue
        return None
        
    def _get_file_datetime(self, clip, date_type='create'):
        """Gets creation or modification datetime for a clip's file path."""
        file_path = clip.GetClipProperty("File Path")
        if not file_path:
            return None
        try:
            stat_info = os.stat(file_path)
            if date_type == 'create':
                ts = getattr(stat_info, 'st_birthtime', stat_info.st_ctime)
            else:
                ts = stat_info.st_mtime
            return datetime.fromtimestamp(ts)
        except (OSError, FileNotFoundError) as e:
            self._log(f"Error accessing file path '{file_path}': {e}")
            return None

    def _get_best_datetime(self, clip):
        """Determines the best datetime for a clip based on user settings."""
        dt = None
        source = "Unknown"

        if self.source_logic_var.get() == "earliest":
            sources = {
                "Filename": self._parse_datetime_from_filename(clip.GetName()),
                "Creation": self._get_file_datetime(clip, 'create'),
                "Modification": self._get_file_datetime(clip, 'modify')
            }
            valid_sources = {k: v for k, v in sources.items() if v is not None}
            if not valid_sources:
                return None, "Failed to find any date"
            
            # Find the earliest date
            earliest_source_name = min(valid_sources, key=valid_sources.get)
            dt = valid_sources[earliest_source_name]
            source = f"Earliest ({earliest_source_name})"

        else: # Priority logic
            if self.parse_filename_var.get():
                dt = self._parse_datetime_from_filename(clip.GetName())
                if dt: source = "Filename"
            
            if not dt:
                fallback_type = self.fallback_date_var.get()
                dt = self._get_file_datetime(clip, fallback_type)
                if dt: source = f"File {'Creation' if fallback_type == 'create' else 'Modification'} Time"
        
        if not dt:
            return None, "Failed to find any date"

        offset_hours = self.tz_offset_var.get()
        if offset_hours != 0:
            dt += timedelta(hours=offset_hours)
            source += f" (Adjusted by {offset_hours}h)"

        return dt.astimezone(), source

    def _format_timedelta(self, td):
        """Formats a timedelta into a human-readable string."""
        if td is None: return "N/A"
        
        td_abs = abs(td)
        days, remainder = divmod(td_abs.total_seconds(), 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        parts = []
        if days > 0: parts.append(f"{int(days)}d")
        if hours > 0: parts.append(f"{int(hours)}h")
        if minutes > 0: parts.append(f"{int(minutes)}m")
        if not parts and seconds > 0: parts.append(f"{int(seconds)}s")
        if not parts: return "0s"
        
        return " ".join(parts)

    def scan_and_analyze(self):
        """Scans clips and provides a summarized log of discrepancies by prefix."""
        self.log_text.delete(1.0, tk.END)
        self._log("--- Starting Discrepancy Analysis ---")
        
        # Get all prefixes from the dropdown to iterate through
        all_prefixes = self.prefix_combo['values']
        if not all_prefixes or "All" in self.prefix_var.get():
            # If "All" is selected, we need to gather all prefixes from the clips themselves
            all_clips = self._get_all_clips(self.media_pool.GetRootFolder())
            prefixes_from_clips = set()
            for clip in all_clips:
                name = clip.GetName()
                match = re.match(r'([a-zA-Z_]+|\d{4})', name)
                if match:
                    prefixes_from_clips.add(match.group(1).rstrip('_'))
                elif len(name) >=3:
                     prefixes_from_clips.add(name[:3] if not name[:3].isdigit() else name[:4])
            prefixes_to_scan = sorted(list(prefixes_from_clips))
        else:
            prefixes_to_scan = [self.prefix_var.get()]

        if not prefixes_to_scan: self._log("No clips found to analyze."); return

        for prefix in prefixes_to_scan:
            clips_in_prefix = self._filter_clips(by_prefix=prefix)
            if not clips_in_prefix: continue
            
            self._log(f"===== Prefix: {prefix} ({len(clips_in_prefix)} clips) =====")

            all_deltas = {'cn': [], 'mn': [], 'mc': []}
            for clip in clips_in_prefix:
                dts = {
                    'name': self._parse_datetime_from_filename(clip.GetName()),
                    'create': self._get_file_datetime(clip, 'create'),
                    'modify': self._get_file_datetime(clip, 'modify')
                }
                if dts['create'] and dts['name']: all_deltas['cn'].append((dts['create'] - dts['name']).total_seconds())
                if dts['modify'] and dts['name']: all_deltas['mn'].append((dts['modify'] - dts['name']).total_seconds())
                if dts['modify'] and dts['create']: all_deltas['mc'].append((dts['modify'] - dts['create']).total_seconds())

            def get_mode_delta(deltas):
                if not deltas: return None
                rounded = [round(d / 60) * 60 for d in deltas] # Round to nearest minute
                try: return statistics.mode(rounded)
                except statistics.ModeError: return statistics.mean(deltas)

            mode_cn = get_mode_delta(all_deltas['cn'])
            mode_mn = get_mode_delta(all_deltas['mn'])
            mode_mc = get_mode_delta(all_deltas['mc'])
            
            # Check for a consistent match and report succinctly
            if mode_mn is not None and abs(mode_mn) <= 60:
                self._log("  - Filename and Modification dates are consistent.")
            elif mode_cn is not None and abs(mode_cn) <= 60:
                self._log("  - Filename and Creation dates are consistent.")
                if mode_mc is not None:
                    relation = "after" if mode_mc >= 0 else "before"
                    self._log(f"    - Note: Modification date is typically {self._format_timedelta(timedelta(seconds=mode_mc))} {relation} Creation date.")
            elif mode_mc is not None and abs(mode_mc) <= 60:
                self._log("  - Creation and Modification dates are consistent.")
                if mode_cn is not None:
                    relation = "after" if mode_cn >= 0 else "before"
                    self._log(f"    - Note: Filename date is typically {self._format_timedelta(timedelta(seconds=mode_cn))} {relation} Creation date.")
            else: # No simple match, this is a real discrepancy worth detailing
                self._log("  - No two sources are consistently within 1 minute.")
                
                # Find the largest, most consistent discrepancy to show an example for
                discrepancy_to_report = None
                if mode_cn is not None and abs(mode_cn) > 60:
                    discrepancy_to_report = ('Create', 'Name', mode_cn, 'cn')
                elif mode_mn is not None and abs(mode_mn) > 60:
                    discrepancy_to_report = ('Modify', 'Name', mode_mn, 'mn')
                
                if discrepancy_to_report:
                    source1, source2, mode_delta, key = discrepancy_to_report
                    relation = "after" if mode_delta >= 0 else "before"
                    self._log(f"  - Most common offset: {source1} is {self._format_timedelta(timedelta(seconds=mode_delta))} {relation} {source2}.")

                    # Find examples for this specific discrepancy
                    examples = []
                    for clip in clips_in_prefix:
                        dts = {
                            'name': self._parse_datetime_from_filename(clip.GetName()),
                            'create': self._get_file_datetime(clip, 'create'),
                            'modify': self._get_file_datetime(clip, 'modify')
                        }
                        s1_key, s2_key = source1.lower(), source2.lower()
                        if dts[s1_key] and dts[s2_key]:
                            delta = (dts[s1_key] - dts[s2_key]).total_seconds()
                            if abs(delta - mode_delta) < 60: # Matches the mode
                                examples.append((clip.GetName(), dts[s1_key], dts[s2_key]))
                    
                    if examples:
                        examples.sort(key=lambda x: x[1]) # Sort by date
                        first_ex = examples[0]
                        last_ex = examples[-1]
                        self._log("    - Example Discrepancy:")
                        self._log(f"      - First Clip: {first_ex[0]}")
                        self._log(f"        - {source1}: {first_ex[1].strftime('%Y-%m-%d %H:%M:%S')}")
                        self._log(f"        - {source2}: {first_ex[2].strftime('%Y-%m-%d %H:%M:%S')}")
                        if len(examples) > 1:
                            self._log(f"      - Last Clip:  {last_ex[0]}")
                            self._log(f"        - {source1}: {last_ex[1].strftime('%Y-%m-%d %H:%M:%S')}")
                            self._log(f"        - {source2}: {last_ex[2].strftime('%Y-%m-%d %H:%M:%S')}")
            self._log("")

    def apply_changes(self):
        """Main function to apply the timecode and date changes."""
        self.log_text.delete(1.0, tk.END)
        self._log("--- Applying Changes ---")
        
        clips = self._filter_clips()
        if not clips: return
            
        if not messagebox.askyesno("Confirm Changes", f"You are about to modify {len(clips)} clips. Are you sure you want to proceed?"):
            self._log("Operation cancelled by user."); return

        success_count, fail_count = 0, 0

        for clip in clips:
            name = clip.GetName()
            self._log(f"Processing: {name}")

            dt, source = self._get_best_datetime(clip)

            if not dt:
                self._log(f"  -> SKIPPED: Could not determine date. ({source})"); fail_count += 1; continue
            
            # Per user feedback, format date as 'Mmm dd maxGoto HH:MM:SS'
            # Example: 'Jun 23 2025 19:37:00'
            scene_date_str = dt.strftime("%b %d %Y %H:%M:%S")
            
            try:
                fps_str = clip.GetClipProperty("FPS")
                if not fps_str: raise ValueError("FPS is null")
                fps = float(fps_str)
                if fps <= 0: raise ValueError("Invalid FPS")
            except (ValueError, TypeError, AttributeError) as e:
                self._log(f"  -> FAILED: Could not determine valid FPS for clip ({e}). Skipping."); fail_count += 1; continue

            midnight = dt.replace(hour=0, minute=0, second=0, microsecond=0)
            total_frames = int((dt - midnight).total_seconds() * fps)
            
            frames_in_day = int(24 * 3600 * fps)
            total_frames %= frames_in_day

            ff = total_frames % int(round(fps))
            total_seconds_int = total_frames // int(round(fps))
            mm, ss = divmod(total_seconds_int, 60)
            hh, mm = divmod(mm, 60)
            
            new_tc = f"{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}"

            set_backup_ok, set_tc_ok, set_date_ok = True, True, True
            
            if self.backup_tc_var.get():
                original_tc = clip.GetClipProperty("Start TC")
                if original_tc and original_tc.strip():
                    set_backup_ok = clip.SetClipProperty("Slate TC", original_tc)

            set_tc_ok = clip.SetClipProperty("Start TC", new_tc)
            # Set 'Scene' property, not 'Scene Date'
            set_date_ok = clip.SetClipProperty("Scene", scene_date_str)
            
            if set_backup_ok and set_tc_ok and set_date_ok:
                self._log(f"  -> SUCCESS: Set TC to {new_tc}, Scene to '{scene_date_str}' (from {source})")
                success_count += 1
            else:
                self._log("  -> FAILED: Resolve API call failed.")
                if not set_backup_ok: self._log("    - Could not back up to 'Slate TC'.")
                if not set_tc_ok: self._log("    - Could not set 'Start TC'.")
                if not set_date_ok: self._log("    - Could not set 'Scene'.")
                fail_count += 1

        self._log(f"\n--- Summary ---\nSuccessfully updated: {success_count} clips.\nFailed or skipped: {fail_count} clips.")
        messagebox.showinfo("Operation Complete", f"Successfully updated {success_count} clips.\nFailed or skipped {fail_count} clips.\n\nSee log for details.")

    def restore_from_backup(self):
        """Restores 'Start TC' from 'Slate TC'."""
        self.log_text.delete(1.0, tk.END)
        self._log("--- Restoring 'Start TC' from 'Slate TC' Backup ---")
        
        clips = self._filter_clips()
        if not clips: return

        if not messagebox.askyesno("Confirm Restore", f"This will restore 'Start TC' from the 'Slate TC' field for {len(clips)} clips. This cannot be undone. Proceed?"):
            self._log("Operation cancelled by user."); return

        success_count, fail_count = 0, 0
        
        for clip in clips:
            slate_tc = clip.GetClipProperty("Slate TC")
            if slate_tc and slate_tc.strip():
                if clip.SetClipProperty("Start TC", slate_tc):
                    self._log(f"Restored TC for '{clip.GetName()}' to {slate_tc}"); success_count += 1
                else:
                    self._log(f"FAILED to restore TC for '{clip.GetName()}'"); fail_count += 1
            else:
                self._log(f"SKIPPED '{clip.GetName()}': No data in 'Slate TC'."); fail_count += 1
        
        self._log(f"\n--- Restore Summary ---\nSuccessfully restored: {success_count} clips.\nFailed or skipped: {fail_count} clips.")
        messagebox.showinfo("Restore Complete", f"Restored {success_count} clips.\nFailed or skipped {fail_count} clips.")


# --- Entry Point ---
if __name__ == "__main__":
    if 'bmd' not in locals() and not hasattr(resolve, 'GetProjectManager'):
         print("Error: DaVinci Resolve object not found. This script must be run from the Resolve console.")
    else:
        app = TimecodeToolApp(resolve)
        app.mainloop()
