#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sip_route_final_merged_8_and_6_v3.py

Phiên bản hoàn chỉnh:
- Giao diện (UI) từ file (8).
- Logic SSH cốt lõi từ file (6) (đã được xác nhận chạy ổn).
- Cluster Fix (logout;) từ file (8).
- MessageBox Fix (tự động khôi phục)
- SỬA LỖI QUAN TRỌNG: Fix lỗi 'race condition' của log (phun log sai chỗ)
  bằng cách truyền 'node_name' tường minh và xóa fallback 'self.current_node'.
"""
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
import sys
import tkinter as tk
from tkinter import scrolledtext, messagebox, Toplevel, Entry, Button, Menu
from tkinter import font as tkFont
import paramiko
import time
import threading
import json
import os
import socket
import re
from tkinter import ttk # Thêm dòng này
import logging
from datetime import datetime
import ttkbootstrap as ttk # Dùng ttkbootstrap thay cho ttk chuẩn
from ttkbootstrap.constants import * # Import các hằng số style (SUCCESS, DANGER...)

class A2PBlockerTab:
    def __init__(self, parent_notebook, app_instance):
        self.app = app_instance 
        self.frame = ttk.Frame(parent_notebook, padding=10)
        parent_notebook.add(self.frame, text=" 🛡️ Chặn A2P (TSSN2D) ")
        
        self.HISTORY_FILE = "a2p_history.json"
        self.local_history = self._load_history()
        self.is_running = False 
        
        self.bold_font = ("Segoe UI", 10, "bold")
        self.del_placeholder = "# Chọn số bên trái -> Chuột phải -> Đưa vào đây\n# Hoặc dán thủ công mỗi dòng 1 số"
        
        self._setup_ui()
        
    def _setup_ui(self):
        style = ttk.Style()
        style.configure("Bold.Treeview.Heading", font=('Segoe UI', 10, 'bold'))
        style.configure("Bold.Treeview", font=('Segoe UI', 10))

        paned = ttk.Panedwindow(self.frame, orient=HORIZONTAL)
        paned.pack(fill=BOTH, expand=True)
        
        # --- CỘT TRÁI ---
        self.left_frame = ttk.Labelframe(paned, text=" ⚠️ Dữ liệu cũ (Cache) - Cần cập nhật ", padding=5, bootstyle="warning")
        paned.add(self.left_frame, weight=1) 
        
        btn_refresh = ttk.Button(self.left_frame, text="1. Quét toàn bộ số ĐANG CHẶN trên Node", command=self.fetch_current_data, bootstyle="info")
        btn_refresh.pack(side=TOP, fill=X, pady=(0, 5))

        search_frame = ttk.Frame(self.left_frame)
        search_frame.pack(side=TOP, fill=X, pady=(0, 5))
        
        ttk.Label(search_frame, text="🔍 Tìm nhanh:").pack(side=LEFT)
        self.entry_search = ttk.Entry(search_frame)
        self.entry_search.pack(side=LEFT, fill=X, expand=True, padx=5)
        self.entry_search.bind("<KeyRelease>", self.on_search_change) 
        
        cols = ("sdt", "time")
        self.tree = ttk.Treeview(self.left_frame, columns=cols, show="headings", height=15, style="Bold.Treeview")
        self.tree.heading("sdt", text="Số điện thoại", anchor="center")
        self.tree.heading("time", text="Ngày chặn (Log)", anchor="center")
        self.tree.column("sdt", width=150, anchor="center")
        self.tree.column("time", width=200, anchor="center")
        
        # [MỚI] Cấu hình màu sắc cho các dòng trong bảng
        # 1. Số vừa mới thêm: Màu Xanh Dương Đậm + In Đậm
        self.tree.tag_configure("new_row", foreground="#0056b3", font=("Segoe UI", 10, "bold"))
        # 2. Số Unknown: Màu Xám (để đỡ rối mắt)
        self.tree.tag_configure("unknown_row", foreground="#6c757d")
        # 3. Số Bình thường (Có ngày giờ cũ): Màu Đen
        self.tree.tag_configure("known_row", foreground="#000000")

        scroll = ttk.Scrollbar(self.left_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side=LEFT, fill=BOTH, expand=True)
        scroll.pack(side=RIGHT, fill=Y)

        self.tree.bind("<Button-3>", self.show_context_menu)

        # --- CỘT PHẢI ---
        right_frame = ttk.Labelframe(paned, text=" ⚙️ Tác vụ Chặn/Gỡ ", padding=10)
        paned.add(right_frame, weight=1)
        
        lbl_add = ttk.Label(right_frame, text="Nhập số cần CHẶN THÊM (Mỗi dòng 1 số):", font=self.bold_font)
        lbl_add.pack(anchor="w")
        
        self.txt_new_block = scrolledtext.ScrolledText(right_frame, height=15, width=30)
        self.txt_new_block.pack(fill=X, pady=5)
        
        lbl_del = ttk.Label(right_frame, text="Nhập số cần GỠ CHẶN:", font=self.bold_font)
        lbl_del.pack(anchor="w")
        self.txt_priority_del = scrolledtext.ScrolledText(right_frame, height=5, width=30)
        self.txt_priority_del.pack(fill=X, pady=5)
        
        self.txt_priority_del.insert("1.0", self.del_placeholder)
        self.txt_priority_del.config(foreground="grey")
        self.txt_priority_del.bind("<FocusIn>", self._on_focus_in_del)
        self.txt_priority_del.bind("<FocusOut>", self._on_focus_out_del)
        
        self.lbl_analysis = ttk.Label(right_frame, text="Trạng thái: Sẵn sàng", foreground="blue", font=self.bold_font)
        self.lbl_analysis.pack(pady=10)
        
        btn_analyze = ttk.Button(right_frame, text="2. Phân tích & Tạo lệnh", command=self.analyze_and_generate, bootstyle="warning")
        btn_analyze.pack(fill=X, pady=2)
        
        action_btn_frame = ttk.Frame(right_frame)
        action_btn_frame.pack(fill=X, pady=2)
        
        # [MỚI] Mặc định là DISABLED (Mờ đi)
        self.btn_execute = ttk.Button(action_btn_frame, text="3. Tiến hành chặn", command=self.execute_ssh, state="disabled", bootstyle="danger")
        self.btn_execute.pack(side=LEFT, fill=X, expand=True, padx=(0, 2))
        
        self.btn_stop = ttk.Button(action_btn_frame, text="⏹️ DỪNG", command=self.stop_action, state="disabled", bootstyle="secondary")
        self.btn_stop.pack(side=RIGHT, fill=X, expand=True, padx=(2, 0))
        
        self.pending_commands = []
        self.temp_nums_to_add = [] 
        self.temp_nums_to_del = [] 
        
        self.root_after = self.app.root.after 
        self.root_after(500, self._setup_log_tags)
        
        self._update_tree([(k, v) for k, v in self.local_history.items()])
        
        # [MỚI] Cờ đánh dấu để tự động quét dữ liệu lần đầu
        self.has_auto_fetched = False
    
    # ==========================================
    # === TÍNH NĂNG KIỂM TRA ĐỒNG BỘ (SYNC) ===
    # ==========================================

    def start_sync_check(self):
        """Bắt đầu quy trình kiểm tra đồng bộ giữa 2 Node."""
        # 1. Chuẩn bị dữ liệu đầu vào
        commands_map = {} # {sđt: lệnh_check}
        lines = self.txt_input_numbers.get('1.0', tk.END).splitlines()
        
        for line in lines:
            line_clean = line.split('#')[0].strip()
            parts = re.split(r'[\s,;]+', line_clean)
            if not parts or not parts[0].isdigit(): continue
            
            raw_num = parts[0]
            num = raw_num[2:] if raw_num.startswith("84") else (raw_num[1:] if raw_num.startswith("0") else raw_num)
            
            cmd_set = self._generate_single_command(num)
            if cmd_set and 'check' in cmd_set:
                commands_map[num] = cmd_set['check']

        if not commands_map:
            messagebox.showwarning("Cảnh báo", "Không tìm thấy số điện thoại hợp lệ để kiểm tra.")
            return

        if not self._prepare_automation(): return

        # 2. Reset UI
        self._clear_check_results_box()
        self.txt_check_results.config(state=tk.NORMAL)
        self.txt_check_results.insert(tk.END, "⏳ Đang quét dữ liệu 2C & 2D đồng thời...\n", "header")
        self.txt_check_results.config(state=tk.DISABLED)
        
        # 3. Chạy 2 luồng song song để lấy dữ liệu về
        self.sync_results = {'C': {}, 'D': {}}
        self.running_threads = 2
        self.stop_event.clear()
        self.update_button_states() # Khóa nút

        user = self.ssh_details['user']
        pw = self.ssh_details['pass']
        
        # Luồng C
        t_c = threading.Thread(target=self._fetch_node_data_worker, 
                               args=(self.ssh_details['host_c'], user, pw, 'C', commands_map))
        t_c.daemon = True
        t_c.start()

        # Luồng D
        t_d = threading.Thread(target=self._fetch_node_data_worker, 
                               args=(self.ssh_details['host_d'], user, pw, 'D', commands_map))
        t_d.daemon = True
        t_d.start()
        
        # 4. Luồng giám sát để tổng hợp kết quả
        monitor = threading.Thread(target=self._monitor_sync_process, args=(list(commands_map.keys()),))
        monitor.daemon = True
        monitor.start()

    def _fetch_node_data_worker(self, host, user, pw, node_label, commands_map):
        """Worker: Kết nối SSH, gửi lệnh check và parse kết quả trả về dict."""
        node_name = f"TSSE2{node_label}" # TSSE2C hoặc TSSE2D
        try:
            self.log_message(f"Kết nối {node_name} để lấy dữ liệu...", node=node_name)
            
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(host, username=user, password=pw, timeout=10)
            shell = ssh.invoke_shell()
            time.sleep(1)
            
            # Init MML
            self.read_shell_output(shell, timeout=1, node=node_name)
            self.send_and_wait(shell, "mml -a", "<", timeout=5, node=node_name)
            
            # Loop commands
            for num, cmd in commands_map.items():
                if self.stop_event.is_set(): break
                
                # Dùng hàm Turbo check output
                raw_out = self.send_and_wait_for_output(shell, cmd, "<", timeout=10, node=node_name)
                
                # Parse kết quả bằng hàm chuẩn
                parse_res = self._parse_anbsp_output(raw_out, num)
                
                # Lưu vào biến global
                self.sync_results[node_label][num] = parse_res

        except Exception as e:
            self.log_message(f"Lỗi lấy dữ liệu {node_name}: {e}", node="SYSTEM")
        finally:
            if shell: 
                try: shell.close() 
                except: pass
            if ssh: 
                try: ssh.close()
                except: pass
            
            self.running_threads -= 1

    def _monitor_sync_process(self, number_list):
        """Chờ 2 luồng xong thì so sánh và hiển thị."""
        while self.running_threads > 0:
            time.sleep(0.5)
        
        self.update_button_states() # Mở khóa nút
        
        # Nếu bị stop thì thôi
        if self.stop_event.is_set(): 
            self.log_message("Đã hủy kiểm tra đồng bộ.", node="SYSTEM")
            return

        # Bắt đầu so sánh và in ra màn hình
        self.root.after(0, lambda: self._display_sync_results(number_list))

    def _display_sync_results(self, number_list):
        """Hiển thị kết quả so sánh (Diff) ra ô Kết quả"""
        self.txt_check_results.config(state=tk.NORMAL)
        self.txt_check_results.delete('1.0', tk.END)
        
        self.txt_check_results.insert(tk.END, "=== KẾT QUẢ ĐỒNG BỘ (2C vs 2D) ===\n\n", "header")
        
        # Tag màu cho kết quả
        self.txt_check_results.tag_configure("sync_ok", foreground="#198754") # Xanh lá
        self.txt_check_results.tag_configure("sync_diff", foreground="#DC3545", font=(self.code_font[0], self.code_font[1], "bold")) # Đỏ đậm
        self.txt_check_results.tag_configure("sync_warn", foreground="#FFC107") # Vàng

        for num in number_list:
            res_c = self.sync_results['C'].get(num, {'status': 'error', 'desc': 'No Data'})
            res_d = self.sync_results['D'].get(num, {'status': 'error', 'desc': 'No Data'})
            
            # Chuẩn hóa dữ liệu để so sánh (None -> '?')
            rc_c = res_c.get('rc')
            md_val_c = res_c.get('md_val')
            bnt_c = res_c.get('bnt')
            
            rc_d = res_d.get('rc')
            md_val_d = res_d.get('md_val')
            bnt_d = res_d.get('bnt')
            
            # Logic so sánh
            is_match = False
            status_text = ""
            tag = "sync_diff"

            # Trường hợp 1: Cả 2 đều chưa khai báo -> OK
            if res_c.get('status') in ['not_found', 'no_data'] and res_d.get('status') in ['not_found', 'no_data']:
                is_match = True
                status_text = "[TRỐNG] Cả 2 chưa khai báo"
                tag = "sync_warn" # Vàng
            
            # Trường hợp 2: Cả 2 đều tìm thấy -> So sánh chi tiết
            elif res_c.get('status') in ['found', 'inherited'] and res_d.get('status') in ['found', 'inherited']:
                if (rc_c == rc_d) and (md_val_c == md_val_d) and (bnt_c == bnt_d):
                    is_match = True
                    status_text = f"[OK] Đồng bộ (RC={rc_c})"
                    tag = "sync_ok" # Xanh
                else:
                    is_match = False
                    status_text = f"[LỆCH] C: RC={rc_c},M/D={md_val_c} | D: RC={rc_d},M/D={md_val_d}"
                    tag = "sync_diff" # Đỏ
            
            # Trường hợp 3: Bên có bên không
            else:
                is_match = False
                status_c_short = "CÓ" if res_c.get('status') == 'found' else "KHÔNG"
                status_d_short = "CÓ" if res_d.get('status') == 'found' else "KHÔNG"
                status_text = f"[LỆCH] 2C: {status_c_short} - 2D: {status_d_short}"
                tag = "sync_diff"

            # In ra màn hình
            self.txt_check_results.insert(tk.END, f"{num}: {status_text}\n", tag)
            
        self.txt_check_results.config(state=tk.DISABLED)
        # Gọi hàm update ngược lại ô Input (Node 1)
        self.root.after(100, self._update_input_ui_from_sync)
        messagebox.showinfo("Hoàn tất", "Đã kiểm tra đồng bộ xong.")
        
    def _update_input_ui_from_sync(self):
        """
        Khôi phục tính năng tô màu Input và ghi chú trạng thái (Sẵn sàng Route/Xóa).
        Dựa trên kết quả đồng bộ của 2 Node.
        """
        try:
            self.txt_input_numbers.config(state=tk.NORMAL)
            
            # Xóa các tag cũ
            self.txt_input_numbers.tag_remove("ok_action", "1.0", tk.END)
            self.txt_input_numbers.tag_remove("bad_action", "1.0", tk.END)
            self.txt_input_numbers.tag_remove("check_comment", "1.0", tk.END)
            self.txt_input_numbers.tag_remove("error_comment", "1.0", tk.END)
            
            # Xóa các comment cũ (từ dấu # trở về sau)
            lines = self.txt_input_numbers.get("1.0", tk.END).splitlines()
            # (Thực hiện xóa text cũ hơi phức tạp nên ta sẽ chỉ append comment mới vào sau dòng sạch)
            # Cách đơn giản: Loop qua từng dòng, tìm dòng tương ứng trong sync_results
            
            # Reset lại text sạch (Bỏ comment cũ đi để add comment mới)
            # Lưu ý: Cách này hơi can thiệp thô bạo, nhưng đảm bảo sạch sẽ.
            clean_lines = []
            for line in lines:
                if line.strip():
                    clean_lines.append(line.split('#')[0].rstrip())
            
            self.txt_input_numbers.delete("1.0", tk.END)
            self.txt_input_numbers.insert("1.0", "\n".join(clean_lines))
            
            # Bắt đầu quét lại để tô màu
            current_line = 1
            for line in clean_lines:
                line_start = f"{current_line}.0"
                line_end = f"{current_line}.end"
                
                parts = re.split(r'[\s,;]+', line.strip())
                if len(parts) < 2:
                    current_line += 1; continue

                raw_num = parts[0]
                action_word = parts[1].upper()
                if "XÓA" in action_word: action_word = "XÓA"
                
                if not raw_num.isdigit(): 
                    current_line += 1; continue
                
                num = raw_num[2:] if raw_num.startswith("84") else (raw_num[1:] if raw_num.startswith("0") else raw_num)
                
                # Lấy kết quả sync
                res_c = self.sync_results['C'].get(num)
                res_d = self.sync_results['D'].get(num)
                
                if not res_c or not res_d: 
                    current_line += 1; continue

                # Logic đánh giá
                tag_to_apply = None
                comment_msg = ""
                comment_tag = "check_comment" # Xanh

                # 1. KIỂM TRA ĐỒNG BỘ TRƯỚC
                is_synced = False
                # So sánh đơn giản status
                if res_c['status'] == res_d['status']:
                    # Nếu cùng found thì so RC
                    if res_c['status'] == 'found':
                         if res_c.get('rc') == res_d.get('rc'): is_synced = True
                    else:
                        is_synced = True # Cùng not_found hoặc no_data
                
                if not is_synced:
                    tag_to_apply = "bad_action"
                    comment_msg = "# LỖI: Dữ liệu 2 Node bị LỆCH. Cần kiểm tra tay!"
                    comment_tag = "error_comment"
                else:
                    # NẾU ĐÃ ĐỒNG BỘ -> XÉT TIẾP ROUTE HAY DELETE
                    status_common = res_c['status'] # Lấy C làm chuẩn
                    desc_common = res_c.get('desc', '').replace('ĐÃ KHAI BÁO', '').strip('() ')
                    
                    if action_word == "ROUTE":
                        # Logic Route: Phải CHƯA CÓ thì mới OK
                        if status_common in ['not_found', 'no_data', 'inherited']:
                            tag_to_apply = "ok_action"
                            comment_msg = "# (OK - Sẵn sàng khai báo)"
                        else:
                            tag_to_apply = "bad_action"
                            comment_msg = f"# LỖI: Đã tồn tại ({desc_common})"
                            comment_tag = "error_comment"
                            
                    elif action_word in ['DELETE', 'XOA', 'XÓA']:
                        # Logic Delete: Phải CÓ THỰC (Found) thì mới xóa được
                        if status_common == 'found':
                            tag_to_apply = "ok_action"
                            comment_msg = f"# (OK - Sẵn sàng xóa {desc_common})"
                        else:
                            tag_to_apply = "bad_action"
                            comment_msg = "# LỖI: Không có dữ liệu riêng để xóa"
                            comment_tag = "error_comment"

                # Áp dụng lên giao diện
                if tag_to_apply:
                    self.txt_input_numbers.tag_add(tag_to_apply, line_start, line_end)
                if comment_msg:
                    self.txt_input_numbers.insert(line_end, f"  {comment_msg}", comment_tag)
                
                current_line += 1
                
            self.txt_input_numbers.config(state=tk.DISABLED)

        except Exception as e:
            print(f"Lỗi update UI Input: {e}")
            
    # --- HÀM LƯU FILE AN TOÀN (MULTI-USER FIX) ---
    def _update_and_save_history(self, add_dict=None, remove_list=None):
        """
        Đọc lại file từ đĩa -> Cập nhật -> Ghi lại
        Logic này giúp tránh việc User A ghi đè làm mất dữ liệu User B vừa thêm.
        """
        try:
            # 1. Luôn đọc mới nhất từ đĩa trước khi sửa
            current_data = self._load_history()
            
            # 2. Xóa các số cần xóa (nếu có)
            if remove_list:
                for num in remove_list:
                    current_data.pop(num, None)
            
            # 3. Thêm các số mới (nếu có)
            if add_dict:
                current_data.update(add_dict)
            
            # 4. Ghi đè lại xuống đĩa
            with open(self.HISTORY_FILE, 'w') as f:
                json.dump(current_data, f, indent=4)
            
            # 5. Cập nhật lại biến RAM để hiển thị
            self.local_history = current_data
            
        except Exception as e:
            self._log_smart(f"❌ LỖI LƯU FILE HISTORY: {e}")
            
    def _setup_log_tags(self):
        try:
            if hasattr(self.app, 'log_tssn2d'):
                w = self.app.log_tssn2d
                # [MỚI] Đổi màu xanh đậm hơn (#006400) cho dễ đọc
                w.tag_config("CMD_SENT", foreground="#004085", font=("Consolas", 10, "bold")) 
                w.tag_config("SUCCESS", foreground="#006400") # DarkGreen
                w.tag_config("ERROR", foreground="#721c24")    
                w.tag_config("NAT_KEY", foreground="#6c757d")  
                w.tag_config("PHONE_NUM", foreground="#d35400", font=("Consolas", 11, "bold")) 
                w.tag_config("RESTRICT", foreground="#006400", font=("Consolas", 10, "bold")) # Xanh đậm + Béo
        except: pass

    def on_search_change(self, event):
        query = self.entry_search.get().strip().lower()
        for item in self.tree.get_children():
            self.tree.delete(item)
        filtered_data = []
        for num, date in self.local_history.items():
            if query in num:
                filtered_data.append((num, date))
        self._update_tree(filtered_data)

    def _log_smart(self, text, node="TSSN2D"):
        # --- THÊM DÒNG NÀY ĐỂ GHI FILE LOG ---
        try:
            if hasattr(self.app, 'logger') and self.app.logger:
                self.app.logger.info(f"[{node}] {text}")
        except: pass
        # -------------------------------------
    
        def _gui_update(clean_text):
            try:
                # Logic tìm khung log thông minh
                if not hasattr(self.app, 'log_tssn2d'): return
                w = self.app.log_tssn2d
                
                # Tự động hiện khung log nếu đang bị ẩn
                if hasattr(self.app, 'log_frame_single') and not self.app.log_frame_single.winfo_ismapped():
                    if hasattr(self.app, 'log_pane_dual'): self.app.log_pane_dual.pack_forget()
                    self.app.log_frame_single.pack(fill=BOTH, expand=True, padx=(5,0))

                w.config(state='normal')
                
                # Regex tô màu log
                nat_match = re.match(r"(NAT)\s+(\d+)\s+(RESTRICT.*)", clean_text)
                if nat_match:
                    w.insert(tk.END, nat_match.group(1) + "  ", "NAT_KEY")
                    w.insert(tk.END, nat_match.group(2) + "  ", "PHONE_NUM") 
                    w.insert(tk.END, nat_match.group(3) + "\n", "RESTRICT")
                elif clean_text.strip().startswith("ZC") or "[Gửi lệnh]" in clean_text:
                    w.insert(tk.END, clean_text + "\n", "CMD_SENT")
                elif "EXECUTED" in clean_text:
                    w.insert(tk.END, clean_text + "\n", "SUCCESS")
                elif "FAULT" in clean_text or "ERROR" in clean_text or "NOT ACCEPTED" in clean_text:
                    w.insert(tk.END, clean_text + "\n", "ERROR")
                else:
                    w.insert(tk.END, clean_text + "\n")
                
                w.see(tk.END)
                w.config(state='disabled')
            except Exception as e: 
                # Chỉ in ra console khi thực sự có lỗi GUI nghiêm trọng
                print(f"Log Error: {e}")
                
        self.root_after(0, lambda: _gui_update(text))

    def _on_focus_in_del(self, event):
        if self.txt_priority_del.get("1.0", "end-1c").strip() == self.del_placeholder.strip():
            self.txt_priority_del.delete("1.0", "end")
            self.txt_priority_del.config(foreground="black")

    def _on_focus_out_del(self, event):
        if not self.txt_priority_del.get("1.0", "end-1c").strip():
            self.txt_priority_del.insert("1.0", self.del_placeholder)
            self.txt_priority_del.config(foreground="grey")

    # --- MENU CHUỘT PHẢI: 3D NỔI & HOVER MƯỢT ---
    def show_context_menu(self, event):
        # 1. Chọn dòng hiện tại
        item = self.tree.identify_row(event.y)
        if item:
            if item not in self.tree.selection():
                self.tree.selection_set(item)
        
        if not self.tree.selection():
            return

        # 2. Tạo cửa sổ Toplevel (Menu giả)
        self.popup = Toplevel(self.app.root)
        self.popup.wm_overrideredirect(True) # Bỏ thanh tiêu đề
        self.popup.geometry(f"+{event.x_root}+{event.y_root}")
        
        # [SỬA] Viền ngoài mỏng, màu Xám Xanh sẫm (Blue Grey)
        self.popup.config(bg="#78909C") 
        
        # 3. Frame nội dung
        # [SỬA] Nền Xám Xanh rất nhạt (#ECEFF1), phẳng (flat) cho gọn
        inner_frame = tk.Frame(self.popup, bg="#ECEFF1", relief="flat", bd=0)
        inner_frame.pack(fill=BOTH, expand=True, padx=1, pady=1)

        # --- CẤU HÌNH STYLE NÚT (Menu Item) ---
        btn_opts = {
            "bg": "#ECEFF1",          # Nền gốc: Xám xanh nhạt
            "fg": "#37474F",          # Chữ: Xám than (Dễ đọc, không gắt)
            "font": ("Segoe UI", 10), # [SỬA] Bỏ Bold để trông thanh thoát, bớt thô
            "bd": 0,
            "relief": "flat",         # Nút phẳng
            "anchor": "w",            # Căn trái
            "padx": 12, "pady": 5,    # [SỬA] Giảm padding cho gọn gàng (Compact)
            "cursor": "hand2",
            "activebackground": "#CFD8DC", # [SỬA] Hover: Xám xanh đậm hơn xíu
            "activeforeground": "#000000"
        }

        # --- HÀM XỬ LÝ HOVER ---
        def on_enter(e):
            e.widget.config(bg="#CFD8DC", fg="black") # Hover màu xám xanh
        
        def on_leave(e):
            e.widget.config(bg="#ECEFF1", fg="#37474F") # Trả về màu cũ

        # --- TẠO CÁC DÒNG MENU ---
        
        # Dòng 1: Gỡ chặn
        # Thêm icon text (✅) nhỏ lại hoặc bỏ đi nếu muốn gọn hơn nữa
        btn_add = tk.Button(inner_frame, text="✅  Gỡ chặn số này", 
                            command=lambda: [self.add_selected_to_remove_list(), self.popup.destroy()],
                            **btn_opts)
        btn_add.pack(fill=X)
        btn_add.bind("<Enter>", on_enter)
        btn_add.bind("<Leave>", on_leave)

        # Kẻ ngang - Màu xám nhạt
        tk.Frame(inner_frame, height=1, bg="#B0BEC5").pack(fill=X, padx=0, pady=0)

        # Dòng 2: Đóng
        btn_close = tk.Button(inner_frame, text="❌  Đóng", 
                              command=self.popup.destroy, 
                              **btn_opts)
        btn_close.pack(fill=X)
        btn_close.bind("<Enter>", on_enter)
        btn_close.bind("<Leave>", on_leave)

        # --- XỬ LÝ ĐÓNG MENU ---
        self.popup.bind("<FocusOut>", lambda e: self.popup.destroy())
        self.popup.focus_set()
        
    def add_selected_to_remove_list(self):
        selected_items = self.tree.selection()
        if not selected_items: return
        
        if self.txt_priority_del.get("1.0", "end-1c").strip() == self.del_placeholder.strip():
            self.txt_priority_del.delete("1.0", "end")
            self.txt_priority_del.config(foreground="black")

        current_text = self.txt_priority_del.get("1.0", "end").strip()
        current_lines = [line.strip() for line in current_text.splitlines() if line.strip()]
        
        added_count = 0
        for item in selected_items:
            values = self.tree.item(item)['values']
            phone = str(values[0])
            if phone not in current_lines:
                current_lines.append(phone)
                added_count += 1
        
        self.txt_priority_del.delete("1.0", "end")
        self.txt_priority_del.insert("1.0", "\n".join(current_lines))
        self._log_smart(f"Đã thêm {added_count} số vào danh sách gỡ chặn.")

    def _load_history(self):
        if os.path.exists(self.HISTORY_FILE):
            try:
                with open(self.HISTORY_FILE, 'r') as f: return json.load(f)
            except: return {}
        return {}

    def _save_history(self):
        try:
            with open(self.HISTORY_FILE, 'w') as f: json.dump(self.local_history, f, indent=4)
        except: pass

    def toggle_ui_state(self, is_running):
        self.is_running = is_running
        stop_state = "normal" if is_running else "disabled"
        if is_running:
            self.btn_stop.config(state="normal", bootstyle="danger")
            self.lbl_analysis.config(text="Đang chạy...", foreground="orange")
        else:
            self.btn_stop.config(state="disabled", bootstyle="secondary")
            self.lbl_analysis.config(text="Sẵn sàng/Đã xong", foreground="blue")

    def stop_action(self):
        if self.is_running:
            self._log_smart("!!! Người dùng bấm DỪNG !!!")
            self.app.stop_event.set()

    def _clean_chunk(self, chunk):
        s = chunk.replace('\r', '')
        s = re.sub(r'NAT\s*[\n]+\s*(\d+)', r'NAT  \1', s)
        s = re.sub(r'[\s\n]+RESTRICT', r'  RESTRICT', s)
        s = re.sub(r'FINAL\s*[\n]+\s*RESULT', r'FINAL RESULT', s)
        s = re.sub(r'\n\s*\n', '\n', s)
        return s

    def fetch_current_data(self):
        host = "10.204.161.61"
        user = "NGHIAP"
        pw = "0918433694"
        
        # [MỚI] Reset danh sách "Vừa thêm" khi load lại từ Node
        self.temp_nums_to_add = []
        
        self.app.stop_event.clear()
        self.toggle_ui_state(True)
        # [MỚI] Disable nút chạy khi đang load dữ liệu
        self.btn_execute.config(state="disabled")
        
        try:
            if hasattr(self.app, 'log_tssn2d'):
                if hasattr(self.app, 'log_pane_dual'): self.app.log_pane_dual.pack_forget()
                if hasattr(self.app, 'log_frame_single'): 
                    self.app.log_frame_single.pack(fill=BOTH, expand=True, padx=(5,0))
                self.app.log_tssn2d.config(state='normal')
                self.app.log_tssn2d.delete('1.0', 'end')
                self.app.log_tssn2d.config(state='disabled')
                self.app.root.update_idletasks()
        except: pass

        def _thread_task():
            ssh = None
            try:
                self._log_smart(f"--- KẾT NỐI LẤY DỮ LIỆU {host} (CHẾ ĐỘ TURBO) ---")
                
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                ssh.connect(host, username=user, password=pw, timeout=20)
                
                shell = ssh.invoke_shell()
                while not shell.recv_ready(): time.sleep(0.1)
                shell.recv(9999) 
                
                cmd = "ZCWI:NAME=CLI;"
                self._log_smart(f"[Gửi lệnh]: {cmd}")
                shell.send(cmd + "\r")
                
                full_data = ""
                start_time = time.time()
                last_log_time = time.time()
                
                while True:
                    if self.app.stop_event.is_set(): raise Exception("Stop.")
                    if time.time() - start_time > 60:
                        self._log_smart("!!! TIMEOUT: Quá thời gian chờ phản hồi.")
                        break
                    
                    if shell.recv_ready():
                        chunk = shell.recv(65535).decode('utf-8', errors='ignore')
                        full_data += chunk
                        if time.time() - last_log_time > 0.5:
                            self._log_smart("... đang tải dữ liệu ...")
                            last_log_time = time.time()
                        if "COMMAND EXECUTED" in chunk or "<" in chunk or "END" in chunk:
                            self._log_smart("✅ Đã nhận tín hiệu kết thúc lệnh.")
                            break
                    else: time.sleep(0.01)
                
                self._log_smart("Đang phân tích dữ liệu...")
                pattern = re.compile(r"NAT\s+(\d+)\s+(RESTRICT\s*:\s*FINAL\s*RESULT)")
                matches = pattern.findall(full_data)
                
                current_on_node = sorted(list(set([m[0] for m in matches])))
                count = len(current_on_node)
                
                self._log_smart(f"\n📊 KẾT QUẢ: Tìm thấy {count} số đang chặn trên Node.")
                
                def _print_bulk_log():
                    if not hasattr(self.app, 'log_tssn2d'): return
                    w = self.app.log_tssn2d
                    w.config(state='normal')
                    w.insert(tk.END, "-" * 40 + "\n")
                    w.insert(tk.END, "CHI TIẾT DANH SÁCH TỪ NODE:\n")
                    lines = [f"NAT  {num:<12}  RESTRICT" for num in current_on_node]
                    big_text = "\n".join(lines)
                    # Dùng tag RESTRICT (đã chỉnh màu đậm)
                    w.insert(tk.END, big_text + "\n", "RESTRICT")
                    w.insert(tk.END, "-" * 40 + "\n")
                    w.see(tk.END)
                    w.config(state='disabled')

                if count > 0: self.root_after(0, _print_bulk_log)

                disk_history = self._load_history()
                node_set = set(current_on_node)
                new_history = {}
                
                for num, date in disk_history.items():
                    if num in node_set: new_history[num] = date
                for num in current_on_node:
                    if num not in new_history: new_history[num] = "Unknown"
                
                self.local_history = new_history
                with open(self.HISTORY_FILE, 'w') as f:
                    json.dump(new_history, f, indent=4)
                
                display_list = [(k, v) for k, v in self.local_history.items()]
                
                def _update_ui_done():
                    self._update_tree(display_list)
                    now_str = datetime.now().strftime("%H:%M:%S")
                    self._mark_data_fresh(now_str) # Kích hoạt bộ đếm giờ
                    
                self.root_after(0, _update_ui_done)
                shell.send("exit;\r")
                
            except Exception as e:
                self._log_smart(f"❌ LỖI: {e}")
            finally:
                if ssh:
                    try: ssh.close()
                    except: pass
                self.root_after(0, lambda: self.toggle_ui_state(False))

        threading.Thread(target=_thread_task, daemon=True).start()

    def _update_tree(self, data_list):
        for i in self.tree.get_children(): self.tree.delete(i)
        
        # Sắp xếp: Unknown xuống dưới, Mới nhất lên trên
        def sort_key(item):
            t = item[1]; return "0000" if "Unknown" in t else t
        data_list.sort(key=sort_key, reverse=True) 
        
        for num, time_str in data_list:
            # [MỚI] Logic chọn tag màu
            row_tag = "known_row" # Mặc định màu đen
            
            if num in self.temp_nums_to_add:
                row_tag = "new_row"   # Vừa thêm -> Xanh đậm + Béo
            elif "Unknown" in time_str:
                row_tag = "unknown_row" # Không rõ ngày -> Xám nhạt
            
            self.tree.insert("", "end", values=(num, time_str), tags=(row_tag,))

    def analyze_and_generate(self):
        # [MỚI] Chặn ngay từ đầu nếu dữ liệu đã hết hạn (quá 3 phút)
        if not getattr(self, 'is_data_fresh', False):
            msg = "Dữ liệu hiện tại có thể đã cũ do chưa được làm mới trong vài phút qua.\n\nĐể tránh đụng độ với các ca trực khác, bạn có muốn công cụ TỰ ĐỘNG QUÉT LẠI dữ liệu mới nhất trước khi tính toán lệnh không?"
            if messagebox.askyesno("⚠️ Cảnh báo dữ liệu cũ", msg, icon='warning'):
                self.fetch_current_data()
                return # Dừng hàm phân tích, chờ quét xong user bấm lại sau
            # Nếu user cố tình chọn No, hệ thống vẫn cho đi tiếp (có thể đổi thành return luôn nếu bạn muốn ép buộc 100%)
        self.local_history = self._load_history()
        current_active_numbers = set(self.local_history.keys())
        
        # [MỚI] Reset nút chặn về disabled trước khi phân tích
        self.btn_execute.config(state="disabled")

        raw_add = self.txt_new_block.get("1.0", "end").strip()
        input_add = [l.strip() for l in raw_add.splitlines() if l.strip() and not l.strip().startswith("#") and l.strip().isdigit()]
        input_add = sorted(list(set(input_add)))

        raw_del = self.txt_priority_del.get("1.0", "end").strip()
        if raw_del == self.del_placeholder.strip(): raw_del = ""
        input_del = [l.strip() for l in raw_del.splitlines() if l.strip() and not l.strip().startswith("#") and l.strip().isdigit()]
        input_del = sorted(list(set(input_del)))
        
        overlap = set(input_add) & set(input_del)
        if overlap:
            overlap_list = sorted(list(overlap))
            display_str = ", ".join(overlap_list[:10])
            if len(overlap_list) > 10: display_str += f"\n... và {len(overlap_list) - 10} số khác."
            
            msg = (f"🔍 PHÁT HIỆN TRÙNG LẶP ({len(overlap)} số):\n👉 {display_str}\n\n"
                   f"💡 GIẢI PHÁP: Tự động BỎ các số này ở ô 'CHẶN THÊM' để ưu tiên lệnh 'GỠ CHẶN'?")
            
            if messagebox.askyesno("Xung đột dữ liệu", msg, icon='question'):
                input_add = [x for x in input_add if x not in overlap]
                self.txt_new_block.delete("1.0", "end")
                self.txt_new_block.insert("1.0", "\n".join(input_add))
            else: return

        final_add = [n for n in input_add if n not in current_active_numbers]
        skipped_add = [n for n in input_add if n in current_active_numbers]
        final_del = [n for n in input_del if n in current_active_numbers]
        skipped_del = [n for n in input_del if n not in current_active_numbers]
        
        if len(final_del) < len(final_add):
            deficit = len(final_add) - len(final_del)
            candidates = []
            from datetime import datetime
            for num, date_str in self.local_history.items():
                if num in final_del: continue
                if str(num).startswith("3"): 
                    continue
                sort_val = datetime.max
                if "Unknown" in date_str: sort_val = datetime.min
                else:
                    try: sort_val = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
                    except: pass
                candidates.append((num, sort_val))
            candidates.sort(key=lambda x: x[1])
            for i in range(min(deficit, len(candidates))):
                final_del.append(candidates[i][0])
            
            if self.txt_priority_del.get("1.0", "end-1c").strip() == self.del_placeholder.strip():
                 self.txt_priority_del.delete("1.0", "end")
                 self.txt_priority_del.config(foreground="black")
            self.txt_priority_del.delete("1.0", "end")
            self.txt_priority_del.insert("1.0", "\n".join(final_del))

        self.pending_commands = []
        if not final_add and not final_del:
            if input_add and len(skipped_add) == len(input_add):
                msg = (f"✅ AN TOÀN TUYỆT ĐỐI\n\nBạn nhập {len(input_add)} số, và tất cả ĐÃ ĐƯỢC CHẶN từ trước.")
                messagebox.showinfo("Đã được bảo vệ", msg)
                self.lbl_analysis.config(text="Tất cả số nhập vào đều đã an toàn.", foreground="green")
            else:
                messagebox.showinfo("Thông báo", "Không có lệnh mới.")
            return

        self.pending_commands.append("ZCWN:CNT,CLI;") 
        for num in final_del: self.pending_commands.append(f"ZCWM:CLI,DEL:TON=NAT,DIG={num}:;")
        for num in final_add: self.pending_commands.append(f"ZCWM:CLI,ADD:TON=NAT,DIG={num},RES=RESTRICT;")
        self.pending_commands.append("ZCWN:MTN,CLI;") 
        
        self.temp_nums_to_add = final_add 
        self.temp_nums_to_del = final_del 

        report = f"KẾ HOẠCH ({len(self.pending_commands)} lệnh):\n🔵 THÊM: {len(final_add)} số\n🟠 XÓA:  {len(final_del)} số"
        self.lbl_analysis.config(text=f"Sẵn sàng: +{len(final_add)} / -{len(final_del)}")
        
        # [MỚI] Chỉ mở khóa nút khi có lệnh
        self.btn_execute.config(state="normal")
        messagebox.showinfo("Phân tích & Cân bằng", report)

    def execute_ssh(self):
        host = "10.204.161.61"
        user = "NGHIAP"
        pw = "0918433694"
        
        if not self.pending_commands: return
        if not messagebox.askyesno("Xác nhận", f"Chạy {len(self.pending_commands)} lệnh?"): return
        
        self.app.stop_event.clear()
        self.toggle_ui_state(True)
        # [MỚI] Khóa nút ngay lập tức
        self.btn_execute.config(state="disabled")
        
        try:
             if hasattr(self.app, 'log_pane_dual'): self.app.log_pane_dual.pack_forget()
             if hasattr(self.app, 'log_frame_single'): 
                 self.app.log_frame_single.pack(fill=BOTH, expand=True, padx=(5,0))
             self.app.log_tssn2d.config(state='normal')
             self.app.root.update_idletasks()
        except: pass
        
        def _update_ui_after_execution():
            try:
                from datetime import datetime
                now_obj = datetime.now()
                date_str = now_obj.strftime("%Y-%m-%d %H:%M:%S")
                time_only_str = now_obj.strftime("%H:%M:%S")
                
                add_dict = {num: date_str for num in self.temp_nums_to_add}
                self._update_and_save_history(add_dict=add_dict, remove_list=self.temp_nums_to_del)
                
                self.entry_search.delete(0, tk.END) 
                display_list = [(k, v) for k, v in self.local_history.items()]
                
                # Gọi update_tree, nó sẽ tự tô đậm các số trong temp_nums_to_add
                self._update_tree(display_list)
                
                self.txt_new_block.delete("1.0", "end")
                self.txt_priority_del.delete("1.0", "end")
                self.txt_priority_del.insert("1.0", self.del_placeholder)
                self.txt_priority_del.config(foreground="grey")
                
                self._mark_data_fresh(time_only_str) # Kích hoạt lại bộ đếm giờ sau khi thao tác xong
                
                self.lbl_analysis.config(text="Đã thực thi xong.")
                self._log_smart("✅ Giao diện đã cập nhật thành công.")
            except Exception as e:
                self._log_smart(f"❌ LỖI CẬP NHẬT UI: {e}")

        def _run():
            ssh = None
            try:
                self._log_smart("!!! BẮT ĐẦU CHẠY LỆNH !!!")
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                ssh.connect(host, username=user, password=pw, timeout=20)
                
                shell = ssh.invoke_shell()
                time.sleep(1.0) 
                if shell.recv_ready(): shell.recv(8192)
                shell.send("\r"); time.sleep(0.5)
                
                has_error = False
                for i, cmd in enumerate(self.pending_commands):
                    if self.app.stop_event.is_set(): raise Exception("Đã dừng.")
                    self._log_smart(f"({i+1}/{len(self.pending_commands)}) {cmd}")
                    
                    shell.send(cmd + "\r")
                    buffer = ""
                    success = False
                    start_time = time.time()
                    
                    while time.time() - start_time < 30: 
                        if self.app.stop_event.is_set(): raise Exception("Đã dừng.")
                        if shell.recv_ready():
                            chunk = shell.recv(4096).decode('utf-8', errors='ignore')
                            pretty_chunk = self._clean_chunk(chunk)
                            buffer += chunk 
                            self._log_smart(pretty_chunk)
                            
                            if re.search(r"(COMMAND EXECUTED|EXECUTED)", buffer): success = True; break
                            if re.search(r"(NOT ACCEPTED|SYNTAX ERROR|FAULT CODE)", buffer): success = False; break
                        else: time.sleep(0.05)
                    
                    if not success:
                        self._log_smart(f"❌ LỖI: Lệnh {i+1} thất bại!")
                        has_error = True; break 
                    time.sleep(0.2)

                if not has_error:
                    self._log_smart("✅ ĐÃ CHẠY XONG. Đang cập nhật giao diện...")
                    self.root_after(0, _update_ui_after_execution)
                else:
                    self._log_smart("⚠️ Dừng do lỗi.")
                
                shell.send("exit;\r")
            except Exception as e:
                self._log_smart(f"Lỗi SSH: {e}")
            finally:
                if ssh:
                    try: ssh.close()
                    except: pass
                self.root_after(0, lambda: self.toggle_ui_state(False))

        threading.Thread(target=_run, daemon=True).start()
        
    # === CƠ CHẾ QUẢN LÝ CACHE (TTL) ===
    def _mark_data_fresh(self, time_str):
        """Đánh dấu dữ liệu là mới nhất, bắt đầu đếm ngược hết hạn"""
        self.is_data_fresh = True
        self.last_update_time = time_str  
        
        self.left_frame.config(text=f" ✅ Dữ liệu thực (Cập nhật: {time_str}) ", bootstyle="success")
        
        # Hủy bộ đếm giờ cũ nếu có (tránh đè luồng)
        if hasattr(self, 'data_expiry_timer') and self.data_expiry_timer:
            self.app.root.after_cancel(self.data_expiry_timer)
            
        # Đặt thời gian hết hạn: 3 phút (180,000 ms)
        self.data_expiry_timer = self.app.root.after(180000, self._mark_data_stale)

    def _mark_data_stale(self):
        """Đánh dấu dữ liệu đã cũ, nhắc người dùng cập nhật và gọi hiệu ứng nhấp nháy"""
        self.is_data_fresh = False
        old_time = getattr(self, 'last_update_time', 'Chưa rõ')
        
        self.left_frame.config(text=f" ⚠️ Dữ liệu đã cũ (Lần cuối: {old_time}) - Hãy quét lại ", bootstyle="warning")
        
        # Bắt đầu nhấp nháy 6 nhịp (tương đương 3 lần chớp Đỏ - Vàng)
        self._blink_warning(count=6)

    def _blink_warning(self, count):
        """Tạo hiệu ứng nhấp nháy viền Label bằng cách đảo màu (bootstyle)"""
        # Nếu đã đếm ngược xong hoặc người dùng vừa bấm nút quét (làm data fresh lại) thì dừng
        if count <= 0 or getattr(self, 'is_data_fresh', False):
            self.left_frame.config(bootstyle="warning") # Trả về màu vàng cố định
            return
            
        # Luân phiên đổi style giữa Vàng (warning) và Đỏ (danger)
        current_style = str(self.left_frame.cget("bootstyle"))
        next_style = "danger" if "warning" in current_style else "warning"
        
        self.left_frame.config(bootstyle=next_style)
        
        # Đặt thời gian chớp: 400ms đổi màu 1 lần
        self.app.root.after(400, lambda: self._blink_warning(count - 1))
        
class SipRouterApp:
    def __init__(self, root):
        self.root = root
        
        # --- 1. SETUP THEME & WINDOW ---
        self.style = ttk.Style(theme="cosmo")
        
        try:
            self.root.state('zoomed') 
        except:
            self.root.geometry("1200x700")

        self.root.title("Công cụ Định tuyến SIP & Ứng cứu 11x - Enterprise Edition")

        # --- 2. BẢNG MÀU CHUẨN (ĐÃ TĂNG TƯƠNG PHẢN HOVER) ---
        # Cấu trúc: (Màu Gốc, Màu Hover Đậm Hơn, Màu Chữ)
        self.COLORS = {
            "primary":   ("#2780E3", "#004a99", "white"),  # Hover chuyển sang xanh đậm hẳn
            "secondary": ("#6C757D", "#42474d", "white"),  # Hover chuyển xám đen
            "success":   ("#198754", "#0f452a", "white"),  # Hover xanh lá đậm
            "danger":    ("#DC3545", "#8a1f29", "white"),  # Hover đỏ bầm
            "warning":   ("#FFC107", "#b38600", "#000000"), 
            "info":      ("#0DCAF0", "#0aa2c2", "#000000"), 
            
            # Màu Text & Log
            "text_dark_blue": "#003366", 
            "log_bg": "#0D1117",  
            "log_fg_c": "#58A6FF", 
            "log_fg_d": "#F9826C", 
        }

        # --- ĐỊNH NGHĨA MÀU NÚT BỊ KHÓA (DISABLE) ---
        DISABLED_BG = "#E9ECEF" 
        DISABLED_FG = "#ADB5BD" 

        # --- 3. CẤU HÌNH STYLE ---
        self.style.configure('TButton', font=('Segoe UI', 10, 'bold'), cursor='hand2')
        
        # Map lại màu cho các style nút
        for name in ["primary", "secondary", "success", "danger", "warning", "info"]:
            bg, bg_hover, fg = self.COLORS[name]
            style_name = f"{name}.TButton"
            
            self.style.configure(style_name, background=bg, foreground=fg, bordercolor=bg)
            
            # [FIX] Đưa trạng thái 'active' (hover) lên trước để ưu tiên hiển thị
            self.style.map(style_name,
                background=[("disabled", DISABLED_BG), ("active", bg_hover), ("!active", bg)],
                foreground=[("disabled", DISABLED_FG), ("active", fg), ("!active", fg)],
                bordercolor=[("disabled", DISABLED_BG), ("active", bg_hover), ("!active", bg)],
                relief=[("pressed", "sunken"), ("!pressed", "raised")] # Thêm hiệu ứng nhấn
            )

        # [FIX] Cấu hình Tab có hiệu ứng Hover rõ ràng
        self.style.configure('TNotebook.Tab', font=('Segoe UI', 11, 'bold'), padding=[20, 8])
        
        self.style.map("TNotebook.Tab",
            background=[
                ("selected", self.COLORS["primary"][0]), # Màu khi được chọn (Xanh)
                ("active", "#D6D8DB"),                   # [MỚI] Màu khi chuột lướt qua (Xám đậm hơn nền)
                ("!selected", "#F8F9FA")                 # Màu bình thường (Xám nhạt/Trắng)
            ],
            foreground=[
                ("selected", "white"), 
                ("active", self.COLORS["primary"][1]),   # [MỚI] Chữ đổi màu xanh đậm khi hover
                ("!selected", "#6C757D")
            ],
            bordercolor=[
                ("selected", self.COLORS["primary"][0]), 
                ("!selected", "#DEE2E6")
            ]
        )

        # Cấu hình Label Frame
        self.style.configure('TLabelframe', background="white")
        self.style.configure('TLabelframe.Label', font=('Segoe UI', 10, 'bold'), foreground=self.COLORS["text_dark_blue"], background="white")

        # --- Biến hệ thống ---
        self.stop_event = threading.Event()
        self.running_threads = 0
        self.allow_free_input = tk.BooleanVar(value=False)
        self.proposed_changeover_action = None
        self.proposed_fallback_action = None
        self.selected_uctt_rc = None
        
        # [QUAN TRỌNG] Lắng nghe thay đổi RC để reset nút (An toàn vận hành)
        self.uctt_rc_var = tk.StringVar(value="113")
        self.uctt_rc_var.trace("w", self._on_rc_selection_change)
        
        self.commands_to_execute_changeover = []
        self.commands_to_execute_fallback = []
        self.skip_bad_lines_var = tk.BooleanVar(value=True)
        
        # --- Logging Setup ---
        self.setup_file_logging()
        
        # --- Font Configuration ---
        self.normal_font = ("Segoe UI", 10)
        self.code_font = ("Cascadia Code", 10) 
        self.placeholder_font = ("Segoe UI", 10, "italic")
        self.bold_font = ("Segoe UI", 10, "bold") 

        # --- [CẬP NHẬT] HINT CHI TIẾT ---
        self.placeholder_text = (
            "HƯỚNG DẪN CÚ PHÁP (Tự động cắt 0/84 ở đầu):\n"
            "----------------------------------------------------------------------\n"
            "1. CỐ ĐỊNH (10 số)\n"
            "   👉 2838xxxxxx route HCM/HNI/IMS\n"
            "2. ĐẦU 1800/1900 (8 hoặc 10 số) - Mặc định IMS\n"
            "   👉 1900xxxxxx route HCM/HNI/IMS\n"
            "3. CFW 91 (8, 9 hoặc 10 số) - Mặc định vIMS\n"
            "   👉 91xxxxxxx  route HCM/HNI/IMS\n"
            "4. CFW 138 (9 hoặc 10 số) - Mặc định HCM\n"
            "   👉 138xxxxxxx route  HCM/IMS\n"
            "5. LỆNH XÓA (Hỗ trợ: delete, xoa, xóa, huy):\n"
            "   👉 2838xxxxxx delete\n"
            "----------------------------------------------------------------------"
        )

        # --- GUI Layout ---
        menubar = Menu(root)
        root.config(menu=menubar)
        options_menu = Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Hệ Thống", menu=options_menu)
        options_menu.add_command(label="Cài đặt SSH...", command=self.open_ssh_settings)
        options_menu.add_separator()
        options_menu.add_command(label="Thoát", command=root.quit)

        # Main Paned
        self.main_paned = ttk.Panedwindow(root, orient=HORIZONTAL)
        self.main_paned.pack(fill=BOTH, expand=True, padx=12, pady=12)

        left_pane = ttk.Frame(self.main_paned)
        right_pane = ttk.Frame(self.main_paned)
        self.main_paned.add(left_pane, weight=1) 
        self.main_paned.add(right_pane, weight=1)

        # Tabs
        notebook = ttk.Notebook(left_pane)
        notebook.pack(fill=BOTH, expand=True)

        tab_route = ttk.Frame(notebook, padding=12) 
        tab_uctt = ttk.Frame(notebook, padding=12)
        notebook.add(tab_route, text=" ĐỊNH TUYẾN AA / vIMS ") 
        notebook.add(tab_uctt, text=" ỨNG CỨU 11x ")
        self.a2p_tab = A2PBlockerTab(notebook, self)
        
        # ================= TAB 1: ROUTE =================
        # 1. Input Area
        input_frame = ttk.Labelframe(tab_route, text=" 📝 1. Nhập liệu định tuyến ", padding=10) 
        input_frame.pack(side=TOP, fill=X, pady=(0, 8))
        
        # Tăng height=11 để chứa đủ nguyên cái Placeholder, không bị khuất
        self.txt_input_numbers = scrolledtext.ScrolledText(input_frame, height=11, width=50, font=self.normal_font, bg="#FFFFFF", relief="flat", borderwidth=1)
        self.txt_input_numbers.pack(fill=BOTH, expand=True, pady=(2,2))
        
        # Checkbox style="round-toggle"
        ttk.Checkbutton(input_frame, text="Cho phép nhập số tự do (tắt kiểm tra độ dài)", variable=self.allow_free_input, bootstyle="round-toggle", cursor="hand2").pack(anchor='w', pady=(5,0))

        # Font placeholder nhỏ lại giống bản Web CSS
        small_italic_font = ("Consolas", 9, "italic")
        self.txt_input_numbers.tag_configure("placeholder", foreground="grey", font=small_italic_font)
        self.txt_input_numbers.tag_configure("ok_action", background="#D1E7DD") 
        self.txt_input_numbers.tag_configure("bad_action", background="#F8D7DA") 
        self.txt_input_numbers.tag_configure("check_comment", foreground="#084298", font=small_italic_font)
        self.txt_input_numbers.tag_configure("error_comment", foreground="#842029", font=small_italic_font)

        self.txt_input_numbers.bind("<FocusIn>", self._on_focus_in)
        self.txt_input_numbers.bind("<FocusOut>", self._on_focus_out)
        self.root.after(100, self._set_placeholder)
        
        # [MỚI] Kích hoạt vòng lặp quét ô nhập liệu liên tục
        self.root.after(500, self._auto_toggle_check_btn)

        # 2. Control Buttons Area (Bỏ viền cho giống Web)
        options_frame = ttk.Frame(tab_route)
        options_frame.pack(side=TOP, fill=X, pady=(0, 8))

        self.btn_run_check = ttk.Button(options_frame, text="🔍 BƯỚC 1: KIỂM TRA TRẠNG THÁI & LỌC LỆNH TỰ ĐỘNG", command=self.start_check_automation, state=tk.DISABLED, bootstyle="info")
        self.btn_run_check.pack(side=LEFT, fill=X, expand=True)

        # Checkbox ẩn lỗi (Đẩy xuống dưới nút Kiểm tra để gọn layout)
        ttk.Checkbutton(tab_route, text="Tự động bỏ qua các hàng lỗi (tô đỏ) khi tạo lệnh", variable=self.skip_bad_lines_var, bootstyle="round-toggle", cursor="hand2").pack(side=TOP, anchor="w", pady=(0, 5))

        # --- [QUAN TRỌNG] ĐƯA KHUNG NÚT CHẠY LÊN PACK TRƯỚC ĐỂ GHIM CHẶT XUỐNG ĐÁY ---
        # 4. Automation Buttons
        auto_frame = ttk.Labelframe(tab_route, text=" 🚀 4. Đẩy lệnh vào hệ thống ", padding=5) 
        auto_frame.pack(side=BOTTOM, fill=X, pady=(2, 0)) # Lệnh side=BOTTOM giúp nó bám sát đáy
        
        auto_frame.columnconfigure(0, weight=1)
        auto_frame.columnconfigure(1, weight=1)

        # Đã set cứng trạng thái DISABLED mặc định cho nút chạy cấu hình
        self.btn_run_both = ttk.Button(auto_frame, text="▶ BƯỚC 2: CHẠY CẤU HÌNH", command=self.start_automation_both, state=DISABLED, bootstyle="primary")
        self.btn_run_both.grid(row=0, column=0, padx=2, sticky="ew")
        
        self.btn_stop = ttk.Button(auto_frame, text="⏹ DỪNG", command=self.stop_automation, state=DISABLED, bootstyle="danger")
        self.btn_stop.grid(row=0, column=1, padx=2, sticky="ew")

        # --- 3. Output & Results (PACK SAU CÙNG VỚI expand=True ĐỂ LẤP ĐẦY KHOẢNG TRỐNG Ở GIỮA) ---
        self.middle_paned = ttk.Panedwindow(tab_route, orient=VERTICAL)
        self.middle_paned.pack(side=TOP, fill=BOTH, expand=True)
        
        # --- Bảng Trạng Thái Thực Tế ---
        res_frame = ttk.Labelframe(self.middle_paned, text=" 📊 2. Trạng thái thực tế (Tham khảo) ", padding=5)
        self.middle_paned.add(res_frame, weight=1)
        
        cols = ("b_num", "node_c", "node_d")
        self.tree_results = ttk.Treeview(res_frame, columns=cols, show="headings", height=3, style="Bold.Treeview") # Giảm height xuống
        
        self.tree_results.heading("b_num", text="Số B-Number", anchor="center")
        self.tree_results.heading("node_c", text="TSSE2C", anchor="center")
        self.tree_results.heading("node_d", text="TSSE2D", anchor="center")
        
        self.tree_results.column("b_num", width=120, anchor="center")
        self.tree_results.column("node_c", width=250, anchor="center")
        self.tree_results.column("node_d", width=250, anchor="center")
        
        self.tree_results.tag_configure("res_ok", foreground="#198754", font=("Segoe UI", 9, "bold")) 
        self.tree_results.tag_configure("res_fail", foreground="#DC3545", font=("Segoe UI", 9, "bold")) 
        self.tree_results.tag_configure("res_inherited", foreground="#d35400", font=("Segoe UI", 9, "bold")) 
        self.tree_results.tag_configure("res_wait", foreground="#adb5bd", font=("Segoe UI", 9, "italic")) 
        self.tree_results.tag_configure("highlight", background="#fff3cd") 

        tree_scroll = ttk.Scrollbar(res_frame, orient="vertical", command=self.tree_results.yview)
        self.tree_results.configure(yscrollcommand=tree_scroll.set)
        self.tree_results.pack(side=LEFT, fill=BOTH, expand=True)
        tree_scroll.pack(side=RIGHT, fill=Y)

        self.tree_results.bind("<ButtonRelease-1>", self.sync_highlight_from_table)
        self.txt_input_numbers.bind("<ButtonRelease-1>", self.sync_highlight_from_input)
        self.txt_input_numbers.bind("<KeyRelease>", self.sync_highlight_from_input)

        # --- Lệnh MML Sẽ Thực Thi ---
        out_frame = ttk.Labelframe(self.middle_paned, text=" ⚙️ 3. Lệnh MML sẽ thực thi (Đã lọc) ", padding=5)
        self.middle_paned.add(out_frame, weight=1) # Hạ weight để cân đối với bảng
        self.txt_output_commands = scrolledtext.ScrolledText(out_frame, height=3, state='disabled', font=self.code_font, bg="#F8F9FA", relief="flat") # Giảm height xuống
        self.txt_output_commands.pack(fill=BOTH, expand=True)
        self.txt_output_commands.tag_configure("unprovisioned", foreground="#DC3545", font=(self.code_font[0], self.code_font[1], "bold"))
        # ================= TAB 2: UCTT =================
        uctt_frame = ttk.Labelframe(tab_uctt, text=" 🔄 Điều khiển Ứng cứu ", padding=12)
        uctt_frame.pack(fill=X, pady=10)
        
        uctt_ctrl = ttk.Frame(uctt_frame)
        uctt_ctrl.pack(fill=X, pady=5)
        
        ttk.Label(uctt_ctrl, text="Chọn RC:", font=self.bold_font, foreground=self.COLORS["text_dark_blue"]).pack(side=LEFT)
        rc_options = ["113", "114", "115 (115/1155/1157)"]
        self.uctt_rc_var.set("113")
        ttk.OptionMenu(uctt_ctrl, self.uctt_rc_var, "113", *rc_options).pack(side=LEFT, padx=10)
        
        self.btn_check_uctt = ttk.Button(uctt_ctrl, text="🔍 Kiểm tra", command=self.check_and_propose_uctt, bootstyle="secondary")
        self.btn_check_uctt.pack(side=LEFT, padx=5)
        
        self.btn_execute_changeover = ttk.Button(uctt_ctrl, text="🔀 Chuyển đổi...", command=lambda: self.execute_uctt_action("changeover"), state=DISABLED, bootstyle="secondary")
        self.btn_execute_changeover.pack(side=LEFT, padx=5)
        
        self.btn_execute_fallback = ttk.Button(uctt_ctrl, text="↩️ Fallback (ANRAR)", command=lambda: self.execute_uctt_action("fallback"), state=DISABLED, bootstyle="secondary")
        self.btn_execute_fallback.pack(side=LEFT, padx=5)
        
        self.btn_stop_uctt = ttk.Button(uctt_ctrl, text="⏹️ DỪNG", command=self.stop_automation, state=DISABLED, bootstyle="danger")
        self.btn_stop_uctt.pack(side=RIGHT)
        
        self.uctt_status_label = ttk.Label(uctt_frame, text="Trạng thái: Chưa kiểm tra", font=("Segoe UI", 11), foreground="#6C757D") 
        self.uctt_status_label.pack(fill=X, pady=15)
        
        self.uctt_commands_label = ttk.Label(uctt_frame, text="Lệnh sẽ chạy: ...", font=self.code_font, foreground="#6C757D")
        self.uctt_commands_label.pack(fill=X)

        # ================= RIGHT PANE: LOGS =================
        self.log_pane_dual = ttk.Panedwindow(right_pane, orient=VERTICAL)
        
        fr_c = ttk.Labelframe(self.log_pane_dual, text=" 📡 Console Log - TSSE2C ", padding=0) 
        self.log_pane_dual.add(fr_c, weight=1)
        # [SỬA] Thêm height=1 để ép nó tự co giãn theo PanedWindow xuống sát đáy
        self.log_c = scrolledtext.ScrolledText(fr_c, height=1, bg=self.COLORS["log_bg"], fg=self.COLORS["log_fg_c"], font=self.code_font, state='disabled', insertbackground="white", borderwidth=0)
        self.log_c.pack(fill=BOTH, expand=True)
        
        fr_d = ttk.Labelframe(self.log_pane_dual, text=" 📡 Console Log - TSSE2D ", padding=0)
        self.log_pane_dual.add(fr_d, weight=1)
        # [SỬA] Thêm height=1 
        self.log_d = scrolledtext.ScrolledText(fr_d, height=1, bg=self.COLORS["log_bg"], fg=self.COLORS["log_fg_d"], font=self.code_font, state='disabled', insertbackground="white", borderwidth=0)
        self.log_d.pack(fill=BOTH, expand=True)

        # 2. Khung chứa Log đơn (TSSN2D)
        self.log_frame_single = ttk.Labelframe(right_pane, text=" 🛡️ Console Log - TSSN2D ", padding=0)
        self.log_tssn2d = scrolledtext.ScrolledText(self.log_frame_single, height=1, bg=self.COLORS["log_bg"], fg="#E0AC00", font=self.code_font, state='disabled', insertbackground="white", borderwidth=0)
        self.log_tssn2d.pack(fill=BOTH, expand=True)

        # --- Bắt sự kiện chuyển Tab ---
        notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        self.CONFIG_FILE = "ssh_config.json"
        self._load_ssh_settings()

        # Auto Balance Layout (Tự động căn chỉnh tỉ lệ giống hệt bản Web Bootstrap)
        def initial_balance():
            try:
                self.root.update_idletasks() # Ép giao diện render xong để lấy kích thước thật
                
                # 1. Cột Trái (Khu vực 1, 2, 3, 4) vs Cột Phải (Log) -> Tỉ lệ 7:5 (Bootstrap col-md-7 và col-md-5)
                total_w = self.main_paned.winfo_width()
                if total_w > 1: 
                    self.main_paned.sashpos(0, int(total_w * 0.58)) # 58% cho cột Trái
                
                # 2. Bảng Trạng thái (3) vs Lệnh MML (4) -> Tỉ lệ 6:4 (Cho bảng kết quả dài hơn một chút)
                total_h_middle = self.middle_paned.winfo_height()
                if total_h_middle > 1: 
                    self.middle_paned.sashpos(0, int(total_h_middle * 0.60)) 
                
                # 3. Hai khung Log (TSSE2C và TSSE2D) -> Tỉ lệ 50/50 chính xác
                total_h_log = self.log_pane_dual.winfo_height()
                if total_h_log > 1: 
                    self.log_pane_dual.sashpos(0, int(total_h_log * 0.50))
            except Exception as e: 
                print(f"Lỗi cân bằng layout: {e}")

        # Chạy hàm này sau khi giao diện đã hiện lên (Chạy 2 lần để đảm bảo mượt)
        self.root.after(200, initial_balance)
        self.root.after(500, initial_balance)
        
        # --- [SỬA LỖI] KHỞI TẠO TAB LOGIC AN TOÀN ---
        def trigger_first_tab_check():
            # Tạo event giả lập CHUẨN, gán notebook vào widget
            mock_event = tk.Event()
            mock_event.widget = notebook
            # Gọi hàm chuyển tab thủ công
            self._on_tab_changed(mock_event)

        # Chạy sau 100ms để đảm bảo giao diện đã load
        self.root.after(100, trigger_first_tab_check)
        
        # Gán widget giả vào event để hàm không lỗi khi gọi thủ công
        event_mock = tk.Event()
        event_mock.widget = notebook
        self.root.after(100, lambda: self._on_tab_changed(event_mock))
        self.temp_check_results = {}
    
    # ================= FIX MÀU TERMINAL (CHỐNG THEME GHI ĐÈ) =================
        def force_dark_terminal():
            try:
                # Ép lại màu đen (#0D1117) sau khi Theme Light đã load xong
                self.log_c.config(state=tk.NORMAL, bg=self.COLORS["log_bg"], fg=self.COLORS["log_fg_c"])
                self.log_c.insert(tk.END, ">>> [TSSE2C] Secure Console Initialized. Ready for commands...\n")
                self.log_c.config(state=tk.DISABLED)

                self.log_d.config(state=tk.NORMAL, bg=self.COLORS["log_bg"], fg=self.COLORS["log_fg_d"])
                self.log_d.insert(tk.END, ">>> [TSSE2D] Secure Console Initialized. Ready for commands...\n")
                self.log_d.config(state=tk.DISABLED)

                self.log_tssn2d.config(state=tk.NORMAL, bg=self.COLORS["log_bg"], fg="#E0AC00")
                self.log_tssn2d.insert(tk.END, ">>> [TSSN2D] Secure Console Initialized. Ready for commands...\n")
                self.log_tssn2d.config(state=tk.DISABLED)
            except: pass

        # Gọi hàm này sau 150ms (Đợi hệ thống vẽ xong giao diện trắng thì mình đè màu đen lên)
        self.root.after(150, force_dark_terminal)
        
    def _on_tab_changed(self, event):
        """Tự động chuyển đổi giao diện Log dựa trên Tab đang chọn (Logic ID)"""
        try:
            # [SỬA] Kiểm tra an toàn: Nếu event không có widget, thoát luôn
            if not hasattr(event, 'widget'):
                return

            notebook = event.widget
            
            # [SỬA] Kiểm tra nếu notebook chưa chọn được tab nào
            if not notebook.select():
                return

            current_tab_id = notebook.select() # Lấy ID của tab hiện tại
            
            # Ẩn tất cả trước
            if hasattr(self, 'log_pane_dual'):
                self.log_pane_dual.pack_forget()
            if hasattr(self, 'log_frame_single'):
                self.log_frame_single.pack_forget()
            
            # Kiểm tra: Nếu tab hiện tại là tab A2P (so sánh ID widget)
            if hasattr(self, 'a2p_tab') and current_tab_id == str(self.a2p_tab.frame):
                self.log_frame_single.pack(fill=BOTH, expand=True, padx=(5,0))
                
                # [MỚI] Tự động chạy Bước 1 khi vừa mở Tab A2P lần đầu tiên
                if not getattr(self.a2p_tab, 'has_auto_fetched', False):
                    self.a2p_tab.has_auto_fetched = True
                    # Delay nhẹ 400ms để giao diện render mượt mà trước khi chạy SSH
                    self.root.after(400, self.a2p_tab.fetch_current_data)
                    
            else:
                # Mặc định hiện log đôi cho các tab khác
                if hasattr(self, 'log_pane_dual'):
                    self.log_pane_dual.pack(fill=BOTH, expand=True, padx=(5,0))
                    
        except Exception as e:
            print(f"Lỗi chuyển tab (đã xử lý): {e}")

    # --- Cập nhật hàm log_message ---
    def log_message(self, message, node=None):
        """
        Hàm ghi log trung tâm:
        1. Ghi vào file log (logs/yyyy-mm-dd.log)
        2. Hiển thị lên giao diện GUI tương ứng với Node.
        """
        # --- 1. GHI FILE LOG (Back-end) ---
        if hasattr(self, 'logger') and self.logger:
            log_tag = "SYSTEM"
            if node: log_tag = node
            try:
                self.logger.info(f"[{log_tag}] {message}")
            except Exception: 
                pass

        # --- 2. HÀM CẬP NHẬT GIAO DIỆN (Front-end) ---
        def _update_gui(widget, msg, is_tssn2d=False):
            try:
                # Nếu là TSSN2D, kiểm tra xem widget có đang hiện không
                if is_tssn2d:
                    if hasattr(self, 'log_frame_single') and not self.log_frame_single.winfo_ismapped():
                        # Nếu chưa hiện -> Ẩn log đôi, hiện log đơn ngay
                        if hasattr(self, 'log_pane_dual'): self.log_pane_dual.pack_forget()
                        self.log_frame_single.pack(fill=tk.BOTH, expand=True, padx=(5,0))
                
                # Mở khóa widget để ghi
                widget.configure(state='normal')
                
                # Insert tin nhắn (Tự động thêm xuống dòng nếu chưa có)
                if not msg.endswith("\n"):
                    msg += "\n"
                widget.insert(tk.END, msg)
                
                # Cuộn xuống cuối cùng để thấy tin mới nhất
                widget.see(tk.END)
                
                # Khóa lại (Read-only)
                widget.configure(state='disabled')
            except Exception as e:
                print(f"GUI LOG ERROR: {e}")

        # --- 3. ĐIỀU HƯỚNG TIN NHẮN VÀO ĐÚNG Ô ---
        # Ưu tiên xử lý TSSN2D trước vì đây là cái bạn đang cần debug
        if node == "TSSN2D":
            if hasattr(self, 'log_tssn2d'):
                self.root.after(0, lambda: _update_gui(self.log_tssn2d, message, is_tssn2d=True))
            else:
                # Fallback nếu chưa khởi tạo log_tssn2d (hiếm gặp)
                print(f"[TSSN2D_raw] {message}")

        elif node == "TSSE2C":
            if hasattr(self, 'log_c'):
                self.root.after(0, lambda: _update_gui(self.log_c, message))

        elif node == "TSSE2D":
            if hasattr(self, 'log_d'):
                self.root.after(0, lambda: _update_gui(self.log_d, message))

        elif node == "SYSTEM":
            # Log hệ thống thì hiện vào ô log đang active hoặc mặc định log_c
            target_widget = self.log_c if hasattr(self, 'log_c') else None
            # Nếu đang ở tab A2P (TSSN2D), có thể bạn muốn hiện system log vào đó luôn
            if hasattr(self, 'log_tssn2d') and self.log_tssn2d.winfo_ismapped():
                target_widget = self.log_tssn2d
            
            if target_widget:
                self.root.after(0, lambda: _update_gui(target_widget, message))

        else:
            # Mặc định tất cả cái khác vào log_c
            if hasattr(self, 'log_c'):
                self.root.after(0, lambda: _update_gui(self.log_c, message))
            
    # [Dán vào class SipRouterApp]
    def setup_file_logging(self):
        """Thiết lập file log: logs/Năm-Tháng/User_Ngày_PID.log"""
        try:
            now = datetime.now()
            
            # Lấy đường dẫn gốc an toàn
            if getattr(sys, 'frozen', False):
                base_dir = os.path.dirname(sys.executable)
            else:
                base_dir = os.path.dirname(os.path.abspath(__file__))
            
            base_log_dir = os.path.join(base_dir, "logs")
            if not os.path.exists(base_log_dir): os.makedirs(base_log_dir)
                
            # Thư mục theo tháng
            month_dir = now.strftime("%Y-%m")
            log_dir = os.path.join(base_log_dir, month_dir)
            if not os.path.exists(log_dir): os.makedirs(log_dir)
            
            # --- TÊN FILE CHỨA USER VÀ PID (QUAN TRỌNG CHO MULTI-USER) ---
            current_user = os.environ.get('USERNAME', 'UnknownUser')
            pid = os.getpid()
            timestamp = now.strftime("%Y-%m-%d")
            
            # Ví dụ: NGHIAP_2023-10-30_1234.log
            log_filename = f"{current_user}_{timestamp}_{pid}.log"
            log_filepath = os.path.join(log_dir, log_filename)
            
            # Setup Logger
            self.logger = logging.getLogger("SipRouterAppLogger")
            self.logger.setLevel(logging.INFO)
            if self.logger.hasHandlers(): self.logger.handlers.clear()

            handler = logging.FileHandler(log_filepath, encoding="utf-8")
            formatter = logging.Formatter("%(asctime)s - %(message)s", datefmt="%H:%M:%S")
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            
            self.logger.info("="*30)
            self.logger.info(f"User: {current_user} | PID: {pid} | Log: {log_filename}")
            self.logger.info("="*30)
            
        except Exception as e:
            print(f"Lỗi tạo file log: {e}")
            self.logger = None
    
    def _on_rc_selection_change(self, *args):
        """(MỚI) Tự động reset trạng thái nút khi người dùng đổi RC khác"""
        
        # [FIX QUAN TRỌNG] Kiểm tra xem nút đã được khởi tạo chưa. 
        # Nếu chưa (do hàm chạy lúc khởi động app), thì thoát ngay để tránh lỗi AttributeError.
        if not hasattr(self, 'btn_execute_changeover') or not hasattr(self, 'btn_execute_fallback'):
            return

        # Nếu đang chạy thread thì không reset giao diện để tránh xung đột
        if self.running_threads > 0:
            return

        # 1. Vô hiệu hóa nút lệnh
        try:
            self.btn_execute_changeover.config(state=tk.DISABLED, text="Chuyển đổi...")
            self.btn_execute_fallback.config(state=tk.DISABLED)
        except Exception:
            pass # Bỏ qua nếu giao diện đang bị hủy
        
        # 2. Reset label trạng thái
        new_rc = self.uctt_rc_var.get()
        if hasattr(self, 'uctt_status_label'):
            self.uctt_status_label.config(text=f"Trạng thái RC={new_rc}: Chưa kiểm tra", foreground="#6C757D") # Màu xám
        
        if hasattr(self, 'uctt_commands_label'):
            self.uctt_commands_label.config(text="Lệnh sẽ chạy: ...", foreground="gray")

        # 3. Xóa dữ liệu cũ trong bộ nhớ
        self.proposed_changeover_action = None
        self.proposed_fallback_action = None
        self.selected_uctt_rc = None # Quan trọng: Xóa RC đã check cũ
        self.commands_to_execute_changeover = []
        self.commands_to_execute_fallback = []
        
    
    def _set_placeholder(self, event=None):
        """Đặt văn bản placeholder vào ô input"""
        self.txt_input_numbers.config(state=tk.NORMAL)
        self.txt_input_numbers.delete("1.0", tk.END)
        self.txt_input_numbers.insert("1.0", self.placeholder_text)
        self.txt_input_numbers.tag_add("placeholder", "1.0", "end")
        self.txt_input_numbers.mark_set("insert", "1.0")


    def _on_focus_in(self, event=None):
        """Xóa placeholder VÀ tag màu cũ khi click vào"""
        try: self.txt_input_numbers.config(state=tk.NORMAL)
        except: pass 
        
        self.txt_input_numbers.tag_remove("ok_action", "1.0", tk.END)
        self.txt_input_numbers.tag_remove("bad_action", "1.0", tk.END)
        self.txt_input_numbers.tag_remove("check_comment", "1.0", tk.END)
        self.txt_input_numbers.tag_remove("error_comment", "1.0", tk.END)

        tags = self.txt_input_numbers.tag_names("1.0")
        if "placeholder" in tags:
            self.txt_input_numbers.delete("1.0", tk.END)
            self.txt_input_numbers.tag_remove("placeholder", "1.0", "end")
        

    def _on_focus_out(self, event=None):
        """Đặt lại placeholder nếu ô trống khi click ra ngoài"""
        content = self.txt_input_numbers.get("1.0", tk.END)
        if not content.strip():
            self.txt_input_numbers.config(state=tk.NORMAL)
            self.txt_input_numbers.tag_remove("ok_action", "1.0", tk.END)
            self.txt_input_numbers.tag_remove("bad_action", "1.0", tk.END)
            self.txt_input_numbers.tag_remove("check_comment", "1.0", tk.END)
            self.txt_input_numbers.tag_remove("error_comment", "1.0", tk.END)
            self.txt_input_numbers.tag_remove("placeholder", "1.0", tk.END)
            
            self.txt_input_numbers.delete("1.0", tk.END)
            self._set_placeholder()
    
    def _auto_toggle_check_btn(self):
        """Vòng lặp ngầm: Bật/Tắt nút Kiểm tra ngay lập tức (Thời gian thực)"""
        try:
            # Chỉ cập nhật nút khi KHÔNG có tiến trình SSH nào đang chạy để tránh xung đột
            if getattr(self, 'running_threads', 0) == 0 and hasattr(self, 'btn_run_check'):
                content = self.txt_input_numbers.get("1.0", tk.END).strip()
                tags = self.txt_input_numbers.tag_names("1.0")
                
                # Nếu là chữ mờ (placeholder) hoặc ô bị xóa trống -> Khóa nút
                if "placeholder" in tags or not content:
                    self.btn_run_check.config(state=tk.DISABLED)
                else:
                    self.btn_run_check.config(state=tk.NORMAL)
        except Exception:
            pass
            
        # Tự động lặp lại quy trình này mỗi 200ms (Cực nhẹ, không hề tốn CPU)
        self.root.after(200, self._auto_toggle_check_btn)
        
        # --- HÀM TẠO BỘ LỆNH UCTT ---
    def _generate_uctt_command_sets(self, selected_rc_raw):
        """(SỬA) Tạo các bộ lệnh gộp cho 1 hoặc nhiều RC"""
        
        rc_list = self._get_rc_list_from_selection(selected_rc_raw)
        
        sets = {
            'check_nop': [],
            'check_op': [],
            'fallback': [],
            'uctt_2': [],
            'uctt_1_sip': [],
            'uctt_1_analog': []
        }

        for rc_str in rc_list:
            # Lệnh kiểm tra NOP
            sets['check_nop'].append(f"ANRSP:RC={rc_str},NOP;")
            # Lệnh kiểm tra OP
            sets['check_op'].append(f"ANRSP:RC={rc_str};")
            # Lệnh Fallback
            sets['fallback'].append(f"ANRAR:RC={rc_str};")
            # Lệnh UCTT-2 (Kích hoạt từ NOP)
            sets['uctt_2'].append(f"ANRAI:RC={rc_str};")

            # Bộ lệnh UCTT-1 (Tạo mới sang SIP/CSCF)
            sets['uctt_1_sip'].extend([
                f"ANRPI:RC={rc_str};",
                "ANRSI:P01=1,SP=MM1,ESS=1,ESR=1,R=CSCF2CO;",
                "ANRSI:P01=2,SP=MM1,ESS=1,ESR=1,R=CSCF2BO;",
                "ANRPE;",
                f"ANRAI:RC={rc_str};"
            ])
            # Bộ lệnh UCTT-1 (Tạo mới sang Analog/TSN2D)
            sets['uctt_1_analog'].extend([
                f"ANRPI:RC={rc_str};",
                "ANRSI:P01=1,SP=MM1,ESS=1,ESR=1,R=TSN2DO;",
                "ANRPE;",
                f"ANRAI:RC={rc_str};"
            ])
            
        return sets

    # --- HÀM KIỂM TRA & ĐỀ XUẤT (ĐÃ UPDATE LOGIC FALLBACK 24H) ---
    def check_and_propose_uctt(self):
        """Kiểm tra trạng thái UCTT trên cả 2 node và đề xuất hành động"""
        rc_raw = self.uctt_rc_var.get()
        if not rc_raw:
            messagebox.showerror("Lỗi", "Vui lòng chọn số RC.")
            return

        # --- [SỬA LỖI NỀN TRẮNG] ---
        try:
            # Xử lý Log C (TSSE2C)
            self.log_c.config(state=tk.NORMAL, bg=self.COLORS["log_bg"], fg=self.COLORS["log_fg_c"]) 
            self.log_c.delete('1.0', tk.END)
            self.log_c.config(state=tk.DISABLED, bg=self.COLORS["log_bg"], fg=self.COLORS["log_fg_c"])
            
            # Xử lý Log D (TSSE2D)
            self.log_d.config(state=tk.NORMAL, bg=self.COLORS["log_bg"], fg=self.COLORS["log_fg_d"])
            self.log_d.delete('1.0', tk.END)
            self.log_d.config(state=tk.DISABLED, bg=self.COLORS["log_bg"], fg=self.COLORS["log_fg_d"])
            
            self.log_message(f"--- Đã xóa log cũ để kiểm tra RC={rc_raw} ---", node="SYSTEM")
        except: pass
        # ---------------------------

        # Reset UI
        self.uctt_status_label.config(text=f"Trạng thái RC={rc_raw}: Đang kiểm tra 2C & 2D...", foreground=self.COLORS["primary"][0])
        self.btn_execute_changeover.config(state=tk.DISABLED, text="Chuyển đổi...")
        self.btn_execute_fallback.config(state=tk.DISABLED)
        self.uctt_commands_label.config(text="Lệnh sẽ chạy: (Chưa có)", foreground="gray")
        
        self.proposed_changeover_action = None
        self.proposed_fallback_action = None
        self.selected_uctt_rc = rc_raw

        host_c = self.ssh_details.get('host_c')
        host_d = self.ssh_details.get('host_d')
        user = self.ssh_details.get('user')
        pw = self.ssh_details.get('pass')

        if not host_c or not host_d or not user:
             messagebox.showerror("Lỗi", "Chưa cài đặt đủ SSH cho TSSE2C và TSSE2D.")
             return

        command_sets = self._generate_uctt_command_sets(rc_raw)
        check_op_cmds = command_sets['check_op']
        check_nop_cmds = command_sets['check_nop']

        results = {"TSSE2C": None, "TSSE2D": None, "error": None}
        results_lock = threading.Lock()

        def check_node_status(host, node_name):
            status = self._get_uctt_status_from_node(host, user, pw, node_name, rc_raw, check_op_cmds, check_nop_cmds)
            with results_lock:
                results[node_name] = status
                if isinstance(status, Exception) and not results["error"]:
                    results["error"] = f"Lỗi {node_name}: {status}"

        # Kích hoạt trạng thái đang chạy
        self.stop_event.clear()
        self.running_threads = 2
        self.update_button_states()

        thread_c = threading.Thread(target=check_node_status, args=(host_c, "TSSE2C"))
        thread_d = threading.Thread(target=check_node_status, args=(host_d, "TSSE2D"))
        thread_c.daemon = True
        thread_d.daemon = True
        thread_c.start()
        thread_d.start()

        wait_thread = threading.Thread(target=self._wait_and_process_uctt_check, args=(thread_c, thread_d, results, rc_raw))
        wait_thread.daemon = True
        wait_thread.start()

    # --- HÀM XỬ LÝ KẾT QUẢ ---
    def _wait_and_process_uctt_check(self, thread_c, thread_d, results, rc_raw):
        thread_c.join()
        thread_d.join()

        def process_results():
            # [FIX] Reset trạng thái để tắt nút Dừng
            self.running_threads = 0
            self.update_button_states()

            status_c = results["TSSE2C"]
            status_d = results["TSSE2D"]
            error = results.get("error")

            final_status_text = f"Trạng thái RC={rc_raw}: "
            
            # --- XỬ LÝ LỖI ---
            if error:
                final_status_text += str(error)
                self.uctt_status_label.config(text=final_status_text, foreground=self.COLORS["danger"][0])
                return
            elif isinstance(status_c, Exception) or isinstance(status_d, Exception):
                final_status_text += "Lỗi kết nối hoặc lệnh."
                self.uctt_status_label.config(text=final_status_text, foreground=self.COLORS["danger"][0])
                return
            elif status_c != status_d:
                final_status_text += "KHÔNG ĐỒNG BỘ!"
                self.uctt_status_label.config(text=final_status_text, foreground=self.COLORS["danger"][0])
                messagebox.showerror("Lỗi", "Trạng thái 2 node không đồng bộ! Vui lòng kiểm tra tay.")
                return

            # --- LOGIC HIỂN THỊ NÚT THÔNG MINH ---
            op_state = status_c['op']
            nop_state = status_c['nop']
            
            final_status_text += f"OP: {op_state}, NOP: {nop_state} [Đồng bộ]"
            self.uctt_status_label.config(text=final_status_text, foreground=self.COLORS["success"][0])
            
            # Chuẩn bị lệnh
            command_sets = self._generate_uctt_command_sets(rc_raw)
            # Mặc định lấy fallback thường (ANRAR), sẽ bị override nếu rơi vào case 24h
            self.commands_to_execute_fallback = command_sets['fallback']
            
            # [QUAN TRỌNG] Reset nút Fallback về Disabled trước
            self.btn_execute_fallback.config(state=tk.DISABLED, text="Fallback (Không khả dụng)")
            
            # 1. TRƯỜNG HỢP ĐANG CHẠY SIP (BÌNH THƯỜNG)
            if op_state == "sip":
                # Fallback bị tắt (Disabled) vì đang ở SIP rồi
                self.btn_execute_fallback.config(text="Fallback (Đang ở SIP)")
                
                if nop_state == "analog":
                    # Đã có NOP Analog -> Chỉ cần kích hoạt (UCTT-2)
                    self.proposed_changeover_action = "uctt_2"
                    self.commands_to_execute_changeover = command_sets['uctt_2']
                    self.btn_execute_changeover.config(state=tk.NORMAL, text="Kích hoạt Analog (ANRAI)")
                else:
                    # Chưa có NOP -> Phải tạo mới và kích hoạt (UCTT-1)
                    self.proposed_changeover_action = "uctt_1_analog"
                    self.commands_to_execute_changeover = command_sets['uctt_1_analog']
                    self.btn_execute_changeover.config(state=tk.NORMAL, text="Tạo & Chuyển sang Analog")
                
                # Thiết lập hành động fallback (dù nút bị disable nhưng vẫn nạp lệnh cho chắc)
                self.proposed_fallback_action = "fallback"

            # 2. TRƯỜNG HỢP ĐANG CHẠY ANALOG (ĐANG ỨNG CỨU)
            elif op_state == "analog":
                # [UPDATE QUAN TRỌNG] Logic Fallback (Chiều về)
                
                if nop_state == "sip":
                    # Trường hợp A: NOP còn giữ cấu hình SIP -> Dùng ANRAR (Fallback thường)
                    self.proposed_fallback_action = "fallback"
                    self.commands_to_execute_fallback = command_sets['fallback']
                    self.btn_execute_fallback.config(state=tk.NORMAL, text="Fallback về SIP (ANRAR)")
                else:
                    # Trường hợp B (Sau 24h): NOP bị rỗng -> Dùng bộ lệnh MÀU XANH (Tạo lại SIP)
                    # Bộ lệnh uctt_1_sip gồm: ANRPI -> 2 lệnh ANRSI (CSCF) -> ANRPE -> ANRAI
                    self.proposed_fallback_action = "uctt_1_sip"
                    self.commands_to_execute_fallback = command_sets['uctt_1_sip']
                    self.btn_execute_fallback.config(state=tk.NORMAL, text="Tạo & Fallback về SIP (Lệnh Xanh)")
                
                # Khi đang ứng cứu thì khóa nút đi ứng cứu
                self.btn_execute_changeover.config(state=tk.DISABLED, text="Đang chạy Analog")

            # 3. TRƯỜNG HỢP KHÁC (Normal/Empty...)
            else:
                self.btn_execute_fallback.config(state=tk.DISABLED)
                if nop_state == "analog":
                    self.proposed_changeover_action = "uctt_2"
                    self.commands_to_execute_changeover = command_sets['uctt_2']
                    self.btn_execute_changeover.config(state=tk.NORMAL, text="Kích hoạt UCTT Analog")
                elif nop_state == "sip":
                     self.proposed_changeover_action = "uctt_2"
                     self.commands_to_execute_changeover = command_sets['uctt_2']
                     self.btn_execute_changeover.config(state=tk.NORMAL, text="Kích hoạt UCTT SIP")
                else:
                    self.proposed_changeover_action = "uctt_1_analog"
                    self.commands_to_execute_changeover = command_sets['uctt_1_analog']
                    self.btn_execute_changeover.config(state=tk.NORMAL, text="Tạo & Kích hoạt UCTT Analog")

        self.root.after(0, process_results)

    # --- HÀM WORKER (SSH) ---
    def _get_uctt_status_from_node(self, host, user, pw, node_name, selected_rc_raw, check_op_cmds, check_nop_cmds):
        """Chạy kiểm tra OP/NOP, log lỗi chi tiết"""
        log = lambda msg: self.log_message(msg, node=node_name)
        shell = None
        ssh = None
        
        if self.stop_event.is_set(): return Exception("Người dùng đã dừng.")

        rc_list = self._get_rc_list_from_selection(selected_rc_raw)
        
        try:
            log(f"Đang kết nối SSH tới {host}...") 
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(host, username=user, password=pw, timeout=10) 
            
            shell = ssh.invoke_shell()
            time.sleep(1); self.read_shell_output(shell, timeout=1, node=node_name)
            
            if not self.send_and_wait(shell, "mml -a", "<", timeout=10, node=node_name):
                raise Exception("Lỗi: Không vào được chế độ MML")

            node_results = {}
            for i, rc_item in enumerate(rc_list):
                if self.stop_event.is_set(): raise Exception("Dừng bởi người dùng.")
                
                log(f"Kiểm tra OP (RC={rc_item})...")
                shell.send(check_op_cmds[i] + "\n")
                op_output = self._read_until_prompt_or_end(shell, ["END", "<"], timeout=15, node=node_name)
                
                rc_result = {'op': 'normal', 'nop': 'empty'}
                
                # [FIX] Sửa logic so sánh: Tìm từ khóa 'CSCF' hoặc 'TSN' bất kỳ
                if "CSCF" in op_output: rc_result['op'] = 'sip'
                elif "TSN" in op_output: rc_result['op'] = 'analog'
                
                log(f"Kiểm tra NOP (RC={rc_item})...")
                shell.send(check_nop_cmds[i] + "\n")
                nop_output = self._read_until_prompt_or_end(shell, ["END", "<"], timeout=15, node=node_name)
                
                # [FIX] Tương tự cho NOP
                if "CSCF" in nop_output: rc_result['nop'] = 'sip'
                elif "TSN" in nop_output: rc_result['nop'] = 'analog'
                
                node_results[rc_item] = rc_result

            first_result = node_results[rc_list[0]]
            log(f"Hoàn tất. Kết quả: {first_result}")
            return first_result

        except Exception as e:
            # [FIX] Log lỗi ra màn hình
            log(f"!!! LỖI KẾT NỐI/KIỂM TRA: {e}") 
            return e 
        finally:
            if shell: 
                try: shell.close() 
                except: pass
            if ssh: 
                try: ssh.close() 
                except: pass
                
                
    
    # --- HÀM THỰC THI KIỂM TRA (TRONG THREAD) ---
    def _run_uctt_check_thread(self, host, user, pw, node_name, rc, check_op_cmd, check_nop_cmd):
        """Chạy lệnh kiểm tra ANRSP và ANRSP NOP trên SSH"""
        log = lambda msg: self.log_message(msg, node=node_name) # Log vào đúng ô
        status_update = lambda text, color: self.root.after(0, lambda: self.uctt_status_label.config(text=text, fg=color))
        button_update = lambda state, text: self.root.after(0, lambda: self.btn_execute_uctt.config(state=state, text=text))

        shell = None
        ssh = None
        current_status = "Lỗi: Không xác định"
        proposed_action = None
        button_text = "Lỗi"
        op_output = ""
        nop_output = ""

        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(host, username=user, password=pw, timeout=10)
            shell = ssh.invoke_shell()
            time.sleep(1)
            self.read_shell_output(shell, timeout=1, node=node_name) # Dọn rác

            if not self.send_and_wait(shell, "mml -a", "<", timeout=10, node=node_name):
                raise Exception("Không vào được MML")

            # 1. Kiểm tra OP Area
            log(f"Kiểm tra OP Area: {check_op_cmd}")
            shell.send(check_op_cmd + "\n")
            op_output = self._read_until_prompt_or_end(shell, ["END", "<"], timeout=15, node=node_name)
            log(f"Output OP:\n{op_output}")
            self.send_and_wait(shell, "", "<", timeout=5, node=node_name) # Refresh

            # Phân tích OP Output
            is_sip_active = "R=CSCF2CO" in op_output or "R=CSCF2BO" in op_output
            is_analog_active = "R=TSN2DO" in op_output

            if is_sip_active:
                current_status = f"Hiện tại RC={rc}: SIP (CSCF)"
                proposed_action = "fallback"
                button_text = f"Thực hiện Fallback RC={rc}"
            elif is_analog_active:
                current_status = f"Hiện tại RC={rc}: Analog (TSN2D)"
                proposed_action = "fallback"
                button_text = f"Thực hiện Fallback RC={rc}"
            else:
                current_status = f"Hiện tại RC={rc}: Bình thường. Kiểm tra NOP..."
                status_update(current_status, "blue") # Cập nhật tạm thời

                # 2. Kiểm tra NOP Area (chỉ khi OP bình thường)
                log(f"Kiểm tra NOP Area: {check_nop_cmd}")
                shell.send(check_nop_cmd + "\n")
                nop_output = self._read_until_prompt_or_end(shell, ["END", "<"], timeout=15, node=node_name)
                log(f"Output NOP:\n{nop_output}")
                self.send_and_wait(shell, "", "<", timeout=5, node=node_name) # Refresh

                # Phân tích NOP Output - Cần cách xác định "có data" chính xác hơn
                # Tạm thời: Kiểm tra có dòng R=... không (ngoài header)
                nop_lines = nop_output.strip().splitlines()
                has_nop_data = False
                for line in nop_lines:
                    line_strip = line.strip()
                    if line_strip.startswith("RC"): continue # Bỏ qua header
                    if line_strip.startswith("END"): continue
                    if line_strip.startswith("<"): continue
                    if "R=" in line_strip: # Nếu có dòng cấu hình R=...
                        has_nop_data = True
                        break
                    # Có thể cần kiểm tra thêm trường hợp "NO DATA EXIST"

                if has_nop_data:
                    current_status = f"Hiện tại RC={rc}: Bình thường (Có cấu hình NOP sẵn)"
                    proposed_action = "uctt_2"
                    button_text = f"Kích hoạt UCTT RC={rc} (ANRAI)"
                else:
                    current_status = f"Hiện tại RC={rc}: Bình thường (Chưa có cấu hình NOP)"
                    proposed_action = "uctt_1_analog" # Mặc định tạo UCTT sang Analog
                    button_text = f"Tạo & Kích hoạt UCTT RC={rc} sang Analog"

        except Exception as e:
            log(f"Lỗi khi kiểm tra UCTT: {e}")
            current_status = f"Trạng thái RC={rc}: Lỗi kiểm tra ({e})"
            proposed_action = None
            status_update(current_status, "red")
            return # Thoát sớm
        finally:
            if shell:
                try: shell.send("exit;\n"); time.sleep(0.5); shell.close()
                except: pass
            if ssh:
                try: ssh.close()
                except: pass

        # Cập nhật UI cuối cùng
        status_update(current_status, "green" if proposed_action else "red")
        if proposed_action:
            self.proposed_uctt_action = proposed_action
            button_update(tk.NORMAL, button_text)
        else:
            button_update(tk.DISABLED, "Lỗi")

    # --- HÀM HELPER ĐỌC OUTPUT CHO KIỂM TRA ---
    def _read_until_prompt_or_end(self, shell, end_markers, timeout=15, node=None):
        """
        (SỬA) Đọc output và IN RA LOG NGAY LẬP TỨC để người dùng thấy thiết bị trả lời.
        """
        output = ""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            if self.stop_event.is_set(): break 
            
            # Đọc dữ liệu mới
            new_output = self.read_shell_output(shell, timeout=0.5, node=node)
            
            if new_output:
                # --- [FIX QUAN TRỌNG] In ra log ngay khi nhận được ---
                # Strip nhẹ để log không bị quá nhiều dòng trống, nhưng giữ nội dung
                if new_output.strip():
                    self.log_message(new_output, node=node)
                # -----------------------------------------------------
                
                output += new_output
                
                # Kiểm tra xem đã có marker kết thúc chưa (END hoặc <)
                if any(marker in output for marker in end_markers):
                    break
            
            time.sleep(0.1) 
            
        return output

    def execute_uctt_action(self, action_type):
        """
        Phiên bản Debug: Bắt lỗi và hiển thị popup nếu có sự cố khi bấm nút.
        """
        try:
            # 1. Lấy dữ liệu từ bộ nhớ
            rc_raw = self.selected_uctt_rc
            action = None
            commands_to_run = []
            button_text = ""

            # 2. Xác định hành động dựa trên loại nút bấm
            if action_type == "changeover":
                action = self.proposed_changeover_action
                commands_to_run = self.commands_to_execute_changeover
                # Kiểm tra an toàn: Nút có tồn tại không?
                if hasattr(self, 'btn_execute_changeover'):
                    button_text = self.btn_execute_changeover.cget('text')
                else:
                    button_text = "Chuyển đổi"
                    
            elif action_type == "fallback":
                action = self.proposed_fallback_action
                commands_to_run = self.commands_to_execute_fallback
                if hasattr(self, 'btn_execute_fallback'):
                    button_text = self.btn_execute_fallback.cget('text')
                else:
                    button_text = "Fallback"
            else:
                messagebox.showerror("Lỗi Code", f"Loại hành động không hợp lệ: {action_type}")
                return

            # 3. [FIX] Kiểm tra dữ liệu và BÁO LỖI CỤ THỂ nếu thiếu
            # Đây là nguyên nhân chính khiến nút "im lặng" nếu không có check này
            missing_info = []
            if not action: missing_info.append("- Không xác định được hành động (Action is None)")
            if not rc_raw: missing_info.append("- Mất thông tin RC đang chọn (RC is None)")
            if not commands_to_run: missing_info.append("- Danh sách lệnh rỗng (List is Empty)")

            if missing_info:
                msg = "\n".join(missing_info)
                messagebox.showwarning("Dữ liệu chưa sẵn sàng", 
                    f"Không thể thực hiện '{button_text}'.\n\nLý do:\n{msg}\n\n👉 Vui lòng bấm nút 'Kiểm tra' lại trước khi thực hiện.")
                return

            # 4. Hiển thị lệnh trong messagebox xác nhận
            cmd_preview = commands_to_run[:5]
            commands_display_confirm = "\n".join(cmd_preview)
            if len(commands_to_run) > 5:
                 commands_display_confirm += f"\n... và {len(commands_to_run) - 5} lệnh nữa."
            
            confirm = messagebox.askyesno("Xác nhận thực thi", 
                f"Bạn có chắc muốn thực hiện:\n'{button_text}'\n\n"
                f"• RC mục tiêu: {rc_raw}\n"
                f"• Tổng số lệnh: {len(commands_to_run)}\n\n"
                f"Chi tiết các lệnh đầu tiên:\n{commands_display_confirm}")
            
            if not confirm:
                return

            # 5. Cập nhật giao diện (Khóa nút ngay lập tức)
            if hasattr(self, 'btn_execute_changeover'):
                self.btn_execute_changeover.config(state=tk.DISABLED)
            if hasattr(self, 'btn_execute_fallback'):
                self.btn_execute_fallback.config(state=tk.DISABLED)
                
            self.uctt_status_label.config(text=f"Trạng thái RC={rc_raw}: Đang thực hiện '{button_text}'...", foreground="#fd7e14") # Màu cam
            self.uctt_commands_label.config(text="Lệnh sẽ chạy: (Đang thực hiện...)", foreground="gray")

            # 6. Chạy Thread xử lý (Logic giữ nguyên)
            user = self.ssh_details['user']
            pw = self.ssh_details['pass']
            host_c = self.ssh_details['host_c']
            host_d = self.ssh_details['host_d']
            effective_action_name = action

            thread_c = threading.Thread(target=self._run_uctt_execution_thread, args=(host_c, user, pw, "TSSE2C", rc_raw, effective_action_name, commands_to_run))
            thread_d = threading.Thread(target=self._run_uctt_execution_thread, args=(host_d, user, pw, "TSSE2D", rc_raw, effective_action_name, commands_to_run))
            
            thread_c.daemon = True
            thread_d.daemon = True

            self.running_threads += 2
            self.stop_event.clear()
            self.update_button_states()

            self.log_message(f"--- Bắt đầu thực hiện '{button_text}' cho RC={rc_raw} ---", node="SYSTEM")
            
            thread_c.start()
            thread_d.start()

            # 7. Reset dữ liệu sau khi đã gửi lệnh đi
            self.proposed_changeover_action = None
            self.proposed_fallback_action = None
            self.selected_uctt_rc = None
            self.commands_to_execute_changeover = []
            self.commands_to_execute_fallback = []

        except Exception as e:
            # Bắt lỗi ẩn và hiển thị lên màn hình thay vì im lặng
            import traceback
            traceback.print_exc() # In ra console đen nếu có
            messagebox.showerror("Lỗi Ngoại Lệ (Exception)", f"Đã xảy ra lỗi khi bấm nút:\n{str(e)}\n\n(Xem chi tiết trong Console Log)")
        
    # --- HÀM THỰC THI UCTT (TRONG THREAD) ---
    def _run_uctt_execution_thread(self, host, user, pw, node_name, rc_raw, action, commands):
        """
        (ĐÃ SỬA FINAL) Chạy bộ lệnh UCTT trực tiếp.
        - KHÔNG DÙNG ANBLI (Transaction).
        - Gửi lệnh ngay sau khi vào MML.
        """
        log = lambda msg: self.log_message(msg, node=node_name)
        status_update = lambda text, color: self.root.after(0, lambda: self.uctt_status_label.config(text=text, fg=color))

        shell = None
        ssh = None
        success = False
        try:
            # 1. Kết nối SSH
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(host, username=user, password=pw, timeout=10)
            shell = ssh.invoke_shell()
            time.sleep(1)
            
            # 2. Dọn dẹp phiên cũ (nếu có)
            initial = self.read_shell_output(shell, timeout=1, node=node_name)
            if initial.strip(): log(f"RECV (init): {initial.strip()}")
            try: shell.send("exit;\n"); time.sleep(0.5); self.read_shell_output(shell, timeout=1, node=node_name)
            except: pass

            # 3. Vào chế độ MML
            if not self.send_and_wait(shell, "mml -a", "<", timeout=10, node=node_name):
                raise Exception("Không vào được MML")

            # --- [QUAN TRỌNG] ĐÃ BỎ KHỐI ANBLI TẠI ĐÂY ---
            # Code sẽ chạy thẳng vào việc gửi lệnh bên dưới
            
            # 4. Gửi các lệnh UCTT trực tiếp
            for i, cmd in enumerate(commands):
                if self.stop_event.is_set(): raise Exception("Người dùng yêu cầu dừng.")
                log(f"Gửi lệnh UCTT {i+1}/{len(commands)}: {cmd}")

                # Xử lý lệnh cần xác nhận 2 bước (ANRAI / ANRAR)
                if cmd.startswith("ANRAI") or cmd.startswith("ANRAR"):
                    log("Phát hiện ANRAI/ANRAR, thực hiện 2 bước...")
                    
                    # Bước 1: Gửi lệnh chính, chờ prompt '<'
                    if not self.send_and_wait(shell, cmd, "<", timeout=15, node=node_name):
                        raise Exception(f"Lệnh {cmd} thất bại (Không thấy prompt '<' GĐ 1)")
                    
                    if self.stop_event.is_set(): raise Exception("Người dùng yêu cầu dừng.")

                    log("Đã nhận '<'. Gửi confirm ';' (GĐ 2)...")
                    # Bước 2: Gửi ';', chờ xác nhận
                    if not self._send_confirm_and_wait_anr(shell, ";", ["<", "EXECUTED", "COMMAND EXECUTED"], timeout=15, node=node_name):
                         raise Exception(f"Lệnh {cmd} thất bại (Không thấy xác nhận GĐ 2)")

                # Xử lý các lệnh cấu hình thường (ANRPI, ANRSI, ANRPE...)
                else: 
                    if not self.send_and_wait(shell, cmd, "EXECUTED", timeout=15, node=node_name):
                         raise Exception(f"Lệnh UCTT thất bại: {cmd} (Không thấy EXECUTED)")

                    # Làm mới buffer sau mỗi lệnh
                    if not self.send_and_wait(shell, "", "<", timeout=10, node=node_name):
                        log(f"CẢNH BÁO: Không nhận được prompt '<' sau lệnh {cmd}")

            # 5. Hoàn tất
            log(f"HOÀN TẤT thực thi {action} cho RC={rc_raw} trên {node_name}")
            success = True

        except Exception as e:
            log(f"!!! LỖI khi thực thi UCTT trên {node_name}: {e}")
            if node_name == "TSSE2C": # Chỉ cập nhật status lỗi từ 1 node đại diện
                status_update(f"Trạng thái RC={rc_raw}: Lỗi thực thi ({e})", "red")
        
        finally:
            # 6. Đóng kết nối
            if shell:
                try: log(f"Đang thoát khỏi MML trên {node_name}..."); shell.send("exit;\n"); time.sleep(0.5); shell.close()
                except: pass
            if ssh:
                try: ssh.close()
                except: pass
            log(f"Đã đóng kết nối tới {node_name}")

            # Cập nhật UI sau khi thread xong
            def _update_thread_count():
                self.running_threads -= 1
                if self.running_threads == 0:
                    final_status = f"Trạng thái RC={rc_raw}: Đã hoàn tất {action}" if success else f"Trạng thái RC={rc_raw}: Thực thi thất bại"
                    final_color = "green" if success else "red"
                    status_update(final_status, final_color)
                    self.proposed_uctt_action = None
                    self.selected_uctt_rc = None
                    self.update_button_states()
                    # Tự động kiểm tra lại
                    self.root.after(500, self.check_and_propose_uctt)

            self.root.after(0, _update_thread_count)
        
    def _send_confirm_and_wait_anr(self, shell, confirm_cmd, wait_for_list, timeout=15, node=None):
        """Gửi lệnh xác nhận (;) và chờ một trong các output trong list."""
        if self.stop_event.is_set():
            raise Exception("Người dùng yêu cầu dừng.")

        time.sleep(0.3) # Chờ chút trước khi gửi confirm
        initial_junk = self.read_shell_output(shell, timeout=1.0, node=node)
        if initial_junk.strip():
            self.log_message(f"--- DỌN RÁC (TRƯỚC CONFIRM '{confirm_cmd.strip()}') --- \n{initial_junk.strip()}\n---------------", node=node)

        if self.stop_event.is_set():
            raise Exception("Người dùng yêu cầu dừng.")
        try:
            shell.send(confirm_cmd + "\n")
        except Exception:
            try:
                shell.send((confirm_cmd + "\n").encode())
            except Exception:
                pass

        output = ""
        start_time = time.time()
        found_confirmation = False

        while time.time() - start_time < timeout:
            if self.stop_event.is_set():
                raise Exception("Người dùng yêu cầu dừng.")
            new_output = self.read_shell_output(shell, timeout=1, node=node)
            if new_output:
                self.log_message(f"RECV (confirm): {new_output.strip()}", node=node)
                output += new_output

                # Kiểm tra xem có output nào khớp trong list không
                for wait_item in wait_for_list:
                    if wait_item in output:
                        self.log_message(f"✓ Phát hiện xác nhận: '{wait_item}'", node=node)
                        found_confirmation = True
                        break # Thoát vòng lặp for
                if found_confirmation:
                    break # Thoát vòng lặp while

                # Kiểm tra lỗi sớm (giống send_and_wait)
                fail_conditions = ["NOT ACCEPTED", "SYNTAX ERROR", "FUNCTION BUSY", "FAULT CODE"]
                if any(err in output for err in fail_conditions):
                    self.log_message(f"Lỗi: Thiết bị từ chối lệnh confirm '{confirm_cmd.strip()}'", node=node)
                    return False # Thất bại

            if found_confirmation: break # Đảm bảo thoát while
            time.sleep(0.2)

        # Dọn rác cuối cùng sau khi tìm thấy hoặc hết giờ
        time.sleep(0.3)
        final_junk = self.read_shell_output(shell, timeout=1.5, node=node)
        if final_junk.strip():
            self.log_message(f"--- DỌN RÁC (SAU CONFIRM '{confirm_cmd.strip()}') --- \n{final_junk.strip()}\n---------------", node=node)

        if not found_confirmation:
             self.log_message(f"LỖI HẾT GIỜ: Không tìm thấy xác nhận ({wait_for_list}) sau khi gửi '{confirm_cmd.strip()}'", node=node)
             return False

        return True # Thành công
        
        # --- Cân bằng ô log ---
        def balance_log_panes():
            try:
                self.root.update_idletasks()
                total_height = self.log_frame.winfo_height()
                if total_height > 20:
                    mid = total_height // 2
                    self.log_frame.sash_place(0, 0, mid)
            except Exception:
                pass

        self.root.after(300, balance_log_panes)
        self.root.after(500, balance_log_panes)

    def _on_enter(self, event, hover_color):
        widget = event.widget
        widget.config(bg=hover_color)

    def _on_leave(self, event):
        widget = event.widget
        original_color = getattr(widget, "original_bg", None)
        if original_color:
            widget.config(bg=original_color)
    
    def _get_route_description(self, rc_value):
        """Chuyển RC value thành mô tả dễ hiểu (AA-HNI, AA-HCM, vIMS)"""
        if not rc_value:
            return "Lỗi RC"
        
        # Map dựa trên logic tạo lệnh của bạn
        rc_map = {
            "703": "AA-HNI",  # route_hni
            "742": "AA-HCM",  # route_hcm
            "607": "vIMS"     # route_91, route_vims, route_fixed_vims
        }
        
        return rc_map.get(str(rc_value), f"RC-{rc_value}")
        
    def _add_hover_effect(self, button, original_color, hover_color):
        button.original_bg = original_color
        button.bind("<Enter>", lambda e, hc=hover_color: self._on_enter(e, hc))
        button.bind("<Leave>", self._on_leave)

    def update_button_states(self):
        """Cập nhật trạng thái hiển thị của toàn bộ các nút an toàn (Có Try-Except bảo vệ)"""
        if self.running_threads > 0:
            try:
                self.btn_generate.config(state=tk.DISABLED)
                self.btn_run_check.config(state=tk.DISABLED)
            except: pass
            
            # Đưa vào Try-Except và hasattr để tránh lỗi khi nút đã bị xóa trên giao diện
            try:
                if hasattr(self, 'btn_run_tsse2c'): self.btn_run_tsse2c.config(state=tk.DISABLED)
                if hasattr(self, 'btn_run_tsse2d'): self.btn_run_tsse2d.config(state=tk.DISABLED)
                if hasattr(self, 'btn_run_both'): self.btn_run_both.config(state=tk.DISABLED)
            except: pass
            
            try:
                self.btn_check_uctt.config(state=tk.DISABLED)
                self.btn_execute_changeover.config(state=tk.DISABLED)
                self.btn_execute_fallback.config(state=tk.DISABLED)
            except: pass
            
            try:
                self.btn_stop.config(state=tk.NORMAL)
                self.btn_stop_uctt.config(state=tk.NORMAL)
            except: pass
        else:
            try:
                self.btn_generate.config(state=tk.NORMAL)
                self.btn_run_check.config(state=tk.NORMAL)
            except: pass

            try:
                if hasattr(self, 'btn_run_tsse2c'): self.btn_run_tsse2c.config(state=tk.NORMAL)
                if hasattr(self, 'btn_run_tsse2d'): self.btn_run_tsse2d.config(state=tk.NORMAL)
                if hasattr(self, 'btn_run_both'): self.btn_run_both.config(state=tk.NORMAL)
            except: pass
            
            try:
                self.btn_check_uctt.config(state=tk.NORMAL)
            except: pass
            
            try:
                self.btn_stop.config(state=tk.DISABLED)
                self.btn_stop_uctt.config(state=tk.DISABLED)
            except: pass

    def stop_automation(self):
        if self.running_threads > 0:
            self.log_message("!!! Người dùng yêu cầu dừng các luồng đang chạy...", node="SYSTEM")
            self.stop_event.set()

    def process_and_generate_commands(self):
        """
        Xử lý input và báo lỗi chi tiết nếu số điện thoại không đúng chuẩn.
        (Đã mở khóa giới hạn độ dài cho lệnh ROUTE và tự động Bật/Tắt nút Chạy)
        """
        self.txt_output_commands.configure(state='normal')
        self.txt_output_commands.delete('1.0', tk.END)
        
        ACTION_MAP = {'DELETE': 'delete', 'XOA': 'delete', 'XÓA': 'delete'}
        text_content = self.txt_input_numbers.get('1.0', tk.END)
        tags = self.txt_input_numbers.tag_names("1.0")
        
        lines = []
        if "placeholder" not in tags and text_content.strip():
            lines = text_content.splitlines()

        command_count = 0
        error_count = 0
        total_lines = 0
        
        # Checkbox cấu hình
        is_free_input_mode = self.allow_free_input.get()
        skip_bad_lines = self.skip_bad_lines_var.get()

        for line_num, line in enumerate(lines):
            line_text_clean = line.split('#', 1)[0].strip()
            
            # Bỏ qua dòng lỗi cũ nếu đang check
            if skip_bad_lines:
                line_index_str = f"{line_num + 1}.0"
                if "bad_action" in self.txt_input_numbers.tag_names(line_index_str):
                    continue

            if not line_text_clean or line_text_clean.startswith("Dán") or line_text_clean.startswith("Ví dụ:"):
                continue

            total_lines += 1
            parts = re.split(r'[\s,;]+', line_text_clean)
            parts = [p.strip() for p in parts if p.strip()]
            
            if len(parts) < 2:
                self.log_message(f"LỖI Dòng {line_num+1}: Thiếu thông tin (Cần: Số điện thoại + Lệnh)", node="SYSTEM")
                error_count += 1
                continue
                
            raw_num = parts[0]
            action_word = parts[1].upper()
            if action_word in ["XÓA", "XOA", "HUY", "DELETE"]: 
                action_word = "DELETE"
            
            if not raw_num.isdigit():
                self.log_message(f"LỖI Dòng {line_num+1}: Số '{raw_num}' có chứa ký tự chữ.", node="SYSTEM")
                error_count += 1
                continue
            
            # Xử lý 84/0 ở đầu
            num = raw_num
            if num.startswith("84"): num = num[2:]
            elif num.startswith("0"): num = num[1:]
            
            # --- [SỬA Ở ĐÂY] CHỈ KIỂM TRA ĐỘ DÀI NẾU LÀ LỆNH DELETE ---
            if action_word == "DELETE" and not is_free_input_mode:
                curr_len = len(num)
                err_msg = ""
                
                if num.startswith("91"): # CFW 91
                    # Chấp nhận 8, 9, 10 số
                    if curr_len not in [8, 9, 10]: 
                        err_msg = f"Số 91x yêu cầu 8, 9 hoặc 10 số (Hiện tại: {curr_len})"
                        
                elif num.startswith("138"): # CFW 138
                    # Chấp nhận 9, 10 số
                    if curr_len not in [9, 10]: 
                        err_msg = f"Số 138x yêu cầu 9 hoặc 10 số (Hiện tại: {curr_len})"
                        
                elif num.startswith("1900") or num.startswith("1800"):
                    if curr_len not in [8, 10]: 
                        err_msg = f"Số 1900/1800 yêu cầu 8 hoặc 10 số (Hiện tại: {curr_len})"
                else: # Cố định (24, 28...)
                    if curr_len != 10: err_msg = f"Số cố định yêu cầu 10 số (Hiện tại: {curr_len}). Ví dụ: 2838... (không tính số 0 đầu)"
                
                if err_msg:
                    self.log_message(f"LỖI Dòng {line_num+1}: {err_msg} -> '{raw_num}'", node="SYSTEM")
                    error_count += 1
                    continue
            # -------------------------------------------

            command_set = self._generate_single_command(num)
            if not command_set:
                self.log_message(f"LỖI Dòng {line_num+1}: Không tạo được lệnh cho số '{num}'", node="SYSTEM")
                error_count += 1
                continue

            action_key = None
            # Logic map lệnh (Route/Delete)
            if action_word == "ROUTE":
                # --- LOGIC MỚI: Ưu tiên Site người dùng nhập ---
                
                # Lấy Site người dùng nhập (nếu có, vị trí index 2)
                site = parts[2].upper() if len(parts) >= 3 else ""
                
                # 1. Xử lý 1900/1800 (Ưu tiên Site nhập, mặc định vIMS)
                if num.startswith("1900") or num.startswith("1800"):
                    if site == 'HCM': action_key = 'route_hcm'
                    elif site == 'HNI': action_key = 'route_hni'
                    else: action_key = 'route_vims' 
                
                # 2. Xử lý 91x -> Đọc Site, mặc định vIMS
                elif num.startswith("91"):
                    if site == 'HNI':   action_key = 'route_hni'
                    elif site == 'HCM': action_key = 'route_hcm'
                    else:               action_key = 'route_91'   # vIMS mặc định
                
                # 3. Xử lý 138x -> Đọc Site, mặc định HCM
                elif num.startswith("138"):
                    if site == 'HNI':   action_key = 'route_hni'
                    else:               action_key = 'route_hcm'  # HCM mặc định
                
                # 4. Kiểm tra Site cho các số Cố định còn lại
                # Nếu không phải các đầu số đặc biệt trên mà KHÔNG CÓ Site -> Báo lỗi
                elif not site: 
                    self.log_message(f"LỖI Dòng {line_num+1}: Lệnh ROUTE thiếu Site (HCM/HNI/VIMS).", node="SYSTEM")
                    error_count += 1
                    continue
                
                # 5. Map Site cho số cố định (24x, 28x...)
                else:
                    if site == 'HCM': action_key = 'route_hcm'
                    elif site == 'HNI': action_key = 'route_hni'
                    elif site in ['VIMS', 'IMS']: action_key = 'route_fixed_vims'
                    else:
                        self.log_message(f"LỖI Dòng {line_num+1}: Site '{parts[2]}' không đúng.", node="SYSTEM")
                        error_count += 1
                        continue

            elif action_word == "DELETE":
                # [SỬA ĐỂ TẠO LỆNH XÓA 2 NODE]
                cmd_c = command_set.get('delete_c')
                cmd_d = command_set.get('delete_d')
                if cmd_c and cmd_d:
                    self.txt_output_commands.insert(tk.END, cmd_c + "\n")
                    self.txt_output_commands.insert(tk.END, cmd_d + "\n")
                    command_count += 1
                    continue # Bỏ qua phần ACTION_MAP bên dưới
                else:
                    action_key = ACTION_MAP.get(action_word)
            else:
                self.log_message(f"LỖI Dòng {line_num+1}: Lệnh '{action_word}' không hợp lệ.", node="SYSTEM")
                error_count += 1
                continue

            # Xuất lệnh
            if action_key:
                cmd = command_set.get(action_key)
                if cmd:
                    self.txt_output_commands.insert(tk.END, cmd + "\n")
                    command_count += 1
                else:
                    self.log_message(f"LỖI Dòng {line_num+1}: Không hỗ trợ lệnh này cho đầu số {num}.", node="SYSTEM")
                    error_count += 1

        self.txt_output_commands.configure(state='disabled')
        
        # --- [MỚI] TỰ ĐỘNG BẬT/TẮT NÚT CHẠY CẤU HÌNH DỰA VÀO SỐ LƯỢNG LỆNH ---
        try:
            if command_count > 0:
                self.btn_run_both.config(state=tk.NORMAL)
            else:
                self.btn_run_both.config(state=tk.DISABLED)
        except: pass
        
        # --- POPUP THÔNG BÁO ---
        if total_lines > 0 and command_count == 0:
            messagebox.showerror(
                "Lỗi Dữ Liệu Đầu Vào", 
                f"Không tạo được lệnh nào từ {total_lines} dòng nhập vào.\n\n"
                "Nguyên nhân phổ biến:\n"
                "- Số điện thoại thiếu/thừa số (Xem chi tiết ở Console Log bên phải).\n"
                "- Sai cú pháp lệnh (ví dụ thiếu Site cho lệnh Route)."
            )
        elif error_count > 0:
            messagebox.showwarning("Cảnh Báo", f"Đã tạo {command_count} lệnh, nhưng có {error_count} dòng lỗi.\nVui lòng xem chi tiết ở Console Log.")

    # ==================================================================
    # === BẮT ĐẦU SỬA LỖI LOG RACE CONDITION ===
    # ==================================================================
    
    def log_message(self, message, node=None):
        """
        Hàm ghi log trung tâm:
        1. Ghi vào file log (logs/yyyy-mm-dd.log)
        2. Hiển thị lên giao diện GUI tương ứng với Node.
        """
        # --- 1. GHI FILE LOG (Back-end) ---
        if hasattr(self, 'logger') and self.logger:
            log_tag = "SYSTEM"
            if node: log_tag = node
            try:
                self.logger.info(f"[{log_tag}] {message}")
            except Exception: 
                pass

        # --- 2. HÀM CẬP NHẬT GIAO DIỆN (Front-end) ---
        def _update_gui(widget, msg, is_tssn2d=False):
            try:
                # Nếu là TSSN2D, kiểm tra xem widget có đang hiện không
                if is_tssn2d:
                    if hasattr(self, 'log_frame_single') and not self.log_frame_single.winfo_ismapped():
                        # Nếu chưa hiện -> Ẩn log đôi, hiện log đơn ngay
                        if hasattr(self, 'log_pane_dual'): self.log_pane_dual.pack_forget()
                        self.log_frame_single.pack(fill=tk.BOTH, expand=True, padx=(5,0))
                
                # Mở khóa widget để ghi
                widget.configure(state='normal')
                
                # Insert tin nhắn (Tự động thêm xuống dòng nếu chưa có)
                if not msg.endswith("\n"):
                    msg += "\n"
                widget.insert(tk.END, msg)
                
                # Cuộn xuống cuối cùng để thấy tin mới nhất
                widget.see(tk.END)
                
                # Khóa lại (Read-only)
                widget.configure(state='disabled')
            except Exception as e:
                print(f"GUI LOG ERROR: {e}")

        # --- 3. ĐIỀU HƯỚNG TIN NHẮN VÀO ĐÚNG Ô ---
        # Ưu tiên xử lý TSSN2D trước vì đây là cái bạn đang cần debug
        if node == "TSSN2D":
            if hasattr(self, 'log_tssn2d'):
                self.root.after(0, lambda: _update_gui(self.log_tssn2d, message, is_tssn2d=True))
            else:
                # Fallback nếu chưa khởi tạo log_tssn2d (hiếm gặp)
                print(f"[TSSN2D_raw] {message}")

        elif node == "TSSE2C":
            if hasattr(self, 'log_c'):
                self.root.after(0, lambda: _update_gui(self.log_c, message))

        elif node == "TSSE2D":
            if hasattr(self, 'log_d'):
                self.root.after(0, lambda: _update_gui(self.log_d, message))

        elif node == "SYSTEM":
            # Log hệ thống thì hiện vào ô log đang active hoặc mặc định log_c
            target_widget = self.log_c if hasattr(self, 'log_c') else None
            # Nếu đang ở tab A2P (TSSN2D), có thể bạn muốn hiện system log vào đó luôn
            if hasattr(self, 'log_tssn2d') and self.log_tssn2d.winfo_ismapped():
                target_widget = self.log_tssn2d
            
            if target_widget:
                self.root.after(0, lambda: _update_gui(target_widget, message))

        else:
            # Mặc định tất cả cái khác vào log_c
            if hasattr(self, 'log_c'):
                self.root.after(0, lambda: _update_gui(self.log_c, message))

    # ==================================================================
    # === KẾT THÚC SỬA LỖI LOG RACE CONDITION ===
    # ==================================================================

    def open_ssh_settings(self):
        self.settings_window = Toplevel(self.root)
        self.settings_window.title("Cài đặt SSH")
        self.settings_window.transient(self.root)
        self.settings_window.grab_set()
        tk.Label(self.settings_window, text="Host TSSE2C:").grid(row=0, column=0, padx=5, pady=5, sticky='e')
        self.entry_host_c = Entry(self.settings_window, width=30)
        self.entry_host_c.grid(row=0, column=1, padx=5, pady=5)
        self.entry_host_c.insert(0, self.ssh_details.get('host_c', '10.202.47.54'))
        tk.Label(self.settings_window, text="Host TSSE2D:").grid(row=1, column=0, padx=5, pady=5, sticky='e')
        self.entry_host_d = Entry(self.settings_window, width=30)
        self.entry_host_d.grid(row=1, column=1, padx=5, pady=5)
        self.entry_host_d.insert(0, self.ssh_details.get('host_d', '10.202.49.54'))
        tk.Label(self.settings_window, text="Username:").grid(row=2, column=0, padx=5, pady=5, sticky='e')
        self.entry_user = Entry(self.settings_window, width=30)
        self.entry_user.grid(row=2, column=1, padx=5, pady=5)
        self.entry_user.insert(0, self.ssh_details.get('user', 'minhth'))
        tk.Label(self.settings_window, text="Password:").grid(row=3, column=0, padx=5, pady=5, sticky='e')
        self.entry_pass = Entry(self.settings_window, width=30, show="*")
        self.entry_pass.grid(row=3, column=1, padx=5, pady=5)
        self.entry_pass.insert(0, self.ssh_details.get('pass', ''))
        self.entry_pass.focus_set()
        save_btn = Button(self.settings_window, text="Lưu", command=self.save_ssh_settings)
        save_btn.grid(row=4, column=0, columnspan=2, pady=10)
        self.root.wait_window(self.settings_window)

    def _load_ssh_settings(self):
        if os.path.exists(self.CONFIG_FILE):
            try:
                with open(self.CONFIG_FILE, 'r') as f:
                    self.ssh_details = json.load(f)
                    return
            except Exception:
                pass
        self.ssh_details = {'host_c':'10.202.47.54','host_d':'10.202.49.54','user':'minhth','pass':''}

    def save_ssh_settings(self):
        self.ssh_details['host_c'] = self.entry_host_c.get()
        self.ssh_details['host_d'] = self.entry_host_d.get()
        self.ssh_details['user'] = self.entry_user.get()
        self.ssh_details['pass'] = self.entry_pass.get()
        try:
            with open(self.CONFIG_FILE, 'w') as f:
                json.dump(self.ssh_details, f, indent=4)
            self.log_message(f"Đã lưu cài đặt SSH vào file {self.CONFIG_FILE}", node="SYSTEM")
        except Exception as e:
            self.log_message(f"LỖI: Không thể lưu cài đặt SSH ra file: {e}", node="SYSTEM")
        self.settings_window.destroy()

    def _generate_single_command(self, original_num):
        commands = {}
        num = str(original_num).strip()
        if not num:
            return None
        try:
            if num.startswith("91"):
                b_val = "36"
                
                # [CẬP NHẬT] Logic L cho CFW 91 (Theo Excel)
                # Nếu 9 số -> L=9; ngược lại -> L=8-10
                if len(num) == 9:
                    l_param = "L=9;"
                else:
                    l_param = "L=8-10;"
                
                commands['check']     = f"ANBSP:B={b_val}-{num};"
                commands['route_91']  = f"ANBSI:B={b_val}-{num},M=0-84,BNT=1,F=500,RC=607,CC=1,{l_param}"  # vIMS (default)
                commands['route_hni'] = f"ANBSI:B={b_val}-{num},M=0-0,BNT=3,F=500,RC=703,CC=1,{l_param}"   # [MỚI] HNI
                commands['route_hcm'] = f"ANBSI:B={b_val}-{num},M=0-0,BNT=3,F=500,RC=742,CC=1,{l_param}"   # [MỚI] HCM
                commands['delete']    = f"ANBSE:B={b_val}-{num};"

            elif num.startswith("138"):
                b_val = "206"
                
                # [CẬP NHẬT] Logic L cho CFW 138 (Theo Excel)
                # Nếu 9 số -> L=9; ngược lại -> L=10
                if len(num) == 9:
                    l_param = "L=9;"
                else:
                    l_param = "L=10;"
                
                commands['check']     = f"ANBSP:B={b_val}-{num};"
                commands['route_hcm'] = f"ANBSI:B={b_val}-{num},M=0-84,BNT=1,F=500,RC=742,CC=1,{l_param}"  # HCM (default)
                commands['route_hni'] = f"ANBSI:B={b_val}-{num},M=0-84,BNT=1,F=500,RC=703,CC=1,{l_param}"  # [MỚI] HNI
                commands['delete']    = f"ANBSE:B={b_val}-{num};"

            # --- (SỬA THEO CÔNG THỨC EXCEL) ---
            elif num.startswith("1900") or num.startswith("1800"):
                b_val = "204"
                if len(num) == 10: l_param = "L=10;"
                else: l_param = "L=8-10;" # Hoặc f"L={len(num)};" tùy logic bạn chọn
                
                commands['check'] = f"ANBSP:B={b_val}-{num};"
                
                # 1. vIMS (Mặc định)
                commands['route_vims'] = f"ANBSI:B={b_val}-{num},M=0-84,BNT=1,F=500,RC=607,CC=1,{l_param}"
                
                # 2. HCM
                commands['route_hcm']  = f"ANBSI:B={b_val}-{num},BNT=3,F=500,RC=742,CC=1,{l_param}"
                
                # 3. [MỚI] HNI
                commands['route_hni']  = f"ANBSI:B={b_val}-{num},BNT=3,F=500,RC=703,CC=1,{l_param}"
                
                commands['delete'] = f"ANBSE:B={b_val}-{num};"
            # --- (HẾT SỬA) ---

            else: # Các số cố định (28x, 24x, 272x ...)
                if num.startswith("28") or num.startswith("24"):
                    b_num = num[:2] + "088" + num[2:10]
                    m_prefix = num[:2]
                    m_val = f"M=5-0{m_prefix}"
                else:
                    b_num = num[:3] + "088" + num[3:10]
                    m_prefix = b_num[:3]
                    m_val = f"M=6-0{m_prefix}"
                b_val = "39"
                commands['check'] = f"ANBSP:B={b_val}-{b_num};"
                commands['delete'] = f"ANBSE:B={b_val}-{b_num};"
                commands['route_hcm'] = f"ANBSI:B={b_val}-{b_num},{m_val},BNT=3,F=500,RC=742,CC=1,L=13;"
                commands['route_hni'] = f"ANBSI:B={b_val}-{b_num},{m_val},BNT=3,F=500,RC=703,CC=1,L=13;"
                commands['route_fixed_vims'] = f"ANBSI:B={b_val}-{b_num},{m_val},BNT=1,F=500,RC=607,CC=1,L=13;"
            
            return commands
            
        except IndexError:
            self.log_message(f"LỖI (IndexError): Số '{num}' quá ngắn hoặc sai định dạng khi tạo lệnh B=.", node="SYSTEM")
            return None
        except Exception as e:
            self.log_message(f"LỖI khi tạo lệnh cho số '{num}': {e}", node="SYSTEM")
            return None

    def start_automation_both(self):
        if not self._prepare_automation(): return
        commands_to_run, is_check_job = self._get_commands_and_job_type()
        if not commands_to_run: return

        if not is_check_job: 
            commands_display = "\n".join(commands_to_run[:10]) 
            if len(commands_to_run) > 10:
                commands_display += f"\n... và {len(commands_to_run) - 10} lệnh nữa."
            
            confirm = messagebox.askyesno(
                "Xác nhận Cấu hình",
                f"Bạn có chắc muốn chạy {len(commands_to_run)} lệnh CẤU HÌNH (Route/Delete) trên CẢ HAI node?\n\n"
                f"Các lệnh sẽ chạy (ví dụ):\n{commands_display}"
            )
            if not confirm:
                self.log_message("HỦY BỎ: Người dùng đã từ chối chạy lệnh.", node="SYSTEM")
                return

        # --- [MỚI] CLEAR CẢ 2 LOG ---
        try:
            self.log_c.config(state=tk.NORMAL, bg=self.COLORS["log_bg"], fg=self.COLORS["log_fg_c"])
            self.log_c.delete('1.0', tk.END)
            self.log_c.config(state=tk.DISABLED)
            
            self.log_d.config(state=tk.NORMAL, bg=self.COLORS["log_bg"], fg=self.COLORS["log_fg_d"])
            self.log_d.delete('1.0', tk.END)
            self.log_d.config(state=tk.DISABLED)
        except: pass
        # ----------------------------

        user = self.ssh_details['user']
        pw = self.ssh_details['pass']
        host_c = self.ssh_details['host_c']
        host_d = self.ssh_details['host_d']
        
        self.log_message(f"Chuẩn bị luồng cho TSSE2C ({host_c})...", node="TSSE2C")
        t_c = threading.Thread(target=self.run_automation_wrapper, args=(host_c, user, pw, commands_to_run, is_check_job))
        t_c.daemon = True
        
        self.log_message(f"Chuẩn bị luồng cho TSSE2D ({host_d})...", node="TSSE2D")
        t_d = threading.Thread(target=self.run_automation_wrapper, args=(host_d, user, pw, commands_to_run, is_check_job))
        t_d.daemon = True

        self.log_message("="*30, node="SYSTEM")
        self.log_message("!!! BẮT ĐẦU CHẠY 2 LUỒNG ĐỒNG THỜI !!!", node="SYSTEM")
        self.log_message("="*30, node="SYSTEM")
        self.running_threads = 2
        self.stop_event.clear()
        self.update_button_states()
        t_c.start()
        t_d.start()

    def start_automation_thread(self, device_name):
        if not self._prepare_automation():
            return
        commands_to_run, is_check_job = self._get_commands_and_job_type()
        if not commands_to_run:
            return
            
        if not is_check_job: 
            commands_display = "\n".join(commands_to_run[:10]) 
            if len(commands_to_run) > 10:
                commands_display += f"\n... và {len(commands_to_run) - 10} lệnh nữa."
            
            confirm = messagebox.askyesno(
                "Xác nhận Cấu hình",
                f"Bạn có chắc muốn chạy {len(commands_to_run)} lệnh CẤU HÌNH (Route/Delete) trên node {device_name}?\n\n"
                f"Các lệnh sẽ chạy (ví dụ):\n{commands_display}"
            )
            if not confirm:
                self.log_message(f"HỦY BỎ: Người dùng đã từ chối chạy lệnh trên {device_name}.", node="SYSTEM")
                return

        # --- [MỚI] CLEAR LOG ---
        try:
            if device_name == 'TSSE2C':
                self.log_c.config(state=tk.NORMAL, bg=self.COLORS["log_bg"], fg=self.COLORS["log_fg_c"])
                self.log_c.delete('1.0', tk.END)
                self.log_c.config(state=tk.DISABLED)
            else:
                self.log_d.config(state=tk.NORMAL, bg=self.COLORS["log_bg"], fg=self.COLORS["log_fg_d"])
                self.log_d.delete('1.0', tk.END)
                self.log_d.config(state=tk.DISABLED)
        except: pass
        # -----------------------

        if device_name == 'TSSE2C':
            host = self.ssh_details['host_c']
        else:
            host = self.ssh_details['host_d']
        user = self.ssh_details['user']
        pw = self.ssh_details['pass']
        self.log_message("="*30, node=device_name)
        self.log_message(f"!!! BẮT ĐẦU CHẠY 1 LUỒNG ({device_name}) !!!", node=device_name)
        self.log_message("="*30, node=device_name)
        self.running_threads = 1
        self.stop_event.clear()
        self.update_button_states()
        t = threading.Thread(target=self.run_automation_wrapper, args=(host, user, pw, commands_to_run, is_check_job))
        t.daemon = True
        t.start()
    
    def _clear_check_results_box(self):
        """Xóa sạch nội dung Bảng kết quả check (an toàn cho thread)"""
        def _clear():
            try:
                for item in self.tree_results.get_children():
                    self.tree_results.delete(item)
            except Exception as e:
                pass
        
        if threading.current_thread() is threading.main_thread():
            _clear()
        else:
            self.root.after(0, _clear)

    def _parse_anbsp_output(self, raw_output, b_number_full):
        """
        Phiên bản V3 (Final): Logic quét dòng (Line Scanning).
        - Tìm dòng chứa: [B-Number] + [khoảng trắng] + [F=]
        - Tự động gom các dòng tham số bị rớt xuống dưới (M=, BNT=).
        - Giữ lại logic tìm cha (Inheritance) nếu không tìm thấy số con.
        """
        try:
            # 1. Kiểm tra các lỗi chung từ Node trả về
            if "NOT ACCEPTED" in raw_output or "FAULT CODE" in raw_output:
                if "ANALYSIS POINT CANNOT BE REACHED" in raw_output:
                    return {'status': 'error', 'desc': 'LỖI: ANALYSIS POINT CANNOT BE REACHED (FAULT CODE 7)'}
                
                # Trích xuất mã lỗi cụ thể nếu có
                fault_match = re.search(r"FAULT CODE\s+(\d+)", raw_output)
                if fault_match:
                    return {'status': 'error', 'desc': f"LỖI: FAULT CODE {fault_match.group(1)}"}
                return {'status': 'error', 'desc': 'LỖI: NOT ACCEPTED'}

            if "NO DATA EXIST" in raw_output:
                return {'status': 'no_data', 'desc': 'CHƯA KHAI BÁO (NO DATA EXIST)'}

            lines = raw_output.splitlines()
            found_block = False
            block_data = ""
            
            # --- LOGIC MỚI: TÌM CHÍNH XÁC SỐ CON ---
            # Regex: Bắt đầu dòng + Số B + Khoảng trắng + Tìm thấy chữ F= ở bất kỳ đâu sau đó
            # re.escape để xử lý dấu - trong số điện thoại (ví dụ 39-28...)
            target_pattern = re.compile(rf"^\s*{re.escape(b_number_full)}\s+.*F=", re.IGNORECASE)

            for i, line in enumerate(lines):
                if target_pattern.search(line):
                    # Đã tìm thấy dòng chứa số VÀ tham số F=
                    found_block = True
                    block_data += line + "\n"
                    
                    # Quét tiếp các dòng bên dưới để lấy các tham số bị rớt dòng (như M=..., BNT=...)
                    # Logic: Dòng tham số con sẽ thụt đầu dòng (bắt đầu bằng khoảng trắng)
                    for next_line in lines[i+1:]:
                        if not next_line.strip(): continue # Bỏ qua dòng trống
                        
                        if next_line.startswith(" ") or next_line.startswith("\t"):
                            block_data += next_line + "\n"
                        else:
                            # Gặp dòng không thụt lề -> Hết block
                            break
                    break # Tìm thấy rồi thì thoát vòng lặp quét dòng

            # 2. XỬ LÝ DỮ LIỆU TÌM ĐƯỢC
            if found_block:
                # Regex tìm các tham số trong đống dữ liệu vừa gom được
                rc_match = re.search(r"RC\s*=\s*(\d+)", block_data)
                m_match = re.search(r"M\s*=\s*([\d-]+)", block_data)
                d_match = re.search(r"D\s*=\s*([\d-]+)", block_data) 
                bnt_match = re.search(r"BNT\s*=\s*(\d+)", block_data)
                
                rc_val = rc_match.group(1) if rc_match else "?"
                bnt_val = bnt_match.group(1) if bnt_match else "?"

                # Xử lý M hoặc D (Miscell / Digit Analysis)
                md_str = "?"
                md_key = None
                md_val = None
                
                if m_match:
                    md_key = "M"
                    md_val = m_match.group(1)
                    md_str = f"M={md_val}"
                elif d_match:
                    md_key = "D"
                    md_val = d_match.group(1)
                    md_str = f"D={md_val}"
                
                # Lấy mô tả RC (ví dụ: AA-HCM, vIMS...)
                route_desc = self._get_route_description(rc_val)
                
                desc = f"ĐÃ KHAI BÁO ({route_desc} | RC={rc_val}, {md_str}, BNT={bnt_val})"
                
                return {
                    'status': 'found', 
                    'desc': desc, 
                    'rc': rc_val, 
                    'md_key': md_key, 
                    'md_val': md_val, 
                    'bnt': bnt_val
                }

            # 3. LOGIC DỰ PHÒNG: TÌM CHA (INHERITANCE)
            # Nếu không tìm thấy dòng chính xác của số con, quét tìm số cha dài nhất
            parent_candidates = []
            
            # Tìm tất cả các dòng bắt đầu bằng prefix (39-, 204-, v.v.)
            # Chỉ lấy các dòng có chứa F= (để chắc chắn là dòng khai báo route)
            all_bnum_matches = re.finditer(r"^(\d+-\d+).*F=", raw_output, re.MULTILINE)
            
            for match in all_bnum_matches:
                # match.group(1) là số điện thoại (ví dụ 39-2808)
                found_num = match.group(1).strip()
                # Nếu số cần tìm (b_number_full) bắt đầu bằng số này -> Đây là cha tiềm năng
                if b_number_full.startswith(found_num) and len(found_num) < len(b_number_full):
                    parent_candidates.append(found_num)
            
            if not parent_candidates:
                return {'status': 'not_found', 'desc': 'CHƯA KHAI BÁO (Không tìm thấy dòng khớp)'}

            # Lấy cha dài nhất (khớp nhất)
            parent_candidates.sort(key=len, reverse=True)
            best_parent = parent_candidates[0]

            # Đệ quy nhẹ: Gọi lại hàm này nhưng giả vờ tìm số cha
            # Lưu ý: Return status là 'inherited' để giao diện biết
            parent_result = self._parse_anbsp_output(raw_output, best_parent)
            
            if parent_result['status'] == 'found':
                parent_result['status'] = 'inherited'
                parent_result['desc'] = f"KẾ THỪA (từ {best_parent}) | {parent_result['desc'].replace('ĐÃ KHAI BÁO', '').strip('() ')}"
                return parent_result
            
            return {'status': 'not_found', 'desc': 'CHƯA KHAI BÁO (Không tìm thấy parent hợp lệ)'}

        except Exception as e:
            return {'status': 'error', 'desc': f"LỖI PHÂN TÍCH: {e}"}

    def update_check_results_ui(self, results, node_name):
        """
        (SỬA) Cập nhật UI dựa trên kết quả check:
        - So sánh M/D chính xác.
        - Báo lỗi đỏ và lý do cụ thể khi không thể xóa.
        """
        try:
            # 1. Update ô "Kết quả Check"
            self.txt_check_results.config(state=tk.NORMAL)
            self.txt_check_results.delete('1.0', tk.END)
            self.txt_check_results.insert(tk.END, f"--- Kết quả từ {node_name} ---\n", "header")
            
            b_num_to_result = {}
            
            for cmd, result_dict in results:
                b_num_match = re.search(r'B=([^;]+)', cmd)
                b_num_clean = b_num_match.group(1) if b_num_match else None
                if not b_num_clean: continue

                b_num_to_result[b_num_clean] = result_dict
                
                status = result_dict.get('status')
                tag = "found"
                if status in ['inherited', 'not_found', 'no_data']: tag = "not_found"
                elif status == 'error': tag = "error"

                self.txt_check_results.insert(tk.END, f"{b_num_clean}: {result_dict.get('desc', 'Lỗi')}\n", tag)
            
            self.txt_check_results.insert(tk.END, "\n")
            self.txt_check_results.see(tk.END)
            self.txt_check_results.config(state=tk.DISABLED)

            # 2. Cập nhật ô "Input"
            self.txt_input_numbers.config(state=tk.NORMAL)
            
            self.txt_input_numbers.tag_remove("ok_action", "1.0", tk.END)
            self.txt_input_numbers.tag_remove("bad_action", "1.0", tk.END)
            
            start_idx = "1.0"
            while True:
                comment_start = self.txt_input_numbers.search(r'\s+#', start_idx, stopindex=tk.END, regexp=True)
                if not comment_start: break
                comment_end = f"{comment_start} lineend"
                self.txt_input_numbers.delete(comment_start, comment_end)
                start_idx = comment_start
                
            # 3. Lặp qua từng dòng của ô Input
            current_line = 1
            while True:
                line_start = f"{current_line}.0"
                line_end = f"{current_line}.end"
                line_text = self.txt_input_numbers.get(line_start, line_end)
                
                if not line_text: break
                
                line_text_clean = line_text.strip()
                if not line_text_clean or line_text_clean.startswith("Dán") or line_text_clean.startswith("Ví dụ:"):
                    current_line += 1
                    continue

                # 4. Parse dòng input
                parts = re.split(r'[\s,;]+', line_text_clean)
                if len(parts) < 2:
                    current_line += 1
                    continue
                    
                raw_num, action_word, *site_parts = parts
                action_word = action_word.upper()
                if "XÓA" in action_word: action_word = "XÓA"
                
                if not raw_num.isdigit():
                    current_line += 1
                    continue
                    
                num = raw_num
                if num.startswith("84"): num = num[2:]
                elif num.startswith("0"): num = num[1:]
                if not num:
                    current_line += 1
                    continue

                # 5. Lấy B-Number và Lệnh dự kiến
                command_set = self._generate_single_command(num)
                if not command_set or 'check' not in command_set:
                    current_line += 1
                    continue
                    
                b_num_clean = command_set.get('check').split('B=')[1].split(';')[0]
                result_dict = b_num_to_result.get(b_num_clean)
                
                if not result_dict:
                    current_line += 1
                    continue 

                # 6. Áp dụng logic tô màu và ghi chú
                status = result_dict.get('status')
                tag_to_apply = None
                comment_to_add = ""
                
                # (MỚI) Biến xác định màu chữ của comment (Mặc định là Xanh - check_comment)
                comment_text_tag = "check_comment"

                # --- Logic cho ROUTE ---
                if action_word == "ROUTE":
                    intended_action_key = None
                    site = site_parts[0].upper() if site_parts else ""
                    if num.startswith("1900") or num.startswith("1800"): intended_action_key = 'route_vims'
                    elif num.startswith("91"):
                        if site == 'HNI':   intended_action_key = 'route_hni'
                        elif site == 'HCM': intended_action_key = 'route_hcm'
                        else:               intended_action_key = 'route_91'
                    elif num.startswith("138"):
                        if site == 'HNI':   intended_action_key = 'route_hni'
                        else:               intended_action_key = 'route_hcm'
                    elif site == 'HCM': intended_action_key = 'route_hcm'
                    elif site == 'HNI': intended_action_key = 'route_hni'
                    elif site in ['VIMS', 'IMS']: intended_action_key = 'route_fixed_vims'
                    
                    intended_cmd = command_set.get(intended_action_key)
                    
                    if not intended_cmd:
                        tag_to_apply = "bad_action"
                        comment_to_add = f"# LỖI: Thiếu Site (HCM/HNI/VIMS)"
                        comment_text_tag = "error_comment" # Chữ Đỏ
                    else:
                        # Regex linh hoạt với khoảng trắng
                        intended_rc = re.search(r"RC\s*=\s*(\d+)", intended_cmd).group(1)
                        intended_m_match = re.search(r"M\s*=\s*([\d-]+)", intended_cmd)
                        intended_d_match = re.search(r"D\s*=\s*([\d-]+)", intended_cmd)
                        intended_bnt = re.search(r"BNT\s*=\s*(\d+)", intended_cmd).group(1)

                        intended_md_key = None
                        intended_md_val = None
                        if intended_m_match:
                            intended_md_key = "M"
                            intended_md_val = intended_m_match.group(1)
                        elif intended_d_match:
                            intended_md_key = "D"
                            intended_md_val = intended_d_match.group(1)

                        intended_route_desc = self._get_route_description(intended_rc)

                        if status in ['inherited', 'not_found', 'no_data']:
                            tag_to_apply = "ok_action" 
                            comment_to_add = f"# (Sẵn sàng route {intended_route_desc})"
                        elif status == 'found':
                            # So sánh logic "y hệt"
                            if (result_dict.get('rc') == intended_rc and
                                result_dict.get('md_key') == intended_md_key and
                                result_dict.get('md_val') == intended_md_val and
                                result_dict.get('bnt') == intended_bnt):
                                tag_to_apply = "bad_action" 
                                comment_to_add = f"# LỖI: Đã có route sẵn ({result_dict.get('desc')})"
                                comment_text_tag = "error_comment" # Chữ Đỏ
                            else:
                                tag_to_apply = "ok_action" 
                                comment_to_add = f"# (Sẵn sàng ĐỔI route -> {intended_route_desc})"
                        else: # status == 'error'
                            tag_to_apply = "bad_action"
                            comment_to_add = f"# LỖI: {result_dict.get('desc')}"
                            comment_text_tag = "error_comment" # Chữ Đỏ
                
                # --- Logic cho DELETE (ĐÃ SỬA THEO YÊU CẦU) ---
                elif action_word in ['DELETE', 'XOA', 'XÓA']:
                    if status == 'found':
                        tag_to_apply = "ok_action" # XANH
                        comment_to_add = f"# (Sẵn sàng xóa - {result_dict.get('desc')})"
                        # comment_text_tag mặc định là xanh -> OK
                        
                    elif status in ['inherited', 'not_found', 'no_data']:
                        tag_to_apply = "bad_action" # Nền Đỏ nhạt
                        # (SỬA) Nội dung thông báo và màu chữ
                        comment_to_add = "# LỖI: Không thể xóa (Chưa khai báo riêng / Không có dữ liệu)"
                        comment_text_tag = "error_comment" # Chữ Đỏ
                        
                    else: # status == 'error'
                        tag_to_apply = "bad_action"
                        comment_to_add = f"# LỖI: {result_dict.get('desc')}"
                        comment_text_tag = "error_comment" # Chữ Đỏ
                
                # 7. Áp dụng
                if tag_to_apply:
                    self.txt_input_numbers.tag_add(tag_to_apply, line_start, line_end)
                if comment_to_add:
                    # (QUAN TRỌNG) Dùng comment_text_tag (xanh hoặc đỏ)
                    self.txt_input_numbers.insert(line_end, f"  {comment_to_add}", comment_text_tag)

                current_line += 1
        
        except Exception as e:
             print(f"Lỗi nghiêm trọng khi cập nhật UI: {e}")
    
    def _collect_and_compare_results(self, results, node_name):
        """
        Hàm mới: Thu thập dữ liệu từ 2 node, đợi đủ thì so sánh và hiển thị.
        """
        # 1. Parse dữ liệu từ dạng list [(cmd, dict)] sang dict {sđt: dict_data}
        parsed_data = {}
        for cmd, res in results:
            b_match = re.search(r'B=([^;]+)', cmd)
            if b_match:
                num = b_match.group(1)
                parsed_data[num] = res
        
        # 2. Lưu vào biến tạm
        # node_name sẽ là "TSSE2C" hoặc "TSSE2D"
        key = 'C' if '2C' in node_name else 'D'
        self.temp_check_results[key] = parsed_data
        
        # 3. Kiểm tra xem đã đủ 2 node chưa
        # Nếu đã có đủ Key 'C' và Key 'D' thì tiến hành so sánh
        if 'C' in self.temp_check_results and 'D' in self.temp_check_results:
            self._finalize_sync_display()

    def _finalize_sync_display(self):
        """Hàm hiển thị kết quả cuối cùng lên Bảng và tự động lọc lệnh"""
        data_c = self.temp_check_results.get('C', {})
        data_d = self.temp_check_results.get('D', {})
        all_nums = sorted(list(set(data_c.keys()) | set(data_d.keys())))
        
        # Xóa dữ liệu cũ trong bảng
        for item in self.tree_results.get_children():
            self.tree_results.delete(item)

        sync_map_for_input = {} 

        for num in all_nums:
            res_c = data_c.get(num, {'status': 'missing', 'desc': 'CHƯA CÓ'})
            res_d = data_d.get(num, {'status': 'missing', 'desc': 'CHƯA CÓ'})
            
            # Xử lý Text và Tag cho Node C
            desc_c = res_c.get('desc', 'CHƯA CÓ').replace('ĐÃ KHAI BÁO', '').strip('() ')
            tag_c = "res_ok" if res_c['status'] == 'found' else ("res_inherited" if res_c['status'] == 'inherited' else "res_fail")
            
            # Xử lý Text và Tag cho Node D
            desc_d = res_d.get('desc', 'CHƯA CÓ').replace('ĐÃ KHAI BÁO', '').strip('() ')
            tag_d = "res_ok" if res_d['status'] == 'found' else ("res_inherited" if res_d['status'] == 'inherited' else "res_fail")

            # Đưa vào Treeview
            item_id = self.tree_results.insert("", "end", values=(num, desc_c, desc_d))
            # Set màu chung cho cả dòng dựa theo trạng thái của C (có thể tùy biến thêm nếu lệch)
            self.tree_results.item(item_id, tags=(tag_c,))

            # --- LOGIC ĐÁNH GIÁ ĐỒNG BỘ ĐỂ GỬI SANG Ô INPUT ---
            empty_stats = ['inherited', 'not_found', 'no_data', 'missing']
            c_is_empty = res_c['status'] in empty_stats
            d_is_empty = res_d['status'] in empty_stats
            
            if c_is_empty and d_is_empty:
                sync_map_for_input[num] = "ok_empty"
            elif (not c_is_empty) and d_is_empty:
                sync_map_for_input[num] = "diff"
            elif c_is_empty and (not d_is_empty):
                sync_map_for_input[num] = "diff"
            else:
                if (res_c.get('rc') == res_d.get('rc') and 
                    res_c.get('md_val') == res_d.get('md_val') and 
                    res_c.get('bnt') == res_d.get('bnt')):
                    sync_map_for_input[num] = "ok_found"
                else:
                    sync_map_for_input[num] = "diff"

        self._highlight_input_based_on_sync(sync_map_for_input)
        
    def _highlight_input_based_on_sync(self, sync_map):
        """
        Tô màu ô input, kiểm tra độ dài an toàn, CÚ PHÁP SITE, và tự động bốc tách lệnh.
        """
        self.txt_input_numbers.config(state=tk.NORMAL)
        
        # 1. Reset: Xóa tag và comment cũ
        self.txt_input_numbers.tag_remove("ok_action", "1.0", tk.END)
        self.txt_input_numbers.tag_remove("bad_action", "1.0", tk.END)
        self.txt_input_numbers.tag_remove("check_comment", "1.0", tk.END)
        self.txt_input_numbers.tag_remove("error_comment", "1.0", tk.END)
        
        full_content = self.txt_input_numbers.get("1.0", tk.END)
        lines = full_content.splitlines()
        clean_lines = []
        for line in lines:
            clean = line.split('#')[0].rstrip()
            if clean: clean_lines.append(clean)
        
        self.txt_input_numbers.delete("1.0", tk.END)
        self.txt_input_numbers.insert("1.0", "\n".join(clean_lines))
        
        # 2. Bắt đầu đánh giá
        lines = self.txt_input_numbers.get("1.0", tk.END).splitlines()
        data_c = self.temp_check_results.get('C', {})
        allow_free = self.allow_free_input.get()
        valid_lines_for_config = [] 

        for i, line in enumerate(lines):
            try:
                clean_line = line.strip()
                parts = re.split(r'[\s,;]+', clean_line)
                if not parts or not parts[0].isdigit(): continue
                
                raw_num = parts[0]
                num = raw_num[2:] if raw_num.startswith("84") else (raw_num[1:] if raw_num.startswith("0") else raw_num)
                
                action_word = parts[1].upper() if len(parts) > 1 else ""
                if action_word in ["XÓA", "XOA", "HUY", "DELETE"]: 
                    action_word = "DELETE"

                line_start = f"{i+1}.0"
                line_end = f"{i+1}.end"
                
                # --- KIỂM TRA ĐỘ DÀI (CHỈ ÁP DỤNG KHI LÀ LỆNH XÓA VÀ KHÔNG TICK NHẬP TỰ DO) ---
                is_len_ok = False
                curr_len = len(num)
                if action_word == "DELETE" and not allow_free:
                    if num.startswith("91") and curr_len in [8, 9, 10]: is_len_ok = True
                    elif num.startswith("138") and curr_len in [9, 10]: is_len_ok = True
                    elif (num.startswith("1900") or num.startswith("1800")) and curr_len in [8, 10]: is_len_ok = True
                    elif not (num.startswith("91") or num.startswith("138") or num.startswith("1900") or num.startswith("1800")) and curr_len == 10: is_len_ok = True
                    
                    if not is_len_ok:
                        self.txt_input_numbers.tag_add("bad_action", line_start, line_end)
                        self.txt_input_numbers.insert(line_end, f" # 🚫 Lỗi: Số quá ngắn ({curr_len} số). Chặn lệnh XÓA dải lớn!", "error_comment")
                        continue
                # -----------------------------------------------------------------------------

                # --- TÌM KEY B-NUMBER CHUẨN ---
                cmd_set = self._generate_single_command(num)
                lookup_key = num 
                if cmd_set and 'check' in cmd_set:
                    match = re.search(r'B=([^;]+)', cmd_set['check'])
                    if match: lookup_key = match.group(1)
                
                status = sync_map.get(lookup_key)
                
                # Lấy mô tả phụ
                res_details = data_c.get(lookup_key, {})
                desc_text = res_details.get('desc', '').replace('ĐÃ KHAI BÁO', '').strip('() ')
                if "KẾ THỪA" in desc_text or not desc_text: desc_text = "Chưa có số này"

                tag_to_apply = None
                comment_msg = ""
                comment_tag = "check_comment" 

                # --- LOGIC HIỂN THỊ VÀ LỌC LỆNH ---
                if action_word == "ROUTE":
                    site = parts[2].upper() if len(parts) > 2 else ""
                    intended_action_key = None
                    
                    if num.startswith("1900") or num.startswith("1800"):
                        if site == 'HCM': intended_action_key = 'route_hcm'
                        elif site == 'HNI': intended_action_key = 'route_hni'
                        else: intended_action_key = 'route_vims'
                    elif num.startswith("91"):
                        if site == 'HNI':   intended_action_key = 'route_hni'
                        elif site == 'HCM': intended_action_key = 'route_hcm'
                        else:               intended_action_key = 'route_91'
                    elif num.startswith("138"):
                        if site == 'HNI':   intended_action_key = 'route_hni'
                        else:               intended_action_key = 'route_hcm'
                    elif site == 'HCM': intended_action_key = 'route_hcm'
                    elif site == 'HNI': intended_action_key = 'route_hni'
                    elif site in ['VIMS', 'IMS']: intended_action_key = 'route_fixed_vims'

                    # [SỬA LỖI Ở ĐÂY] Kiểm tra Site hợp lệ trước khi làm gì khác
                    is_site_valid = True
                    if not site and not (num.startswith("1900") or num.startswith("1800") or num.startswith("91") or num.startswith("138")):
                        tag_to_apply = "bad_action"
                        comment_msg = " # 🚫 Lỗi: Thiếu Site (HCM/HNI/VIMS)"
                        comment_tag = "error_comment"
                        is_site_valid = False
                    elif site and site not in ['HCM', 'HNI', 'VIMS', 'IMS']:
                        tag_to_apply = "bad_action"
                        comment_msg = f" # 🚫 Lỗi: Site '{site}' không hợp lệ"
                        comment_tag = "error_comment"
                        is_site_valid = False

                    if is_site_valid:
                        # Rút trích mã RC (742, 703, 607) dự định từ lệnh MML ảo
                        intended_cmd = cmd_set.get(intended_action_key) if cmd_set and intended_action_key else None
                        intended_rc = ""
                        if intended_cmd:
                            rc_match = re.search(r"RC\s*=\s*(\d+)", intended_cmd)
                            if rc_match: intended_rc = rc_match.group(1)

                        if status == "diff":
                            tag_to_apply = "bad_action"
                            comment_msg = " # ❗ Lệch Data (Sẽ đồng bộ lại)"
                            valid_lines_for_config.append(clean_line) 

                        elif status == "ok_found":
                            current_rc = res_details.get('rc')
                            # So sánh RC dự định và RC thực tế trên đài
                            if intended_rc and intended_rc == current_rc:
                                tag_to_apply = "bad_action"
                                comment_msg = f" # ⚠️ Trùng khớp ({desc_text})"
                            else:
                                intended_desc = self._get_route_description(intended_rc) if intended_rc else "Mới"
                                tag_to_apply = "ok_action"
                                comment_msg = f" # 🔄 OK (Sẽ đổi hướng -> {intended_desc})"
                                valid_lines_for_config.append(clean_line) # Được đẩy vào mảng để sinh lệnh Đổi Hướng
                        
                        elif status == "ok_empty":
                            tag_to_apply = "ok_action"
                            comment_msg = " # ✅ OK (Tạo mới)"
                            valid_lines_for_config.append(clean_line)

                elif action_word == "DELETE":
                    if status == "diff":
                        tag_to_apply = "bad_action"
                        comment_msg = " # ❗ Lệch Data (Sẽ đồng bộ lại)"
                        valid_lines_for_config.append(clean_line)
                    elif status == "ok_found":
                        tag_to_apply = "ok_action"
                        comment_msg = f" # ✅ OK (Sẵn sàng xóa {desc_text})"
                        valid_lines_for_config.append(clean_line)
                    elif status == "ok_empty":
                        tag_to_apply = "bad_action"
                        comment_msg = " # 🚫 Lỗi: Không xóa được (Chưa có số này)"
                        comment_tag = "error_comment"

                if tag_to_apply:
                    self.txt_input_numbers.tag_add(tag_to_apply, line_start, line_end)
                if comment_msg:
                    self.txt_input_numbers.insert(line_end, comment_msg, comment_tag)
            
            except Exception as e:
                print(f"Lỗi highlight dòng {i+1}: {e}")
                continue

        self.txt_input_numbers.config(state=tk.DISABLED)
        
        # --- TỰ ĐỘNG GỌI HÀM SINH LỆNH NẾU CÓ DÒNG HỢP LỆ ---
        if valid_lines_for_config:
            self.log_message("Đang tự động sinh lệnh MML tối ưu...", node="SYSTEM")
            self._auto_generate_from_list(valid_lines_for_config)
        else:
            self.txt_output_commands.configure(state='normal')
            self.txt_output_commands.delete('1.0', tk.END)
            self.txt_output_commands.insert(tk.END, "# Mọi thứ đã chuẩn xác. Không có lệnh nào cần chạy thêm!\n")
            self.txt_output_commands.configure(state='disabled')
            
            try:
                self.btn_run_tsse2c.config(state=tk.DISABLED)
                self.btn_run_tsse2d.config(state=tk.DISABLED)
                self.btn_run_both.config(state=tk.DISABLED)
            except: pass

    # --- [MỚI] HÀM PHỤ TRỢ ĐỂ SINH LỆNH TỰ ĐỘNG MÀ KHÔNG LÀM MẤT CHỮ TRONG Ô INPUT ---
    def _auto_generate_from_list(self, valid_lines):
        """Hàm phụ trợ để ép sinh lệnh từ danh sách list string đã lọc"""
        # 1. Lưu lại trạng thái và nội dung đang có trên màn hình
        old_state = self.txt_input_numbers.cget('state')
        self.txt_input_numbers.config(state=tk.NORMAL)
        # Lấy nội dung gốc (kèm comment) để lát nữa trả lại
        old_text_with_comments = self.txt_input_numbers.get('1.0', tk.END)
        
        # 2. Xóa ô input và đưa vào CHỈ những dòng hợp lệ
        self.txt_input_numbers.delete('1.0', tk.END)
        self.txt_input_numbers.insert('1.0', "\n".join(valid_lines))
        
        # 3. Tắt tạm tính năng "bỏ qua dòng lỗi" và gọi hàm sinh lệnh gốc
        old_skip = self.skip_bad_lines_var.get()
        self.skip_bad_lines_var.set(False) 
        
        # Gọi hàm gốc để nó đọc ô input (lúc này chỉ chứa dòng hợp lệ) và sinh ra bảng kết quả MML
        self.process_and_generate_commands()
        
        # 4. Phục hồi lại hiện trạng cũ cho người dùng
        self.skip_bad_lines_var.set(old_skip)
        self.txt_input_numbers.delete('1.0', tk.END)
        self.txt_input_numbers.insert('1.0', old_text_with_comments)
        
        # Chạy lại đoạn tô màu cho chắc ăn (vì insert lại text gốc có thể mất tag màu)
        # Chúng ta giả lập lại việc tô màu dựa trên comment có sẵn
        lines = old_text_with_comments.splitlines()
        for i, line in enumerate(lines):
            start = f"{i+1}.0"
            end = f"{i+1}.end"
            if "✅ OK" in line:
                self.txt_input_numbers.tag_add("ok_action", start, end)
                # Tìm và bôi xanh phần comment
                hash_idx = line.find('#')
                if hash_idx != -1: self.txt_input_numbers.tag_add("check_comment", f"{start}+{hash_idx}c", end)
            elif "🚫 Lỗi" in line or "⚠️ Trùng khớp" in line or "LỖI:" in line or "❗ Lệch" in line:
                self.txt_input_numbers.tag_add("bad_action", start, end)
                hash_idx = line.find('#')
                if hash_idx != -1: self.txt_input_numbers.tag_add("error_comment", f"{start}+{hash_idx}c", end)
                
        self.txt_input_numbers.config(state=old_state)
        
        # 5. Kích hoạt lại nút chạy vì đã có lệnh
        try:
            self.btn_run_tsse2c.config(state=tk.NORMAL)
            self.btn_run_tsse2d.config(state=tk.NORMAL)
            self.btn_run_both.config(state=tk.NORMAL)
        except: pass
    
    # ================== TÍNH NĂNG HIGHLIGHT CHÉO ==================
    def sync_highlight_from_table(self, event):
        """Click Bảng -> Bôi đen dòng Input"""
        selected_item = self.tree_results.selection()
        if not selected_item: return
        
        item_values = self.tree_results.item(selected_item[0], 'values')
        if not item_values: return
        b_num_from_table = item_values[0] # Lấy số đang click (VD: 39-2808...)

        # Đổi màu dòng đang chọn trong Treeview (Màu vàng)
        for item in self.tree_results.get_children():
            tags = list(self.tree_results.item(item, 'tags'))
            if "highlight" in tags: tags.remove("highlight")
            self.tree_results.item(item, tags=tags)
        
        current_tags = list(self.tree_results.item(selected_item[0], 'tags'))
        self.tree_results.item(selected_item[0], tags=current_tags + ["highlight"])

        # Tìm dòng tương ứng trên Input
        lines = self.txt_input_numbers.get("1.0", tk.END).splitlines()
        for i, line in enumerate(lines):
            clean_line = line.split('#')[0].strip()
            parts = re.split(r'[\s,;]+', clean_line)
            if not parts or not parts[0].isdigit(): continue
            
            raw_num = parts[0]
            num = raw_num[2:] if raw_num.startswith("84") else (raw_num[1:] if raw_num.startswith("0") else raw_num)
            
            # Tính ra b_num để so sánh
            cmd_set = self._generate_single_command(num)
            if cmd_set and 'check' in cmd_set:
                match = re.search(r'B=([^;]+)', cmd_set['check'])
                if match and match.group(1) == b_num_from_table:
                    # Bôi đen dòng i
                    start_idx = f"{i+1}.0"
                    end_idx = f"{i+1}.end"
                    self.txt_input_numbers.tag_remove(tk.SEL, "1.0", tk.END)
                    self.txt_input_numbers.tag_add(tk.SEL, start_idx, end_idx)
                    self.txt_input_numbers.mark_set(tk.INSERT, start_idx)
                    self.txt_input_numbers.see(start_idx)
                    self.txt_input_numbers.focus_set()
                    break

    def sync_highlight_from_input(self, event):
        """Click Input -> Đổi màu Bảng"""
        try:
            insert_idx = self.txt_input_numbers.index(tk.INSERT)
            line_num = int(insert_idx.split('.')[0])
            line_text = self.txt_input_numbers.get(f"{line_num}.0", f"{line_num}.end")
            
            clean_line = line_text.split('#')[0].strip()
            parts = re.split(r'[\s,;]+', clean_line)
            if not parts or not parts[0].isdigit(): return
            
            raw_num = parts[0]
            num = raw_num[2:] if raw_num.startswith("84") else (raw_num[1:] if raw_num.startswith("0") else raw_num)
            
            cmd_set = self._generate_single_command(num)
            target_b_num = ""
            if cmd_set and 'check' in cmd_set:
                match = re.search(r'B=([^;]+)', cmd_set['check'])
                if match: target_b_num = match.group(1)
            
            if not target_b_num: return

            # Xóa highlight cũ
            for item in self.tree_results.get_children():
                tags = list(self.tree_results.item(item, 'tags'))
                if "highlight" in tags: tags.remove("highlight")
                self.tree_results.item(item, tags=tags)

            # Tìm và highlight dòng mới
            for item in self.tree_results.get_children():
                values = self.tree_results.item(item, 'values')
                if values and target_b_num in str(values[0]):
                    current_tags = list(self.tree_results.item(item, 'tags'))
                    self.tree_results.item(item, tags=current_tags + ["highlight"])
                    self.tree_results.see(item) # Tự động cuộn bảng tới dòng đó
                    break
        except Exception: pass
    
    def _prepare_automation(self):
        if not self.ssh_details.get('user'):
            messagebox.showerror("Lỗi", "Vui lòng 'Tùy chọn -> Cài đặt SSH...' trước.")
            return False
        return True

    def _get_commands_and_job_type(self):
        commands_to_run = self.txt_output_commands.get('1.0', tk.END).strip().splitlines()
        if not commands_to_run:
            messagebox.showwarning("Cảnh báo", "Không có lệnh nào trong ô 'Lệnh đã tạo' để chạy.")
            return None, None
        is_check_job = False
        if commands_to_run[0].strip().startswith("ANBSP"):
            is_check_job = True
            self.log_message("Phát hiện tác vụ KIỂM TRA (read-only).", node="SYSTEM")
        else:
            self.log_message("Phát hiện tác vụ CẤU HÌNH (write).", node="SYSTEM")
        return commands_to_run, is_check_job
        
    def _mark_input_error(self, line_number, msg):
        """Hàm phụ trợ để đánh dấu dòng lỗi màu đỏ trong ô Input"""
        start_idx = f"{line_number}.0"
        end_idx = f"{line_number}.end"
        self.txt_input_numbers.tag_add("bad_action", start_idx, end_idx)
        self.txt_input_numbers.insert(end_idx, f" {msg}", "error_comment")

    def start_check_automation(self):
        """Pre-Check nghiêm ngặt trước khi kết nối (Chặn mọi cú pháp sai)"""
        
        # --- [MỚI] CHỐT CHẶN AN TOÀN ---
        tags = self.txt_input_numbers.tag_names("1.0")
        content = self.txt_input_numbers.get("1.0", tk.END).strip()
        if "placeholder" in tags or not content:
            return # Thoát luôn không làm gì cả nếu là chữ mờ hoặc trống
        # -------------------------------
        # --- [SỬA LỖI NGHIÊM TRỌNG] RESET TOÀN BỘ TRẠNG THÁI CŨ TRƯỚC KHI CHECK MỚI ---
        # 1. Khóa ngay nút Chạy Cấu Hình để chống bấm nhầm
        try: self.btn_run_both.config(state=tk.DISABLED)
        except: pass
        
        # 2. Xóa sạch ô Lệnh MML cũ
        self.txt_output_commands.config(state=tk.NORMAL)
        self.txt_output_commands.delete('1.0', tk.END)
        self.txt_output_commands.insert("1.0", "# Đang chờ dữ liệu kiểm tra mới...")
        self.txt_output_commands.config(state=tk.DISABLED)
        
        # 3. Xóa sạch Bảng trạng thái cũ
        try:
            for item in self.tree_results.get_children():
                self.tree_results.delete(item)
        except: pass
        # -----------------------------------------------------------------------------

           
        try:
            self.log_c.config(state=tk.NORMAL, bg=self.COLORS["log_bg"], fg=self.COLORS["log_fg_c"])
            self.log_c.delete('1.0', tk.END)
            self.log_c.config(state=tk.DISABLED)
            
            self.log_d.config(state=tk.NORMAL, bg=self.COLORS["log_bg"], fg=self.COLORS["log_fg_d"])
            self.log_d.delete('1.0', tk.END)
            self.log_d.config(state=tk.DISABLED)
        except: pass

        # 1. Dọn dẹp Textbox trước khi quét
        self.txt_input_numbers.config(state=tk.NORMAL)
        self.txt_input_numbers.tag_remove("ok_action", "1.0", tk.END)
        self.txt_input_numbers.tag_remove("bad_action", "1.0", tk.END)
        self.txt_input_numbers.tag_remove("check_comment", "1.0", tk.END)
        self.txt_input_numbers.tag_remove("error_comment", "1.0", tk.END)
        
        full_content = self.txt_input_numbers.get("1.0", tk.END)
        lines = full_content.splitlines()
        clean_lines = [line.split('#')[0].rstrip() for line in lines if line.strip()]
        self.txt_input_numbers.delete("1.0", tk.END)
        self.txt_input_numbers.insert("1.0", "\n".join(clean_lines))

        # 2. Bắt đầu quét từng dòng
        lines = self.txt_input_numbers.get("1.0", tk.END).splitlines()
        allow_free = self.allow_free_input.get()
        has_error = False
        check_commands = []
        
        for i, line in enumerate(lines):
            clean_line = line.strip()
            if not clean_line or clean_line.startswith("Dán") or clean_line.startswith("Ví dụ:"): continue
            
            parts = re.split(r'[\s,;]+', clean_line)
            if len(parts) < 2:
                self._mark_input_error(i+1, "# 🚫 Lỗi: Thiếu lệnh xử lý (Route/Delete)")
                has_error = True
                continue
            
            raw_num = parts[0]
            action_word = parts[1].upper()
            
            if not raw_num.isdigit():
                self._mark_input_error(i+1, "# 🚫 Lỗi: Chứa ký tự không phải số")
                has_error = True
                continue

            # --- [MỚI] KIỂM TRA CHÍNH TẢ CÚ PHÁP (Chặn 'rew', v.v.) ---
            if action_word not in ["ROUTE", "DELETE", "XOA", "XÓA", "HUY"]:
                self._mark_input_error(i+1, f"# 🚫 Lỗi: Sai cú pháp lệnh '{action_word}'")
                has_error = True
                continue

            # --- [MỚI] KIỂM TRA CHÍNH TẢ SITE (Chặn 'hdsd', v.v.) ---
            if action_word == "ROUTE":
                site = parts[2].upper() if len(parts) >= 3 else ""
                if site and site not in ['HCM', 'HNI', 'VIMS', 'IMS']:
                    self._mark_input_error(i+1, f"# 🚫 Lỗi: Site '{site}' không hợp lệ")
                    has_error = True
                    continue

            if action_word in ["XÓA", "XOA", "HUY", "DELETE"]: 
                action_word = "DELETE"
            
            num = raw_num[2:] if raw_num.startswith("84") else (raw_num[1:] if raw_num.startswith("0") else raw_num)
            curr_len = len(num)
            is_len_ok = False

            # --- KIỂM TRA ĐỘ DÀI KHI DÙNG LỆNH XÓA ---
            if action_word == "DELETE" and not allow_free:
                if num.startswith("91") and curr_len in [8, 9, 10]: is_len_ok = True
                elif num.startswith("138") and curr_len in [9, 10]: is_len_ok = True
                elif (num.startswith("1900") or num.startswith("1800")) and curr_len in [8, 10]: is_len_ok = True
                elif not (num.startswith("91") or num.startswith("138") or num.startswith("1900") or num.startswith("1800")) and curr_len == 10: is_len_ok = True
                
                if not is_len_ok:
                    self._mark_input_error(i+1, f"# 🚫 Lỗi: Số quá ngắn ({curr_len} số). Chặn lệnh XÓA dải lớn!")
                    has_error = True
                    continue
            
            # Tạo lệnh để đẩy xuống mảng check
            cmd_set = self._generate_single_command(num)
            if cmd_set and 'check' in cmd_set:
                check_commands.append(cmd_set['check'])

        self.txt_input_numbers.config(state=tk.DISABLED)

        # 3. CHẶN ĐỨNG NẾU PHÁT HIỆN BẤT KỲ LỖI NÀO
        if has_error:
            messagebox.showerror("Lỗi Nhập Liệu", "Phát hiện cú pháp sai hoặc số bị chặn!\nHệ thống đã đánh dấu dòng lỗi màu đỏ.\nVui lòng sửa lại trước khi Kiểm tra.")
            return

        if not check_commands:
            messagebox.showwarning("Cảnh báo", "Không có số nào hợp lệ để kiểm tra.")
            return

        if not self._prepare_automation(): return
        
        # 4. CHUẨN KỊ KIỂM TRA THỰC TẾ
        self._clear_check_results_box()
        self.log_message("Bắt đầu đẩy lệnh xuống thiết bị để KIỂM TRA (read-only)...", node="SYSTEM")
        
        self.temp_check_results = {}
        
        # Hiện Text tạm thông báo
        for item in self.tree_results.get_children(): self.tree_results.delete(item)
        self.tree_results.insert("", "end", values=("Đang lấy dữ liệu...", "Vui lòng đợi", "Vui lòng đợi"))

        user = self.ssh_details['user']
        pw = self.ssh_details['pass']
        host_c = self.ssh_details['host_c']
        host_d = self.ssh_details['host_d']
        
        t_c = threading.Thread(target=self.run_automation_wrapper, args=(host_c, user, pw, check_commands, True))
        t_c.daemon = True
        t_d = threading.Thread(target=self.run_automation_wrapper, args=(host_d, user, pw, check_commands, True))
        t_d.daemon = True

        self.running_threads = 2
        self.stop_event.clear()
        self.update_button_states()
        t_c.start()
        t_d.start()

    def run_automation_wrapper(self, host, user, pw, commands, is_check_job):
        """Wrapper chạy thread với màu báo hiệu chuẩn Bootstrap (Đã đồng bộ self.COLORS)"""
        job_status = "unknown"
        error_msg = "" # Biến lưu chi tiết lỗi

        try:
            self.run_automation(host, user, pw, commands, is_check_job)
            job_status = "success"
        except Exception as e:
            job_status = "error"
            error_msg = str(e) # Lưu lỗi để hiện popup
            self.log_message(f"Lỗi ngoại lệ: {e}", node="SYSTEM")
        finally:
            def _update_ui_after_thread():
                self.running_threads -= 1

                if self.running_threads == 0:
                    self.stop_event.clear()
                    self.update_button_states()

                    if not self.stop_event.is_set():
                        # --- DÙNG MÀU TỪ SELF.COLORS CHO ĐỒNG BỘ ---
                        # Màu Bootstrap chuẩn cho thông báo (hardcode nhẹ ở đây là ok vì là màu background alert)
                        SUCCESS_BG = "#D1E7DD" # Xanh nhạt
                        SUCCESS_FG = "#0F5132" # Xanh đậm
                        ERROR_BG   = "#F8D7DA" # Đỏ nhạt
                        ERROR_FG   = "#842029" # Đỏ đậm
                        
                        msg_title = "Hoàn tất Tác vụ"
                        msg_body = "Quy trình đã kết thúc."

                        if job_status == "success":
                            try:
                                # Blink Xanh
                                self.log_c.config(bg=SUCCESS_BG, fg=SUCCESS_FG)
                                self.log_d.config(bg=SUCCESS_BG, fg=SUCCESS_FG)
                                messagebox.showinfo(msg_title, msg_body + "\n\n✅ TRẠNG THÁI: THÀNH CÔNG")
                            except Exception: pass
                        else:
                            try:
                                # Blink Đỏ
                                self.log_c.config(bg=ERROR_BG, fg=ERROR_FG)
                                self.log_d.config(bg=ERROR_BG, fg=ERROR_FG)
                                # (SỬA) Hiện chi tiết lỗi trong popup
                                messagebox.showwarning(msg_title, msg_body + f"\n\n⚠️ CÓ LỖI XẢY RA:\n{error_msg}")
                            except Exception: pass

                        # Reset về màu GitHub Dark chuẩn (Lấy từ self.COLORS)
                        def reset_color():
                            try:
                                self.log_c.config(bg=self.COLORS["log_bg"], fg=self.COLORS["log_fg_c"])
                                self.log_d.config(bg=self.COLORS["log_bg"], fg=self.COLORS["log_fg_d"])
                            except: pass

                        self.root.after(3000, reset_color)

            self.root.after(0, _update_ui_after_thread)
    # ==================================================================
    # === BẮT ĐẦU KHỐI SSH LOGIC (ĐÃ SỬA TƯỜNG MINH) ===
    # ==================================================================

    def run_automation(self, host, user, pw, commands, is_check_job):
        """
        SỬA (01/11): Logic 'is_check_job' được sửa để
                     xử lý 'result_dict' từ _parse_anbsp_output
        """
        if host == self.ssh_details.get('host_c'):
            node_name = "TSSE2C"
        elif host == self.ssh_details.get('host_d'):
            node_name = "TSSE2D"
        else:
            node_name = "UNKNOWN"

        log = lambda msg: self.log_message(msg, node=node_name)

        log("="*30)
        log(f"BẮT ĐẦU PHIÊN LÀM VIỆC TỚI {node_name} ({host})")

        shell = None
        ssh = None
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(host, username=user, password=pw, timeout=10)

            shell = ssh.invoke_shell()
            time.sleep(1)
            
            initial = self.read_shell_output(shell, timeout=1, node=node_name)
            if initial.strip():
                log(f"RECV (init): {initial.strip()}")

            if self.stop_event.is_set(): raise Exception("Người dùng yêu cầu dừng.")
            MML_COMMAND = "mml -a"
            MML_PROMPT = "<"

            log(f"Đang vào chế độ MML bằng lệnh '{MML_COMMAND}'...")
            if not self.send_and_wait(shell, MML_COMMAND, MML_PROMPT, timeout=10, node=node_name):
                 raise Exception(f"Không thể vào chế độ MML (không thấy prompt '{MML_PROMPT}')")
            log("Đã vào chế độ MML.")

            if self.stop_event.is_set(): raise Exception("Người dùng yêu cầu dừng.")

            if is_check_job:
                log("Chế độ KIỂM TRA: Sẽ chạy lệnh riêng lẻ và phân tích output.")
                # (SỬA) check_results giờ là list[ (cmd, result_dict) ]
                check_results = [] 

                for i, cmd in enumerate(commands):
                    if self.stop_event.is_set(): raise Exception("Người dùng yêu cầu dừng.")
                    log(f"({i+1}/{len(commands)}) Gửi: {cmd}")

                    raw_output = self.send_and_wait_for_output(shell, cmd, MML_PROMPT, timeout=15, node=node_name)

                    if self.stop_event.is_set(): raise Exception("Người dùng yêu cầu dừng.")
                    
                    b_number_full = ""
                    b_match = re.search(r'B=([^;]+)', cmd)
                    if b_match:
                        b_number_full = b_match.group(1).strip()
                    else:
                        log(f"CẢNH BÁO: Không thể trích xuất B-Number từ lệnh: {cmd}")
                        check_results.append((cmd, {'status': 'error', 'desc': 'LỖI LỆNH (Không thấy B=...)'}))
                        continue
                    
                    # (SỬA) Lấy về result_dict
                    result_dict = self._parse_anbsp_output(raw_output, b_number_full)
                    
                    check_results.append((cmd, result_dict))

                log(f"HOÀN TẤT: Đã chạy xong {len(commands)} lệnh kiểm tra.")
                
                if check_results:
                    log(f"Đã lấy xong dữ liệu {node_name}. Đang chờ node còn lại để so sánh...")
                    # Gọi hàm thu thập dữ liệu thay vì hàm update UI trực tiếp
                    self.root.after(0, lambda r=check_results, n=node_name: self._collect_and_compare_results(r, n))

            else:
                # (KHỐI LỆNH CẤU HÌNH (else) GIỮ NGUYÊN NHƯ CŨ)
                log("Chế độ CẤU HÌNH: Sẽ bắt đầu giao dịch (ANBLI...).")

                if self.stop_event.is_set(): raise Exception("Người dùng yêu cầu dừng.")
                log("Đang gửi ANBLI; (chờ 'EXECUTED')...")

                shell.send("ANBLI;\n")
                output = ""
                start_time = time.time()
                anbli_success = False
                protection_error = False

                while time.time() - start_time < 10:
                    if self.stop_event.is_set(): raise Exception("Người dùng yêu cầu dừng.")
                    new_output = self.read_shell_output(shell, timeout=1, node=node_name)
                    if new_output:
                        log(f"RECV: {new_output.strip()}")
                        output += new_output
                        if "EXECUTED" in output:
                            anbli_success = True
                            time.sleep(0.3)
                            self.read_shell_output(shell, timeout=1.0, node=node_name)
                            break
                        if "PROTECTION CANNOT BE REMOVED" in output:
                            protection_error = True
                            break
                        fail_conditions = ["NOT ACCEPTED", "SYNTAX ERROR", "FUNCTION BUSY", "FAULT CODE"]
                        if any(err in output for err in fail_conditions if err != "FAULT CODE 38"):
                            break
                    time.sleep(0.2)

                if self.stop_event.is_set(): raise Exception("Người dùng yêu cầu dừng.")

                if anbli_success:
                    log("ANBLI thành công. Bắt đầu giao dịch MỚI.")
                    if self.stop_event.is_set(): raise Exception("Người dùng yêu cầu dừng.")
                    log("Đang gửi ANBZI; (chờ 'ORDERED')...")
                    if not self.send_and_wait(shell, "ANBZI;", "ORDERED", timeout=30, node=node_name):
                        raise Exception("Lỗi khi chạy ANBZI hoặc không nhận được 'ORDERED'")
                    if self.stop_event.is_set(): raise Exception("Người dùng yêu cầu dừng.")
                    self._send_ctrl_d_and_wait(shell, timeout=610, node=node_name)
                    log("ANBZI hoàn tất.")
                    if self.stop_event.is_set(): raise Exception("Người dùng yêu cầu dừng.")
                    log("Đang làm mới terminal (gửi Enter) để dọn rác...")
                    if not self.send_and_wait(shell, "", MML_PROMPT, timeout=10, node=node_name):
                        log("CẢNH BÁO: Không nhận được prompt '<' khi làm mới.")
                    log("Terminal đã được làm mới. (1)")
                    if self.stop_event.is_set(): raise Exception("Người dùng yêu cầu dừng.")
                    log("Đang gửi ANBCI; (sẽ gửi CTRL+D ngay sau đó)...")
                    shell.send("ANBCI;\n")
                    log("Đã gửi ANBCI;.")
                    if self.stop_event.is_set(): raise Exception("Người dùng yêu cầu dừng.")
                    self._send_ctrl_d_and_wait(shell, timeout=30, node=node_name)
                    log("ANBCI hoàn tất.")

                elif protection_error:
                    log("!!! CẢNH BÁO: Phát hiện lỗi PROTECTION CANNOT BE REMOVED")
                    log(">>> Tự động TIẾP TỤC. Chuyển sang chế độ 'Khôi phục Giao dịch'...")
                    
                    if self.stop_event.is_set(): raise Exception("Người dùng yêu cầu dừng.")

                    # --- SỬA LOGIC LINH HOẠT CHO ANBZI (ORDERED hoặc EXECUTED) ---
                    log("Đang gửi ANBZI; (chế độ khôi phục)...")
                    shell.send("ANBZI;\n") # Gửi thủ công để tự xử lý luồng phản hồi
                    
                    anbzi_buffer = ""
                    start_time_rec = time.time()
                    anbzi_done = False

                    while time.time() - start_time_rec < 30:
                        if self.stop_event.is_set(): raise Exception("Người dùng yêu cầu dừng.")
                        
                        # Đọc dữ liệu mới
                        new_data = self.read_shell_output(shell, timeout=0.2, node=node_name)
                        if new_data:
                            if new_data.strip(): log(f"RECV (Recovery): {new_data.strip()}")
                            anbzi_buffer += new_data
                            
                            # TRƯỜNG HỢP 1: Nhận được EXECUTED luôn -> Xong, không cần Ctrl+D
                            if "EXECUTED" in anbzi_buffer or "COMMAND EXECUTED" in anbzi_buffer:
                                log("✓ ANBZI thành công ngay lập tức (Nhận được EXECUTED).")
                                anbzi_done = True
                                break
                            
                            # TRƯỜNG HỢP 2: Nhận được ORDERED -> Phải gửi Ctrl+D
                            if "ORDERED" in anbzi_buffer:
                                log("✓ Nhận được ORDERED. Đang gửi CTRL+D để xác nhận...")
                                # Hàm này sẽ gửi Ctrl+D và tự chờ EXECUTED tiếp
                                self._send_ctrl_d_and_wait(shell, timeout=610, node=node_name)
                                anbzi_done = True
                                break
                                
                            # Check lỗi
                            fail_conditions = ["NOT ACCEPTED", "SYNTAX ERROR", "FUNCTION BUSY", "FAULT CODE"]
                            if any(err in anbzi_buffer for err in fail_conditions):
                                log(f"Lỗi: ANBZI bị từ chối: {anbzi_buffer}")
                                break

                    if not anbzi_done:
                         raise Exception("Lỗi ANBZI (Khôi phục): Timeout hoặc không nhận được phản hồi hợp lệ (ORDERED/EXECUTED).")

                    log("ANBZI (khôi phục) hoàn tất.")
                    # -------------------------------------------------------------

                    if self.stop_event.is_set(): raise Exception("Người dùng yêu cầu dừng.")

                    log("Đang làm mới terminal (gửi Enter) để dọn rác...")
                    if not self.send_and_wait(shell, "", MML_PROMPT, timeout=10, node=node_name):
                        log("CẢNH BÁO: Không nhận được prompt '<' khi làm mới.")
                    log("Terminal đã được làm mới. (1)")
                    if self.stop_event.is_set(): raise Exception("Người dùng yêu cầu dừng.")

                    log("Đang gửi ANBCI; (sẽ gửi CTRL+D ngay sau đó)...")
                    shell.send("ANBCI;\n")
                    log("Đã gửi ANBCI;.")
                    if self.stop_event.is_set(): raise Exception("Người dùng yêu cầu dừng.")

                    self._send_ctrl_d_and_wait(shell, timeout=30, node=node_name)
                    log("ANBCI (khôi phục) hoàn tất.")

                else:
                    log(f"!!! LỖI: ANBLI thất bại (Output: {output.strip()})")
                    raise Exception("Lỗi khi chạy ANBLI (không phải lỗi 38)")

                if self.stop_event.is_set(): raise Exception("Người dùng yêu cầu dừng.")

                log("Đang làm mới terminal (gửi Enter) để dọn rác...")
                if not self.send_and_wait(shell, "", MML_PROMPT, timeout=10, node=node_name):
                    log("CẢNH BÁO: Không nhận được prompt '<' khi làm mới.")
                log("Terminal đã được làm mới. (2)")
                if self.stop_event.is_set(): raise Exception("Người dùng yêu cầu dừng.")

                log(f"Bắt đầu gửi {len(commands)} lệnh cấu hình...")
                for i, cmd in enumerate(commands):
                    if self.stop_event.is_set(): raise Exception("Người dùng yêu cầu dừng.")
                    log(f"({i+1}/{len(commands)}) Gửi: {cmd}")
                    if not self.send_and_wait(shell, cmd, "EXECUTED", timeout=10, node=node_name):
                        raise Exception(f"Lệnh thất bại: {cmd}")

                    if self.stop_event.is_set(): raise Exception("Người dùng yêu cầu dừng.")
                    log(f"Làm mới terminal sau lệnh {i+1}...")
                    if not self.send_and_wait(shell, "", MML_PROMPT, timeout=10, node=node_name):
                        log(f"CẢNH BÁO: Không nhận được prompt '<' khi làm mới (lệnh {i+1}).")

                log("Tất cả các lệnh đã được gửi thành công.")
                if self.stop_event.is_set(): raise Exception("Người dùng yêu cầu dừng.")

                log("Đang áp dụng thay đổi với ANBAI (Giai đoạn 1)...")

                if not self.send_and_wait(shell, "ANBAI;", MML_PROMPT, timeout=15, node=node_name):
                    raise Exception("Lỗi GĐ 1 ANBAI: Không thấy prompt '<' trả về")
                if self.stop_event.is_set(): raise Exception("Người dùng yêu cầu dừng.")

                log("Đã nhận prompt '<'. Gửi confirm ';' (Giai đoạn 2)...")

                time.sleep(0.3); self.read_shell_output(shell, timeout=1.0, node=node_name)
                shell.send(";\n") 

                output_anbai = ""
                start_time_anbai = time.time()
                anbai_success = False

                while time.time() - start_time_anbai < 15: 
                    if self.stop_event.is_set(): raise Exception("Người dùng yêu cầu dừng.")
                    new_output = self.read_shell_output(shell, timeout=1, node=node_name)
                    if new_output:
                        log(f"RECV: {new_output.strip()}")
                        output_anbai += new_output

                        if "COMMAND EXECUTED" in output_anbai or "EXECUTED" in output_anbai:
                            anbai_success = True
                            log(f"✓ Phát hiện thành công: {'EXECUTED' if 'EXECUTED' in output_anbai else 'COMMAND EXECUTED'}")
                            break 
                        fail_conditions = ["NOT ACCEPTED", "SYNTAX ERROR", "FUNCTION BUSY", "FAULT CODE"]
                        if any(err in output_anbai for err in fail_conditions):
                             raise Exception("Lỗi GĐ 2 ANBAI: Bị từ chối (NOT ACCEPTED, etc.)")
                    time.sleep(0.2)

                if not anbai_success:
                    raise Exception("Lỗi GĐ 2 ANBAI: Hết giờ chờ 'EXECUTED' / 'COMMAND EXECUTED'")

                if self.stop_event.is_set(): raise Exception("Người dùng yêu cầu dừng.")

                log("Làm mới terminal (gửi Enter) để dọn rác...")
                if not self.send_and_wait(shell, "", MML_PROMPT, timeout=10, node=node_name):
                    log("CẢNH BÁO: Không nhận được prompt '<' khi làm mới.")
                log("Terminal đã được làm mới. (3)")

                log(f"HOÀN TẤT: Đã áp dụng thành công các thay đổi trên {node_name} ({host})")

        except Exception as e:
            if "Người dùng yêu cầu dừng" not in str(e):
                 log(f"!!! LỖI NGHIÊM TRỌNG ({node_name}): {e}")
                 log(f"Quy trình trên {node_name} bị hủy. CÁC THAY ĐỔI CÓ THỂ CHƯA ĐƯỢT ÁP DỤNG.")
                 # [THÊM DÒNG NÀY] Ném lỗi ra cho luồng cha bắt và hiển thị Popup cảnh báo!
                 raise Exception(f"Mất kết nối tới {node_name}: {e}")
            else:
                 log(f"--- Quy trình trên {node_name} đã dừng theo yêu cầu ---")

            if shell:
                log(f"Đang đóng kết nối tới {node_name} do lỗi hoặc dừng...")

        finally:
            if shell:
                try:
                    log(f"Đang thoát khỏi MML trên {node_name} (gửi 'exit;')...")
                    shell.send("exit;\n")
                    time.sleep(0.5)
                    shell.close()
                except Exception:
                    pass
            if ssh:
                try:
                    ssh.close()
                except Exception:
                    pass
            log(f"Đã đóng kết nối tới {node_name} ({host})")
            log("="*30)

    def _send_ctrl_d_and_wait(self, shell, timeout=610, node=None):
        """
        SỬA: Thêm 'node=None' và truyền nó cho các hàm con
        TỐI ƯU: Di chuyển list ra ngoài vòng lặp 'while'
        """
        if self.stop_event.is_set():
            raise Exception("Người dùng yêu cầu dừng.")

        time.sleep(0.5)
        initial_junk = self.read_shell_output(shell, timeout=1.0, node=node)
        if initial_junk.strip():
            self.log_message(f"--- DỌN RÁC (TRƯỚC CTRL+D) --- \n{initial_junk.strip()}\n---------------", node=node)

        if self.stop_event.is_set():
            raise Exception("Người dùng yêu cầu dừng.")
        self.log_message(f"Gửi CTRL+D để thực thi (chờ tối đa {timeout}s)...", node=node)
        try:
            shell.send(b'\x04')
        except Exception:
            try:
                shell.send("\x04")
            except Exception:
                pass

        output = ""
        start_time = time.time()
        command_executed = False

        # --- TỐI ƯU HÓA: Khai báo list 1 lần bên ngoài vòng lặp ---
        success_patterns = ["COMMAND EXECUTED", "EXECUTED", "FUNCTION ACTIVATED"]
        fail_conditions = [
            "NOT ACCEPTED", "SYNTAX ERROR", "FUNCTION BUSY", "FAULT CODE"
        ]
        # --- KẾT THÚC TỐI ƯU HÓA ---

        while time.time() - start_time < timeout:
            if self.stop_event.is_set():
                raise Exception("Người dùng yêu cầu dừng.")
            new_output = self.read_shell_output(shell, timeout=1, node=node)
            if new_output:
                self.log_message(f"RECV: {new_output.strip()}", node=node)
                output += new_output

                # Giờ chỉ sử dụng list đã khai báo
                if any(pattern in output for pattern in success_patterns):
                    command_executed = True
                    self.log_message(f"✓ Phát hiện thành công: {[p for p in success_patterns if p in output]}", node=node)
                    break

                # Giờ chỉ sử dụng list đã khai báo
                if any(err in output for err in fail_conditions):
                    self.log_message(f"Lỗi: Thiết bị từ chối sau khi gửi CTRL+D", node=node)
                    break

            time.sleep(0.2)

        if not command_executed:
            if "NOT ACCEPTED" in output or "SYNTAX ERROR" in output or "FUNCTION BUSY" in output:
                 raise Exception("Lỗi thực thi: Thiết bị từ chối (NOT ACCEPTED/SYNTAX/BUSY)")
            else:
                 self.log_message(f"!!! DEBUG: Toàn bộ output nhận được:\n{output}\n!!!", node=node)
                 raise Exception(f"LỖI HẾT GIỜ: Không tìm thấy success pattern sau {timeout}s")

        if self.stop_event.is_set():
            raise Exception("Người dùng yêu cầu dừng.")
        time.sleep(0.5)
        final_junk = self.read_shell_output(shell, timeout=2.0, node=node)
        if final_junk.strip():
            self.log_message(f"--- DỌN RÁC (SAU CTRL+D) --- \n{final_junk.strip()}\n---------------", node=node)

        return True
    
    # --- [MỚI] HÀM GỬI LỆNH ĐA NĂNG (Hỗ trợ list prompts) ---
    def send_command_wait_prompts(self, shell, cmd, wait_for_list, timeout=30, node=None):
        """
        Gửi lệnh và chờ cho đến khi gặp BẤT KỲ chuỗi nào trong wait_for_list.
        Dùng cho các lệnh trả về prompt lạ như <CW_> hoặc <___>.
        """
        if self.stop_event.is_set():
            raise Exception("Người dùng yêu cầu dừng.")

        # Dọn rác buffer trước khi gửi
        time.sleep(0.2)
        initial_junk = self.read_shell_output(shell, timeout=0.5, node=node)
        if initial_junk.strip():
            # Log rác nếu cần, hoặc bỏ qua cho gọn
            pass

        # Gửi lệnh
        try:
            shell.send(cmd + "\n")
            self.log_message(f"SENT: {cmd}", node=node) # Log lệnh gửi đi
        except Exception:
            try: shell.send((cmd + "\n").encode())
            except: pass

        output_buffer = ""
        start_time = time.time()

        while time.time() - start_time < timeout:
            if self.stop_event.is_set():
                raise Exception("Người dùng yêu cầu dừng.")

            # Dùng hàm read turbo có sẵn
            new_output = self.read_shell_output(shell, timeout=0.1, node=node)

            if new_output:
                # Log ngay lập tức (Streaming output)
                if new_output.strip():
                    self.log_message(new_output, node=node)
                
                output_buffer += new_output

                # 1. Kiểm tra lỗi phổ biến
                fail_conditions = ["NOT ACCEPTED", "SYNTAX ERROR", "FUNCTION BUSY", "FAULT CODE"]
                if any(err in output_buffer for err in fail_conditions):
                    self.log_message(f"Lỗi: Thiết bị từ chối lệnh: {cmd}", node=node)
                    return output_buffer # Trả về để bên ngoài xử lý tiếp (hoặc raise Exception)

                # 2. Kiểm tra danh sách prompt mong muốn
                # Ví dụ: wait_for_list = ["<CW_>", "<___>", "COMMAND EXECUTED"]
                for marker in wait_for_list:
                    if marker in output_buffer:
                        # Tìm thấy prompt kết thúc -> Done
                        return output_buffer

            time.sleep(0.1)

        self.log_message(f"LỖI HẾT GIỜ (Timeout {timeout}s): Không thấy prompt kết thúc.", node=node)
        return output_buffer
        
    def read_shell_output(self, shell, timeout=2, node=None):
        """
        PHIÊN BẢN TURBO V2: Đọc dữ liệu thô nhanh nhất có thể.
        """
        output = ""
        start_time = time.time()
        
        while True:
            # Check stop event
            if self.stop_event.is_set(): break
            
            # Hết giờ thì thoát
            if time.time() - start_time > timeout: break

            try:
                if shell.recv_ready():
                    # Đọc liên tục đến khi hết sạch buffer
                    while shell.recv_ready():
                        # Tăng buffer lên 65535 để đọc 1 cú được nhiều log hơn
                        data = shell.recv(65535) 
                        if not data: break
                        output += data.decode('utf-8', errors='ignore')
                    return output
                else:
                    # Ngủ cực ngắn để không chiếm CPU nhưng phản hồi nhanh
                    time.sleep(0.005) 
            except Exception:
                break

        return output

    def send_and_wait(self, shell, cmd, wait_for, timeout=10, node=None):
        """
        PHIÊN BẢN SIÊU TỐC (Cho Route/Delete): 
        Bắn lệnh liên tục, chỉ cần thấy khớp từ khóa (EXECUTED/<) là đi tiếp ngay.
        """
        if self.stop_event.is_set(): raise Exception("Người dùng yêu cầu dừng.")

        # [TỐI ƯU] Bỏ qua bước đọc rác và sleep(0.3) đầu vào
        # Vì lệnh trước đó kết thúc là buffer đã sạch rồi.

        try:
            shell.send(cmd + "\n")
        except Exception:
            try: shell.send((cmd + "\n").encode())
            except: pass

        output = ""
        start_time = time.time()

        while time.time() - start_time < timeout:
            if self.stop_event.is_set(): raise Exception("Người dùng yêu cầu dừng.")
            
            # Gọi hàm read turbo (timeout cực ngắn 0.05s)
            new_output = self.read_shell_output(shell, timeout=0.05, node=node)
            
            if new_output:
                # Log ra màn hình để bạn theo dõi kịp
                if new_output.strip():
                    self.log_message(f"RECV: {new_output.strip()}", node=node)
                
                output += new_output

                # 1. Kiểm tra thành công (wait_for thường là "EXECUTED" hoặc "<")
                if wait_for in output:
                    return True

                # 2. Kiểm tra lỗi ngay lập tức để không phải chờ hết timeout
                fail_conditions = [
                    "NOT ACCEPTED", "SYNTAX ERROR", "FUNCTION BUSY", 
                    "FAULT CODE", "Command not found"
                ]
                if any(err in output for err in fail_conditions):
                    self.log_message(f"Lỗi: Thiết bị từ chối lệnh: {cmd}", node=node)
                    return False
            
            # Không cần sleep cứng, hàm read_shell_output đã điều tiết CPU rồi

        self.log_message(f"LỖI HẾT GIỜ: Không tìm thấy '{wait_for}' sau khi gửi '{cmd}'", node=node)
        return False
        
    def _get_rc_list_from_selection(self, selected_rc_raw):
        """(MỚI) Lấy danh sách RC thực tế từ lựa chọn dropdown."""
        selected_rc = selected_rc_raw.split(" ")[0] # Lấy "115" từ "115 (...)"
        if selected_rc == "115":
            return ["115", "1155", "1157"]
        else:
            return [selected_rc] # Trả về list chứa 1 item, ví dụ ["113"]
            
    def send_and_wait_for_output(self, shell, cmd, wait_for_marker, timeout=15, node=None):
        """
        PHIÊN BẢN SIÊU TỐC: Bỏ dọn rác đầu vào, giảm độ trễ vòng lặp.
        """
        if self.stop_event.is_set(): raise Exception("Người dùng yêu cầu dừng.")

        # [TỐI ƯU] BỎ QUA bước time.sleep(0.3) và đọc rác. 
        # Lý do: Lệnh trước đó đã đọc đến dấu nhắc '<' nên buffer đang sạch.
        
        try:
            shell.send(cmd + "\n")
        except Exception:
            try: shell.send((cmd + "\n").encode())
            except: pass

        output_buffer = "" 
        start_time = time.time()

        while time.time() - start_time < timeout:
            if self.stop_event.is_set(): raise Exception("Người dùng yêu cầu dừng.")
            
            # Gọi hàm read turbo với timeout cực ngắn
            new_output = self.read_shell_output(shell, timeout=0.05, node=node)
            
            if new_output:
                # Log ngay (nhưng log ngắn gọn thôi nếu muốn nhanh hơn nữa)
                if new_output.strip():
                    self.log_message(f"RECV: {new_output.strip()}", node=node)
                
                output_buffer += new_output 

                # Check lỗi nhanh
                if any(err in output_buffer for err in ["NOT ACCEPTED", "SYNTAX ERROR", "FAULT CODE"]):
                    # Vẫn trả về output để hàm parse phân tích lỗi cụ thể
                    return output_buffer 

                # Check dấu kết thúc
                if wait_for_marker in output_buffer:
                    return output_buffer

            # [TỐI ƯU] Không sleep cứng ở đây nữa, hàm read_shell_output đã lo việc đó
            # Vòng lặp sẽ quay lại ngay lập tức để check dữ liệu mới

        self.log_message(f"LỖI HẾT GIỜ: Không tìm thấy '{wait_for_marker}'", node=node)
        return output_buffer

if __name__ == "__main__":
    try:
        import paramiko
    except ImportError:
        print("LỖI: Thiếu thư viện paramiko.")
        exit()
        
    # QUAN TRỌNG: Dùng 'flatly' để các override màu sắc hoạt động chuẩn nhất
    root = ttk.Window(themename="flatly") 
    
    app = SipRouterApp(root)
    root.mainloop()