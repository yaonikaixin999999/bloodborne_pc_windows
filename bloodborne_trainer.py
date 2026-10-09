# Windows port modifications by yaonikaixin999999, 2026-10-06.
# SPDX-License-Identifier: GPL-2.0-or-later
"""Chinese trainer interface for this repository's native Windows build.

Saved preferences are only suggestions. Connecting never activates a feature;
the user must press Apply. Importing this module does not create a Tk window or
attach to any process.
"""
import argparse
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tkinter as tk
from tkinter import messagebox, ttk

FROZEN = getattr(sys, "frozen", False)
# 冻结成 exe 后 __file__ 不再是源码路径：数据根（user/trainer.json）取 exe 所在目录。
ROOT = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent
PREFERENCES_PATH = ROOT / "user" / "trainer.json"
if FROZEN and (sys.stdout is None or sys.stderr is None):
    # windowed 模式没有标准流：接回父进程句柄（管道/重定向可用），
    # 否则丢弃输出，保证 --check 等调用不崩溃。
    _sink = None
    try:
        _sink = open(os.dup(1), "w", encoding="utf-8", errors="replace", buffering=1)
    except OSError:
        pass
    if sys.stdout is None: sys.stdout = _sink or open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None: sys.stderr = _sink or sys.stdout
FEATURES = ("health", "stamina", "echoes", "items")
FEATURE_LABELS = {
    "health": "无限生命（自动补满）",
    "stamina": "无限体力（自动补满）",
    "echoes": "设置血之回响",
    "items": "设置已有物品数量",
}
DEFAULT_PREFERENCES = {
    "health": False, "stamina": False, "echoes": False, "items": False,
    "echoes_amount": 1000000, "items_amount": 20,
}


def validate_amounts(echoes, items):
    """Return validated integers without silently rounding or truncating."""
    values = []
    for value, label, low, high in (
        (echoes, "血之回响", 0, 99999999),
        (items, "物品数量", 1, 99),
    ):
        if isinstance(value, bool):
            raise ValueError(f"{label}必须是 {low}～{high} 的整数。")
        if isinstance(value, int):
            number = value
        elif isinstance(value, str) and value.strip().isascii() and value.strip().isdecimal():
            number = int(value.strip())
        else:
            raise ValueError(f"{label}必须是 {low}～{high} 的整数。")
        if not low <= number <= high:
            raise ValueError(f"{label}必须是 {low}～{high} 的整数。")
        values.append(number)
    return tuple(values)


def read_preferences(path=PREFERENCES_PATH):
    preferences = dict(DEFAULT_PREFERENCES)
    try:
        saved = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return preferences
    if not isinstance(saved, dict):
        return preferences
    for feature in FEATURES:
        if isinstance(saved.get(feature), bool):
            preferences[feature] = saved[feature]
    # Invalid saved amounts must not cause startup to fail or become usable.
    for key, other, index in (("echoes_amount", 20, 0), ("items_amount", 1000000, 1)):
        try:
            pair = (saved[key], other) if index == 0 else (other, saved[key])
            preferences[key] = validate_amounts(*pair)[index]
        except (KeyError, ValueError):
            pass
    return preferences


