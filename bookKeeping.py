from flask import Flask, flash, render_template, request, redirect, session, send_file
import sqlite3
import xlsxwriter
import pandas as pd
import numpy as np
from sklearn.linear_model import LinearRegression
from collections import defaultdict
from datetime import datetime
import bcrypt

app = Flask(__name__)
app.secret_key = 'your-secret-key'  # 請替換為你的秘密金鑰

# 路由：首頁
@app.route('/')
def index():
    if 'username' in session:
        return render_template('welcome.html', username=session['username'])
    else:
        return redirect('/homepage')


@app.route('/homepage')
def homepage():
    return render_template('index.html')


# 建立資料庫連線
def create_connection():
    conn = sqlite3.connect('database.db')
    return conn


# 建立使用者資料表
def create_users_table():
    conn = create_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL
        )
    ''')  # 確保 password 欄位為 TEXT
    conn.commit()
    conn.close()


# 建立記帳資料表
def create_expenses_table():
    conn = create_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            category TEXT NOT NULL,
            amount REAL NOT NULL,
            note TEXT,
            date TEXT NOT NULL,
            tags TEXT
        )
    ''')  # 新增 tags 欄位
    conn.commit()
    conn.close()


# 建立預設支出資料表
def create_default_expenses_table():
    conn = create_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS default_expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            category TEXT NOT NULL,
            budget REAL NOT NULL
        )
    ''')
    conn.commit()
    conn.close()


# 新增 tags 欄位到 expenses 資料表（如尚未存在）
def add_tags_column():
    conn = create_connection()
    cursor = conn.cursor()
    # 檢查是否已經有 tags 欄位
    cursor.execute("PRAGMA table_info(expenses)")
    columns = [info[1] for info in cursor.fetchall()]
    if 'tags' not in columns:
        cursor.execute('ALTER TABLE expenses ADD COLUMN tags TEXT')
        conn.commit()
    conn.close()


# 執行資料表建立
create_users_table()
create_expenses_table()
create_default_expenses_table()
add_tags_column()


# 路由：使用者註冊
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        # 從表單獲取使用者註冊資訊
        username = request.form['username']
        password = request.form['password']

        try:
            with sqlite3.connect('database.db') as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT username FROM users WHERE username = ?', (username,))
                existing_username = cursor.fetchone()

                if existing_username is not None:
                    return render_template('register.html', message='帳號已註冊過！')

                # 密碼哈希處理並解碼為 UTF-8 字串
                hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

                # 將使用者資訊儲存到資料庫
                cursor.execute('INSERT INTO users (username, password) VALUES (?, ?)', (username, hashed_password))
                conn.commit()

                # 註冊成功，轉到註冊成功頁面
                return render_template('registration_success.html', message='註冊成功')
        except Exception as e:
            # 記錄錯誤或顯示有用的錯誤訊息
            print(f"Error during registration: {e}")  # 在終端顯示錯誤
            return render_template('register.html', message='註冊失敗，請稍後再試。')

    return render_template('register.html')


# 路由：使用者登入
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        # 從表單獲取使用者登入資訊
        username = request.form['username']
        password = request.form['password']

        try:
            with sqlite3.connect('database.db') as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT password FROM users WHERE username = ?', (username,))
                result = cursor.fetchone()

                if result:
                    stored_password = result[0]
                    
                    # 確認 stored_password 是否為 bytes，如果不是，則編碼為 bytes
                    if isinstance(stored_password, str):
                        stored_password = stored_password.encode('utf-8')

                    # 驗證密碼
                    if bcrypt.checkpw(password.encode('utf-8'), stored_password):
                        session['username'] = username
                        return redirect('/')
                    else:
                        return render_template('login.html', message='帳號或密碼錯誤')
                else:
                    return render_template('login.html', message='帳號或密碼錯誤')
        except Exception as e:
            print(f"Error during login: {e}")  # 在終端顯示錯誤
            return render_template('login.html', message='登入失敗，請稍後再試。')

    return render_template('login.html')


# 路由：記帳頁面
@app.route('/expense', methods=['GET', 'POST'])
def expense():
    if 'username' not in session:
        return redirect('/login')

    if request.method == 'POST':
        # 從表單獲取記帳資訊
        category = request.form['category']
        note = request.form['note']
        amount = float(request.form['amount'])
        record_type = request.form['record_type']
        date_today = request.form['date']
        tags = request.form.get('tags', '')  # 新增標籤欄位

        # 根據收或支設置金額正負號
        if record_type == 'income':
            amount = abs(amount)
            category = '收入'
        else:
            amount = -abs(amount)

        try:
            # 將記帳資訊儲存到資料庫
            with sqlite3.connect('database.db') as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO expenses (username, category, note, amount, date, tags)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (session['username'], category, note, amount, date_today, tags))
                conn.commit()

                # 獲取所有支出
                cursor.execute('SELECT * FROM expenses WHERE username = ? ORDER BY date', (session['username'],))
                expenses = cursor.fetchall()

                # 檢查支出是否超過預算
                category_budgets = get_category_budgets(session['username'])
                budget_exceeded = is_budget_exceeded(category, expenses, category_budgets)
                if budget_exceeded:
                    flash('您的支出已超過預算金額！')
                else:
                    flash('記帳成功！')
        except Exception as e:
            print(f"Error during expense recording: {e}")  # 在終端顯示錯誤
            flash('記帳失敗，請稍後再試。')

    # 從資料庫中獲取使用者的所有記帳資料
    try:
        with sqlite3.connect('database.db') as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM expenses WHERE username = ? ORDER BY date', (session['username'],))
            expenses = cursor.fetchall()

            # 計算月總額和損益
            total_expense = sum(expense[3] for expense in expenses if expense[3] < 0)
            profit_loss = calculate_profit_loss(expenses)
    except Exception as e:
        print(f"Error fetching expenses: {e}")  # 在終端顯示錯誤
        expenses = []
        total_expense = 0
        profit_loss = 0

    return render_template('expense.html',
                           expenses=expenses,
                           expense=total_expense,
                           profit_loss=profit_loss)


# 路由：進階功能
@app.route('/advanced', methods=['GET', 'POST'])
def advanced():
    if 'username' not in session:
        return redirect('/login')

    if request.method == 'POST':
        if 'set_budget' in request.form:
            set_budget(request.form)

    # 獲取支出類別佔比及預算數值
    categorized_expenses, category_budgets = get_expenses_and_budgets()
    category_budgets = get_category_budgets(session['username'])

    return render_template('advanced.html', categorized_expenses=categorized_expenses, category_budgets=category_budgets)


# 路由: 編輯記帳項目
@app.route('/edit_expense/<int:expense_id>', methods=['GET', 'POST'])
def edit_expense(expense_id):
    if 'username' not in session:
        return redirect('/login')

    if request.method == 'POST':
        category = request.form['category']
        note = request.form['note']
        amount = float(request.form['amount'])
        date_today = request.form['date']
        tags = request.form.get('tags', '')  # 新增標籤欄位

        # 根據收或支設置金額正負號
        if category == '收入':
            amount = abs(amount)
        else:
            amount = -abs(amount)

        try:
            with sqlite3.connect('database.db') as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE expenses
                    SET category = ?, note = ?, amount = ?, date = ?, tags = ?
                    WHERE id = ?
                ''', (category, note, amount, date_today, tags, expense_id))
                conn.commit()
                return redirect('/expense')
        except Exception as e:
            print(f"Error updating expense: {e}")  # 在終端顯示錯誤
            flash('更新記帳項目失敗，請稍後再試。')
            return redirect(f'/edit_expense/{expense_id}')
    else:
        try:
            with sqlite3.connect('database.db') as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM expenses WHERE id = ?', (expense_id,))
                expense = cursor.fetchone()
        except Exception as e:
            print(f"Error fetching expense for editing: {e}")  # 在終端顯示錯誤
            flash('無法獲取記帳項目，請稍後再試。')
            return redirect('/expense')
        return render_template('edit.html', expense=expense)


