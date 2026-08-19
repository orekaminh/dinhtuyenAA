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
import json
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
# DB đặt cạnh .exe (khi đóng gói) hoặc cạnh SNOC2_RouteAA.py (khi chạy script) -> bền, KHÔNG phụ thuộc
# thư mục làm việc (CWD). Tránh tình trạng chạy .exe từ shortcut/đường dẫn khác lại dùng DB khác.
if getattr(sys, 'frozen', False):
    APP_DIR = os.path.dirname(sys.executable)      # thư mục chứa .exe (ổn định, ghi được)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
INSTANCE_DIR = os.path.join(APP_DIR, 'instance')
os.makedirs(INSTANCE_DIR, exist_ok=True)
DB_PATH = os.path.join(INSTANCE_DIR, 'users.db')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + DB_PATH.replace('\\', '/')  # instance/users.db cạnh .exe
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
    'TSSE2D': {'host': '10.202.49.54', 'user': 'minhth', 'pass': 'S@igon#10'},
    # Node chặn A2P (CLI blocklist) - dùng cho tab Chặn A2P
    'TSSN2D': {'host': '10.204.161.61', 'user': 'NGHIAP', 'pass': '0918433694'}
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

class A2PHistory(db.Model):
    # Danh sách số đang chặn A2P trên node TSSN2D (thay cho a2p_history.json của bản desktop).
    # Dùng DB để chia sẻ giữa nhiều người dùng và an toàn khi truy cập đồng thời.
    number = db.Column(db.String(20), primary_key=True)
    blocked_at = db.Column(db.String(30)) # "YYYY-MM-DD HH:MM:SS" hoặc "Unknown"
    
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

    # 2b. Chọn node đích (mặc định cả 2). Chỉ chấp nhận TSSE2C/TSSE2D.
    target_nodes = [n for n in (data.get('target_nodes') or ['TSSE2C', 'TSSE2D']) if n in ('TSSE2C', 'TSSE2D')]
    if not target_nodes:
        target_nodes = ['TSSE2C', 'TSSE2D']
    # Đẩy riêng 1 node -> ghi rõ phạm vi vào audit log
    if len(target_nodes) < 2:
        log_content = f"[Đẩy RIÊNG: {', '.join(target_nodes)}]\n" + log_content

    stop_event.clear()

    # 3. Luồng chạy chính
    def run_wrapper():
        threads = []
        for node in target_nodes:
            t = threading.Thread(target=run_ssh_task, args=(node, commands, False))
            t.start()
            threads.append(t)
        for t in threads:
            t.join()

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

# =====================================================================
# ===           TÍNH NĂNG ỨNG CỨU 11x (UCTT) - PORT TỪ DESKTOP      ===
# =====================================================================

# --- 1. LOGIC THUẦN (Không SSH) ---
def _get_rc_list_from_selection(selected_rc_raw):
    """Lấy danh sách RC thực tế từ lựa chọn dropdown ('115 (...)' -> 115/1155/1157)."""
    selected_rc = str(selected_rc_raw).split(" ")[0]  # Lấy "115" từ "115 (...)"
    if selected_rc == "115":
        return ["115", "1155", "1157"]
    return [selected_rc]

def _generate_uctt_command_sets(selected_rc_raw):
    """Tạo các bộ lệnh UCTT cho 1 hoặc nhiều RC (giữ nguyên 100% logic desktop)."""
    rc_list = _get_rc_list_from_selection(selected_rc_raw)
    sets = {
        'check_nop': [], 'check_op': [], 'fallback': [],
        'uctt_2': [], 'uctt_1_sip': [], 'uctt_1_analog': []
    }
    for rc_str in rc_list:
        sets['check_nop'].append(f"ANRSP:RC={rc_str},NOP;")   # Kiểm tra vùng NOP
        sets['check_op'].append(f"ANRSP:RC={rc_str};")        # Kiểm tra vùng OP
        sets['fallback'].append(f"ANRAR:RC={rc_str};")        # Fallback thường
        sets['uctt_2'].append(f"ANRAI:RC={rc_str};")          # Kích hoạt từ NOP có sẵn
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

def _decide_uctt_actions(op_state, nop_state, rc_raw):
    """Quyết định nút Changeover/Fallback dựa trên trạng thái OP/NOP (port logic desktop 1803-1871).
    Trả về dict: {changeover:{enabled,label,action}, fallback:{enabled,label,action}}"""
    changeover = {'enabled': False, 'label': 'Chuyển đổi...', 'action': None}
    fallback = {'enabled': False, 'label': 'Fallback (Không khả dụng)', 'action': None}

    # 1. ĐANG CHẠY SIP (Bình thường) -> Fallback tắt, Changeover bật
    if op_state == "sip":
        fallback['label'] = "Fallback (Đang ở SIP)"
        if nop_state == "analog":
            changeover = {'enabled': True, 'label': 'Kích hoạt Analog (ANRAI)', 'action': 'uctt_2'}
        else:
            changeover = {'enabled': True, 'label': 'Tạo & Chuyển sang Analog', 'action': 'uctt_1_analog'}

    # 2. ĐANG CHẠY ANALOG (Đang ứng cứu) -> Changeover tắt, Fallback bật
    elif op_state == "analog":
        changeover = {'enabled': False, 'label': 'Đang chạy Analog', 'action': None}
        if nop_state == "sip":
            # NOP còn giữ SIP -> ANRAR thường
            fallback = {'enabled': True, 'label': 'Fallback về SIP (ANRAR)', 'action': 'fallback'}
        else:
            # Sau 24h, NOP rỗng -> Tạo lại SIP (Lệnh Xanh)
            fallback = {'enabled': True, 'label': 'Tạo & Fallback về SIP (Lệnh Xanh)', 'action': 'uctt_1_sip'}

    # 3. TRƯỜNG HỢP KHÁC (Normal/Empty)
    else:
        if nop_state == "analog":
            changeover = {'enabled': True, 'label': 'Kích hoạt UCTT Analog', 'action': 'uctt_2'}
        elif nop_state == "sip":
            changeover = {'enabled': True, 'label': 'Kích hoạt UCTT SIP', 'action': 'uctt_2'}
        else:
            changeover = {'enabled': True, 'label': 'Tạo & Kích hoạt UCTT Analog', 'action': 'uctt_1_analog'}

    return {'changeover': changeover, 'fallback': fallback}

