from SNOC2_RouteAA import app, db, User
from werkzeug.security import generate_password_hash

def create_user(username, password):
    with app.app_context():
        # Kiểm tra user tồn tại chưa
        existing = User.query.filter_by(username=username).first()
        if existing:
            print(f"❌ User '{username}' đã tồn tại!")
            return

        # Hash mật khẩu
        hashed_pw = generate_password_hash(password, method='pbkdf2:sha256')
        
        # Tạo user mới với cờ must_change_password = True
        new_user = User(username=username, password=hashed_pw, must_change_password=True)
        db.session.add(new_user)
        db.session.commit()
        print(f"✅ Đã tạo user '{username}'. Mật khẩu: {password}")
        print("   -> User này sẽ bị buộc đổi mật khẩu khi đăng nhập lần đầu.")

def reset_user_pass(username, new_password):
    with app.app_context():
        user = User.query.filter_by(username=username).first()
        if not user:
            print("❌ Không tìm thấy user.")
            return
        
        user.password = generate_password_hash(new_password, method='pbkdf2:sha256')
        user.must_change_password = True # Reset lại thì bắt đổi lại
        db.session.commit()
        print(f"♻️ Đã reset mật khẩu cho '{username}'.")

if __name__ == "__main__":
    print("--- CÔNG CỤ QUẢN LÝ USER ---")
    while True:
        print("\n1. Tạo User mới")
        print("2. Reset mật khẩu User")
        print("3. Thoát")
        choice = input("Chọn: ")
        
        if choice == '1':
            u = input("Nhập Username: ")
            p = input("Nhập Password mặc định: ")
            create_user(u, p)
        elif choice == '2':
            u = input("Nhập Username cần reset: ")
            p = input("Nhập Password mới: ")
            reset_user_pass(u, p)
        elif choice == '3':
            break