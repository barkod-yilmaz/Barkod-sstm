from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
import sqlite3
import os
import base64
from datetime import datetime
from functools import wraps
import secrets
import io

app = Flask(__name__, static_folder='.')
app.secret_key = secrets.token_hex(32)
CORS(app)

ADMIN_PASSWORD = "RFCRFCPLRNM343804380"
DB_PATH = "products.db"
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            barcode TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            data BLOB NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES products (id) ON DELETE CASCADE
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth = request.headers.get('Authorization', '')
        if auth != f"Bearer {ADMIN_PASSWORD}":
            return jsonify({"error": "Yetkisiz erişim"}), 401
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/admin.html')
def admin_panel():
    return send_from_directory('.', 'admin.html')

@app.route('/<path:filename>')
def serve_static(filename):
    if os.path.exists(filename):
        return send_from_directory('.', filename)
    return jsonify({"error": "Dosya bulunamadı"}), 404

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    password = data.get('password', '')
    if password == ADMIN_PASSWORD:
        return jsonify({"success": True, "token": ADMIN_PASSWORD})
    return jsonify({"success": False, "error": "Hatalı şifre"}), 401

@app.route('/api/products', methods=['GET'])
@admin_required
def get_products():
    conn = get_db()
    products = conn.execute('SELECT * FROM products ORDER BY created_at DESC').fetchall()
    result = []
    for p in products:
        photos = conn.execute('SELECT id, filename FROM photos WHERE product_id = ?', (p['id'],)).fetchall()
        result.append({
            "id": p['id'],
            "barcode": p['barcode'],
            "created_at": p['created_at'],
            "updated_at": p['updated_at'],
            "photo_count": len(photos),
            "photos": [{"id": ph['id'], "filename": ph['filename']} for ph in photos]
        })
    conn.close()
    return jsonify(result)

@app.route('/api/search/<barcode>', methods=['GET'])
def search_product(barcode):
    conn = get_db()
    product = conn.execute('SELECT * FROM products WHERE barcode = ?', (barcode,)).fetchone()
    if not product:
        conn.close()
        return jsonify({"error": "Bu barkoda ait kayıt bulunamadı"}), 404
    
    photos = conn.execute('SELECT id, filename FROM photos WHERE product_id = ?', (product['id'],)).fetchall()
    conn.close()
    
    return jsonify({
        "id": product['id'],
        "barcode": product['barcode'],
        "created_at": product['created_at'],
        "photos": [{"id": ph['id'], "filename": ph['filename']} for ph in photos]
    })

@app.route('/api/products', methods=['POST'])
@admin_required
def add_product():
    data = request.json
    barcode = data.get('barcode', '').strip()
    photos = data.get('photos', [])
    
    if not barcode:
        return jsonify({"error": "Barkod boş olamaz"}), 400
    
    conn = get_db()
    existing = conn.execute('SELECT * FROM products WHERE barcode = ?', (barcode,)).fetchone()
    
    if existing:
        product_id = existing['id']
    else:
        cursor = conn.execute('INSERT INTO products (barcode) VALUES (?)', (barcode,))
        product_id = cursor.lastrowid
    
    for photo in photos:
        filename = photo.get('filename', 'photo.jpg')
        data_b64 = photo.get('data', '')
        if data_b64:
            binary_data = base64.b64decode(data_b64)
            conn.execute('INSERT INTO photos (product_id, filename, data) VALUES (?, ?, ?)',
                        (product_id, filename, binary_data))
    
    conn.execute('UPDATE products SET updated_at = CURRENT_TIMESTAMP WHERE id = ?', (product_id,))
    conn.commit()
    conn.close()
    
    return jsonify({"success": True, "message": "Ürün başarıyla kaydedildi", "product_id": product_id})

@app.route('/api/photo/<int:photo_id>', methods=['GET'])
def get_photo(photo_id):
    conn = get_db()
    photo = conn.execute('SELECT * FROM photos WHERE id = ?', (photo_id,)).fetchone()
    conn.close()
    
    if not photo:
        return jsonify({"error": "Fotoğraf bulunamadı"}), 404
    
    return send_file(
        io.BytesIO(photo['data']),
        mimetype='image/jpeg',
        as_attachment=False,
        download_name=photo['filename']
    )

@app.route('/api/products/<int:product_id>', methods=['DELETE'])
@admin_required
def delete_product(product_id):
    conn = get_db()
    conn.execute('DELETE FROM photos WHERE product_id = ?', (product_id,))
    conn.execute('DELETE FROM products WHERE id = ?', (product_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": "Ürün başarıyla silindi"})

@app.route('/api/photos/<int:photo_id>', methods=['DELETE'])
@admin_required
def delete_photo(photo_id):
    conn = get_db()
    conn.execute('DELETE FROM photos WHERE id = ?', (photo_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": "Fotoğraf başarıyla silindi"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