# --- 2. HELPER SSH CHO UCTT (port read_shell_output / send_and_wait / ...) ---
def _uctt_log(node_name, msg, log_type='raw'):
    socketio.emit('log', {'msg': msg, 'type': log_type, 'node': node_name})

def _uctt_read(shell, node_name, timeout=2):
    """Đọc buffer tốc độ cao (port read_shell_output)."""
    output = ""
    start = time.time()
    while True:
        if stop_event.is_set(): break
        if time.time() - start > timeout: break
        try:
            if shell.recv_ready():
                while shell.recv_ready():
                    data = shell.recv(65535)
                    if not data: break
                    output += data.decode('utf-8', errors='ignore')
                return output
            else:
                time.sleep(0.005)
        except Exception:
            break
    return output

def _uctt_send_and_wait(shell, node_name, cmd, wait_for, timeout=10):
    """Gửi lệnh, chờ thấy wait_for (port send_and_wait). Trả True/False."""
    if stop_event.is_set(): raise Exception("Người dùng yêu cầu dừng.")
    try:
        shell.send(cmd + "\n")
    except Exception:
        try: shell.send((cmd + "\n").encode())
        except Exception: pass

    output = ""
    start = time.time()
    while time.time() - start < timeout:
        if stop_event.is_set(): raise Exception("Người dùng yêu cầu dừng.")
        new_output = _uctt_read(shell, node_name, timeout=0.05)
        if new_output:
            if new_output.strip():
                _uctt_log(node_name, f"RECV: {new_output.strip()}\n", 'raw')
            output += new_output
            if wait_for in output:
                return True
            fail_conditions = ["NOT ACCEPTED", "SYNTAX ERROR", "FUNCTION BUSY", "FAULT CODE", "Command not found"]
            if any(err in output for err in fail_conditions):
                _uctt_log(node_name, f"❌ Thiết bị từ chối lệnh: {cmd}\n", 'error')
                return False
    _uctt_log(node_name, f"⚠️ HẾT GIỜ: Không thấy '{wait_for}' sau khi gửi '{cmd}'\n", 'error')
    return False

def _uctt_read_until(shell, node_name, end_markers, timeout=15):
    """Đọc output tới khi thấy 1 trong end_markers (port _read_until_prompt_or_end)."""
    output = ""
    start = time.time()
    while time.time() - start < timeout:
        if stop_event.is_set(): break
        new_output = _uctt_read(shell, node_name, timeout=0.5)
        if new_output:
            if new_output.strip():
                _uctt_log(node_name, new_output, 'raw')
            output += new_output
            if any(marker in output for marker in end_markers):
                break
        time.sleep(0.1)
    return output

def _uctt_send_confirm(shell, node_name, confirm_cmd, wait_for_list, timeout=15):
    """Gửi lệnh xác nhận (;) và chờ một trong wait_for_list (port _send_confirm_and_wait_anr)."""
    if stop_event.is_set(): raise Exception("Người dùng yêu cầu dừng.")

    time.sleep(0.3)
    junk = _uctt_read(shell, node_name, timeout=1.0)
    if junk.strip():
        _uctt_log(node_name, junk, 'raw')

    if stop_event.is_set(): raise Exception("Người dùng yêu cầu dừng.")
    try:
        shell.send(confirm_cmd + "\n")
    except Exception:
        try: shell.send((confirm_cmd + "\n").encode())
        except Exception: pass

    output = ""
    start = time.time()
    found = False
    while time.time() - start < timeout:
        if stop_event.is_set(): raise Exception("Người dùng yêu cầu dừng.")
        new_output = _uctt_read(shell, node_name, timeout=1)
        if new_output:
            _uctt_log(node_name, f"RECV (confirm): {new_output.strip()}\n", 'raw')
            output += new_output
            for item in wait_for_list:
                if item in output:
                    _uctt_log(node_name, f"✓ Phát hiện xác nhận: '{item}'\n", 'success')
                    found = True
                    break
            if found: break
            if any(err in output for err in ["NOT ACCEPTED", "SYNTAX ERROR", "FUNCTION BUSY", "FAULT CODE"]):
                _uctt_log(node_name, f"❌ Thiết bị từ chối confirm '{confirm_cmd.strip()}'\n", 'error')
                return False
        time.sleep(0.2)

    time.sleep(0.3)
    final_junk = _uctt_read(shell, node_name, timeout=1.5)
    if final_junk.strip():
        _uctt_log(node_name, final_junk, 'raw')

    if not found:
        _uctt_log(node_name, f"⚠️ HẾT GIỜ: Không thấy xác nhận {wait_for_list} sau '{confirm_cmd.strip()}'\n", 'error')
        return False
    return True

