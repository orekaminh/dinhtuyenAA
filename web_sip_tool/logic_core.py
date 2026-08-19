import re

def generate_commands(input_text, allow_free_input=False, skip_errors=True, mode='CONFIG'):
    """
    Tạo lệnh MML.
    - mode: 'CONFIG' (Route/Delete) hoặc 'CHECK' (ANBSP)
    """
    commands = []
    lines = input_text.strip().splitlines()
    
    # Danh sách lệnh xóa mở rộng
    DELETE_KEYWORDS = ["DELETE", "XOA", "XÓA", "HUY"]

    for i, line in enumerate(lines):
        clean_line = line.split('#')[0].strip()
        if not clean_line: continue
        
        error_reason = None
        parts = re.split(r'[\s,;]+', clean_line)
        
        # CHECK (ANBSP) chỉ cần con số -> cho phép dán số trần (1 cột).
        # CONFIG (route/delete) vẫn bắt buộc có hành động.
        if len(parts) < 2 and mode != 'CHECK':
            error_reason = "Thiếu tham số"
        else:
            raw_num = parts[0]
            
            # [SỬA LỖI Ở ĐÂY] Khai báo biến action trước khi đem xuống dưới kiểm tra
            # (guard: dòng chỉ có số khi CHECK thì không có parts[1])
            action = parts[1].upper() if len(parts) > 1 else ""
            
            # [Fix] Xử lý số bắt đầu bằng 84 hoặc 0
            num = raw_num
            if num.startswith("84"): num = num[2:]
            elif num.startswith("0"): num = num[1:]
            
            if not num.isdigit():
                error_reason = f"Số không hợp lệ: {raw_num}"
            elif not allow_free_input and action in DELETE_KEYWORDS:
                curr_len = len(num)
                is_len_valid = True
                
                # [UPDATE] Validation linh hoạt hơn theo logic Excel
                if num.startswith("91"):
                    if curr_len not in [8, 9, 10]: is_len_valid = False
                elif num.startswith("138"):
                    if curr_len not in [9, 10]: is_len_valid = False
                elif (num.startswith("1900") or num.startswith("1800")):
                    if curr_len not in [8, 10]: is_len_valid = False
                elif not (num.startswith("91") or num.startswith("138") or num.startswith("1900") or num.startswith("1800")) and curr_len != 10: 
                    is_len_valid = False
                
                if not is_len_valid:
                    error_reason = f"Chặn lệnh XÓA do số quá ngắn ({curr_len}): {raw_num}"

        if error_reason:
            if not skip_errors: commands.append(f"# [LỖI Dòng {i+1}] {error_reason}")
            continue

        # Lấy lại các biến sau khi đã validate (action/site có thể rỗng nếu chỉ KIỂM TRA)
        action = parts[1].upper() if len(parts) > 1 else ""
        site = parts[2].upper() if len(parts) > 2 else ""
        
        cmd = None
        
        # --- CHẾ ĐỘ KIỂM TRA (ANBSP) ---
        if mode == 'CHECK':
            if num.startswith("91"):
                cmd = f"ANBSP:B=36-{num};"
            elif num.startswith("138"):
                cmd = f"ANBSP:B=206-{num};"
            elif num.startswith("1900") or num.startswith("1800"):
                cmd = f"ANBSP:B=204-{num};"
            else: # Cố định
                if num.startswith("28") or num.startswith("24"):
                    b_num = num[:2] + "088" + num[2:10]
                else:
                    b_num = num[:3] + "088" + num[3:10]
                cmd = f"ANBSP:B=39-{b_num};"

        # --- CHẾ ĐỘ CẤU HÌNH (ANBSI/ANBSE) ---
        else:
            if num.startswith("91"):
                b_val = "36"
                if len(num) == 9: l_param = "L=9;"
                else: l_param = "L=8-10;"
                
                if action == "ROUTE":
                    # [UPDATE] 91: HNI/HCM dùng M=0-0, BNT=3 | vIMS dùng M=0-84, BNT=1
                    if site == "HNI":
                        cmd = f"ANBSI:B={b_val}-{num},M=0-0,BNT=3,F=500,RC=703,CC=1,{l_param}"
                    elif site == "HCM":
                        cmd = f"ANBSI:B={b_val}-{num},M=0-0,BNT=3,F=500,RC=742,CC=1,{l_param}"
                    else:
                        # Mặc định vIMS (607)
                        cmd = f"ANBSI:B={b_val}-{num},M=0-84,BNT=1,F=500,RC=607,CC=1,{l_param}"
                        
                elif action in DELETE_KEYWORDS:
                    cmd = f"ANBSE:B={b_val}-{num};"

            elif num.startswith("138"):
                b_val = "206"
                if len(num) == 9: l_param = "L=9;"
                else: l_param = "L=10;"
                
                if action == "ROUTE":
                    # [UPDATE] 138: Cả HCM/HNI đều dùng M=0-84, BNT=1 (Theo Excel)
                    if site == "HNI":
                        cmd = f"ANBSI:B={b_val}-{num},M=0-84,BNT=1,F=500,RC=703,CC=1,{l_param}"
                    else:
                        # Mặc định HCM (742)
                        cmd = f"ANBSI:B={b_val}-{num},M=0-84,BNT=1,F=500,RC=742,CC=1,{l_param}"
                        
                elif action in DELETE_KEYWORDS:
                    cmd = f"ANBSE:B={b_val}-{num};"
                    
            elif num.startswith("1900") or num.startswith("1800"):
                b_val = "204"
                if len(num) == 10: l_param = "L=10;"
                else: l_param = "L=8-10;"

                if action == "ROUTE":
                    if site == "HCM":
                        # HCM: RC=742, BNT=3, Không M
                        cmd = f"ANBSI:B={b_val}-{num},BNT=3,F=500,RC=742,CC=1,{l_param}"
                    elif site == "HNI":
                        # [MỚI] HNI: RC=703, BNT=3, Không M
                        cmd = f"ANBSI:B={b_val}-{num},BNT=3,F=500,RC=703,CC=1,{l_param}"
                    else:
                        # Mặc định vIMS: RC=607, BNT=1, Có M
                        cmd = f"ANBSI:B={b_val}-{num},M=0-84,BNT=1,F=500,RC=607,CC=1,{l_param}"
                        
                elif action in DELETE_KEYWORDS:
                    cmd = f"ANBSE:B={b_val}-{num};"

            else: # Cố định
                if num.startswith("28") or num.startswith("24"):
                    b_num = num[:2] + "088" + num[2:10]
                    m_prefix = num[:2]; m_val = f"M=5-0{m_prefix}"
                else:
                    b_num = num[:3] + "088" + num[3:10]
                    m_prefix = b_num[:3]; m_val = f"M=6-0{m_prefix}"
                
                b_val = "39"
                if action in DELETE_KEYWORDS:
                    cmd = f"ANBSE:B={b_val}-{b_num};"
                elif action == "ROUTE":
                    # [FIX AN TOÀN] Kiểm tra chính xác hướng, không dùng else mặc định
                    rc = None
                    if site == "HCM":
                        rc = "742"
                    elif site == "HNI":
                        rc = "703"
                    elif site in ["IMS", "VIMS"]: # Chấp nhận cả IMS và VIMS
                        rc = "607"
                    
                    if rc:
                        cmd = f"ANBSI:B={b_val}-{b_num},{m_val},BNT=3,F=500,RC={rc},CC=1,L=13;"
                    else:
                        # Nếu nhập sai hướng hoặc quên nhập hướng
                        error_reason = f"Hướng '{site}' không hợp lệ (Chỉ nhận: HCM, HNI, IMS)"
                        if not skip_errors:
                            commands.append(f"# [LỖI Dòng {i+1}] {error_reason}")
                        continue # Bỏ qua, không sinh lệnh sai

        if cmd:
            commands.append(cmd)
        elif not skip_errors:
             commands.append(f"# [LỖI Dòng {i+1}] Không tạo được lệnh (Mode: {mode})")
            
    return commands