# 路由: 刪除記帳項目
@app.route('/delete_expense/<int:expense_id>', methods=['POST'])
def delete_expense(expense_id):
    try:
        with sqlite3.connect('database.db') as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM expenses WHERE id = ?', (expense_id,))
            conn.commit()
        flash('記帳項目已刪除。')
    except Exception as e:
        print(f"Error deleting expense: {e}")  # 在終端顯示錯誤
        flash('刪除記帳項目失敗，請稍後再試。')
    return redirect('/expense')


# 路由：財務分析
@app.route('/financial_analysis')
def financial_analysis():
    if 'username' not in session:
        return redirect('/login')

    try:
        # 獲取使用者的所有記帳資料
        with sqlite3.connect('database.db') as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM expenses WHERE username = ? ORDER BY date', (session['username'],))
            expenses = cursor.fetchall()

        # 準備支出類別分佈數據
        category_data = defaultdict(float)
        for expense in expenses:
            category = expense[2]
            amount = expense[3]
            if amount < 0:
                category_data[category] += abs(amount)

        categories = list(category_data.keys())
        category_amounts = list(category_data.values())

        # 準備每月支出趨勢數據
        monthly_data = defaultdict(float)
        for expense in expenses:
            date_obj = datetime.strptime(expense[5], '%Y-%m-%d')  # 假設 date 格式為 'YYYY-MM-DD'
            month = date_obj.strftime('%Y-%m')
            amount = expense[3]
            if amount < 0:
                monthly_data[month] += abs(amount)

        months = sorted(monthly_data.keys())
        monthly_amounts = [monthly_data[month] for month in months]

        # 預測未來 3 個月的支出
        prediction_results = predict_future_expenses(expenses, months_ahead=3)

    except Exception as e:
        print(f"Error during financial analysis: {e}")  # 在終端顯示錯誤
        categories = []
        category_amounts = []
        months = []
        monthly_amounts = []
        prediction_results = {'months': [], 'predicted_amounts': []}

    return render_template('financial_analysis.html',
                           categories=categories,
                           category_amounts=category_amounts,
                           months=months,
                           monthly_amounts=monthly_amounts,
                           prediction_months=prediction_results['months'],
                           prediction_amounts=prediction_results['predicted_amounts'])