# --- 3. WORKER SSH (chạy trong thread) ---
def run_uctt_check_task(node_name, rc_raw, results, lock):
    """Worker SSH: kiểm tra OP/NOP cho RC trên 1 node (port _get_uctt_status_from_node)."""
    cfg = SSH_CONFIG.get(node_name)
    rc_list = _get_rc_list_from_selection(rc_raw)
    cmd_sets = _generate_uctt_command_sets(rc_raw)
    check_op_cmds = cmd_sets['check_op']
    check_nop_cmds = cmd_sets['check_nop']
    ssh = None
    shell = None

    if stop_event.is_set():
        with lock: results[node_name] = Exception("Người dùng đã dừng.")
        return

    try:
        _uctt_log(node_name, f"--- KẾT NỐI {node_name} ({cfg['host']}) ---\n", 'info')
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(cfg['host'], username=cfg['user'], password=cfg['pass'], timeout=10)
        shell = ssh.invoke_shell()
        time.sleep(1)
        _uctt_read(shell, node_name, timeout=1)  # Dọn rác banner

        if not _uctt_send_and_wait(shell, node_name, "mml -a", "<", timeout=10):
            raise Exception("Không vào được chế độ MML")

        node_results = {}
        for i, rc_item in enumerate(rc_list):
            if stop_event.is_set(): raise Exception("Dừng bởi người dùng.")

            _uctt_log(node_name, f"🔍 Kiểm tra OP (RC={rc_item})...\n", 'cmd')
            shell.send(check_op_cmds[i] + "\n")
            op_output = _uctt_read_until(shell, node_name, ["<"], timeout=15)

            rc_result = {'op': 'normal', 'nop': 'empty'}
            if "CSCF" in op_output: rc_result['op'] = 'sip'
            elif "TSN" in op_output: rc_result['op'] = 'analog'

            _uctt_log(node_name, f"🔍 Kiểm tra NOP (RC={rc_item})...\n", 'cmd')
            shell.send(check_nop_cmds[i] + "\n")
            nop_output = _uctt_read_until(shell, node_name, ["<"], timeout=15)

            if "CSCF" in nop_output: rc_result['nop'] = 'sip'
            elif "TSN" in nop_output: rc_result['nop'] = 'analog'

            node_results[rc_item] = rc_result

        first_result = node_results[rc_list[0]]
        _uctt_log(node_name, f"✓ Hoàn tất kiểm tra. Kết quả: {first_result}\n", 'success')
        with lock:
            results[node_name] = first_result

    except Exception as e:
        _uctt_log(node_name, f"❌ LỖI KẾT NỐI/KIỂM TRA: {e}\n", 'error')
        with lock:
            results[node_name] = e
    finally:
        if shell:
            try: shell.close()
            except Exception: pass
        if ssh:
            try: ssh.close()
            except Exception: pass

def run_uctt_exec_task(node_name, commands, action, rc_raw, results, lock):
    """Worker SSH: thực thi bộ lệnh UCTT trên 1 node (port _run_uctt_execution_thread).
    QUAN TRỌNG: KHÔNG dùng transaction ANBLI. Vào MML rồi gửi thẳng lệnh ANR*."""
    cfg = SSH_CONFIG.get(node_name)
    ssh = None
    shell = None
    success = False
    try:
        _uctt_log(node_name, f"--- KẾT NỐI {node_name} ({cfg['host']}) ---\n", 'info')
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(cfg['host'], username=cfg['user'], password=cfg['pass'], timeout=10)
        shell = ssh.invoke_shell()
        time.sleep(1)

        # Dọn dẹp phiên cũ (nếu có)
        _uctt_read(shell, node_name, timeout=1)
        try:
            shell.send("exit;\n"); time.sleep(0.5); _uctt_read(shell, node_name, timeout=1)
        except Exception:
            pass

        # Vào chế độ MML
        if not _uctt_send_and_wait(shell, node_name, "mml -a", "<", timeout=10):
            raise Exception("Không vào được MML")

        # --- ĐÃ BỎ KHỐI ANBLI: gửi lệnh UCTT trực tiếp ---
        for i, cmd in enumerate(commands):
            if stop_event.is_set(): raise Exception("Người dùng yêu cầu dừng.")
            _uctt_log(node_name, f"➡️ Gửi lệnh UCTT {i+1}/{len(commands)}: {cmd}\n", 'cmd')

            # Lệnh cần xác nhận 2 bước (ANRAI / ANRAR)
            if cmd.startswith("ANRAI") or cmd.startswith("ANRAR"):
                _uctt_log(node_name, "  (Phát hiện ANRAI/ANRAR -> xác nhận 2 bước)\n", 'info')
                # Bước 1: gửi lệnh chính, chờ prompt '<'
                if not _uctt_send_and_wait(shell, node_name, cmd, "<", timeout=15):
                    raise Exception(f"Lệnh {cmd} thất bại (GĐ1 không thấy '<')")
                if stop_event.is_set(): raise Exception("Người dùng yêu cầu dừng.")
                # Bước 2: gửi ';' confirm
                _uctt_log(node_name, "  Đã nhận '<'. Gửi confirm ';' (GĐ2)...\n", 'cmd')
                if not _uctt_send_confirm(shell, node_name, ";", ["<", "EXECUTED", "COMMAND EXECUTED"], timeout=15):
                    raise Exception(f"Lệnh {cmd} thất bại (GĐ2 không xác nhận)")
            # Lệnh cấu hình thường (ANRPI, ANRSI, ANRPE...)
            else:
                if not _uctt_send_and_wait(shell, node_name, cmd, "EXECUTED", timeout=15):
                    raise Exception(f"Lệnh UCTT thất bại: {cmd} (Không thấy EXECUTED)")
                # Làm mới buffer sau mỗi lệnh
                if not _uctt_send_and_wait(shell, node_name, "", "<", timeout=10):
                    _uctt_log(node_name, f"⚠️ Không nhận được '<' sau lệnh {cmd}\n", 'error')

        _uctt_log(node_name, f"✅ HOÀN TẤT thực thi '{action}' cho RC={rc_raw} trên {node_name}\n", 'success')
        success = True

    except Exception as e:
        _uctt_log(node_name, f"❌ LỖI khi thực thi UCTT trên {node_name}: {e}\n", 'error')
    finally:
        if shell:
            try: shell.send("exit;\n"); time.sleep(0.5); shell.close()
            except Exception: pass
        if ssh:
            try: ssh.close()
            except Exception: pass
        with lock:
            results[node_name] = success

