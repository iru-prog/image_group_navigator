import os
import re
import tkinter as tk
from tkinter import messagebox
import subprocess

image_folder = "/Volumes/500/PICT/pixivより(未整理)"

def try_int(s):
    try:
        return int(s)
    except:
        return s

def natural_key(s):
    return [try_int(c) for c in re.split(r'(\d+)', s)]

all_files = os.listdir(image_folder)
valid_exts = ('.jpg', '.jpeg', '.png', '.gif')
image_files = [f for f in all_files if f.lower().endswith(valid_exts)]

group_dict = {}
for filename in image_files:
    prefix = filename.split('_')[0]
    group_dict.setdefault(prefix, []).append(filename)

group_keys = sorted(group_dict.keys(), key=natural_key)
for key in group_keys:
    group_dict[key].sort(key=natural_key)

def extract_middle_number(name):
    parts = name.split('_')
    if len(parts) >= 3:
        return parts[1]
    return ""

def get_middle_groups(filelist):
    middle_group_dict = {}
    for f in filelist:
        key = extract_middle_number(f)
        middle_group_dict.setdefault(key, []).append(f)
    return middle_group_dict

root = tk.Tk()
root.title("画像グループ一覧")
root.geometry("960x600")

left_frame = tk.Frame(root)
left_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
left_listbox = tk.Listbox(left_frame, font=("Helvetica", 12), exportselection=False)
left_listbox.pack(fill=tk.BOTH, expand=True)
left_btn_frame = tk.Frame(left_frame)
left_btn_frame.pack(fill=tk.X, pady=2)
left_up_btn = tk.Button(left_btn_frame, text="↑")
left_up_btn.pack(side=tk.LEFT, expand=True, fill=tk.X)
left_down_btn = tk.Button(left_btn_frame, text="↓")
left_down_btn.pack(side=tk.LEFT, expand=True, fill=tk.X)

middle_frame = tk.Frame(root)
middle_frame.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)
middle_listbox = tk.Listbox(middle_frame, font=("Helvetica", 12), exportselection=False)
middle_listbox.pack(fill=tk.BOTH, expand=True)
middle_btn_frame = tk.Frame(middle_frame)
middle_btn_frame.pack(fill=tk.X, pady=2)
middle_up_btn = tk.Button(middle_btn_frame, text="↑")
middle_up_btn.pack(side=tk.LEFT, expand=True, fill=tk.X)
middle_down_btn = tk.Button(middle_btn_frame, text="↓")
middle_down_btn.pack(side=tk.LEFT, expand=True, fill=tk.X)

right_frame = tk.Frame(root)
right_frame.grid(row=0, column=2, sticky="nsew", padx=5, pady=5)
right_listbox = tk.Listbox(right_frame, font=("Helvetica", 12), exportselection=False)
right_listbox.pack(fill=tk.BOTH, expand=True)

root.grid_columnconfigure(0, weight=1)
root.grid_columnconfigure(1, weight=1)
root.grid_columnconfigure(2, weight=1)
root.grid_rowconfigure(0, weight=1)

def open_image(filepath):
    try:
        subprocess.run(['open', filepath], check=True)
    except Exception as e:
        messagebox.showerror("エラー", f"画像を開けませんでした: {e}")

def on_left_double_click(event):
    selection = left_listbox.curselection()
    if not selection:
        return
    group_key = left_listbox.get(selection[0])
    filelist = group_dict[group_key]
    if filelist:
        open_image(os.path.join(image_folder, filelist[0]))

def on_middle_double_click(event):
    left_selection = left_listbox.curselection()
    middle_selection = middle_listbox.curselection()
    if not left_selection or not middle_selection:
        return
    left_key = left_listbox.get(left_selection[0])
    middle_key = middle_listbox.get(middle_selection[0])
    filelist = group_dict[left_key]
    middle_groups = get_middle_groups(filelist)
    files = middle_groups.get(middle_key, [])
    if files:
        open_image(os.path.join(image_folder, files[0]))