# 計算損益
def calculate_profit_loss(expenses_data):
    income = sum(expense[3] for expense in expenses_data if expense[3] > 0)
    expenses = sum(expense[3] for expense in expenses_data if expense[3] < 0)
    return income + expenses


# 設定預算
def set_budget(form_data):
    try:
        with sqlite3.connect('database.db') as conn:
            cursor = conn.cursor()

            # 插入或更新預算紀錄
            for key, budget in form_data.items():
                if key.startswith('budget_'):
                    category = key.split('_', 1)[1]
                    try:
                        budget = float(budget)
                    except ValueError:
                        budget = 0.0
                    # 檢查是否已存在該類別的預算
                    cursor.execute('SELECT * FROM default_expenses WHERE username = ? AND category = ?', (session['username'], category))
                    existing = cursor.fetchone()
                    if existing:
                        cursor.execute('UPDATE default_expenses SET budget = ? WHERE id = ?', (budget, existing[0]))
                    else:
                        cursor.execute('INSERT INTO default_expenses (username, category, budget) VALUES (?, ?, ?)',
                                      (session['username'], category, budget))

            conn.commit()
            flash('預算已設定成功！')

    except Exception as e:
        conn.rollback()  # 發生錯誤時回滾交易
        print(f"Error setting budget: {e}")  # 在終端顯示錯誤
        flash('設定預算時發生錯誤！請重試。')


# 獲取支出類別佔比及預算數值的函式
def get_expenses_and_budgets():
    try:
        # 連接到資料庫
        with sqlite3.connect('database.db') as conn:
            cursor = conn.cursor()

            # 獲取使用者的所有支出資料
            cursor.execute('''
                SELECT category, ABS(SUM(amount)) 
                FROM expenses 
                WHERE username = ? AND amount < 0 
                GROUP BY category 
                HAVING SUM(amount) < 0
            ''', (session['username'],))
            categorized_expenses = cursor.fetchall()

            # 總支出金額
            total_expenses = sum(expense[1] for expense in categorized_expenses)

            # 獲取使用者的支出類別及預算數值
            cursor.execute('SELECT category, budget FROM default_expenses WHERE username = ?', (session['username'],))
            category_budgets = dict(cursor.fetchall())

        # 計算支出類別佔比
        if total_expenses > 0:
            categorized_expenses = [
                (expense[0], expense[1], round(expense[1] / total_expenses * 100, 2))
                for expense in categorized_expenses
            ]
        else:
            categorized_expenses = [(expense[0], expense[1], 0) for expense in categorized_expenses]

        categorized_expenses = sorted(categorized_expenses, key=lambda x: x[1], reverse=True)

        return categorized_expenses, category_budgets
    except Exception as e:
        print(f"Error fetching expenses and budgets: {e}")  # 在終端顯示錯誤
        return [], {}