# --- 4. SOCKET EVENTS ---
@socketio.on('run_uctt_check')
def handle_uctt_check(data):
    rc_raw = data.get('rc', '113')
    stop_event.clear()
    socketio.emit('log_system', {'msg': f'🔄 Đang kiểm tra UCTT RC={rc_raw} trên 2C & 2D...', 'type': 'info'})
    socketio.emit('uctt_busy', {'busy': True})

    results = {}
    lock = threading.Lock()

    def run_wrapper():
        t1 = threading.Thread(target=run_uctt_check_task, args=('TSSE2C', rc_raw, results, lock))
        t2 = threading.Thread(target=run_uctt_check_task, args=('TSSE2D', rc_raw, results, lock))
        t1.start(); t2.start()
        t1.join(); t2.join()

        status_c = results.get('TSSE2C')
        status_d = results.get('TSSE2D')

        disabled = {'enabled': False, 'label': 'Chuyển đổi...', 'action': None}
        disabled_fb = {'enabled': False, 'label': 'Fallback (Không khả dụng)', 'action': None}

        # Lỗi hoặc thiếu kết quả
        if isinstance(status_c, Exception) or isinstance(status_d, Exception) or status_c is None or status_d is None:
            socketio.emit('uctt_check_result', {
                'sync_ok': False,
                'status_text': f'RC={rc_raw}: Lỗi kết nối hoặc lệnh trên ít nhất 1 node.',
                'status_color': 'danger',
                'changeover': disabled, 'fallback': disabled_fb
            })
            return

        # Không đồng bộ
        if status_c != status_d:
            socketio.emit('uctt_check_result', {
                'sync_ok': False,
                'status_text': f'RC={rc_raw}: ⚠️ KHÔNG ĐỒNG BỘ! (2C: {status_c}, 2D: {status_d}). Vui lòng kiểm tra tay!',
                'status_color': 'danger',
                'changeover': disabled, 'fallback': disabled_fb
            })
            return

        # Đồng bộ -> quyết định nút
        op_state = status_c['op']
        nop_state = status_c['nop']
        actions = _decide_uctt_actions(op_state, nop_state, rc_raw)
        # Sinh sẵn danh sách lệnh để client xem trước + đưa vào hộp xác nhận
        cmd_sets = _generate_uctt_command_sets(rc_raw)
        co, fb = actions['changeover'], actions['fallback']
        preview_co = cmd_sets.get(co['action'], []) if (co['enabled'] and co['action']) else []
        preview_fb = cmd_sets.get(fb['action'], []) if (fb['enabled'] and fb['action']) else []
        socketio.emit('uctt_check_result', {
            'sync_ok': True,
            'status_text': f'RC={rc_raw}: OP={op_state.upper()}, NOP={nop_state.upper()} [Đồng bộ ✓]',
            'status_color': 'success',
            'changeover': actions['changeover'],
            'fallback': actions['fallback'],
            'preview_changeover': preview_co,
            'preview_fallback': preview_fb,
        })

    threading.Thread(target=run_wrapper).start()

@socketio.on('execute_uctt')
def handle_uctt_execute(data):
    rc_raw = data.get('rc', '')
    action = data.get('action', '')
    valid_actions = ('uctt_2', 'uctt_1_analog', 'uctt_1_sip', 'fallback')

    if not rc_raw or action not in valid_actions:
        socketio.emit('log_system', {'msg': '❌ Yêu cầu UCTT không hợp lệ.', 'type': 'error'})
        socketio.emit('uctt_finished', {'ok': False})
        return

    try:
        # An toàn: server TỰ sinh lệnh từ RC + action, không tin lệnh client gửi
        cmd_sets = _generate_uctt_command_sets(rc_raw)
        commands = cmd_sets.get(action, [])
        if not commands:
            socketio.emit('log_system', {'msg': '❌ Không sinh được lệnh UCTT.', 'type': 'error'})
            socketio.emit('uctt_finished', {'ok': False})
            return

        # Lấy user TRƯỚC khi vào thread (thread phụ không có request context)
        user_action = current_user.username if current_user.is_authenticated else "Unknown"
        stop_event.clear()
        socketio.emit('log_system', {'msg': f'🚨 Bắt đầu thực thi UCTT [{action}] RC={rc_raw}...', 'type': 'info'})

        results = {}
        lock = threading.Lock()

        def run_wrapper():
            t1 = threading.Thread(target=run_uctt_exec_task, args=('TSSE2C', commands, action, rc_raw, results, lock))
            t2 = threading.Thread(target=run_uctt_exec_task, args=('TSSE2D', commands, action, rc_raw, results, lock))
            t1.start(); t2.start()
            t1.join(); t2.join()

            ok = bool(results.get('TSSE2C')) and bool(results.get('TSSE2D'))

            # Chỉ ghi audit log nếu KHÔNG bị bấm Dừng (giống mẫu config)
            if not stop_event.is_set():
                with app.app_context():
                    log_content = f"[UCTT {action}] RC={rc_raw}\n" + "\n".join(commands)
                    new_log = ActionLog(username=user_action, commands=log_content)
                    db.session.add(new_log)
                    db.session.commit()

            socketio.emit('uctt_finished', {'ok': ok, 'rc': rc_raw, 'action': action})

        threading.Thread(target=run_wrapper).start()
    except Exception as e:
        socketio.emit('log_system', {'msg': f'❌ Lỗi xử lý yêu cầu UCTT: {e}', 'type': 'error'})
        socketio.emit('uctt_finished', {'ok': False})