def save_preferences(preferences, path=PREFERENCES_PATH):
    echoes, items = validate_amounts(preferences["echoes_amount"], preferences["items_amount"])
    saved = {feature: bool(preferences[feature]) for feature in FEATURES}
    saved.update(echoes_amount=echoes, items_amount=items)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(saved, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_backend():
    return importlib.import_module("trainer_windows")


class TrainerApp:
    def __init__(self, root, backend=None, preferences_path=PREFERENCES_PATH):
        self.root = root
        self.backend = load_backend() if backend is None else backend
        self.preferences_path = Path(preferences_path)
        self.session = None
        self.processes = []
        self._poll_id = None
        preferences = read_preferences(self.preferences_path)
        self.process_choice = tk.StringVar(root)
        self.status = tk.StringVar(root, "未连接。先启动游戏，然后扫描进程。")
        self.applied_status = tk.StringVar(root, "未启用任何功能")
        self.feature_vars = {
            key: tk.BooleanVar(root, value=preferences[key]) for key in FEATURES
        }
        self.echoes = tk.StringVar(root, str(preferences["echoes_amount"]))
        self.items = tk.StringVar(root, str(preferences["items_amount"]))
        self.feature_widgets = []
        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.close_window)
        self.scan()
        self._schedule_poll()

    def _build_ui(self):
        self.root.title("血源 · Windows 修改器")
        self.root.geometry("560x620")
        self.root.minsize(500, 590)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        frame = ttk.Frame(self.root, padding=16)
        frame.grid(sticky="nsew")
        frame.columnconfigure(0, weight=1)
        ttk.Label(frame, text="血源修改器", font=("Microsoft YaHei UI", 16, "bold")).grid(
            row=0, column=0, sticky="w", pady=(0, 4))
        ttk.Label(frame, text="适配本项目的 Windows 原生版本").grid(row=1, column=0, sticky="w")

        process_frame = ttk.LabelFrame(frame, text="连接游戏", padding=10)
        process_frame.grid(row=2, column=0, sticky="ew", pady=(12, 10))
        process_frame.columnconfigure(0, weight=1)
        self.process_dropdown = ttk.Combobox(
            process_frame, textvariable=self.process_choice, state="readonly", width=34)
        self.process_dropdown.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        self.scan_button = ttk.Button(process_frame, text="扫描进程", command=self.scan)
        self.scan_button.grid(row=1, column=0, sticky="w")
        self.connect_button = ttk.Button(process_frame, text="连接", command=self.connect)
        self.connect_button.grid(row=1, column=1, sticky="e")

        settings = ttk.LabelFrame(frame, text="修改功能", padding=10)
        settings.grid(row=3, column=0, sticky="ew")
        settings.columnconfigure(0, weight=1)
        for row, key in enumerate(FEATURES):
            widget = ttk.Checkbutton(settings, text=FEATURE_LABELS[key], variable=self.feature_vars[key])
            widget.grid(row=row, column=0, sticky="w", pady=5)
            self.feature_widgets.append(widget)
            if key in ("echoes", "items"):
                amount = self.echoes if key == "echoes" else self.items
                entry = ttk.Entry(settings, textvariable=amount, width=12)
                entry.grid(row=row, column=1, sticky="e", padx=(8, 0))
                self.feature_widgets.append(entry)
        ttk.Label(settings, text="回响：0～99,999,999　物品：1～99").grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))

        ttk.Label(
            frame, text="回响在获取/消费时更新；物品数量在使用时更新，不添加新物品。",
            wraplength=480, justify="left",
        ).grid(row=4, column=0, sticky="ew", pady=(8, 4))
        ttk.Label(frame, textvariable=self.applied_status, wraplength=480).grid(
            row=5, column=0, sticky="w", pady=(0, 6))
        action_frame = ttk.Frame(frame)
        action_frame.grid(row=6, column=0, sticky="ew")
        action_frame.columnconfigure((0, 1, 2), weight=1)
        self.apply_button = ttk.Button(action_frame, text="应用设置", command=self.apply_settings)
        self.apply_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.restore_button = ttk.Button(action_frame, text="恢复全部", command=self.restore_all)
        self.restore_button.grid(row=0, column=1, sticky="ew", padx=6)
        self.disconnect_button = ttk.Button(action_frame, text="断开连接", command=self.disconnect)
        self.disconnect_button.grid(row=0, column=2, sticky="ew", padx=(6, 0))
        ttk.Label(frame, textvariable=self.status, wraplength=480, justify="left").grid(
            row=7, column=0, sticky="ew", pady=(12, 8))
        ttk.Button(frame, text="打开游戏启动器", command=self.launch_game).grid(
            row=8, column=0, sticky="w")
        self._set_connected(False)

    def _set_connected(self, connected):
        state = "normal" if connected else "disabled"
        for widget in self.feature_widgets + [self.apply_button, self.restore_button, self.disconnect_button]:
            widget.configure(state=state)
        self.connect_button.configure(state="disabled" if connected or not self.processes else "normal")
        self.process_dropdown.configure(state="disabled" if connected else "readonly")

    def _show_error(self, title, error):
        self.status.set(str(error))
        messagebox.showerror(title, str(error), parent=self.root)

    def scan(self):
        previous = self.process_choice.get()
        try:
            self.processes = list(self.backend.discover_games())
        except Exception as error:
            self._show_error("扫描失败", error)
            return
        choices = [f"PID {process.pid} · {Path(process.path).name}" for process in self.processes]
        self.process_dropdown.configure(values=choices)
        if previous in choices:
            self.process_choice.set(previous)
        else:
            self.process_choice.set(choices[0] if choices else "")
        self._set_connected(self.session is not None)
        if self.session is None:
            self.status.set("发现游戏进程，请选择后连接。" if choices else "未发现游戏进程。请先打开启动器启动游戏。")

    def connect(self):
        if self.session is not None:
            return
        index = self.process_dropdown.current()
        if not 0 <= index < len(self.processes):
            self.status.set("请先扫描并选择游戏进程。")
            return
        try:
            session = self.backend.TrainerSession.connect(self.processes[index].pid)
        except Exception as error:
            self._show_error("连接失败", error)
            return
        self.session = session
        self._set_connected(True)
        self.applied_status.set("未启用任何功能 · 点击“应用设置”才会生效")
        self.status.set(f"已连接 PID {session.pid}。设置尚未应用。")

    def _refresh_applied_status(self):
        if self.session is None:
            self.applied_status.set("未启用任何功能")
            return
        enabled = set(self.session.enabled)
        short_labels = {"health": "生命", "stamina": "体力", "echoes": "回响", "items": "物品"}
        labels = [short_labels[key] for key in FEATURES if key in enabled]
        self.applied_status.set("已启用：" + "、".join(labels) if labels else "未启用任何功能")

    def apply_settings(self):
        if self.session is None:
            return
        try:
            echoes, items = validate_amounts(self.echoes.get(), self.items.get())
            enabled = {key for key, variable in self.feature_vars.items() if variable.get()}
            self.session.apply(enabled, echoes=echoes, items=items)
        except Exception as error:
            self._refresh_applied_status()
            self._show_error("应用失败", error)
            return
        self._refresh_applied_status()
        self.status.set("设置已应用。取消勾选后再次应用可关闭对应功能。")
        preferences = {key: variable.get() for key, variable in self.feature_vars.items()}
        preferences.update(echoes_amount=echoes, items_amount=items)
        try:
            save_preferences(preferences, self.preferences_path)
        except OSError as error:
            self._show_error("设置已生效，但保存失败", error)

    def restore_all(self):
        if self.session is None:
            return False
        try:
            self.session.apply(set())
        except Exception as error:
            self._refresh_applied_status()
            self._show_error("恢复失败，请重试", error)
            return False
        for variable in self.feature_vars.values():
            variable.set(False)
        self._refresh_applied_status()
        self.status.set("所有修改功能已关闭；已经获得或消耗的数值不会回滚。")
        return True

    def _clear_session(self, status):
        self.session = None
        for variable in self.feature_vars.values():
            variable.set(False)
        self._set_connected(False)
        self._refresh_applied_status()
        self.status.set(status)

    def disconnect(self):
        if self.session is None:
            return True
        try:
            self.session.close()
        except Exception as error:
            # The process may have exited between restoration and closing.
            try:
                alive = self.session.is_alive()
            except Exception:
                alive = True
            if alive:
                self._refresh_applied_status()
                self._show_error("断开失败，请先重试恢复", error)
                return False
        self._clear_session("已恢复修改并断开连接。")
        return True

    def _schedule_poll(self):
        self._poll_id = self.root.after(1000, self._poll)

    def _poll(self):
        self._poll_id = None
        if self.session is not None:
            try:
                alive = self.session.is_alive()
            except Exception as error:
                self.status.set(f"无法检查游戏状态：{error}")
            else:
                if not alive:
                    try:
                        self.session.close()
                    except Exception:
                        pass  # No hooks remain in an exited process.
                    self._clear_session("游戏进程已退出。重新启动后请扫描并连接。")
        self._schedule_poll()

    def launch_game(self):
        launcher = ROOT / "启动游戏.exe"
        script = ROOT / "run_windows.py"
        if FROZEN and launcher.is_file():
            command = [str(launcher)]
        elif script.is_file():
            command = [sys.executable, str(script), "--gui"]
        else:
            self._show_error("无法打开启动器", "没有找到 启动游戏.exe 或 run_windows.py。请将修改器放在项目目录中。")
            return
        try:
            environment = os.environ.copy()
            environment.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
            subprocess.Popen(command, cwd=ROOT, env=environment)
        except OSError as error:
            self._show_error("无法打开启动器", error)

    def close_window(self):
        if not self.disconnect():
            return
        if self._poll_id is not None:
            self.root.after_cancel(self._poll_id)
            self._poll_id = None
        self.root.destroy()


def main(argv=None):
    parser = argparse.ArgumentParser(description="血源 Windows 原生版修改器")
    parser.add_argument("--gui", action="store_true", help="打开中文窗口（默认）")
    parser.add_argument("--check", action="store_true", help="只检查可用进程，不连接或修改")
    arguments = parser.parse_args(argv)
    try:
        backend = load_backend()
        if arguments.check:
            processes = backend.discover_games()
            print(f"发现 {len(processes)} 个候选游戏进程；未连接、未应用修改。")
            return 0
        root = tk.Tk()
        TrainerApp(root, backend=backend)
        root.mainloop()
    except Exception as error:
        if arguments.check:
            print(f"检查失败：{error}", file=sys.stderr)
        else:
            # pythonw has no console, so initialization failures need a dialog.
            messagebox.showerror("修改器无法启动", str(error))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
