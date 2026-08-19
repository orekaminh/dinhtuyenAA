from flask import Flask, render_template, request, redirect, url_for, flash, session
from datetime import datetime, timedelta
from flask_socketio import SocketIO, emit
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import paramiko
import time
import threading
import re
import os
import sys
from logic_core import generate_commands
import csv
from io import StringIO
from flask import Response

# --- CẤU HÌNH CƠ BẢN ---
def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

app = Flask(__name__, template_folder=resource_path('templates'), static_folder=resource_path('static'))
app.config['SECRET_KEY'] = 'secret_key_bao_mat_cao_hon' # Nên đổi cái này phức tạp hơn
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db' # File DB sẽ nằm cùng thư mục
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=8)

# Khởi tạo Extension
db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login' # Nếu chưa login thì đá về route này

socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')
stop_event = threading.Event()

SSH_CONFIG = {
    'TSSE2C': {'host': '10.202.47.54', 'user': 'minhth', 'pass': 'S@igon#10'},
    'TSSE2D': {'host': '10.202.49.54', 'user': 'minhth', 'pass': 'S@igon#10'}
}

# --- DATABASE MODEL ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    must_change_password = db.Column(db.Boolean, default=True) # Cờ bắt buộc đổi pass

class ActionLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.now)
    username = db.Column(db.String(150), nullable=False)
    commands = db.Column(db.Text, nullable=False) # Lưu lại khối lệnh MML đã chạy
    
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.route('/history')
@login_required
def view_history():
    search_query = request.args.get('q', '').strip()
    start_date_str = request.args.get('start_date', '')
    end_date_str = request.args.get('end_date', '')
    page = request.args.get('page', 1, type=int)
    per_page = 50

    # Khởi tạo query gốc
    query = ActionLog.query

    # 1. Lọc theo từ khóa (nếu có)
    if search_query:
        query = query.filter(
            ActionLog.username.contains(search_query) | 
            ActionLog.commands.contains(search_query)
        )
    
    # 2. Lọc theo Từ ngày (nếu có)
    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            query = query.filter(ActionLog.timestamp >= start_date)
        except: pass

    # 3. Lọc theo Đến ngày (nếu có)
    if end_date_str:
        try:
            # Cộng thêm 1 ngày rồi trừ đi 1 giây để lấy trọn vẹn đến 23:59:59 của ngày đó
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d') + timedelta(days=1, seconds=-1)
            query = query.filter(ActionLog.timestamp <= end_date)
        except: pass

    # Phân trang kết quả
    pagination = query.order_by(ActionLog.timestamp.desc()).paginate(page=page, per_page=per_page, error_out=False)
    
    return render_template('history.html', pagination=pagination, user=current_user, 
                           search_query=search_query, start_date=start_date_str, end_date=end_date_str)

@app.route('/export-history')
@login_required
def export_history():
    # Copy nguyên block lấy điều kiện từ hàm view_history xuống
    search_query = request.args.get('q', '').strip()
    start_date_str = request.args.get('start_date', '')
    end_date_str = request.args.get('end_date', '')
    
    query = ActionLog.query
    if search_query:
        query = query.filter(ActionLog.username.contains(search_query) | ActionLog.commands.contains(search_query))
    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            query = query.filter(ActionLog.timestamp >= start_date)
        except: pass
    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d') + timedelta(days=1, seconds=-1)
            query = query.filter(ActionLog.timestamp <= end_date)
        except: pass

    # Lấy toàn bộ data sau khi lọc (không phân trang)
    logs = query.order_by(ActionLog.timestamp.desc()).all()

    def generate():
        data = StringIO()
        writer = csv.writer(data)
        writer.writerow(['Thời gian', 'Người thực hiện', 'Nội dung thao tác'])
        yield data.getvalue().encode('utf-8-sig') 
        data.seek(0); data.truncate(0)
        
        for log in logs:
            writer.writerow([log.timestamp.strftime('%Y-%m-%d %H:%M:%S'), log.username, log.commands])
            yield data.getvalue().encode('utf-8-sig')
            data.seek(0); data.truncate(0)

    time_str = datetime.now().strftime('%Y%m%d_%H%M')
    return Response(generate(), mimetype='text/csv', headers={"Content-Disposition": f"attachment; filename=Log_TacDong_{time_str}.csv"})
    