# --- 5. ROUTE TRANG UCTT ---
@app.route('/uctt')
@login_required
def uctt():
    return render_template('uctt.html', user=current_user)

# =====================================================================
# ===            TÍNH NĂNG CHẶN A2P (TSSN2D) - PORT TỪ DESKTOP      ===
# =====================================================================
# Node TSSN2D dùng CLI blocklist (ZCWI/ZCWM/ZCWN). Lưu ý khác routing/UCTT:
#   - KHÔNG vào chế độ 'mml -a', KHÔNG dùng Ctrl+D.
#   - Gửi lệnh kết thúc bằng '\r' (CR), không phải '\n'.

A2P_NODE = 'TSSN2D'
A2P_BLOCKLIST_RE = re.compile(r"NAT\s+(\d+)\s+(RESTRICT\s*:\s*FINAL\s*RESULT)")

# --- 1. LOGIC THUẦN (Không SSH, test được) ---
def _a2p_parse_blocklist(raw_output):
    """Tách danh sách số đang chặn từ output ZCWI (giữ nguyên regex desktop)."""
    return sorted(set(m[0] for m in A2P_BLOCKLIST_RE.findall(raw_output)))

def _a2p_normalize_pair(num):
    """Cắt 84 đầu (nếu có) rồi cắt 0 đầu (nếu có) -> số gốc N; trả [N]."""
    n = num.strip()
    if n.startswith("84"):
        n = n[2:]
    elif n.startswith("0"):
        n = n[1:]
    if not n:
        return []
    return [n]

def _a2p_parse_input(text):
    """Lọc số hợp lệ + chuẩn hóa + mở rộng theo cặp {N, 84N}.
    Bỏ dòng trống, bỏ dòng #, chỉ nhận chuỗi toàn số."""
    out = set()
    for l in (text or "").splitlines():
        s = l.strip()
        if not s or s.startswith("#") or not s.isdigit():
            continue
        out.update(_a2p_normalize_pair(s))
    return sorted(out)

def _a2p_build_commands(final_add, final_del):
    """Sinh bộ lệnh ZCW* (giữ nguyên thứ tự desktop: đếm -> xóa -> thêm -> đếm)."""
    cmds = ["ZCWN:CNT,CLI;"]
    for num in final_del:
        cmds.append(f"ZCWM:CLI,DEL:TON=NAT,DIG={num}:;")
    for num in final_add:
        cmds.append(f"ZCWM:CLI,ADD:TON=NAT,DIG={num},RES=RESTRICT;")
    cmds.append("ZCWN:MTN,CLI;")
    return cmds

def _a2p_analyze(input_add, input_del, history_dict):
    """Port analyze_and_generate (phần logic thuần). history_dict = {số: ngày}.
    Trả về dict gồm final_add/final_del/skipped/conflict_removed/rebalanced."""
    current_active = set(history_dict.keys())

    add = sorted(set(input_add))
    dele = sorted(set(input_del))

    # 1. Trùng lặp add ∩ del -> ưu tiên GỠ (bỏ khỏi danh sách THÊM)
    overlap = sorted(set(add) & set(dele))
    if overlap:
        add = [x for x in add if x not in overlap]

    # 2. Lọc theo trạng thái thực tế
    final_add = [n for n in add if n not in current_active]
    skipped_add = [n for n in add if n in current_active]      # đã chặn rồi
    final_del = [n for n in dele if n in current_active]
    skipped_del = [n for n in dele if n not in current_active]  # vốn chưa chặn

    # 3. REBALANCE: nếu thêm nhiều hơn xóa -> tự bù xóa các số cũ nhất
    #    (loại trừ số đã nằm trong final_del và số bắt đầu bằng "3")
    rebalanced = []
    if len(final_del) < len(final_add):
        deficit = len(final_add) - len(final_del)
        candidates = []
        for num, date_str in history_dict.items():
            if num in final_del:
                continue
            if str(num).startswith("3"):
                continue
            # Ưu tiên xóa: Unknown = cũ nhất (xóa trước); ngày hợp lệ sort theo thời gian;
            # ngày sai định dạng = đẩy xuống cuối (ít bị tự xóa nhất) — giống desktop dùng datetime.max.
            if "Unknown" in str(date_str):
                sort_val = (0, "")
            else:
                try:
                    datetime.strptime(str(date_str), "%Y-%m-%d %H:%M:%S")
                    sort_val = (1, str(date_str))
                except ValueError:
                    sort_val = (2, "")
            candidates.append((num, sort_val))
        candidates.sort(key=lambda x: x[1])
        for i in range(min(deficit, len(candidates))):
            final_del.append(candidates[i][0])
            rebalanced.append(candidates[i][0])

    return {
        'final_add': final_add,
        'final_del': final_del,
        'skipped_add': skipped_add,
        'skipped_del': skipped_del,
        'conflict_removed': overlap,
        'rebalanced': rebalanced,
    }

def _a2p_make_report(plan):
    """Tạo chuỗi báo cáo kế hoạch để hiển thị cho người dùng."""
    parts = [f"🔵 THÊM: {len(plan['final_add'])} số   🟠 XÓA: {len(plan['final_del'])} số"]
    if plan['conflict_removed']:
        parts.append(f"⚠️ Bỏ {len(plan['conflict_removed'])} số trùng ở ô THÊM (ưu tiên GỠ).")
    if plan['rebalanced']:
        parts.append(f"⚖️ Tự bù XÓA {len(plan['rebalanced'])} số cũ nhất để cân bằng số lượng.")
    if plan['skipped_add']:
        parts.append(f"✅ Bỏ qua {len(plan['skipped_add'])} số ĐÃ được chặn từ trước.")
    if plan['skipped_del']:
        parts.append(f"ℹ️ Bỏ qua {len(plan['skipped_del'])} số GỠ vốn chưa được chặn.")
    return "\n".join(parts)

