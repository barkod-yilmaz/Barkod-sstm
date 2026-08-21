from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
import sqlite3
import os
import base64
import zipfile
from io import BytesIO
from datetime import datetime
from functools import wraps
import secrets
import json

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
    return jsonify({"success": False, "error": "Hatalı şifre"}), 401@app.route('/api/products', methods=['GET'])
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
        BytesIO(photo['data']),
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
    return jsonify({"success": True, "message": "Ürün başarıyla silindi"})@app.route('/api/export_zip', methods=['GET'])
@admin_required
def export_zip():
    conn = get_db()
    products = conn.execute('SELECT * FROM products').fetchall()
    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        urunler = []
        for p in products:
            photos = conn.execute('SELECT * FROM photos WHERE product_id = ?', (p['id'],)).fetchall()
            photo_list = []
            for ph in photos:
                photo_filename = f"foto_{ph['id']}.jpg"
                zf.writestr(f"fotograflar/{photo_filename}", ph['data'])
                photo_list.append({
                    "filename": ph['filename'],
                    "file": f"fotograflar/{photo_filename}"
                })
            urunler.append({
                "barcode": p['barcode'],
                "photos": photo_list
            })
        zf.writestr("urunler.json", json.dumps(urunler, ensure_ascii=False))
    conn.close()
    zip_buffer.seek(0)
    return send_file(
        zip_buffer,
        mimetype='application/zip',
        as_attachment=True,
        download_name='barkod_yedek_' + datetime.now().strftime('%Y-%m-%d_%H-%M-%S') + '.zip'
    )

@app.route('/api/import_zip', methods=['POST'])
@admin_required
def import_zip():
    if 'file' not in request.files:
        return jsonify({"error": "Dosya seçilmedi"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "Dosya seçilmedi"}), 400

    try:
        zip_file = zipfile.ZipFile(file)
        urunler_json = zip_file.read('urunler.json')
        urunler = json.loads(urunler_json)

        conn = get_db()
        for urun in urunler:
            barcode = urun.get('barcode', '').strip()
            if not barcode:
                continue

            existing = conn.execute('SELECT id FROM products WHERE barcode = ?', (barcode,)).fetchone()
            if existing:
                product_id = existing['id']
            else:
                cursor = conn.execute('INSERT INTO products (barcode) VALUES (?)', (barcode,))
                product_id = cursor.lastrowid

            for photo_info in urun.get('photos', []):
                filename = photo_info.get('filename', 'photo.jpg')
                file_path = photo_info.get('file', '')
                try:
                    photo_data = zip_file.read(file_path)
                except KeyError:
                    continue

                existing_photo = conn.execute(
                    'SELECT id FROM photos WHERE product_id = ? AND filename = ?',
                    (product_id, filename)
                ).fetchone()
                if existing_photo:
                    continue

                conn.execute('INSERT INTO photos (product_id, filename, data) VALUES (?, ?, ?)',
                            (product_id, filename, photo_data))

        conn.commit()
        conn.close()
        return jsonify({"success": True, "message": "ZIP yedek başarıyla içe aktarıldı"})
    except Exception as e:
        return jsonify({"error": f"Dosya okunamadı: {str(e)}"}), 400

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