# --- AUTH ROUTES ---
@app.route('/admin/manage-users', methods=['GET', 'POST'])
@login_required
def manage_users_web():
    # Phân quyền: Chỉ cho phép user 'admin' truy cập
    if current_user.username != 'admin':
        flash('Bạn không có quyền truy cập trang quản trị!', 'danger')
        return redirect(url_for('index'))

    if request.method == 'POST':
        new_username = request.form.get('username')
        new_password = request.form.get('password')

        # Kiểm tra xem user đã tồn tại chưa
        existing_user = User.query.filter_by(username=new_username).first()
        if existing_user:
            flash(f"Tài khoản '{new_username}' đã tồn tại!", 'danger')
        elif len(new_password) < 6:
            flash('Mật khẩu mặc định phải từ 6 ký tự trở lên!', 'warning')
        else:
            # Tạo user mới và bắt buộc đổi mật khẩu
            hashed_pw = generate_password_hash(new_password, method='pbkdf2:sha256')
            new_user = User(username=new_username, password=hashed_pw, must_change_password=True)
            db.session.add(new_user)
            db.session.commit()
            flash(f"✅ Đã tạo tài khoản '{new_username}' thành công!", 'success')
            return redirect(url_for('manage_users_web'))

    # Lấy danh sách tất cả user để hiển thị ra bảng
    all_users = User.query.all()
    return render_template('manage_users.html', users=all_users, user=current_user)

@app.route('/admin/delete-user/<int:user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    # 1. Chặn người dùng thường, chỉ admin mới được gọi lệnh này
    if current_user.username != 'admin':
        flash('Bạn không có quyền thực hiện thao tác này!', 'danger')
        return redirect(url_for('index'))

    user_to_delete = User.query.get_or_404(user_id)

    # 2. Logic chuẩn: Không cho phép tự xóa account đang dùng để đăng nhập
    if user_to_delete.id == current_user.id:
        flash('🚫 Lỗi: Không thể tự xóa tài khoản đang đăng nhập!', 'danger')
    else:
        username_deleted = user_to_delete.username
        db.session.delete(user_to_delete)
        db.session.commit()
        flash(f"🗑️ Đã xóa tài khoản '{username_deleted}' thành công!", 'success')

    return redirect(url_for('manage_users_web'))
    
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
        
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password, password):
            login_user(user)
            session.permanent = True
            # Nếu user phải đổi pass, chuyển hướng sang trang đổi pass
            if user.must_change_password:
                flash('Đây là lần đăng nhập đầu tiên. Vui lòng đổi mật khẩu!', 'warning')
                return redirect(url_for('change_password'))
            return redirect(url_for('index'))
        else:
            flash('Sai tên đăng nhập hoặc mật khẩu.', 'danger')
            
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        new_pass = request.form.get('new_password')
        confirm_pass = request.form.get('confirm_password')
        
        if new_pass != confirm_pass:
            flash('Mật khẩu xác nhận không khớp!', 'danger')
        elif len(new_pass) < 6:
            flash('Mật khẩu phải dài hơn 6 ký tự!', 'danger')
        else:
            current_user.password = generate_password_hash(new_pass, method='pbkdf2:sha256')
            current_user.must_change_password = False # Tắt cờ bắt buộc đổi
            db.session.commit()
            flash('Đổi mật khẩu thành công! Hãy sử dụng Tool.', 'success')
            return redirect(url_for('index'))
            
    return render_template('change_password.html')

# --- MIDDLEWARE: CHẶN USER CHƯA ĐỔI PASS ---
@app.before_request
def check_password_change():
    if current_user.is_authenticated and current_user.must_change_password:
        # Cho phép truy cập static files và trang logout/change-password
        if request.endpoint not in ['change_password', 'logout', 'static']:
            return redirect(url_for('change_password'))

@app.route('/')
@login_required # Bắt buộc người dùng phải đăng nhập mới vào được tool
def index():
    # Cung cấp biến 'user' cho giao diện HTML bằng current_user
    return render_template('index.html', user=current_user)