# --- 2. DB HISTORY (thay a2p_history.json, dùng chung & an toàn đa người dùng) ---
def _a2p_get_history():
    """Trả về dict {số: ngày} từ bảng A2PHistory."""
    with app.app_context():
        return {h.number: h.blocked_at for h in A2PHistory.query.all()}

def _a2p_reconcile_history(node_numbers):
    """Đồng bộ bảng history với danh sách thực tế trên node sau khi quét:
    - bỏ số không còn trên node; - số mới trên node -> 'Unknown'; - giữ ngày cũ."""
    node_set = set(node_numbers)
    with app.app_context():
        existing = {h.number: h.blocked_at for h in A2PHistory.query.all()}
        for num in set(existing) - node_set:
            A2PHistory.query.filter_by(number=num).delete()
        for num in node_set - set(existing):
            db.session.add(A2PHistory(number=num, blocked_at="Unknown"))
        db.session.commit()

def _a2p_apply_history(final_add, final_del):
    """Cập nhật history sau khi thực thi thành công (thêm có timestamp, xóa)."""
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with app.app_context():
        for num in final_del:
            A2PHistory.query.filter_by(number=num).delete()
        for num in final_add:
            h = db.session.get(A2PHistory, num)
            if h:
                h.blocked_at = date_str
            else:
                db.session.add(A2PHistory(number=num, blocked_at=date_str))
        db.session.commit()

# --- 3. HELPER SSH CHO A2P (gửi '\r', không vào MML mode) ---
# Cách ly đa người dùng: mỗi phiên socket (sid) có cờ dừng riêng và nhận phản hồi
# qua room=sid (không broadcast). Nhờ vậy thao tác/nút DỪNG của người này không ảnh
# hưởng người khác, và bảng/kế hoạch của người này không hiện lên màn người kia.
a2p_stop_events = {}
# Thời điểm quét gần nhất (dùng chung mọi phiên) để client quyết định tự quét lại khi mở trang.
a2p_last_scan = {'epoch': None, 'display': None}

def _a2p_get_stop(sid):
    ev = a2p_stop_events.get(sid)
    if ev is None:
        ev = threading.Event()
        a2p_stop_events[sid] = ev
    return ev

def _a2p_log(sid, msg, log_type='raw'):
    socketio.emit('log', {'msg': msg, 'type': log_type, 'node': A2P_NODE}, room=sid)

def _a2p_clean_chunk(chunk):
    """Làm gọn output cho dễ đọc (port _clean_chunk)."""
    s = chunk.replace('\r', '')
    s = re.sub(r'NAT\s*[\n]+\s*(\d+)', r'NAT  \1', s)
    s = re.sub(r'[\s\n]+RESTRICT', r'  RESTRICT', s)
    s = re.sub(r'FINAL\s*[\n]+\s*RESULT', r'FINAL RESULT', s)
    s = re.sub(r'\n\s*\n', '\n', s)
    return s

# --- 4. WORKER SSH (chạy trong thread) ---
def run_a2p_fetch_task(sid, stop_ev):
    """Quét toàn bộ số đang chặn trên TSSN2D bằng ZCWI:NAME=CLI; rồi parse."""
    cfg = SSH_CONFIG.get(A2P_NODE)
    ssh = None
    try:
        _a2p_log(sid, f"--- KẾT NỐI {A2P_NODE} ({cfg['host']}) - QUÉT DANH SÁCH CHẶN ---\n", 'info')
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(cfg['host'], username=cfg['user'], password=cfg['pass'], timeout=20)

        shell = ssh.invoke_shell()
        start = time.time()
        while not shell.recv_ready() and time.time() - start < 5:
            time.sleep(0.1)
        if shell.recv_ready():
            shell.recv(9999)  # dọn banner

        cmd = "ZCWI:NAME=CLI;"
        _a2p_log(sid, f"[Gửi lệnh]: {cmd}\n", 'cmd')
        shell.send(cmd + "\r")

        full_data = ""
        start = time.time()
        last_log = time.time()
        while True:
            if stop_ev.is_set():
                raise Exception("Người dùng yêu cầu dừng.")
            if time.time() - start > 60:
                _a2p_log(sid, "!!! TIMEOUT: Quá thời gian chờ phản hồi.\n", 'error')
                break
            if shell.recv_ready():
                chunk = shell.recv(65535).decode('utf-8', errors='ignore')
                full_data += chunk
                if time.time() - last_log > 0.5:
                    _a2p_log(sid, "... đang tải dữ liệu ...\n", 'raw')
                    last_log = time.time()
                if "COMMAND EXECUTED" in chunk or "<" in chunk or "END" in chunk:
                    _a2p_log(sid, "✅ Đã nhận tín hiệu kết thúc lệnh.\n", 'success')
                    break
            else:
                time.sleep(0.01)

        numbers = _a2p_parse_blocklist(full_data)
        _a2p_log(sid, f"\n📊 KẾT QUẢ: Tìm thấy {len(numbers)} số đang chặn trên Node.\n", 'success')

        # In chi tiết danh sách ra console (giống _print_bulk_log của desktop)
        if numbers:
            _a2p_log(sid, "-" * 40 + "\nCHI TIẾT DANH SÁCH TỪ NODE:\n", 'raw')
            _a2p_log(sid, "\n".join(f"NAT  {n:<12}  RESTRICT" for n in numbers) + "\n", 'success')
            _a2p_log(sid, "-" * 40 + "\n", 'raw')

        # Đồng bộ history & lấy ngày để hiển thị
        _a2p_reconcile_history(numbers)
        a2p_last_scan['epoch'] = time.time()
        a2p_last_scan['display'] = datetime.now().strftime("%H:%M:%S")
        history = _a2p_get_history()
        rows = [[n, history.get(n, "Unknown")] for n in numbers]

        socketio.emit('a2p_blocklist', {'rows': rows, 'count': len(numbers)}, room=sid)
        try:
            shell.send("exit;\r")
        except Exception:
            pass

    except Exception as e:
        _a2p_log(sid, f"❌ LỖI QUÉT: {e}\n", 'error')
        socketio.emit('a2p_blocklist', {'rows': None, 'error': str(e)}, room=sid)
    finally:
        if ssh:
            try: ssh.close()
            except Exception: pass
        socketio.emit('a2p_fetch_finished', room=sid)