def is_budget_exceeded(category, expenses, category_budgets):
    # 查找指定類別的預算金額
    budget = category_budgets.get(category)
    budget = float(budget) if budget is not None else 0

    if budget == 0.0 or budget == '':
        return False

    # 計算該類別的總支出
    category_expenses = sum(abs(expense[3]) for expense in expenses if expense[2] == category and expense[3] < 0)

    # 檢查開支是否超過預算
    if category_expenses > budget:
        return True
    else:
        return False


def get_category_budgets(username):
    try:
        # 連接到資料庫
        with sqlite3.connect('database.db') as conn:
            cursor = conn.cursor()

            # 從資料庫中獲取使用者的預算數值
            cursor.execute('SELECT category, budget FROM default_expenses WHERE username = ?', (username,))
            category_budgets = dict(cursor.fetchall())

        return category_budgets
    except Exception as e:
        print(f"Error fetching category budgets: {e}")  # 在終端顯示錯誤
        return {}


# 預測未來幾個月的支出
def predict_future_expenses(expenses_data, months_ahead=3):
    """
    使用簡單線性回歸預測未來幾個月的支出。
    :param expenses_data: 使用者的支出數據（列表）
    :param months_ahead: 預測的月數
    :return: 預測結果的字典
    """
    # 準備資料
    df = pd.DataFrame(expenses_data, columns=['id', 'username', 'category', 'amount', 'note', 'date', 'tags'])
    df['date'] = pd.to_datetime(df['date'])
    df = df[df['amount'] < 0]  # 僅考慮支出
    if df.empty:
        return {'months': [], 'predicted_amounts': []}

    df = df.set_index('date').resample('M').sum().reset_index()

    # 提取月份數字
    df['month_num'] = np.arange(len(df))  # 月份轉換為數值

    # 準備訓練數據
    X = df[['month_num']]
    y = df['amount']

    # 建立並訓練模型
    model = LinearRegression()
    model.fit(X, y)

    # 預測未來幾個月
    last_month_num = df['month_num'].max()
    future_month_nums = np.array([last_month_num + i for i in range(1, months_ahead + 1)]).reshape(-1, 1)
    predictions = model.predict(future_month_nums)

    # 準備結果
    future_months = []
    last_date = df['date'].max()
    for i in range(1, months_ahead + 1):
        future_month = (last_date + pd.DateOffset(months=i)).strftime('%Y-%m')
        future_months.append(future_month)

    prediction_results = {
        'months': future_months,
        'predicted_amounts': [round(abs(amount), 2) for amount in predictions]
    }

    return prediction_results


# 匯出記帳資料到 Excel
@app.route('/export', methods=['GET'])
def export():
    if 'username' not in session:
        return redirect('/login')

    try:
        # 獲取使用者的所有記帳資料
        with sqlite3.connect('database.db') as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM expenses WHERE username = ? ORDER BY date', (session['username'],))
            expenses = cursor.fetchall()

        # 創建 Excel 檔案
        workbook = xlsxwriter.Workbook('記帳資料.xlsx')
        worksheet = workbook.add_worksheet()

        # 寫入標題列
        headers = ['ID', 'Username', 'Category', 'Amount', 'Note', 'Date', 'Tags']
        for col, header in enumerate(headers):
            worksheet.write(0, col, header)

        # 寫入資料
        for row, expense in enumerate(expenses):
            for col, data in enumerate(expense):
                worksheet.write(row + 1, col, data)

        # 關閉 Excel 檔案
        workbook.close()

        # 下載 Excel 檔案
        return send_file('記帳資料.xlsx', as_attachment=True)
    except Exception as e:
        print(f"Error exporting to Excel: {e}")  # 在終端顯示錯誤
        flash('匯出失敗，請稍後再試。')
        return redirect('/expense')


# 路由：使用者登出
@app.route('/logout')
def logout():
    session.pop('username', None)
    flash('已成功登出。')
    return redirect('/homepage')


if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5001, debug=True)