# --- LOGIC PARSER (GIỮ NGUYÊN TỪ BẢN TRƯỚC) ---
def _get_route_description(rc_value):
    rc_map = {"703": "AA-HNI", "742": "AA-HCM", "607": "vIMS"}
    return rc_map.get(str(rc_value), f"RC-{rc_value}")

def _parse_anbsp_output(raw_output, b_number_full):
    try:
        if "NOT ACCEPTED" in raw_output or "FAULT CODE" in raw_output:
            if "ANALYSIS POINT CANNOT BE REACHED" in raw_output:
                return {'status': 'error', 'desc': 'LỖI: FAULT CODE 7'}
            fault_match = re.search(r"FAULT CODE\s+(\d+)", raw_output)
            if fault_match:
                return {'status': 'error', 'desc': f"LỖI: FAULT CODE {fault_match.group(1)}"}
            return {'status': 'error', 'desc': 'LỖI: NOT ACCEPTED'}

        if "NO DATA EXIST" in raw_output:
            return {'status': 'no_data', 'desc': 'CHƯA KHAI BÁO (NO DATA EXIST)'}

        lines = raw_output.splitlines()
        found_block = False
        block_data = ""
        target_pattern = re.compile(rf"^\s*{re.escape(b_number_full)}\s+.*F=", re.IGNORECASE)

        for i, line in enumerate(lines):
            if target_pattern.search(line):
                found_block = True
                block_data += line + "\n"
                for next_line in lines[i+1:]:
                    if not next_line.strip(): continue
                    if next_line.startswith(" ") or next_line.startswith("\t"):
                        block_data += next_line + "\n"
                    else: break
                break

        if found_block:
            rc_match = re.search(r"RC\s*=\s*(\d+)", block_data)
            m_match = re.search(r"M\s*=\s*([\d-]+)", block_data)
            d_match = re.search(r"D\s*=\s*([\d-]+)", block_data) 
            bnt_match = re.search(r"BNT\s*=\s*(\d+)", block_data)
            
            rc_val = rc_match.group(1) if rc_match else "?"
            bnt_val = bnt_match.group(1) if bnt_match else "?"
            md_str = f"M={m_match.group(1)}" if m_match else (f"D={d_match.group(1)}" if d_match else "?")
            
            route_desc = _get_route_description(rc_val)
            desc = f"ĐÃ KHAI BÁO ({route_desc} | RC={rc_val}, {md_str}, BNT={bnt_val})"
            return {'status': 'found', 'desc': desc}

        # Logic Inheritance
        parent_candidates = []
        all_bnum_matches = re.finditer(r"^(\d+-\d+).*F=", raw_output, re.MULTILINE)
        for match in all_bnum_matches:
            found_num = match.group(1).strip()
            if b_number_full.startswith(found_num) and len(found_num) < len(b_number_full):
                parent_candidates.append(found_num)
        
        if not parent_candidates:
            return {'status': 'not_found', 'desc': 'CHƯA KHAI BÁO (Không tìm thấy)'}

        parent_candidates.sort(key=len, reverse=True)
        best_parent = parent_candidates[0]
        parent_result = _parse_anbsp_output(raw_output, best_parent)
        if parent_result['status'] == 'found':
            parent_result['status'] = 'inherited'
            clean_desc = parent_result['desc'].replace('ĐÃ KHAI BÁO', '').strip('() ')
            parent_result['desc'] = f"KẾ THỪA (từ {best_parent}) | {clean_desc}"
            return parent_result
        
        return {'status': 'not_found', 'desc': 'CHƯA KHAI BÁO'}
    except Exception as e:
        return {'status': 'error', 'desc': f"LỖI PHÂN TÍCH: {e}"}

# --- SOCKET EVENTS ---
@socketio.on('stop_task')
def handle_stop_task():
    stop_event.set()
    emit('log_system', {'msg': '🛑 Đã nhận lệnh DỪNG...', 'type': 'error'})

@socketio.on('generate_config_preview')
def handle_generate_preview(data):
    input_text = data.get('input', '')
    allow_free = data.get('allow_free', False)
    commands = generate_commands(input_text, allow_free_input=allow_free, skip_errors=False, mode='CONFIG')
    cmd_str = "\n".join(commands) if commands else "# Không tạo được lệnh."
    emit('config_generated', {'commands': cmd_str})