def run_a2p_exec_task(sid, stop_ev, commands, final_add, final_del, user_action, results):
    """Thực thi bộ lệnh ZCW* trên TSSN2D (port execute_ssh). Dừng nếu 1 lệnh lỗi.

    Tối ưu so với bản desktop (sip_route.py ~L961): bỏ time.sleep(0.2) giữa các lệnh,
    giảm sleep khởi động, và gom output mỗi lệnh emit 1 lần (thay vì emit từng chunk)
    để giảm tải CPU + số frame WebSocket trên server yếu. Có đo thời gian để chẩn đoán.
    """
    cfg = SSH_CONFIG.get(A2P_NODE)
    ssh = None
    has_error = False
    t_total0 = time.time()
    connect_dur = 0.0
    wait_total = 0.0          # tổng thời gian chờ node phản hồi (gửi -> EXECUTED)
    slow_i, slow_dur = 0, 0.0  # lệnh chờ lâu nhất
    try:
        _a2p_log(sid, f"--- KẾT NỐI {A2P_NODE} ({cfg['host']}) - BẮT ĐẦU CHẠY LỆNH ---\n", 'info')
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(cfg['host'], username=cfg['user'], password=cfg['pass'], timeout=20)

        shell = ssh.invoke_shell()
        time.sleep(0.5)
        if shell.recv_ready():
            shell.recv(8192)
        shell.send("\r")
        time.sleep(0.2)
        connect_dur = time.time() - t_total0

        for i, cmd in enumerate(commands):
            if stop_ev.is_set():
                raise Exception("Đã dừng.")
            _a2p_log(sid, f"({i+1}/{len(commands)}) {cmd}\n", 'cmd')
            shell.send(cmd + "\r")

            buffer = ""
            success = False
            cmd_start = time.time()
            while time.time() - cmd_start < 30:
                if stop_ev.is_set():
                    raise Exception("Đã dừng.")
                if shell.recv_ready():
                    buffer += shell.recv(4096).decode('utf-8', errors='ignore')
                    if re.search(r"(COMMAND EXECUTED|EXECUTED)", buffer):
                        success = True
                        break
                    if re.search(r"(NOT ACCEPTED|SYNTAX ERROR|FAULT CODE)", buffer):
                        success = False
                        break
                else:
                    time.sleep(0.05)

            cmd_dur = time.time() - cmd_start
            wait_total += cmd_dur
            if cmd_dur > slow_dur:
                slow_i, slow_dur = i + 1, cmd_dur

            # Gom output của cả lệnh, emit 1 lần (giảm số lần emit trên server yếu)
            pretty = _a2p_clean_chunk(buffer).strip()
            if pretty:
                _a2p_log(sid, pretty + "\n", 'raw')

            if not success:
                _a2p_log(sid, f"❌ LỖI: Lệnh {i+1} thất bại!\n", 'error')
                has_error = True
                break
            # Bỏ time.sleep(0.2) giữa các lệnh: gửi lệnh kế ngay khi đã thấy EXECUTED

        total_dur = time.time() - t_total0
        if not has_error:
            _a2p_log(sid, "✅ ĐÃ CHẠY XONG tất cả lệnh.\n", 'success')
        else:
            _a2p_log(sid, "⚠️ Dừng do lỗi.\n", 'error')
        _a2p_log(sid,
                 f"⏱ Kết nối {connect_dur:.1f}s | {len(commands)} lệnh | "
                 f"chờ node {wait_total:.1f}s | tổng {total_dur:.1f}s"
                 + (f" (chậm nhất: lệnh {slow_i} {slow_dur:.1f}s)" if commands else "") + "\n",
                 'info')

        try:
            shell.send("exit;\r")
        except Exception:
            pass

    except Exception as e:
        _a2p_log(sid, f"❌ Lỗi SSH: {e}\n", 'error')
        has_error = True
    finally:
        if ssh:
            try: ssh.close()
            except Exception: pass
        results['ok'] = not has_error

# --- 5. SOCKET EVENTS ---
@socketio.on('a2p_init')
def handle_a2p_init():
    """Khi mở trang A2P: trả danh sách đã biết (cache DB) + thời điểm quét gần nhất.
    Client tự quét lại nếu dữ liệu cũ/chưa từng quét (giống desktop mở tab lần đầu)."""
    history = _a2p_get_history()
    rows = sorted([[n, d] for n, d in history.items()], key=lambda r: r[0])
    epoch = a2p_last_scan['epoch']
    age = int(time.time() - epoch) if epoch else None
    fresh = age is not None and age < 180
    emit('a2p_state', {
        'rows': rows,
        'count': len(rows),
        'last_scan': a2p_last_scan['display'],
        'fresh': fresh,
        'age_sec': age if age is not None else 0,
    })

@socketio.on('run_a2p_fetch')
def handle_a2p_fetch():
    sid = request.sid
    stop_ev = _a2p_get_stop(sid)
    stop_ev.clear()
    emit('log_system', {'msg': '🔄 Đang quét danh sách số đang chặn A2P...', 'type': 'info'})
    socketio.start_background_task(run_a2p_fetch_task, sid, stop_ev)

