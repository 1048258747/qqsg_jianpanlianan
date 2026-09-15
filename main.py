# -*- coding: utf-8 -*-
"""
QQ三国键盘连按工具 - 主程序

功能：
- 自动锁定QQ三国游戏窗口
- 支持自定义按键序列和按键盘间隔
- 模拟物理按键操作
- 支持系统托盘隐藏
- 图像识别与流程编辑器
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import threading
import time
import random
import re
import sys
import os
import json
import ctypes
from ctypes import wintypes, windll

import cv2
import numpy as np
import pyautogui
import customtkinter as ctk
from PIL import Image, ImageDraw

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.1

try:
    import pystray
    TRAY_AVAILABLE = True
except ImportError:
    TRAY_AVAILABLE = False
    print("警告: 未安装pystray，系统托盘功能不可用")


def resource_path(rel):
    """返回资源文件的绝对路径，兼容 PyInstaller 打包后的临时目录"""
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


# ==================== 图像识别与鼠标控制模块 ====================

class ImageRecognizer:
    def __init__(self, confidence_threshold=0.8):
        self.confidence_threshold = confidence_threshold

    def find_image_on_screen(self, template_path, region=None, confidence=None):
        start_time = time.time()
        if confidence is None:
            confidence = self.confidence_threshold
        template_data = np.fromfile(template_path, dtype=np.uint8)
        template = cv2.imdecode(template_data, cv2.IMREAD_COLOR)
        if template is None:
            return False, 0, 0, 0.0, f"无法加载模板图像: {template_path}"
        template_height, template_width = template.shape[:2]
        if region:
            screenshot = pyautogui.screenshot(region=region)
            offset_x, offset_y = region[0], region[1]
        else:
            screenshot = pyautogui.screenshot()
            offset_x, offset_y = 0, 0
        screenshot_cv = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
        if template_height > screenshot_cv.shape[0] or template_width > screenshot_cv.shape[1]:
            return False, 0, 0, 0.0, "模板图像大于搜索区域"
        result = cv2.matchTemplate(screenshot_cv, template, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
        confidence_found = max_val
        if confidence_found >= confidence:
            top_left = max_loc
            center_x = top_left[0] + template_width // 2 + offset_x
            center_y = top_left[1] + template_height // 2 + offset_y
            return True, center_x, center_y, confidence_found, None
        else:
            return False, 0, 0, confidence_found, f"未找到匹配，最高置信度: {confidence_found:.3f}"

    def find_all_images_on_screen(self, template_path, region=None, confidence=None):
        if confidence is None:
            confidence = self.confidence_threshold
        template_data = np.fromfile(template_path, dtype=np.uint8)
        template = cv2.imdecode(template_data, cv2.IMREAD_COLOR)
        if template is None:
            return []
        template_height, template_width = template.shape[:2]
        if region:
            screenshot = pyautogui.screenshot(region=region)
            offset_x, offset_y = region[0], region[1]
        else:
            screenshot = pyautogui.screenshot()
            offset_x, offset_y = 0, 0
        screenshot_cv = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
        result = cv2.matchTemplate(screenshot_cv, template, cv2.TM_CCOEFF_NORMED)
        locations = np.where(result >= confidence)
        matches = []
        for pt in zip(*locations[::-1]):
            center_x = pt[0] + template_width // 2 + offset_x
            center_y = pt[1] + template_height // 2 + offset_y
            match_confidence = result[pt[1], pt[0]]
            matches.append((center_x, center_y, match_confidence))
        matches = self._remove_overlapping_matches(matches, template_width, template_height)
        return matches

    def _remove_overlapping_matches(self, matches, template_width, template_height):
        if not matches:
            return []
        matches.sort(key=lambda x: x[2], reverse=True)
        filtered = []
        threshold_x = template_width * 0.5
        threshold_y = template_height * 0.5
        for match in matches:
            is_duplicate = False
            for existing in filtered:
                if abs(match[0] - existing[0]) < threshold_x and abs(match[1] - existing[1]) < threshold_y:
                    is_duplicate = True
                    break
            if not is_duplicate:
                filtered.append(match)
        return filtered

    def wait_for_image(self, template_path, timeout=10, check_interval=0.5, region=None, confidence=None):
        start_time = time.time()
        while time.time() - start_time < timeout:
            success, x, y, conf, error = self.find_image_on_screen(template_path, region, confidence)
            if success:
                return True, x, y, conf, None
            time.sleep(check_interval)
        return False, 0, 0, 0.0, f"等待图像超时 ({timeout}秒)"


class MouseController:
    def __init__(self):
        pass

    def click(self, x=None, y=None, button='left', clicks=1, interval=0.1):
        if x is not None and y is not None:
            pyautogui.moveTo(x, y)
        pyautogui.click(button=button, clicks=clicks, interval=interval)

    def double_click(self, x=None, y=None):
        if x is not None and y is not None:
            pyautogui.moveTo(x, y)
        pyautogui.doubleClick()

    def right_click(self, x=None, y=None):
        if x is not None and y is not None:
            pyautogui.moveTo(x, y)
        pyautogui.rightClick()

    def move_to(self, x, y, duration=0.2):
        pyautogui.moveTo(x, y, duration=duration)

    def move_relative(self, x_offset, y_offset, duration=0.2):
        pyautogui.moveRel(x_offset, y_offset, duration=duration)

    def drag_to(self, x, y, duration=0.5, button='left'):
        pyautogui.dragTo(x, y, duration=duration, button=button)

    def get_position(self):
        return pyautogui.position()

    def scroll(self, clicks, x=None, y=None):
        pyautogui.scroll(clicks, x=x, y=y)


class AutomationEngine:
    def __init__(self, confidence_threshold=0.8):
        self.image_recognizer = ImageRecognizer(confidence_threshold)
        self.mouse_controller = MouseController()
        self.debug_callback = None

    def set_debug_callback(self, callback):
        self.debug_callback = callback

    def log(self, message):
        if self.debug_callback:
            self.debug_callback(message)

    def find_and_click(self, template_path, button='left', clicks=1, region=None, confidence=None, delay_before=0, delay_after=0.5):
        if delay_before > 0:
            time.sleep(delay_before)
        self.log(f"查找图像: {template_path}")
        success, x, y, conf, error = self.image_recognizer.find_image_on_screen(template_path, region, confidence)
        if success:
            self.log(f"找到图像，位置: ({x}, {y})，置信度: {conf:.3f}")
            self.mouse_controller.click(x, y, button=button, clicks=clicks)
            self.log(f"已点击位置: ({x}, {y})")
            if delay_after > 0:
                time.sleep(delay_after)
            return True, None
        else:
            self.log(f"未找到图像: {error}")
            return False, error

    def find_and_click_relative(self, template_path, offset_x=0, offset_y=0, button='left', region=None, confidence=None, delay_after=0.5):
        self.log(f"查找图像: {template_path}")
        success, x, y, conf, error = self.image_recognizer.find_image_on_screen(template_path, region, confidence)
        if success:
            target_x = x + offset_x
            target_y = y + offset_y
            self.log(f"找到图像，点击相对位置: ({target_x}, {target_y})")
            self.mouse_controller.click(target_x, target_y, button=button)
            if delay_after > 0:
                time.sleep(delay_after)
            return True, None
        else:
            self.log(f"未找到图像: {error}")
            return False, error

    def wait_and_click(self, template_path, timeout=10, button='left', region=None, confidence=None, delay_after=0.5):
        self.log(f"等待图像出现: {template_path}，超时: {timeout}秒")
        success, x, y, conf, error = self.image_recognizer.wait_for_image(template_path, timeout, region=region, confidence=confidence)
        if success:
            self.log(f"图像出现，位置: ({x}, {y})")
            self.mouse_controller.click(x, y, button=button)
            self.log(f"已点击位置: ({x}, {y})")
            if delay_after > 0:
                time.sleep(delay_after)
            return True, None
        else:
            self.log(f"等待图像失败: {error}")
            return False, error

    def check_image_exists(self, template_path, region=None, confidence=None):
        success, x, y, conf, error = self.image_recognizer.find_image_on_screen(template_path, region, confidence)
        return success

    def capture_region(self, output_path, region=None):
        try:
            if region:
                screenshot = pyautogui.screenshot(region=region)
            else:
                screenshot = pyautogui.screenshot()
            screenshot.save(output_path)
            return True, None
        except Exception as e:
            return False, str(e)


# ==================== 流程引擎模块 ====================

VK_CODES_FLOW = {
    'A': 0x41, 'B': 0x42, 'C': 0x43, 'D': 0x44, 'E': 0x45,
    'F': 0x46, 'G': 0x47, 'H': 0x48, 'I': 0x49, 'J': 0x4A,
    'K': 0x4B, 'L': 0x4C, 'M': 0x4D, 'N': 0x4E, 'O': 0x4F,
    'P': 0x50, 'Q': 0x51, 'R': 0x52, 'S': 0x53, 'T': 0x54,
    'U': 0x55, 'V': 0x56, 'W': 0x57, 'X': 0x58, 'Y': 0x59,
    'Z': 0x5A,
    '0': 0x30, '1': 0x31, '2': 0x32, '3': 0x33, '4': 0x34,
    '5': 0x35, '6': 0x36, '7': 0x37, '8': 0x38, '9': 0x39,
    'F1': 0x70, 'F2': 0x71, 'F3': 0x72, 'F4': 0x73,
    'F5': 0x74, 'F6': 0x75, 'F7': 0x76, 'F8': 0x77,
    'F9': 0x78, 'F10': 0x79, 'F11': 0x7A, 'F12': 0x7B,
    'SPACE': 0x20, 'ENTER': 0x0D, 'TAB': 0x09,
    'ESC': 0x1B, 'BACKSPACE': 0x08, 'DELETE': 0x2E,
    'UP': 0x26, 'DOWN': 0x28, 'LEFT': 0x25, 'RIGHT': 0x27,
    'SHIFT': 0x10, 'CTRL': 0x11, 'ALT': 0x12,
}


class FlowStep:
    TYPE_IMAGE_CLICK = "image_click"
    TYPE_IMAGE_CHECK = "image_check"
    TYPE_KEYBOARD = "keyboard"
    TYPE_MOUSE_MOVE = "mouse_move"
    TYPE_DELAY = "delay"
    TYPE_LOOP_START = "loop_start"
    TYPE_LOOP_END = "loop_end"
    TYPE_CONDITION = "condition"
    TYPE_BRANCH = "branch"

    def __init__(self, step_type, params=None):
        self.step_type = step_type
        self.params = params or {}
        self.enabled = True

    def to_dict(self):
        return {
            'step_type': self.step_type,
            'params': self.params,
            'enabled': self.enabled
        }

    @classmethod
    def from_dict(cls, data):
        step = cls(data['step_type'], data.get('params', {}))
        step.enabled = data.get('enabled', True)
        return step


class FlowEngine:
    def __init__(self, confidence_threshold=0.8):
        self.automation = AutomationEngine(confidence_threshold)
        self.running = False
        self.steps = []
        self.debug_callback = None
        self.variables = {}
        self._stop_event = threading.Event()
        self.target_hwnd = None

    def set_debug_callback(self, callback):
        self.debug_callback = callback
        self.automation.set_debug_callback(callback)

    def log(self, message):
        if self.debug_callback:
            self.debug_callback(message)

    def set_steps(self, steps):
        self.steps = steps

    def load_flow_from_file(self, filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.steps = []
            for step_data in data.get('steps', []):
                self.steps.append(FlowStep.from_dict(step_data))
            return True, None
        except Exception as e:
            return False, str(e)

    def save_flow_to_file(self, filepath):
        try:
            data = {
                'steps': [step.to_dict() for step in self.steps]
            }
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True, None
        except Exception as e:
            return False, str(e)

    def start(self, loop_count=1):
        if self.running:
            return False
        if not self.steps:
            self.log("错误: 没有流程步骤")
            return False
        self.loop_count = loop_count
        if self.target_hwnd:
            try:
                windll.user32.SetForegroundWindow(self.target_hwnd)
                windll.user32.ShowWindow(self.target_hwnd, 9)
                self.log(f"已切换到目标窗口")
                time.sleep(0.3)
            except Exception as e:
                self.log(f"切换窗口失败: {e}")
        self.running = True
        self._stop_event.clear()
        self.variables = {}
        thread = threading.Thread(target=self._execute_flow, daemon=True)
        thread.start()
        return True

    def stop(self):
        self.running = False
        self._stop_event.set()

    def is_running(self):
        return self.running

    def _execute_flow(self):
        self.log("流程开始执行")
        try:
            if self.loop_count == 0:
                iteration = 1
                while self.running and not self._stop_event.is_set():
                    self.log(f"=== 流程循环 {iteration} ===")
                    self._execute_steps(self.steps, 0, len(self.steps))
                    iteration += 1
            else:
                for i in range(self.loop_count):
                    if not self.running or self._stop_event.is_set():
                        break
                    if self.loop_count > 1:
                        self.log(f"=== 流程循环 {i + 1}/{self.loop_count} ===")
                    self._execute_steps(self.steps, 0, len(self.steps))
        except Exception as e:
            self.log(f"流程执行异常: {e}")
        self.running = False
        self.log("流程执行结束")

    def _execute_steps(self, steps, start_idx, end_idx, loop_count=1):
        for current_loop in range(loop_count):
            if not self.running:
                return
            if loop_count > 1:
                self.log(f"=== 循环 {current_loop + 1}/{loop_count} ===")
            idx = start_idx
            while idx < end_idx and self.running:
                if self._stop_event.is_set():
                    return
                step = steps[idx]
                if not step.enabled:
                    idx += 1
                    continue
                try:
                    should_continue, jump_idx = self._execute_step(step, steps, idx)
                    if jump_idx is not None:
                        idx = jump_idx
                    elif should_continue:
                        idx += 1
                    else:
                        break
                except Exception as e:
                    self.log(f"步骤执行失败 (索引 {idx}): {e}")
                    break

    def _execute_step(self, step, all_steps, current_idx):
        step_type = step.step_type
        params = step.params
        if step_type == FlowStep.TYPE_IMAGE_CLICK:
            return self._execute_image_click(params)
        elif step_type == FlowStep.TYPE_IMAGE_CHECK:
            return self._execute_image_check(params, all_steps, current_idx)
        elif step_type == FlowStep.TYPE_KEYBOARD:
            return self._execute_keyboard(params)
        elif step_type == FlowStep.TYPE_MOUSE_MOVE:
            return self._execute_mouse_move(params)
        elif step_type == FlowStep.TYPE_DELAY:
            return self._execute_delay(params)
        elif step_type == FlowStep.TYPE_LOOP_START:
            return self._execute_loop_start(params, all_steps, current_idx)
        elif step_type == FlowStep.TYPE_LOOP_END:
            return self._execute_loop_end(current_idx)
        elif step_type == FlowStep.TYPE_CONDITION:
            return self._execute_condition(params, all_steps, current_idx)
        elif step_type == FlowStep.TYPE_BRANCH:
            return self._execute_branch(params, all_steps, current_idx)
        else:
            self.log(f"未知步骤类型: {step_type}")
            return True, None

    def _execute_image_click(self, params):
        template_path = params.get('template_path', '')
        button = params.get('button', 'left')
        clicks = params.get('clicks', 1)
        confidence = params.get('confidence')
        delay_before = params.get('delay_before', 0)
        delay_after = params.get('delay_after', 0.5)
        on_fail = params.get('on_fail', 'continue')
        if not os.path.exists(template_path):
            self.log(f"模板文件不存在: {template_path}")
            if on_fail == 'break':
                return False, None
            return True, None
        success, error = self.automation.find_and_click(
            template_path, button=button, clicks=clicks,
            confidence=confidence, delay_before=delay_before, delay_after=delay_after
        )
        if not success:
            if on_fail == 'break':
                return False, None
        return True, None

    def _execute_image_check(self, params, all_steps, current_idx):
        template_path = params.get('template_path', '')
        confidence = params.get('confidence')
        condition = params.get('condition', 'exists')
        if_true_goto = params.get('if_true_goto')
        if_false_goto = params.get('if_false_goto')
        if not os.path.exists(template_path):
            self.log(f"模板文件不存在: {template_path}")
            return True, None
        exists = self.automation.check_image_exists(template_path, confidence=confidence)
        result = exists if condition == 'exists' else not exists
        if result:
            self.log(f"条件满足: 图像{'存在' if condition == 'exists' else '不存在'}")
            if if_true_goto is not None:
                return True, if_true_goto
        else:
            self.log(f"条件不满足: 图像{'存在' if condition == 'exists' else '不存在'}")
            if if_false_goto is not None:
                return True, if_false_goto
        return True, None

    def _execute_keyboard(self, params):
        key = params.get('key', '')
        press_count = params.get('press_count', 1)
        press_duration = params.get('press_duration', 50)
        interval = params.get('interval', 100)
        if not key:
            self.log("错误: 未指定按键")
            return True, None
        self.log(f"发送键盘: {key} ({press_count}次)")
        vk_code = VK_CODES_FLOW.get(key.upper())
        if vk_code is None:
            self.log(f"未知按键: {key}")
            return True, None
        key_map = {
            'SPACE': 'space', 'ENTER': 'enter', 'TAB': 'tab',
            'ESC': 'esc', 'BACKSPACE': 'backspace', 'DELETE': 'delete',
            'UP': 'up', 'DOWN': 'down', 'LEFT': 'left', 'RIGHT': 'right',
            'SHIFT': 'shift', 'CTRL': 'ctrl', 'ALT': 'alt',
        }
        for i in range(press_count):
            if not self.running:
                return True, None
            if key.upper() in key_map:
                pyautogui.press(key_map[key.upper()])
            elif len(key) == 1:
                pyautogui.press(key.lower())
            else:
                pyautogui.press(key.lower())
            if i < press_count - 1:
                time.sleep(interval / 1000.0)
        return True, None

    def _execute_mouse_move(self, params):
        x = params.get('x', 0)
        y = params.get('y', 0)
        duration = params.get('duration', 0.2)
        self.log(f"移动鼠标到: ({x}, {y})")
        self.automation.mouse_controller.move_to(x, y, duration)
        return True, None

    def _execute_delay(self, params):
        duration = params.get('duration', 1)
        self.log(f"等待 {duration} 秒")
        start_time = time.time()
        while time.time() - start_time < duration:
            if not self.running:
                return True, None
            time.sleep(min(0.1, duration))
        return True, None

    def _execute_loop_start(self, params, all_steps, current_idx):
        loop_count = params.get('loop_count', 1)
        loop_until_image = params.get('loop_until_image')
        loop_until_confidence = params.get('loop_until_image_confidence')
        loop_depth = 1
        end_idx = current_idx + 1
        while end_idx < len(all_steps) and loop_depth > 0:
            if all_steps[end_idx].step_type == FlowStep.TYPE_LOOP_START:
                loop_depth += 1
            elif all_steps[end_idx].step_type == FlowStep.TYPE_LOOP_END:
                loop_depth -= 1
            end_idx += 1
        loop_end_idx = end_idx - 1
        if loop_until_image:
            max_iterations = loop_count if loop_count > 0 else 10000
            iteration = 0
            while iteration < max_iterations and self.running:
                self.log(f"=== 循环 {iteration + 1} (等待图像: {loop_until_image}) ===")
                self._execute_steps(all_steps, current_idx + 1, loop_end_idx)
                if os.path.exists(loop_until_image):
                    exists = self.automation.check_image_exists(loop_until_image, confidence=loop_until_confidence)
                    if exists:
                        self.log(f"图像出现，退出循环: {loop_until_image}")
                        break
                iteration += 1
            return True, loop_end_idx + 1
        else:
            actual_count = loop_count if loop_count > 0 else 1
            self._execute_steps(all_steps, current_idx + 1, loop_end_idx, actual_count)
            return True, loop_end_idx + 1

    def _execute_loop_end(self, current_idx):
        return True, None

    def _execute_condition(self, params, all_steps, current_idx):
        condition_type = params.get('condition_type', 'image_exists')
        template_path = params.get('template_path', '')
        confidence = params.get('confidence')
        if not os.path.exists(template_path):
            self.log(f"模板文件不存在: {template_path}")
            return True, None
        exists = self.automation.check_image_exists(template_path, confidence=confidence)
        condition_met = exists if condition_type == 'image_exists' else not exists
        if condition_met:
            self.log(f"条件为真: 图像{'存在' if condition_type == 'image_exists' else '不存在'}")
            true_steps = params.get('true_steps', [])
            if true_steps:
                step_objects = [FlowStep.from_dict(s) for s in true_steps]
                self._execute_steps(step_objects, 0, len(step_objects))
        else:
            self.log(f"条件为假")
            false_steps = params.get('false_steps', [])
            if false_steps:
                step_objects = [FlowStep.from_dict(s) for s in false_steps]
                self._execute_steps(step_objects, 0, len(step_objects))
        return True, None

    def _execute_branch(self, params, all_steps, current_idx):
        branches = params.get('branches', [])
        for i, branch in enumerate(branches):
            template_path = branch.get('template_path', '')
            confidence = branch.get('confidence')
            if os.path.exists(template_path):
                exists = self.automation.check_image_exists(template_path, confidence=confidence)
                if exists:
                    self.log(f"分支 {i + 1} 匹配")
                    steps = branch.get('steps', [])
                    if steps:
                        step_objects = [FlowStep.from_dict(s) for s in steps]
                        self._execute_steps(step_objects, 0, len(step_objects))
                    return True, None
        self.log("没有分支匹配")
        return True, None


# ==================== 窗口管理模块 ====================

user32 = ctypes.windll.user32
_results_list = []


def _enum_windows_callback(hwnd, lParam):
    if user32.IsWindowVisible(hwnd):
        length = user32.GetWindowTextLengthW(hwnd)
        if length > 0:
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            title = buffer.value
            if title:
                _results_list.append((hwnd, title))
    return True


def get_all_windows():
    global _results_list
    _results_list = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(WNDENUMPROC(_enum_windows_callback), 0)
    return _results_list


def get_window_hwnd_by_title(title_pattern: str, exclude_patterns=None):
    windows = get_all_windows_by_title(title_pattern, exclude_patterns)
    if windows:
        return windows[0]
    return None, None


def get_all_windows_by_title(title_pattern: str, exclude_patterns=None):
    if exclude_patterns is None:
        exclude_patterns = ['连按工具', 'Visual Studio', 'Trae', 'Code']
    matched_windows = []
    windows = get_all_windows()
    for hwnd, title in windows:
        if re.search(title_pattern, title, re.IGNORECASE):
            excluded = False
            for exclude in exclude_patterns:
                if exclude.lower() in title.lower():
                    excluded = True
                    break
            if not excluded:
                matched_windows.append((hwnd, title))
    return matched_windows


def set_foreground_window(hwnd):
    user32.SetForegroundWindow(hwnd)


def bring_window_to_top(hwnd):
    user32.BringWindowToTop(hwnd)


def is_window_active(hwnd):
    active_hwnd = user32.GetForegroundWindow()
    return active_hwnd == hwnd


def get_window_rect(hwnd):
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top


def get_process_id_from_hwnd(hwnd):
    process_id = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
    return process_id.value


class WindowManager:
    def __init__(self):
        self.target_hwnd = None
        self.target_title = None

    def find_and_lock(self, title_pattern: str):
        hwnd, title = get_window_hwnd_by_title(title_pattern)
        if hwnd:
            self.target_hwnd = hwnd
            self.target_title = title
            return True, title
        return False, None

    def is_target_active(self):
        if self.target_hwnd is None:
            return False
        return is_window_active(self.target_hwnd)

    def activate_target(self):
        if self.target_hwnd:
            set_foreground_window(self.target_hwnd)
            return True
        return False

    def get_target_info(self):
        if self.target_hwnd:
            rect = get_window_rect(self.target_hwnd)
            return {
                'hwnd': self.target_hwnd,
                'title': self.target_title,
                'rect': rect
            }
        return None


# ==================== 键盘输入模块 ====================

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_CHAR = 0x0102

VK_CODES = {
    'A': 0x41, 'B': 0x42, 'C': 0x43, 'D': 0x44, 'E': 0x45,
    'F': 0x46, 'G': 0x47, 'H': 0x48, 'I': 0x49, 'J': 0x4A,
    'K': 0x4B, 'L': 0x4C, 'M': 0x4D, 'N': 0x4E, 'O': 0x4F,
    'P': 0x50, 'Q': 0x51, 'R': 0x52, 'S': 0x53, 'T': 0x54,
    'U': 0x55, 'V': 0x56, 'W': 0x57, 'X': 0x58, 'Y': 0x59,
    'Z': 0x5A,
    '0': 0x30, '1': 0x31, '2': 0x32, '3': 0x33, '4': 0x34,
    '5': 0x35, '6': 0x36, '7': 0x37, '8': 0x38, '9': 0x39,
    'F1': 0x70, 'F2': 0x71, 'F3': 0x72, 'F4': 0x73,
    'F5': 0x74, 'F6': 0x75, 'F7': 0x76, 'F8': 0x77,
    'F9': 0x78, 'F10': 0x79, 'F11': 0x7A, 'F12': 0x7B,
    'SPACE': 0x20, 'ENTER': 0x0D, 'TAB': 0x09,
    'ESC': 0x1B, 'BACKSPACE': 0x08, 'DELETE': 0x2E,
    'INSERT': 0x2D, 'HOME': 0x24, 'END': 0x23,
    'PAGEUP': 0x21, 'PAGEDOWN': 0x22,
    'UP': 0x26, 'DOWN': 0x28, 'LEFT': 0x25, 'RIGHT': 0x27,
    'SHIFT': 0x10, 'CTRL': 0x11, 'ALT': 0x12,
    'LWIN': 0x5B, 'RWIN': 0x5C,
    'NUMPAD0': 0x60, 'NUMPAD1': 0x61, 'NUMPAD2': 0x62,
    'NUMPAD3': 0x63, 'NUMPAD4': 0x64, 'NUMPAD5': 0x65,
    'NUMPAD6': 0x66, 'NUMPAD7': 0x67, 'NUMPAD8': 0x68,
    'NUMPAD9': 0x69,
    'MULTIPLY': 0x6A, 'ADD': 0x6B, 'SUBTRACT': 0x6D,
    'DECIMAL': 0x6E, 'DIVIDE': 0x6F,
    '`': 0xC0, '-': 0xBD, '=': 0xBB, '[': 0xDB, ']': 0xDD,
    '\\': 0xDC, ';': 0xBA, "'": 0xDE, ',': 0xBC, '.': 0xBE, '/': 0xBF,
}


def get_vk_code(key: str) -> int:
    key_upper = key.upper()
    if key_upper in VK_CODES:
        return VK_CODES[key_upper]
    if len(key) == 1:
        vk = user32.VkKeyScanW(ord(key))
        if vk != -1:
            return vk & 0xFF
    raise ValueError(f"未知按键: {key}")


def key_press(hwnd: int, key: str, press_duration: float = 0.05):
    vk_code = get_vk_code(key)
    scan_code = user32.MapVirtualKeyW(vk_code, 0)
    lParam_down = scan_code << 16
    lParam_up = (scan_code << 16) | (1 << 30) | (1 << 31)
    user32.PostMessageW(hwnd, WM_KEYDOWN, vk_code, lParam_down)
    time.sleep(press_duration)
    user32.PostMessageW(hwnd, WM_KEYUP, vk_code, lParam_up)


def switch_to_english_input():
    VK_SHIFT = 0x10
    user32.keybd_event(VK_SHIFT, 0, 0, 0)
    user32.keybd_event(VK_SHIFT, 0, 2, 0)


class AutoKeyPresser:
    def __init__(self):
        self.running = False
        self.thread = None
        self.keys = ['A']
        self.current_key_index = 0
        self.interval = 500
        self.press_duration = 50
        self.window_manager = WindowManager()
        self.debug_callback = None
        self.press_count = 0
        self.auto_switch_input = True
        self.jitter = 50

    def set_debug_callback(self, callback):
        self.debug_callback = callback

    def log(self, message):
        if self.debug_callback:
            self.debug_callback(message)

    def set_keys(self, keys: list):
        validated_keys = []
        for key in keys:
            try:
                get_vk_code(key)
                validated_keys.append(key.upper())
            except ValueError:
                return False, key
        self.keys = validated_keys
        return True, None

    def set_interval(self, interval_ms: int):
        if interval_ms >= 10:
            self.interval = interval_ms
            return True
        return False

    def set_press_duration(self, duration_ms: int):
        if duration_ms >= 10:
            self.press_duration = duration_ms
            return True
        return False

    def set_auto_switch_input(self, enabled: bool):
        self.auto_switch_input = enabled

    def set_jitter(self, jitter_ms: int):
        if jitter_ms >= 0:
            self.jitter = jitter_ms
            return True
        return False

    def _key_loop(self):
        self.press_count = 0
        self.current_key_index = 0
        self.log(f"连按线程已启动，按键序列: {self.keys}")
        if self.auto_switch_input and self.window_manager.target_hwnd:
            self.log("尝试切换到英文输入法...")
            try:
                switch_to_english_input()
                time.sleep(0.1)
            except:
                pass
        while self.running:
            hwnd = self.window_manager.target_hwnd
            if hwnd:
                current_key = self.keys[self.current_key_index]
                self.press_count += 1
                self.log(f"发送按键: {current_key} (第{self.press_count}次，序列位置{self.current_key_index + 1}/{len(self.keys)})")
                try:
                    duration_with_jitter = self.press_duration + random.randint(-self.jitter, self.jitter)
                    duration_with_jitter = max(10, duration_with_jitter)
                    key_press(hwnd, current_key, duration_with_jitter / 1000.0)
                except Exception as e:
                    self.log(f"按键发送失败: {e}")
                self.current_key_index = (self.current_key_index + 1) % len(self.keys)
            else:
                self.log("错误: 未找到目标窗口")
            interval_with_jitter = self.interval + random.randint(-self.jitter, self.jitter)
            interval_with_jitter = max(10, interval_with_jitter)
            time.sleep(interval_with_jitter / 1000.0)
        self.log("连按线程已停止")

    def start(self):
        if self.running:
            return False
        if not self.window_manager.target_hwnd:
            self.log("错误: 未锁定窗口")
            return False
        if not self.keys:
            self.log("错误: 未设置按键序列")
            return False
        self.running = True
        self.thread = threading.Thread(target=self._key_loop, daemon=True)
        self.thread.start()
        return True

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=1.0)
            self.thread = None

    def is_running(self):
        return self.running


# ==================== GUI 模块 ====================

class KeyPresserGUI:
    C = {
        'bg':       '#0f1219',
        'sidebar':  '#151a24',
        'card':     '#1a2029',
        'border':   '#2a3140',
        'input':    '#232b38',
        'input_hl': '#2d3646',
        'fg':       '#e8eaf0',
        'dim':      '#8b91a5',
        'accent':   '#3b8cff',
        'accent_h': '#5aa2ff',
        'success':  '#2fbf71',
        'success_h':'#47d389',
        'danger':   '#e5484d',
        'danger_h': '#f06166',
        'warn':     '#f5a524',
        'log_bg':   '#12161f',
    }
    FONT_FAMILY = 'Microsoft YaHei UI'
    HOTKEY_VK = {
        'F1': 0x70, 'F2': 0x71, 'F3': 0x72, 'F4': 0x73, 'F5': 0x74, 'F6': 0x75,
        'F7': 0x76, 'F8': 0x77, 'F9': 0x78, 'F10': 0x79, 'F11': 0x7A, 'F12': 0x7B,
        'HOME': 0x24, 'END': 0x23, 'INSERT': 0x2D, 'DELETE': 0x2E,
    }
    HOTKEY_CHOICES = ['F6', 'F7', 'F8', 'F9', 'F10', 'F11', 'F12',
                      'HOME', 'END', 'INSERT', 'DELETE']

    def __init__(self):
        ctk.set_appearance_mode('dark')
        self.root = ctk.CTk()
        self.root.title("QQ三国键盘连按工具")
        self.WIN_W, self.WIN_H = 1020, 760
        self.root.geometry(f"{self.WIN_W}x{self.WIN_H}")
        self.root.minsize(960, 700)
        self.root.configure(fg_color=self.C['bg'])

        try:
            icon_path = resource_path(os.path.join('assets', 'app.ico'))
            if os.path.exists(icon_path):
                self.root.iconbitmap(icon_path)
        except Exception:
            pass

        self._setup_treeview_style()

        self.auto_key_presser = AutoKeyPresser()
        self.auto_key_presser.set_debug_callback(self._log_message)

        self.flow_engine = FlowEngine()
        self.flow_engine.set_debug_callback(self._log_message)
        self.flow_steps = []
        self.current_step_index = -1

        self.tray_icon = None
        self.tray_thread = None
        self.is_window_hidden = False

        self._hotkey_name = 'F8'
        self._hotkey_tid = None
        self._hotkey_ready = threading.Event()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._setup_ui()
        self._center_window()
        self._setup_hotkey()

        if TRAY_AVAILABLE:
            self._setup_tray()

    def _font(self, size=13, weight='normal'):
        return ctk.CTkFont(family=self.FONT_FAMILY, size=size, weight=weight)

    def _setup_treeview_style(self):
        """流程步骤列表仍用 ttk.Treeview，配色融入深色主题"""
        C = self.C
        style = ttk.Style(self.root)
        style.theme_use('clam')
        style.configure('Treeview', background=C['input'], fieldbackground=C['input'],
                        foreground=C['fg'], rowheight=30, borderwidth=0,
                        font=(self.FONT_FAMILY, 10))
        style.configure('Treeview.Heading', background=C['sidebar'], foreground=C['dim'],
                        borderwidth=0, relief='flat', padding=(8, 10),
                        font=(self.FONT_FAMILY, 10, 'bold'))
        style.map('Treeview',
                  background=[('selected', C['accent'])],
                  foreground=[('selected', '#ffffff')])
        style.map('Treeview.Heading', background=[('active', C['border'])])
        style.configure('Vertical.TScrollbar', background=C['input'], troughcolor=C['card'],
                        bordercolor=C['card'], arrowcolor=C['dim'],
                        darkcolor=C['card'], lightcolor=C['card'])
        style.map('Vertical.TScrollbar', background=[('active', C['border'])])

    # ==================== 全局快捷键 ====================

    def _setup_hotkey(self):
        t = threading.Thread(target=self._hotkey_loop, daemon=True)
        t.start()
        self._hotkey_ready.wait(timeout=2)

    def _hotkey_loop(self):
        self._hotkey_tid = windll.kernel32.GetCurrentThreadId()
        self._register_hotkey()
        self._hotkey_ready.set()
        msg = wintypes.MSG()
        while windll.user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == 0x0312:  # WM_HOTKEY
                try:
                    self.root.after(0, self._toggle_key_press)
                except Exception:
                    break
            elif msg.message == 0x0400:  # WM_USER: 快捷键已更换，重新注册
                self._register_hotkey()
        self._unregister_hotkey()

    def _register_hotkey(self):
        self._unregister_hotkey()
        vk = self.HOTKEY_VK.get(self._hotkey_name, 0x77)
        if not windll.user32.RegisterHotKey(None, 1, 0x4000, vk):  # MOD_NOREPEAT
            self._log_message(f"警告: 快捷键 {self._hotkey_name} 注册失败，可能被其他程序占用")

    def _unregister_hotkey(self):
        windll.user32.UnregisterHotKey(None, 1)

    def _apply_hotkey(self):
        name = self.hotkey_var.get().upper()
        if name not in self.HOTKEY_VK:
            messagebox.showwarning("警告", f"不支持的快捷键: {name}")
            return
        self._hotkey_name = name
        if self._hotkey_tid:
            windll.user32.PostThreadMessageW(self._hotkey_tid, 0x0400, 0, 0)
        self.hotkey_badge.configure(text=f"快捷键 {name} 开始/停止")
        self._log_message(f"全局快捷键已设置: {name}（开始/停止连按）")

    def _toggle_key_press(self):
        if self.auto_key_presser.is_running():
            self._stop_key_press()
        else:
            self._start_key_press()

    def _create_tray_image(self):
        try:
            tray_png = resource_path(os.path.join('assets', 'tray.png'))
            if os.path.exists(tray_png):
                return Image.open(tray_png)
        except Exception:
            pass
        width = 64
        height = 64
        image = Image.new('RGB', (width, height), color=(66, 133, 244))
        dc = ImageDraw.Draw(image)
        dc.rectangle([16, 16, 48, 48], outline='white', width=3)
        dc.text((24, 20), "K", fill='white')
        return image

    def _setup_tray(self):
        if not TRAY_AVAILABLE:
            return
        def run_tray():
            try:
                menu = pystray.Menu(
                    pystray.MenuItem("显示窗口", self._show_window, default=True),
                    pystray.MenuItem("退出程序", self._exit_from_tray)
                )
                self.tray_icon = pystray.Icon(
                    "QQ三国连按工具",
                    self._create_tray_image(),
                    "QQ三国键盘连按工具",
                    menu
                )
                self.tray_icon.run()
            except Exception as e:
                print(f"托盘启动失败: {e}")
        self.tray_thread = threading.Thread(target=run_tray, daemon=True)
        self.tray_thread.start()
        time.sleep(0.5)

    def _show_window(self, icon=None, item=None):
        self.root.after(0, self._restore_window)

    def _exit_from_tray(self, icon=None, item=None):
        self.root.after(0, self._do_exit)

    def _restore_window(self):
        self.is_window_hidden = False
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        self._log_message("窗口已显示")

    def _hide_to_tray(self):
        self.is_window_hidden = True
        self.root.withdraw()
        self._log_message("窗口已隐藏到系统托盘，点击托盘图标可显示")

    def _center_window(self):
        x = (self.root.winfo_screenwidth() - self.WIN_W) // 2
        y = (self.root.winfo_screenheight() - self.WIN_H) // 2
        self.root.geometry(f'{self.WIN_W}x{self.WIN_H}+{x}+{y}')

    def _toggle_window_visibility(self):
        if self.is_window_hidden:
            self._restore_window()
        else:
            self._hide_to_tray()

    def _on_close(self):
        if TRAY_AVAILABLE and self.tray_icon:
            result = messagebox.askyesnocancel("退出确认", "是否完全退出程序？\n\n选择'否'则隐藏到系统托盘")
            if result is None:
                return
            elif result:
                self._do_exit()
            else:
                self._hide_to_tray()
        else:
            result = messagebox.askyesnocancel("退出确认", "是否退出程序？")
            if result:
                self._do_exit()

    def _do_exit(self):
        if self.auto_key_presser.is_running():
            self.auto_key_presser.stop()
        if self._hotkey_tid:
            windll.user32.PostThreadMessageW(self._hotkey_tid, 0x0012, 0, 0)  # WM_QUIT
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except:
                pass
        self.root.destroy()

    def _exit_application(self):
        self._do_exit()

    def _card(self, parent, title, expand=False):
        C = self.C
        card = ctk.CTkFrame(parent, corner_radius=10, fg_color=C['card'],
                            border_color=C['border'], border_width=1)
        ctk.CTkLabel(card, text=title, font=self._font(13, 'bold'),
                     text_color=C['accent']).pack(anchor='w', padx=14, pady=(10, 4))
        body = ctk.CTkFrame(card, fg_color='transparent')
        body.pack(fill='both' if expand else 'x', expand=expand, padx=14, pady=(0, 12))
        return card, body

    def _show_page(self, name):
        C = self.C
        if name == 'keys':
            self.page_keys.tkraise()
        else:
            self.page_flow.tkraise()
        for btn, active in ((self.nav_keys_btn, name == 'keys'),
                            (self.nav_flow_btn, name == 'flow')):
            if active:
                btn.configure(fg_color=C['accent'], text_color='#ffffff',
                              hover_color=C['accent_h'])
            else:
                btn.configure(fg_color='transparent', text_color=C['dim'],
                              hover_color=C['input_hl'])

    def _setup_ui(self):
        C = self.C
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(0, weight=1)

        # ===== 侧边栏 =====
        self.sidebar = ctk.CTkFrame(self.root, width=200, corner_radius=0,
                                    fg_color=C['sidebar'])
        self.sidebar.grid(row=0, column=0, sticky='nsew')
        self.sidebar.grid_propagate(False)

        ctk.CTkLabel(self.sidebar, text="QQ三国", font=self._font(22, 'bold'),
                     text_color=C['fg']).pack(anchor='w', padx=20, pady=(22, 0))
        ctk.CTkLabel(self.sidebar, text="键盘连按工具", font=self._font(12),
                     text_color=C['dim']).pack(anchor='w', padx=20, pady=(0, 22))

        self.nav_keys_btn = ctk.CTkButton(self.sidebar, text="键盘连按", anchor='w',
                                          height=40, corner_radius=8, font=self._font(),
                                          command=lambda: self._show_page('keys'))
        self.nav_keys_btn.pack(fill='x', padx=12, pady=3)
        self.nav_flow_btn = ctk.CTkButton(self.sidebar, text="流程编辑器", anchor='w',
                                          height=40, corner_radius=8, font=self._font(),
                                          command=lambda: self._show_page('flow'))
        self.nav_flow_btn.pack(fill='x', padx=12, pady=3)

        status_card = ctk.CTkFrame(self.sidebar, corner_radius=10, fg_color=C['card'],
                                   border_color=C['border'], border_width=1)
        status_card.pack(side='bottom', fill='x', padx=12, pady=16)
        ctk.CTkLabel(status_card, text="运行状态", font=self._font(12, 'bold'),
                     text_color=C['dim']).pack(anchor='w', padx=12, pady=(10, 2))
        self.lock_badge = ctk.CTkLabel(status_card, text="● 未锁定窗口",
                                       font=self._font(12), text_color=C['dim'])
        self.lock_badge.pack(anchor='w', padx=12, pady=2)
        self.run_badge = ctk.CTkLabel(status_card, text="● 待机",
                                      font=self._font(12), text_color=C['dim'])
        self.run_badge.pack(anchor='w', padx=12, pady=2)
        self.hotkey_badge = ctk.CTkLabel(status_card,
                                         text=f"快捷键 {self._hotkey_name} 开始/停止",
                                         font=self._font(12), text_color=C['dim'])
        self.hotkey_badge.pack(anchor='w', padx=12, pady=(2, 10))

        # ===== 内容区 =====
        self.content = ctk.CTkFrame(self.root, fg_color='transparent')
        self.content.grid(row=0, column=1, sticky='nsew', padx=16, pady=16)
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_rowconfigure(1, minsize=180)

        self.page_keys = ctk.CTkFrame(self.content, fg_color='transparent')
        self.page_flow = ctk.CTkFrame(self.content, fg_color='transparent')
        for p in (self.page_keys, self.page_flow):
            p.grid(row=0, column=0, sticky='nsew')

        self._build_page_keys()
        self._build_page_flow()

        # ===== 日志卡片（两个页面共享） =====
        log_card, log_body = self._card(self.content, "调试日志")
        log_card.grid(row=1, column=0, sticky='ew', pady=(12, 0))
        self.log_text = ctk.CTkTextbox(log_body, height=120, corner_radius=8,
                                       fg_color=C['log_bg'], border_color=C['border'],
                                       border_width=1, wrap='word',
                                       font=ctk.CTkFont(family='Consolas', size=12),
                                       text_color='#c8cdd8')
        self.log_text.pack(fill='x')
        self._log_tk = self.log_text._textbox
        self._log_tk.tag_configure('time', foreground='#5c6274')
        self._log_tk.tag_configure('info', foreground='#c8cdd8')
        self._log_tk.tag_configure('ok', foreground=C['success'])
        self._log_tk.tag_configure('warn', foreground=C['warn'])
        self._log_tk.tag_configure('error', foreground=C['danger'])
        self.log_text.configure(state='disabled')

        self._show_page('keys')

    def _set_lock_status(self, locked):
        if locked:
            self.lock_badge.configure(text="● 已锁定窗口", text_color=self.C['success'])
        else:
            self.lock_badge.configure(text="● 未锁定窗口", text_color=self.C['dim'])

    def _set_run_status(self, text, color_key=None):
        color = self.C[color_key] if color_key else self.C['dim']
        self.run_badge.configure(text=f"● {text}", text_color=color)

    def _build_page_keys(self):
        C = self.C
        page = self.page_keys
        page.grid_columnconfigure(0, weight=1)

        # ===== 窗口管理 =====
        card, body = self._card(page, "窗口管理")
        card.grid(row=0, column=0, sticky='ew', pady=(0, 12))

        r1 = ctk.CTkFrame(body, fg_color='transparent')
        r1.pack(fill='x', pady=(0, 8))
        ctk.CTkLabel(r1, text="窗口标题", font=self._font(), text_color=C['fg']).pack(side='left', padx=(0, 10))
        self.window_pattern_var = tk.StringVar(value="QQ三国.*线")
        ctk.CTkEntry(r1, textvariable=self.window_pattern_var, width=220, height=32,
                     fg_color=C['input'], border_color=C['border'],
                     text_color=C['fg'], font=self._font()).pack(side='left', padx=(0, 10))
        self.find_btn = ctk.CTkButton(r1, text="查找窗口", width=100, height=32,
                                      fg_color=C['input_hl'], hover_color=C['border'],
                                      font=self._font(), command=self._find_windows)
        self.find_btn.pack(side='left')

        r2 = ctk.CTkFrame(body, fg_color='transparent')
        r2.pack(fill='x')
        ctk.CTkLabel(r2, text="选择窗口", font=self._font(), text_color=C['fg']).pack(side='left', padx=(0, 10))
        self.window_combo_var = tk.StringVar()
        self.window_combo = ctk.CTkComboBox(r2, variable=self.window_combo_var, values=[],
                                            state='readonly', width=380, height=32,
                                            fg_color=C['input'], border_color=C['border'],
                                            button_color=C['input_hl'], button_hover_color=C['border'],
                                            dropdown_fg_color=C['input'], dropdown_text_color=C['fg'],
                                            dropdown_hover_color=C['accent'],
                                            text_color=C['fg'], font=self._font(),
                                            command=self._on_window_selected)
        self.window_combo.pack(side='left', padx=(0, 10))
        self.lock_btn = ctk.CTkButton(r2, text="锁定窗口", width=110, height=32,
                                      fg_color=C['accent'], hover_color=C['accent_h'],
                                      font=self._font(13, 'bold'), command=self._lock_window)
        self.lock_btn.pack(side='right')
        self.found_windows = []

        # ===== 连按设置 =====
        card, body = self._card(page, "连按设置")
        card.grid(row=1, column=0, sticky='ew', pady=(0, 12))

        r = ctk.CTkFrame(body, fg_color='transparent')
        r.pack(fill='x', pady=(0, 8))
        ctk.CTkLabel(r, text="按键序列", font=self._font(), text_color=C['fg']).pack(side='left', padx=(0, 10))
        self.keys_var = tk.StringVar(value="")
        ctk.CTkEntry(r, textvariable=self.keys_var, width=330, height=32,
                     fg_color=C['input'], border_color=C['border'],
                     text_color=C['fg'], font=self._font()).pack(side='left', padx=(0, 10))
        ctk.CTkLabel(r, text="多个按键用逗号分隔", font=self._font(12),
                     text_color=C['dim']).pack(side='left')

        r = ctk.CTkFrame(body, fg_color='transparent')
        r.pack(fill='x', pady=(0, 8))
        self.interval_var = tk.StringVar(value="20")
        self.duration_var = tk.StringVar(value="10")
        self.jitter_var = tk.StringVar(value="10")
        for label, var in (("间隔(ms)", self.interval_var),
                           ("时长(ms)", self.duration_var),
                           ("随机抖动(ms)", self.jitter_var)):
            ctk.CTkLabel(r, text=label, font=self._font(), text_color=C['fg']).pack(side='left', padx=(0, 8))
            ctk.CTkEntry(r, textvariable=var, width=80, height=32, justify='center',
                         fg_color=C['input'], border_color=C['border'],
                         text_color=C['fg'], font=self._font()).pack(side='left', padx=(0, 16))

        r = ctk.CTkFrame(body, fg_color='transparent')
        r.pack(fill='x')
        self.auto_switch_var = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(r, text="自动切换英文输入法", variable=self.auto_switch_var,
                        font=self._font(), text_color=C['fg'],
                        fg_color=C['accent'], hover_color=C['accent_h'],
                        border_color=C['border'], checkmark_color='#ffffff').pack(side='left')

        # ===== 控制 =====
        card, body = self._card(page, "控制")
        card.grid(row=2, column=0, sticky='ew')

        r = ctk.CTkFrame(body, fg_color='transparent')
        r.pack(fill='x', pady=(0, 10))
        self.start_btn = ctk.CTkButton(r, text="开始连按", width=170, height=40, corner_radius=8,
                                       fg_color=C['success'], hover_color=C['success_h'],
                                       font=self._font(14, 'bold'), command=self._start_key_press)
        self.start_btn.pack(side='left', padx=(0, 12))
        self.stop_btn = ctk.CTkButton(r, text="停止连按", width=170, height=40, corner_radius=8,
                                      fg_color=C['danger'], hover_color=C['danger_h'],
                                      font=self._font(14, 'bold'), state='disabled',
                                      command=self._stop_key_press)
        self.stop_btn.pack(side='left')

        r = ctk.CTkFrame(body, fg_color='transparent')
        r.pack(fill='x')
        ctk.CTkLabel(r, text="全局快捷键", font=self._font(), text_color=C['fg']).pack(side='left', padx=(0, 10))
        self.hotkey_var = tk.StringVar(value=self._hotkey_name)
        ctk.CTkComboBox(r, variable=self.hotkey_var, values=self.HOTKEY_CHOICES,
                        state='readonly', width=110, height=32,
                        fg_color=C['input'], border_color=C['border'],
                        button_color=C['input_hl'], button_hover_color=C['border'],
                        dropdown_fg_color=C['input'], dropdown_text_color=C['fg'],
                        dropdown_hover_color=C['accent'],
                        text_color=C['fg'], font=self._font()).pack(side='left', padx=(0, 10))
        ctk.CTkButton(r, text="应用", width=70, height=32,
                      fg_color=C['input_hl'], hover_color=C['border'],
                      font=self._font(), command=self._apply_hotkey).pack(side='left', padx=(0, 12))
        ctk.CTkLabel(r, text="游戏中随时按快捷键开始/停止连按", font=self._font(12),
                     text_color=C['dim']).pack(side='left')

    def _build_page_flow(self):
        C = self.C
        page = self.page_flow
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(2, weight=1)

        # ===== 流程管理 =====
        card, body = self._card(page, "流程管理")
        card.grid(row=0, column=0, sticky='ew', pady=(0, 12))
        btns = ctk.CTkFrame(body, fg_color='transparent')
        btns.pack(fill='x')
        ctk.CTkButton(btns, text="新建流程", width=96, height=30, fg_color=C['input_hl'],
                      hover_color=C['border'], font=self._font(),
                      command=self._new_flow).pack(side='left', padx=(0, 8))
        ctk.CTkButton(btns, text="打开流程", width=96, height=30, fg_color=C['input_hl'],
                      hover_color=C['border'], font=self._font(),
                      command=self._load_flow).pack(side='left', padx=(0, 8))
        ctk.CTkButton(btns, text="保存流程", width=96, height=30, fg_color=C['accent'],
                      hover_color=C['accent_h'], font=self._font(13, 'bold'),
                      command=self._save_flow).pack(side='left', padx=(0, 8))
        ctk.CTkButton(btns, text="清空流程", width=96, height=30, fg_color=C['input_hl'],
                      hover_color=C['border'], font=self._font(),
                      command=self._clear_flow).pack(side='left')

        # ===== 添加步骤 =====
        card, body = self._card(page, "添加步骤")
        card.grid(row=1, column=0, sticky='ew', pady=(0, 12))
        grid_f = ctk.CTkFrame(body, fg_color='transparent')
        grid_f.pack(fill='x')
        step_buttons = [
            ("图像点击", FlowStep.TYPE_IMAGE_CLICK), ("图像判断", FlowStep.TYPE_IMAGE_CHECK),
            ("键盘按键", FlowStep.TYPE_KEYBOARD), ("鼠标移动", FlowStep.TYPE_MOUSE_MOVE),
            ("延迟", FlowStep.TYPE_DELAY),
            ("循环开始", FlowStep.TYPE_LOOP_START), ("循环结束", FlowStep.TYPE_LOOP_END),
            ("条件判断", FlowStep.TYPE_CONDITION), ("多分支", FlowStep.TYPE_BRANCH),
        ]
        for i, (text, st) in enumerate(step_buttons):
            row, col = divmod(i, 5)
            ctk.CTkButton(grid_f, text=text, width=104, height=30,
                          fg_color=C['input_hl'], hover_color=C['border'],
                          font=self._font(12),
                          command=lambda t=st: self._add_step(t)).grid(
                row=row, column=col, padx=(0, 8), pady=(0, 8), sticky='w')

        # ===== 流程步骤 =====
        card, body = self._card(page, "流程步骤（双击编辑）", expand=True)
        card.grid(row=2, column=0, sticky='nsew', pady=(0, 12))

        tree_wrap = ctk.CTkFrame(body, fg_color='transparent')
        tree_wrap.pack(fill='both', expand=True)
        columns = ('序号', '类型', '描述', '状态')
        self.step_tree = ttk.Treeview(tree_wrap, columns=columns, show='headings', height=8)
        widths = {'序号': (50, 'center'), '类型': (110, 'center'), '描述': (420, 'w'), '状态': (70, 'center')}
        for col in columns:
            self.step_tree.heading(col, text=col)
            w, anchor = widths[col]
            self.step_tree.column(col, width=w, anchor=anchor)
        self.step_tree.tag_configure('odd', background=C['input_hl'])
        self.step_tree.tag_configure('disabled', foreground=C['dim'])
        self.step_tree.pack(side='left', fill='both', expand=True)
        scrollbar = ttk.Scrollbar(tree_wrap, orient='vertical', command=self.step_tree.yview)
        scrollbar.pack(side='right', fill='y')
        self.step_tree.configure(yscrollcommand=scrollbar.set)
        self.step_tree.bind('<Double-1>', self._edit_step)

        op = ctk.CTkFrame(body, fg_color='transparent')
        op.pack(fill='x', pady=(8, 0))
        for text, cmd in (("上移", self._move_step_up), ("下移", self._move_step_down),
                          ("编辑", self._edit_selected_step), ("删除", self._delete_step),
                          ("启用/禁用", self._toggle_step_enabled)):
            ctk.CTkButton(op, text=text, width=84, height=30, fg_color=C['input_hl'],
                          hover_color=C['border'], font=self._font(12),
                          command=cmd).pack(side='left', padx=(0, 8))

        # ===== 流程控制 =====
        card, body = self._card(page, "流程控制")
        card.grid(row=3, column=0, sticky='ew')
        r = ctk.CTkFrame(body, fg_color='transparent')
        r.pack(fill='x')
        self.flow_start_btn = ctk.CTkButton(r, text="执行流程", width=140, height=36,
                                            corner_radius=8, fg_color=C['success'],
                                            hover_color=C['success_h'],
                                            font=self._font(13, 'bold'), command=self._start_flow)
        self.flow_start_btn.pack(side='left', padx=(0, 10))
        self.flow_stop_btn = ctk.CTkButton(r, text="停止流程", width=140, height=36,
                                           corner_radius=8, fg_color=C['danger'],
                                           hover_color=C['danger_h'],
                                           font=self._font(13, 'bold'), state='disabled',
                                           command=self._stop_flow)
        self.flow_stop_btn.pack(side='left', padx=(0, 24))
        ctk.CTkLabel(r, text="默认置信度", font=self._font(), text_color=C['fg']).pack(side='left', padx=(0, 8))
        self.flow_confidence_var = tk.StringVar(value="0.8")
        ctk.CTkEntry(r, textvariable=self.flow_confidence_var, width=70, height=30,
                     justify='center', fg_color=C['input'], border_color=C['border'],
                     text_color=C['fg'], font=self._font()).pack(side='left', padx=(0, 20))
        ctk.CTkLabel(r, text="循环次数", font=self._font(), text_color=C['fg']).pack(side='left', padx=(0, 8))
        self.flow_loop_count_var = tk.StringVar(value="1")
        ctk.CTkEntry(r, textvariable=self.flow_loop_count_var, width=70, height=30,
                     justify='center', fg_color=C['input'], border_color=C['border'],
                     text_color=C['fg'], font=self._font()).pack(side='left')

    def _log_message(self, message):
        def update():
            if any(k in message for k in ('错误', '失败', '异常', '未找到')):
                tag = 'error'
            elif '警告' in message:
                tag = 'warn'
            elif any(k in message for k in ('已锁定', '已加载', '已保存', '成功', '开始执行', '找到图像', '已点击')):
                tag = 'ok'
            else:
                tag = 'info'
            self.log_text.configure(state='normal')
            self._log_tk.insert(tk.END, time.strftime('%H:%M:%S'), 'time')
            self._log_tk.insert(tk.END, f"  {message}\n", tag)
            self._log_tk.see(tk.END)
            self.log_text.configure(state='disabled')
        self.root.after(0, update)

    def _find_windows(self):
        pattern = self.window_pattern_var.get()
        if not pattern:
            messagebox.showwarning("警告", "请输入窗口标题模式!")
            return
        self.found_windows = get_all_windows_by_title(pattern)
        if not self.found_windows:
            messagebox.showwarning("警告", f"未找到匹配'{pattern}'的窗口!\n请确保游戏已启动。")
            self.window_combo.configure(values=[])
            self.window_combo_var.set("")
            return
        window_titles = [title for _, title in self.found_windows]
        self.window_combo.configure(values=window_titles)
        if len(self.found_windows) == 1:
            self.window_combo_var.set(window_titles[0])
            self._log_message(f"找到 1 个窗口，自动锁定: {window_titles[0]}")
            self._lock_window()
        else:
            self.window_combo_var.set(f"请选择窗口 (找到 {len(self.found_windows)} 个)")
            self._log_message(f"找到 {len(self.found_windows)} 个窗口，请选择一个后点击锁定")

    def _on_window_selected(self, event=None):
        selected_title = self.window_combo_var.get()
        if selected_title and not selected_title.startswith("请选择"):
            self._log_message(f"已选择窗口: {selected_title}")

    def _lock_window(self):
        selected_title = self.window_combo_var.get()
        if not selected_title or selected_title.startswith("请选择"):
            messagebox.showwarning("警告", "请先查找并选择一个窗口!")
            return
        hwnd = None
        for h, title in self.found_windows:
            if title == selected_title:
                hwnd = h
                break
        if hwnd:
            self.auto_key_presser.window_manager.target_hwnd = hwnd
            self.auto_key_presser.window_manager.target_title = selected_title
            self.flow_engine.target_hwnd = hwnd
            self.lock_btn.configure(text="解锁窗口", command=self._unlock_window)
            self.find_btn.configure(state='disabled')
            self.window_combo.configure(state='disabled')
            self._set_lock_status(True)
            self._log_message(f"已锁定窗口: {selected_title}")
        else:
            messagebox.showerror("错误", "无法锁定窗口，请重新查找")

    def _unlock_window(self):
        self.auto_key_presser.window_manager.target_hwnd = None
        self.auto_key_presser.window_manager.target_title = None
        self.flow_engine.target_hwnd = None
        self.lock_btn.configure(text="锁定窗口", command=self._lock_window)
        self.find_btn.configure(state='normal')
        self.window_combo.configure(state='readonly')
        self._set_lock_status(False)
        self._log_message("已解锁窗口")

    def _parse_keys(self, keys_str: str) -> list:
        if not keys_str.strip():
            return []
        keys = re.split(r'[,;\s]+', keys_str.strip())
        return [k for k in keys if k]

    def _start_key_press(self):
        if self.auto_key_presser.is_running():
            return
        if not self.auto_key_presser.window_manager.target_hwnd:
            messagebox.showwarning("警告", "请先锁定游戏窗口!")
            return
        try:
            keys_str = self.keys_var.get()
            keys = self._parse_keys(keys_str)
            if not keys:
                messagebox.showerror("错误", "请输入至少一个按键!")
                return
            success, invalid_key = self.auto_key_presser.set_keys(keys)
            if not success:
                messagebox.showerror("错误", f"无效的按键: {invalid_key}")
                return
            interval = int(self.interval_var.get())
            duration = int(self.duration_var.get())
            auto_switch = self.auto_switch_var.get()
            jitter = int(self.jitter_var.get())
            if not self.auto_key_presser.set_interval(interval):
                messagebox.showerror("错误", "按键间隔必须 >= 10ms")
                return
            if not self.auto_key_presser.set_press_duration(duration):
                messagebox.showerror("错误", "按键时长必须 >= 10ms")
                return
            self.auto_key_presser.set_auto_switch_input(auto_switch)
            self.auto_key_presser.set_jitter(jitter)
            self._log_message(f"准备启动: 按键序列={keys}, 间隔={interval}ms, 时长={duration}ms, 抖动={jitter}ms")
            if self.auto_key_presser.start():
                self.start_btn.configure(state='disabled')
                self.stop_btn.configure(state='normal')
                self._set_run_status("连按中", 'success')
            else:
                messagebox.showerror("错误", "启动失败!")
        except ValueError as e:
            messagebox.showerror("错误", f"参数错误: {e}")

    def _stop_key_press(self):
        self.auto_key_presser.stop()
        self.start_btn.configure(state='normal')
        self.stop_btn.configure(state='disabled')
        self._set_run_status("待机")

    def _new_flow(self):
        if self.flow_steps:
            result = messagebox.askyesnocancel("确认", "当前流程未保存，是否继续？")
            if result is None or not result:
                return
        self.flow_steps = []
        self._refresh_step_list()
        self._log_message("已新建流程")

    def _load_flow(self):
        filepath = filedialog.askopenfilename(
            title="选择流程文件",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        if filepath:
            success, error = self.flow_engine.load_flow_from_file(filepath)
            if success:
                self.flow_steps = self.flow_engine.steps
                self._refresh_step_list()
                self._log_message(f"已加载流程: {filepath}")
            else:
                messagebox.showerror("错误", f"加载流程失败: {error}")

    def _save_flow(self):
        if not self.flow_steps:
            messagebox.showwarning("警告", "流程为空，无法保存")
            return
        filepath = filedialog.asksaveasfilename(
            title="保存流程文件",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        if filepath:
            self.flow_engine.set_steps(self.flow_steps)
            success, error = self.flow_engine.save_flow_to_file(filepath)
            if success:
                self._log_message(f"流程已保存: {filepath}")
                messagebox.showinfo("成功", "流程已保存")
            else:
                messagebox.showerror("错误", f"保存失败: {error}")

    def _clear_flow(self):
        result = messagebox.askyesno("确认", "是否清空当前流程？")
        if result:
            self.flow_steps = []
            self._refresh_step_list()
            self._log_message("流程已清空")

    def _add_step(self, step_type):
        step = FlowStep(step_type)
        if step_type == FlowStep.TYPE_IMAGE_CLICK:
            step.params = {
                'template_path': '', 'button': 'left', 'clicks': 1,
                'confidence': 0.8, 'delay_before': 0, 'delay_after': 0.5,
                'on_fail': 'continue'
            }
        elif step_type == FlowStep.TYPE_IMAGE_CHECK:
            step.params = {
                'template_path': '', 'confidence': 0.8, 'condition': 'exists',
                'if_true_goto': None, 'if_false_goto': None
            }
        elif step_type == FlowStep.TYPE_KEYBOARD:
            step.params = {
                'key': 'A', 'press_count': 1, 'press_duration': 50, 'interval': 100
            }
        elif step_type == FlowStep.TYPE_MOUSE_MOVE:
            step.params = {'x': 0, 'y': 0, 'duration': 0.2}
        elif step_type == FlowStep.TYPE_DELAY:
            step.params = {'duration': 1.0}
        elif step_type == FlowStep.TYPE_LOOP_START:
            step.params = {
                'loop_count': 1, 'loop_until_image': '',
                'loop_until_image_confidence': 0.8
            }
        elif step_type == FlowStep.TYPE_LOOP_END:
            step.params = {}
        elif step_type == FlowStep.TYPE_CONDITION:
            step.params = {
                'condition_type': 'image_exists', 'template_path': '',
                'confidence': 0.8, 'true_steps': [], 'false_steps': []
            }
        elif step_type == FlowStep.TYPE_BRANCH:
            step.params = {'branches': [], 'default_steps': []}

        self.flow_steps.append(step)
        self._refresh_step_list()
        self._log_message(f"已添加步骤: {self._get_step_type_name(step_type)}")
        self._edit_step_dialog(len(self.flow_steps) - 1)

    def _get_step_type_name(self, step_type):
        names = {
            FlowStep.TYPE_IMAGE_CLICK: "图像点击",
            FlowStep.TYPE_IMAGE_CHECK: "图像判断",
            FlowStep.TYPE_KEYBOARD: "键盘按键",
            FlowStep.TYPE_MOUSE_MOVE: "鼠标移动",
            FlowStep.TYPE_DELAY: "延迟",
            FlowStep.TYPE_LOOP_START: "循环开始",
            FlowStep.TYPE_LOOP_END: "循环结束",
            FlowStep.TYPE_CONDITION: "条件判断",
            FlowStep.TYPE_BRANCH: "多分支"
        }
        return names.get(step_type, step_type)

    def _refresh_step_list(self):
        for item in self.step_tree.get_children():
            self.step_tree.delete(item)
        for i, step in enumerate(self.flow_steps):
            type_name = self._get_step_type_name(step.step_type)
            desc = self._get_step_description(step)
            status = "启用" if step.enabled else "禁用"
            tags = []
            if i % 2 == 1:
                tags.append('odd')
            if not step.enabled:
                tags.append('disabled')
            self.step_tree.insert('', 'end', values=(i + 1, type_name, desc, status), tags=tags)

    def _get_step_description(self, step):
        params = step.params
        if step.step_type == FlowStep.TYPE_IMAGE_CLICK:
            path = params.get('template_path', '')
            filename = os.path.basename(path) if path else '未设置'
            return f"点击图像: {filename}"
        elif step.step_type == FlowStep.TYPE_IMAGE_CHECK:
            path = params.get('template_path', '')
            filename = os.path.basename(path) if path else '未设置'
            condition = params.get('condition', 'exists')
            return f"判断图像{'存在' if condition == 'exists' else '不存在'}: {filename}"
        elif step.step_type == FlowStep.TYPE_KEYBOARD:
            key = params.get('key', '')
            count = params.get('press_count', 1)
            return f"按键: {key} ({count}次)"
        elif step.step_type == FlowStep.TYPE_MOUSE_MOVE:
            x = params.get('x', 0)
            y = params.get('y', 0)
            return f"移动到: ({x}, {y})"
        elif step.step_type == FlowStep.TYPE_DELAY:
            duration = params.get('duration', 0)
            return f"等待: {duration}秒"
        elif step.step_type == FlowStep.TYPE_LOOP_START:
            count = params.get('loop_count', 1)
            until_image = params.get('loop_until_image', '')
            if until_image:
                return f"循环直到图像: {os.path.basename(until_image)}"
            return f"循环: {count}次"
        elif step.step_type == FlowStep.TYPE_LOOP_END:
            return "循环结束"
        elif step.step_type == FlowStep.TYPE_CONDITION:
            path = params.get('template_path', '')
            filename = os.path.basename(path) if path else '未设置'
            return f"条件判断: {filename}"
        elif step.step_type == FlowStep.TYPE_BRANCH:
            branches = params.get('branches', [])
            return f"多分支: {len(branches)}个分支"
        return ""

    def _edit_step(self, event):
        selection = self.step_tree.selection()
        if selection:
            item = selection[0]
            index = self.step_tree.index(item)
            self._edit_step_dialog(index)

    def _edit_selected_step(self):
        selection = self.step_tree.selection()
        if selection:
            item = selection[0]
            index = self.step_tree.index(item)
            self._edit_step_dialog(index)
        else:
            messagebox.showwarning("警告", "请先选择要编辑的步骤")

    def _edit_step_dialog(self, index):
        if index < 0 or index >= len(self.flow_steps):
            return
        C = self.C
        step = self.flow_steps[index]
        dialog = ctk.CTkToplevel(self.root)
        dialog.title(f"编辑步骤 - {self._get_step_type_name(step.step_type)}")
        dialog.resizable(False, False)
        dialog.configure(fg_color=C['bg'])
        dialog.transient(self.root)

        self._dialog_vars = []

        form_frame = ctk.CTkFrame(dialog, corner_radius=10, fg_color=C['card'],
                                  border_color=C['border'], border_width=1)
        form_frame.pack(fill='both', expand=True, padx=14, pady=(14, 0))
        row = 0

        if step.step_type == FlowStep.TYPE_IMAGE_CLICK:
            self._add_entry(form_frame, row, "模板图像:", step.params, 'template_path', is_file=True); row += 1
            self._add_combo(form_frame, row, step.params, 'button', ['left', 'right', 'middle'], label="鼠标按钮:"); row += 1
            self._add_entry(form_frame, row, "点击次数:", step.params, 'clicks', kind='int'); row += 1
            self._add_entry(form_frame, row, "置信度:", step.params, 'confidence', kind='float'); row += 1
            self._add_entry(form_frame, row, "前置延迟(秒):", step.params, 'delay_before', kind='float'); row += 1
            self._add_entry(form_frame, row, "后置延迟(秒):", step.params, 'delay_after', kind='float'); row += 1
            self._add_combo(form_frame, row, step.params, 'on_fail', ['continue', 'break'], label="失败时:")
        elif step.step_type == FlowStep.TYPE_IMAGE_CHECK:
            self._add_entry(form_frame, row, "模板图像:", step.params, 'template_path', is_file=True); row += 1
            self._add_entry(form_frame, row, "置信度:", step.params, 'confidence', kind='float'); row += 1
            self._add_combo(form_frame, row, step.params, 'condition', ['exists', 'not_exists'], label="条件:"); row += 1
            self._add_entry(form_frame, row, "真时跳转索引:", step.params, 'if_true_goto', kind='int_or_none'); row += 1
            self._add_entry(form_frame, row, "假时跳转索引:", step.params, 'if_false_goto', kind='int_or_none')
        elif step.step_type == FlowStep.TYPE_KEYBOARD:
            self._add_entry(form_frame, row, "按键:", step.params, 'key'); row += 1
            self._add_entry(form_frame, row, "按键次数:", step.params, 'press_count', kind='int'); row += 1
            self._add_entry(form_frame, row, "按键时长(ms):", step.params, 'press_duration', kind='int'); row += 1
            self._add_entry(form_frame, row, "按键间隔(ms):", step.params, 'interval', kind='int')
        elif step.step_type == FlowStep.TYPE_MOUSE_MOVE:
            self._add_entry(form_frame, row, "X坐标:", step.params, 'x', kind='int'); row += 1
            self._add_entry(form_frame, row, "Y坐标:", step.params, 'y', kind='int'); row += 1
            self._add_entry(form_frame, row, "移动时长(秒):", step.params, 'duration', kind='float')
        elif step.step_type == FlowStep.TYPE_DELAY:
            self._add_entry(form_frame, row, "延迟时长(秒):", step.params, 'duration', kind='float')
        elif step.step_type == FlowStep.TYPE_LOOP_START:
            self._add_entry(form_frame, row, "循环次数(0=无限):", step.params, 'loop_count', kind='int'); row += 1
            self._add_entry(form_frame, row, "循环直到图像:", step.params, 'loop_until_image', is_file=True); row += 1
            self._add_entry(form_frame, row, "图像置信度:", step.params, 'loop_until_image_confidence', kind='float')
        elif step.step_type == FlowStep.TYPE_LOOP_END:
            ctk.CTkLabel(form_frame, text="循环结束标记，无需配置", font=self._font(),
                         text_color=C['dim']).grid(row=0, column=0, columnspan=3, pady=16)
        elif step.step_type == FlowStep.TYPE_CONDITION:
            self._add_entry(form_frame, row, "模板图像:", step.params, 'template_path', is_file=True); row += 1
            self._add_combo(form_frame, row, step.params, 'condition_type', ['image_exists', 'image_not_exists'], label="条件类型:"); row += 1
            self._add_entry(form_frame, row, "置信度:", step.params, 'confidence', kind='float'); row += 1
            ctk.CTkLabel(form_frame, text="真/假分支需在高级编辑器中配置", font=self._font(12),
                         text_color=C['dim']).grid(row=row, column=0, columnspan=3, sticky='w', padx=14, pady=6)
        elif step.step_type == FlowStep.TYPE_BRANCH:
            ctk.CTkLabel(form_frame, text="多分支需在高级编辑器中配置", font=self._font(),
                         text_color=C['dim']).grid(row=0, column=0, columnspan=3, pady=16)

        btn_frame = ctk.CTkFrame(dialog, fg_color='transparent')
        btn_frame.pack(fill='x', padx=14, pady=14)

        def on_ok():
            for key, var, kind in self._dialog_vars:
                raw = var.get().strip()
                try:
                    if kind == 'int':
                        step.params[key] = int(raw)
                    elif kind == 'float':
                        step.params[key] = float(raw)
                    elif kind == 'int_or_none':
                        step.params[key] = int(raw) if raw else None
                    else:
                        step.params[key] = raw
                except ValueError:
                    pass
            dialog.destroy()
            self._refresh_step_list()
            self._log_message(f"已更新步骤: {self._get_step_type_name(step.step_type)}")

        ctk.CTkButton(btn_frame, text="确定", command=on_ok, width=110, height=34,
                      fg_color=C['accent'], hover_color=C['accent_h'],
                      font=self._font(13, 'bold')).pack(side='left', padx=(0, 10))
        ctk.CTkButton(btn_frame, text="取消", command=dialog.destroy, width=110, height=34,
                      fg_color=C['input_hl'], hover_color=C['border'],
                      font=self._font()).pack(side='left')

        dialog.update_idletasks()
        w = max(540, dialog.winfo_reqwidth())
        h = dialog.winfo_reqheight()
        x = (dialog.winfo_screenwidth() - w) // 2
        y = (dialog.winfo_screenheight() - h) // 2
        dialog.geometry(f"{w}x{h}+{x}+{y}")
        dialog.after(200, dialog.grab_set)

    def _add_entry(self, parent, row, label, params, key, is_file=False, kind='str'):
        C = self.C
        ctk.CTkLabel(parent, text=label, font=self._font(),
                     text_color=C['fg']).grid(row=row, column=0, sticky='w', padx=(14, 10), pady=6)
        var = tk.StringVar(value='' if params.get(key) is None else str(params.get(key, '')))
        entry = ctk.CTkEntry(parent, textvariable=var, width=250, height=30,
                             fg_color=C['input'], border_color=C['border'],
                             text_color=C['fg'], font=self._font())
        entry.grid(row=row, column=1, sticky='w', pady=6)
        self._dialog_vars.append((key, var, kind))
        if is_file:
            def browse():
                filepath = filedialog.askopenfilename(
                    title="选择图像文件",
                    filetypes=[("Image files", "*.png *.jpg *.jpeg *.bmp"), ("All files", "*.*")]
                )
                if filepath:
                    var.set(filepath)
            ctk.CTkButton(parent, text="浏览", command=browse, width=64, height=30,
                          fg_color=C['input_hl'], hover_color=C['border'],
                          font=self._font(12)).grid(row=row, column=2, padx=(8, 0))

    def _add_combo(self, parent, row, params, key, values, label=""):
        C = self.C
        ctk.CTkLabel(parent, text=label, font=self._font(),
                     text_color=C['fg']).grid(row=row, column=0, sticky='w', padx=(14, 10), pady=6)
        var = tk.StringVar(value=str(params.get(key, values[0])))
        combo = ctk.CTkComboBox(parent, variable=var, values=values, state='readonly',
                                width=248, height=30,
                                fg_color=C['input'], border_color=C['border'],
                                button_color=C['input_hl'], button_hover_color=C['border'],
                                dropdown_fg_color=C['input'], dropdown_text_color=C['fg'],
                                dropdown_hover_color=C['accent'],
                                text_color=C['fg'], font=self._font())
        combo.grid(row=row, column=1, sticky='w', pady=6)
        self._dialog_vars.append((key, var, 'str'))

    def _move_step_up(self):
        selection = self.step_tree.selection()
        if selection:
            item = selection[0]
            index = self.step_tree.index(item)
            if index > 0:
                self.flow_steps[index], self.flow_steps[index - 1] = self.flow_steps[index - 1], self.flow_steps[index]
                self._refresh_step_list()
                self.step_tree.selection_set(self.step_tree.get_children()[index - 1])

    def _move_step_down(self):
        selection = self.step_tree.selection()
        if selection:
            item = selection[0]
            index = self.step_tree.index(item)
            if index < len(self.flow_steps) - 1:
                self.flow_steps[index], self.flow_steps[index + 1] = self.flow_steps[index + 1], self.flow_steps[index]
                self._refresh_step_list()
                self.step_tree.selection_set(self.step_tree.get_children()[index + 1])

    def _delete_step(self):
        selection = self.step_tree.selection()
        if selection:
            item = selection[0]
            index = self.step_tree.index(item)
            result = messagebox.askyesno("确认", f"是否删除步骤 {index + 1}？")
            if result:
                self.flow_steps.pop(index)
                self._refresh_step_list()
                self._log_message(f"已删除步骤 {index + 1}")

    def _toggle_step_enabled(self):
        selection = self.step_tree.selection()
        if selection:
            item = selection[0]
            index = self.step_tree.index(item)
            self.flow_steps[index].enabled = not self.flow_steps[index].enabled
            self._refresh_step_list()
            status = "启用" if self.flow_steps[index].enabled else "禁用"
            self._log_message(f"步骤 {index + 1} 已{status}")

    def _start_flow(self):
        if self.flow_engine.is_running():
            return
        if not self.flow_steps:
            messagebox.showwarning("警告", "流程为空，请先添加步骤!")
            return
        try:
            confidence = float(self.flow_confidence_var.get())
            loop_count = int(self.flow_loop_count_var.get())
        except ValueError:
            messagebox.showerror("错误", "参数格式错误")
            return
        self.flow_engine = FlowEngine(confidence_threshold=confidence)
        self.flow_engine.set_debug_callback(self._log_message)
        self.flow_engine.set_steps(self.flow_steps)
        if self.auto_key_presser.window_manager.target_hwnd:
            self.flow_engine.target_hwnd = self.auto_key_presser.window_manager.target_hwnd
        if self.flow_engine.start(loop_count=loop_count):
            self.flow_start_btn.configure(state='disabled')
            self.flow_stop_btn.configure(state='normal')
            self._set_run_status("流程执行中", 'accent')
            self._log_message(f"流程开始执行，循环次数: {loop_count if loop_count > 0 else '无限'}")
            self._poll_flow_status()
        else:
            messagebox.showerror("错误", "流程启动失败!")

    def _poll_flow_status(self):
        if self.flow_engine.is_running():
            self.root.after(500, self._poll_flow_status)
        else:
            self.flow_start_btn.configure(state='normal')
            self.flow_stop_btn.configure(state='disabled')
            self._set_run_status("待机")

    def _stop_flow(self):
        self.flow_engine.stop()
        self.flow_start_btn.configure(state='normal')
        self.flow_stop_btn.configure(state='disabled')
        self._set_run_status("待机")
        self._log_message("流程已停止")

    def run(self):
        self.root.mainloop()


def _is_admin():
    try:
        return bool(windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _relaunch_as_admin():
    """以管理员权限重启当前脚本；返回 True 表示新进程已启动，当前进程应退出"""
    try:
        script = os.path.abspath(sys.argv[0])
        ret = windll.shell32.ShellExecuteW(None, 'runas', sys.executable,
                                           f'"{script}" --no-admin', None, 1)
        return ret > 32
    except Exception:
        return False


if __name__ == "__main__":
    if "--no-admin" not in sys.argv and not _is_admin():
        if _relaunch_as_admin():
            sys.exit()
    app = KeyPresserGUI()
    app.run()