@socketio.on('run_check_automation')
def handle_check_automation(data):
    input_text = data.get('input', '')
    allow_free = data.get('allow_free', False)
    check_commands = generate_commands(input_text, allow_free_input=allow_free, skip_errors=True, mode='CHECK')
    if not check_commands:
        emit('log_system', {'msg': '❌ Không có lệnh kiểm tra.', 'type': 'error'}); return
    emit('log_system', {'msg': f'🔄 Đang kiểm tra {len(check_commands)} lệnh...', 'type': 'info'})
    stop_event.clear()
    emit('clear_results')
    def run_wrapper():
        t1 = threading.Thread(target=run_ssh_task, args=('TSSE2C', check_commands, True))
        t2 = threading.Thread(target=run_ssh_task, args=('TSSE2D', check_commands, True))
        t1.start()
        t2.start()
        
        t1.join() # Chờ TSSE2C xong
        t2.join() # Chờ TSSE2D xong
        
        # Chỉ gửi tín hiệu khi CẢ HAI đã hoàn thành
        socketio.emit('check_finished')

    threading.Thread(target=run_wrapper).start()

@socketio.on('execute_config_ssh')
def handle_execute_config(data):
    # 1. Lấy danh sách lệnh
    commands = [line.strip() for line in data.get('commands', '').split('\n') if line.strip() and not line.strip().startswith('#')]
    if not commands: return
    
    # 2. Xử lý làm sạch nội dung hiển thị cho Log
    raw_input_data = data.get('raw_input', '')
    user_action = current_user.username if current_user.is_authenticated else "Unknown"
    
    clean_actions = []
    if raw_input_data:
        for line in raw_input_data.split('\n'):
            core_part = line.split('#')[0].strip()
            if core_part:
                clean_actions.append(core_part)
                
    log_content = "\n".join(clean_actions) if clean_actions else "Thao tác cấu hình"

    stop_event.clear()

    # 3. Luồng chạy chính
    def run_wrapper():
        t1 = threading.Thread(target=run_ssh_task, args=('TSSE2C', commands, False))
        t2 = threading.Thread(target=run_ssh_task, args=('TSSE2D', commands, False))
        
        t1.start()
        t2.start()
        
        t1.join()
        t2.join()

        # === ĐOẠN ĐIỀU CHỈNH: KIỂM TRA TRẠNG THÁI TRƯỚC KHI LƯU ===
        # Chỉ lưu vào DB nếu người dùng KHÔNG bấm nút Dừng (stop_event không được set)
        if not stop_event.is_set():
            # Vì đang chạy trong luồng phụ (Thread), cần gọi app_context để thao tác với DB
            with app.app_context():
                new_log = ActionLog(username=user_action, commands=log_content)
                db.session.add(new_log)
                db.session.commit()
        
        socketio.emit('execution_finished', {'status': 'done'})

    threading.Thread(target=run_wrapper).start()