@socketio.on('run_a2p_analyze')
def handle_a2p_analyze(data):
    add = _a2p_parse_input(data.get('add_text', ''))
    dele = _a2p_parse_input(data.get('del_text', ''))
    history = _a2p_get_history()
    plan = _a2p_analyze(add, dele, history)
    commands = _a2p_build_commands(plan['final_add'], plan['final_del'])
    can_exec = bool(plan['final_add'] or plan['final_del'])
    # all_safe: nhập số để CHẶN nhưng tất cả đã được chặn từ trước (không có lệnh nào để chạy)
    all_safe = (not can_exec) and len(add) > 0
    # Chạy đồng bộ trong handler -> emit() trần chỉ gửi cho client đã yêu cầu
    emit('a2p_plan', {
        'final_add': plan['final_add'],
        'final_del': plan['final_del'],
        'commands': commands,
        'report': _a2p_make_report(plan),
        'can_execute': can_exec,
        'conflict_removed': plan['conflict_removed'],
        'all_safe': all_safe,
        'input_add_count': len(add),
    })

@socketio.on('execute_a2p')
def handle_a2p_execute(data):
    sid = request.sid
    stop_ev = _a2p_get_stop(sid)
    # Chỉ nhận số hợp lệ; server tự sinh lại lệnh (không tin chuỗi lệnh client gửi)
    final_add = [str(x) for x in data.get('final_add', []) if str(x).isdigit()]
    final_del = [str(x) for x in data.get('final_del', []) if str(x).isdigit()]
    if not final_add and not final_del:
        emit('log_system', {'msg': '❌ Không có lệnh A2P để chạy.', 'type': 'error'})
        emit('a2p_finished', {'ok': False})
        return

    commands = _a2p_build_commands(final_add, final_del)
    user_action = current_user.username if current_user.is_authenticated else "Unknown"
    stop_ev.clear()
    emit('log_system', {'msg': f'🚨 Bắt đầu chặn/gỡ A2P (+{len(final_add)} / -{len(final_del)})...', 'type': 'info'})

    results = {}

    def run_wrapper():
        run_a2p_exec_task(sid, stop_ev, commands, final_add, final_del, user_action, results)
        ok = results.get('ok', False)
        # Chỉ cập nhật history + audit khi thành công và không bị dừng
        if ok and not stop_ev.is_set():
            _a2p_apply_history(final_add, final_del)
            with app.app_context():
                log_content = (f"[A2P] THÊM: {', '.join(final_add) or '(không)'} | "
                               f"XÓA: {', '.join(final_del) or '(không)'}\n" + "\n".join(commands))
                db.session.add(ActionLog(username=user_action, commands=log_content))
                db.session.commit()
        socketio.emit('a2p_finished', {'ok': ok}, room=sid)

    socketio.start_background_task(run_wrapper)

@socketio.on('stop_a2p')
def handle_a2p_stop():
    """Nút DỪNG của A2P: chỉ set cờ dừng của ĐÚNG phiên gọi (không đụng tab/người khác)."""
    ev = a2p_stop_events.get(request.sid)
    if ev:
        ev.set()
    emit('log_system', {'msg': '🛑 Đã nhận lệnh DỪNG A2P...', 'type': 'error'})

@socketio.on('disconnect')
def _a2p_cleanup_stop():
    a2p_stop_events.pop(request.sid, None)

# --- 6. ROUTE TRANG A2P ---
@app.route('/a2p')
@login_required
def a2p():
    return render_template('a2p.html', user=current_user)

@app.route('/a2p/import', methods=['POST'])
@login_required
def a2p_import():
    """Nhập dữ liệu lịch sử chặn từ file JSON cũ (a2p_history.json) vào DB.
    Format: {"<số>": "<YYYY-MM-DD HH:MM:SS>" hoặc "Unknown", ...}. Upsert (cập nhật ngày nếu số đã có)."""
    if current_user.username != 'admin':
        flash('Chỉ admin được nhập dữ liệu A2P.', 'danger')
        return redirect(url_for('a2p'))

    f = request.files.get('file')
    if not f or not f.filename:
        flash('Chưa chọn file JSON để nhập.', 'warning')
        return redirect(url_for('a2p'))

    try:
        raw = f.read().decode('utf-8-sig', errors='ignore')
        data = json.loads(raw)
    except Exception as e:
        flash(f'File JSON không hợp lệ: {e}', 'danger')
        return redirect(url_for('a2p'))

    if not isinstance(data, dict):
        flash('Cấu trúc JSON phải là {"số": "ngày chặn"} giống a2p_history.json.', 'danger')
        return redirect(url_for('a2p'))

    updated = inserted = skipped = 0
    for num, date in data.items():
        num = str(num).strip()
        if not num.isdigit():
            skipped += 1
            continue
        date_str = str(date).strip() if date else 'Unknown'
        h = db.session.get(A2PHistory, num)
        if h:
            h.blocked_at = date_str
            updated += 1
        else:
            db.session.add(A2PHistory(number=num, blocked_at=date_str))
            inserted += 1
    db.session.commit()

    msg = f'✅ Đã nhập JSON: cập nhật {updated}, thêm mới {inserted} số.'
    if skipped:
        msg += f' (Bỏ qua {skipped} khóa không phải số.)'
    flash(msg, 'success')
    return redirect(url_for('a2p'))

# Tạo bảng DB ở mức module (idempotent) để bảng luôn tồn tại bất kể cách khởi động
# (python SNOC2_RouteAA.py, WSGI/gunicorn, hay import từ manage_users.py).
with app.app_context():
    db.create_all()

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

    # debug=False + use_reloader=False: tránh Werkzeug reloader khởi động .exe hai lần khi đóng gói PyInstaller
    socketio.run(app, host='0.0.0.0', port=5000, debug=False, use_reloader=False, allow_unsafe_werkzeug=True)