def on_right_double_click(event):
    left_selection = left_listbox.curselection()
    middle_selection = middle_listbox.curselection()
    right_selection = right_listbox.curselection()
    if not (left_selection and middle_selection and right_selection):
        return
    left_key = left_listbox.get(left_selection[0])
    middle_key = middle_listbox.get(middle_selection[0])
    filelist = group_dict[left_key]
    middle_groups = get_middle_groups(filelist)
    files = middle_groups.get(middle_key, [])
    idx = right_selection[0]
    if 0 <= idx < len(files):
        open_image(os.path.join(image_folder, files[idx]))

def update_right_list(middle_key, filelist):
    middle_groups = get_middle_groups(filelist)
    files = middle_groups.get(middle_key, [])

    right_listbox.delete(0, tk.END)
    for f in files:
        parts = f.split('_', 2)
        display_name = parts[2] if len(parts) > 2 else ''
        if '.' in display_name:
            display_name = os.path.splitext(display_name)[0]
        right_listbox.insert(tk.END, display_name)

    if right_listbox.size() > 0:
        right_listbox.selection_clear(0, tk.END)
        right_listbox.selection_set(0)
        right_listbox.activate(0)

def on_left_select(event):
    selection = left_listbox.curselection()
    if not selection:
        middle_listbox.delete(0, tk.END)
        right_listbox.delete(0, tk.END)
        return
    group_key = left_listbox.get(selection[0])
    filelist = group_dict[group_key]
    middle_groups = get_middle_groups(filelist)
    sorted_middle_keys = sorted(middle_groups.keys(), key=natural_key)

    middle_listbox.delete(0, tk.END)
    for k in sorted_middle_keys:
        middle_listbox.insert(tk.END, k)

    right_listbox.delete(0, tk.END)

    if sorted_middle_keys:
        middle_listbox.selection_clear(0, tk.END)
        middle_listbox.selection_set(0)
        middle_listbox.activate(0)
        update_right_list(sorted_middle_keys[0], filelist)
    else:
        right_listbox.delete(0, tk.END)

def on_middle_select(event):
    left_selection = left_listbox.curselection()
    middle_selection = middle_listbox.curselection()
    if not left_selection or not middle_selection:
        right_listbox.delete(0, tk.END)
        return
    left_key = left_listbox.get(left_selection[0])
    middle_key = middle_listbox.get(middle_selection[0])
    filelist = group_dict[left_key]

    update_right_list(middle_key, filelist)

def move_selection(listbox, direction):
    if not listbox.size():
        return
    selection = listbox.curselection()
    if not selection:
        index = 0 if direction > 0 else listbox.size() - 1
    else:
        index = selection[0] + direction
        if index < 0:
            index = 0
        elif index >= listbox.size():
            index = listbox.size() - 1
    listbox.selection_clear(0, tk.END)
    listbox.selection_set(index)
    listbox.activate(index)
    listbox.see(index)

    # ここで選択行変更後の動作をダブルクリック動作に合わせる
    if listbox == left_listbox:
        group_key = listbox.get(index)
        filelist = group_dict[group_key]
        if filelist:
            open_image(os.path.join(image_folder, filelist[0]))
        # 中リストを更新して先頭選択、右リスト更新
        on_left_select(None)
    elif listbox == middle_listbox:
        left_selection = left_listbox.curselection()
        if not left_selection:
            return
        left_key = left_listbox.get(left_selection[0])
        middle_key = listbox.get(index)
        filelist = group_dict[left_key]
        middle_groups = get_middle_groups(filelist)
        files = middle_groups.get(middle_key, [])
        if files:
            open_image(os.path.join(image_folder, files[0]))

left_up_btn.config(command=lambda: move_selection(left_listbox, -1))
left_down_btn.config(command=lambda: move_selection(left_listbox, 1))
middle_up_btn.config(command=lambda: move_selection(middle_listbox, -1))
middle_down_btn.config(command=lambda: move_selection(middle_listbox, 1))

left_listbox.bind("<<ListboxSelect>>", on_left_select)
middle_listbox.bind("<<ListboxSelect>>", on_middle_select)
left_listbox.bind("<Double-Button-1>", on_left_double_click)
middle_listbox.bind("<Double-Button-1>", on_middle_double_click)
right_listbox.bind("<Double-Button-1>", on_right_double_click)

for key in group_keys:
    left_listbox.insert(tk.END, key)

if group_keys:
    left_listbox.selection_set(0)
    left_listbox.activate(0)
    on_left_select(None)

root.mainloop()