# --- WORKER SSH (CORE LOGIC ĐÃ SỬA) ---
def run_ssh_task(node_name, commands, is_check_job):
    def log(msg, type='raw'):
        socketio.emit('log', {'msg': msg, 'type': type, 'node': node_name})

    def read_turbo(shell, timeout=1.0):
        """Đọc buffer tốc độ cao"""
        output = ""
        start = time.time()
        while time.time() - start < timeout:
            if stop_event.is_set(): break
            try:
                if shell.recv_ready():
                    while shell.recv_ready():
                        data = shell.recv(65535)
                        if not data: break
                        output += data.decode('utf-8', errors='ignore')
                else:
                    time.sleep(0.01)
            except: break
        if output: log(output, 'raw')
        return output

    def send_and_wait_prompt(shell, cmd, wait_marker="<", timeout=10):
        log(f"[SEND] {cmd}\n", 'cmd')
        shell.send(cmd + "\n")
        full_out = ""
        start = time.time()
        while time.time() - start < timeout:
            chunk = read_turbo(shell, 0.1)
            if chunk:
                full_out += chunk
                if wait_marker in full_out: return True, full_out
                if "NOT ACCEPTED" in full_out or "FAULT CODE" in full_out: return False, full_out
        return False, full_out

    # --- HÀM TRANSACTION THÔNG MINH (QUAN TRỌNG) ---
    def smart_transaction_step(shell, cmd, timeout=30):
        """
        Gửi lệnh (ANBZI/ANBCI/CMD) và tự động xử lý ORDERED -> Ctrl+D.
        BẮT BUỘC trả về EXECUTED mới tính là thành công.
        """
        log(f"[SEND] {cmd}\n", 'cmd')
        shell.send(cmd + "\n")
        full_out = ""
        start = time.time()
        
        step_ctrl_d_sent = False
        
        while time.time() - start < timeout:
            if stop_event.is_set(): break
            chunk = read_turbo(shell, 0.1)
            full_out += chunk
            
            # 1. Nếu thấy ORDERED -> Gửi Ctrl+D (Như file OK)
            if "ORDERED" in full_out and not step_ctrl_d_sent:
                log("  >>> [INFO] Nhận ORDERED. Gửi Ctrl+D...\n", 'cmd')
                time.sleep(0.5)
                shell.send("\x04") # Gửi Ctrl+D
                step_ctrl_d_sent = True
                full_out = "" # Xóa buffer để đợi EXECUTED mới
                start = time.time() # Reset thời gian chờ
                timeout = 600 # Tăng thời gian chờ xử lý
                continue

            # 2. Thành công CHUẨN
            if "COMMAND EXECUTED" in full_out or "EXECUTED" in full_out:
                return True, full_out
                
            # 3. Lỗi
            if "NOT ACCEPTED" in full_out or "SYNTAX ERROR" in full_out:
                if "FAULT CODE 38" in full_out: return False, full_out # Để bên ngoài xử lý Recovery
                log(f"❌ Lệnh bị từ chối: {cmd}\n", 'error')
                return False, full_out
                
        # 4. Hết giờ mà chỉ thấy prompt < (Lỗi file NOK) -> BÁO LỖI
        if "<" in full_out:
            log(f"⚠️ Lệnh '{cmd.strip()}' timeout nhưng thấy prompt '<'. KHÔNG CHẤP NHẬN.\n", 'error')
        else:
            log(f"❌ Timeout lệnh '{cmd.strip()}'.\n", 'error')
            
        return False, full_out

    ssh = None
    try:
        cfg = SSH_CONFIG.get(node_name)
        log(f"--- KẾT NỐI {node_name} ---\n", 'info')
        
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(cfg['host'], username=cfg['user'], password=cfg['pass'], timeout=10)
        
        shell = ssh.invoke_shell()
        read_turbo(shell, 1) # Dọn rác banner

        log("> mml\n", 'cmd')
        if not send_and_wait_prompt(shell, "mml", "<", 10)[0]:
            raise Exception("Không vào được MML")

        # === CHẾ ĐỘ CHECK ===
        if is_check_job:
            log("--- BẮT ĐẦU CHECK ---\n", 'info')
            for cmd in commands:
                if stop_event.is_set(): break
                ok, out = send_and_wait_prompt(shell, cmd, "<", 15)
                b_match = re.search(r'B=([\d-]+)', cmd)
                if b_match:
                    parsed = _parse_anbsp_output(out, b_match.group(1))
                    socketio.emit('check_result_item', {
                        'node': node_name, 'b_num': b_match.group(1),
                        'status': parsed['status'], 'desc': parsed['desc']
                    })

        # === CHẾ ĐỘ CONFIG (SỬA LOGIC ANBCI) ===
        else:
            log("--- BẮT ĐẦU CẤU HÌNH ---\n", 'info')
            
            # 1. ANBLI
            log("[SEND] ANBLI;\n", 'cmd')
            shell.send("ANBLI;\n")
            anbli_out = ""
            start = time.time()
            anbli_ok = False
            rec_needed = False
            
            while time.time() - start < 10:
                chunk = read_turbo(shell, 0.2)
                anbli_out += chunk
                if "EXECUTED" in anbli_out: anbli_ok = True; break
                if "PROTECTION CANNOT BE REMOVED" in anbli_out or "FAULT CODE 38" in anbli_out:
                    rec_needed = True; break
                if "NOT ACCEPTED" in anbli_out: break

            proceed = False

            # 2. GIAO DỊCH (TRANSACTION)
            if anbli_ok:
                log("✓ ANBLI thành công.\n", 'success')
                # ANBZI
                if smart_transaction_step(shell, "ANBZI;")[0]:
                    # ANBCI (Quan trọng: Dùng smart_transaction_step để bắt EXECUTED)
                    # Refresh buffer trước khi gửi
                    send_and_wait_prompt(shell, "", "<", 5)
                    
                    ok_anbci, _ = smart_transaction_step(shell, "ANBCI;", timeout=60)
                    if ok_anbci:
                        log("✓ ANBCI thành công (Đã thấy EXECUTED).\n", 'success')
                        proceed = True
                    else:
                        log("❌ ANBCI thất bại (Không thấy EXECUTED). DỪNG.\n", 'error')
                else:
                    log("❌ ANBZI thất bại.\n", 'error')

            elif rec_needed:
                log("⚠️ Lỗi 38. Chuyển sang RECOVERY MODE...\n", 'warning')
                # ANBZI (Recovery)
                if smart_transaction_step(shell, "ANBZI;")[0]:
                    send_and_wait_prompt(shell, "", "<", 5)
                    # ANBCI (Recovery)
                    ok_anbci, _ = smart_transaction_step(shell, "ANBCI;", timeout=60)
                    if ok_anbci:
                        log("✓ ANBCI (Recovery) thành công.\n", 'success')
                        proceed = True
                    else:
                        log("❌ ANBCI (Recovery) thất bại. DỪNG.\n", 'error')
                else:
                    log("❌ ANBZI (Recovery) thất bại.\n", 'error')
            else:
                log(f"❌ ANBLI lỗi: {anbli_out}\n", 'error')

            # 3. GỬI LỆNH VÀ APPLY
            if proceed:
                send_and_wait_prompt(shell, "", "<", 5) # Dọn rác lần cuối
                
                # Chạy lệnh
                for cmd in commands:
                    if stop_event.is_set(): break
                    ok_cmd, _ = smart_transaction_step(shell, cmd, timeout=20)
                    if not ok_cmd:
                        log(f"❌ Lỗi khi gửi lệnh: {cmd}. DỪNG.\n", 'error')
                        break # Dừng ngay nếu lệnh con lỗi
                
                # ANBAI (2 bước)
                if not stop_event.is_set():
                    log("--- APPLY (ANBAI) ---\n", 'info')
                    if send_and_wait_prompt(shell, "ANBAI;", "<", 15)[0]:
                        log("  >>> Nhận prompt <. Gửi Confirm (;)...\n", 'cmd')
                        shell.send(";\n")
                        
                        # Chờ EXECUTED cho bước confirm
                        ok_final, out_final = smart_transaction_step(shell, "", timeout=30) # Lệnh rỗng vì đã gửi ;
                        if ok_final or "COMMAND EXECUTED" in out_final: # Check lỏng hơn chút ở bước cuối
                             log("✅ ANBAI THÀNH CÔNG.\n", 'success')
                        else:
                             log(f"❌ ANBAI Confirm lỗi: {out_final}\n", 'error')
                    else:
                        log("❌ ANBAI (Bước 1) lỗi: Không thấy prompt <\n", 'error')

        log(f"✅ Kết thúc phiên {node_name}.\n", 'success')

    except Exception as e:
        log(f"❌ LỖI HỆ THỐNG: {e}\n", 'error')
    finally:
        if ssh: 
            try: shell.send("exit;\n"); ssh.close()
            except: pass
        socketio.emit('task_finished')

if __name__ == '__main__':
    # Tạo bảng DB nếu chưa có
    with app.app_context():
        db.create_all()
        
        # --- TẠO TÀI KHOẢN MẶC ĐỊNH NẾU DB TRỐNG ---
        if not User.query.first(): 
            default_user = User(
                username='admin',
                password=generate_password_hash('admin123', method='pbkdf2:sha256'),
                must_change_password=True
            )
            db.session.add(default_user)
            db.session.commit()
            print(">>> Đã tạo tài khoản mặc định: admin / admin123")

    socketio.run(app, host='0.0.0.0', port=5000, debug=True, allow_unsafe_werkzeug=True)