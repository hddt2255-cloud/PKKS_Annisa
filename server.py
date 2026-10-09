import http.server
import socketserver
import json
import os
import sys
import re
import urllib.parse
import threading
import base64
import urllib.request
import shutil

DEFAULT_APPS_SCRIPT_URL = "https://pkks-b9f13-default-rtdb.firebaseio.com/"
DEFAULT_GDRIVE_FOLDER_ID = "1_kO2Vv5xn7eiz-X4ht9iJ3LbRXliL07x"
DEFAULT_GDRIVE_EXEC_URL = "https://script.google.com/macros/s/AKfycbykNKnIhlwXTr-u6OX7rBbAmyyWq1J3OKtJUOQ5ocg1yowiyswFIUEByRbipMQN9qBM/exec"

def to_firebase_key(s):
    return re.sub(r'[.$#\[\]/\s]+', '_', str(s or 'unknown'))

def normalize_firebase_url(url=None):
    raw = (url or '').strip()
    if not raw or 'script.google.com' in raw or 'firebaseio.com' not in raw:
        return DEFAULT_APPS_SCRIPT_URL.rstrip('/')
    return raw.rstrip('/')

def extract_gdrive_folder_id(url_or_id):
    if not url_or_id:
        return None
    url_or_id = str(url_or_id).strip()
    if 'folders/' in url_or_id:
        return url_or_id.split('folders/')[1].split('?')[0].split('/')[0]
    elif 'id=' in url_or_id:
        return url_or_id.split('id=')[1].split('&')[0]
    elif len(url_or_id) > 10 and '/' not in url_or_id and '.' not in url_or_id:
        return url_or_id
    return None

def bg_upload(file_content, filename, mime_type, apps_script_url, user_name, folder_id="", user_id="admin", item_id="1.1", file_id="", npsn="20231556"):
    try:
        base_url = normalize_firebase_url(apps_script_url)
        active_folder_id = extract_gdrive_folder_id(folder_id) or DEFAULT_GDRIVE_FOLDER_ID
        b64_data = base64.b64encode(file_content).decode('utf-8')
        safe_npsn = to_firebase_key(npsn or "20231556")
        safe_file_id = to_firebase_key(file_id or filename)
        size_str = f"{round(len(file_content) / 1024, 1)} KB"

        # 1. Unggah & simpan fisik berkas LANGSUNG ke Google Drive (bukan ke Firebase)
        if active_folder_id and DEFAULT_GDRIVE_EXEC_URL:
            try:
                gdrive_payload = urllib.parse.urlencode({
                    'filename': filename,
                    'mimeType': mime_type,
                    'file': b64_data,
                    'user': user_name or 'Pengunggah',
                    'folderId': active_folder_id
                }).encode('utf-8')
                req_gd = urllib.request.Request(DEFAULT_GDRIVE_EXEC_URL, data=gdrive_payload, method='POST')
                req_gd.add_header('Content-Type', 'application/x-www-form-urlencoded')
                urllib.request.urlopen(req_gd, timeout=60)
                print(f"Direct upload to Google Drive ({active_folder_id}) successful for {filename}")
            except Exception as gd_err:
                print(f"Google Drive upload notice for {filename}: {gd_err}")

        # 2. Gunakan Firebase HANYA sebagai jembatan metadata & kepemilikan user (tanpa menyimpan file/dataUrl)
        meta_record = {
            'id': file_id or safe_file_id,
            'fileKey': file_id or safe_file_id,
            'itemId': item_id or '1.1',
            'name': filename,
            'savedName': filename,
            'originalName': filename,
            'mimeType': mime_type,
            'size': size_str,
            'sizeBytes': len(file_content),
            'user': user_name or 'Pengunggah',
            'userId': user_id or 'admin',
            'npsn': str(npsn or '20231556'),
            'folder': 'Google Drive',
            'driveFolderId': active_folder_id,
            'driveUrl': f"https://drive.google.com/drive/folders/{active_folder_id}",
            'isDrive': True,
            'isFirebaseBridge': True
        }

        req_meta = urllib.request.Request(
            f"{base_url}/pkks_file_meta/{safe_npsn}/{safe_file_id}.json",
            data=json.dumps(meta_record).encode('utf-8'),
            method='PUT'
        )
        req_meta.add_header('Content-Type', 'application/json')
        urllib.request.urlopen(req_meta, timeout=30)

        print(f"Firebase bridge metadata sync successful for {filename}")
    except Exception as e:
        print(f"Background upload/bridge sync notice for {filename}: {e}")

def bg_delete(filename, apps_script_url, folder_id="", file_id="", npsn="20231556"):
    try:
        base_url = normalize_firebase_url(apps_script_url)
        active_folder_id = extract_gdrive_folder_id(folder_id) or DEFAULT_GDRIVE_FOLDER_ID
        safe_npsn = to_firebase_key(npsn or "20231556")
        keys_to_delete = set()
        if file_id:
            keys_to_delete.add(to_firebase_key(file_id))
        if filename:
            keys_to_delete.add(to_firebase_key(filename))

        # 1. Hapus langsung dari Google Drive
        if active_folder_id and DEFAULT_GDRIVE_EXEC_URL and filename:
            try:
                del_payload = urllib.parse.urlencode({
                    'action': 'delete',
                    'fileName': filename,
                    'filename': filename,
                    'file': filename,
                    'folderId': active_folder_id
                }).encode('utf-8')
                req_gd = urllib.request.Request(DEFAULT_GDRIVE_EXEC_URL, data=del_payload, method='POST')
                req_gd.add_header('Content-Type', 'application/x-www-form-urlencoded')
                urllib.request.urlopen(req_gd, timeout=30)
            except Exception:
                pass

        # 2. Hapus catatan metadata dari jembatan Firebase
        for k in keys_to_delete:
            for node in ['pkks_file_meta', 'pkks_files']:
                try:
                    req = urllib.request.Request(
                        f"{base_url}/{node}/{safe_npsn}/{k}.json",
                        method='DELETE'
                    )
                    urllib.request.urlopen(req, timeout=30)
                except Exception:
                    pass

        print(f"Background delete from Google Drive & Firebase bridge successful for {filename}")
    except Exception as e:
        print(f"Background delete notice for {filename}: {e}")



# Force UTF-8 encoding for Windows console
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

PORT = 8001
if len(sys.argv) > 1:
    try:
        PORT = int(sys.argv[1])
    except ValueError:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PKKS_FOLDER_NAME = "PKKS 2026"
UPLOADS_DIR = os.path.join(BASE_DIR, PKKS_FOLDER_NAME)

# DATA_DIR and UPLOADS_DIR are now dynamic based on NPSN

INITIAL_USERS = [
  {"id": "admin", "name": "Admin (Abdul Yakub, S.Ag)", "role": "kepsek", "jabatan": "Kepala Sekolah / Admin"},
  {"id": "abdul_yakub", "name": "Abdul Yakub, S.Ag", "role": "kepsek", "jabatan": "Kepala Sekolah & Evaluator"},
  {"id": "susanti", "name": "Susanti, S.Kom, S.Pd", "role": "guru", "jabatan": "Guru Komputer / TI"},
  {"id": "legina_puspa", "name": "Legina Puspa Wardini,S.Pd.I", "role": "guru", "jabatan": "Guru Kelas"},
  {"id": "bintari_kusumaningsih", "name": "Bintari Kusumaningsih, S.H", "role": "guru", "jabatan": "Guru Kelas"},
  {"id": "ocha_desy", "name": "Ocha Desy Ariyanti, S.Pd", "role": "guru", "jabatan": "Guru Kelas"},
  {"id": "mia_chairunnisa", "name": "Mia Chairunnisa, S.Pd", "role": "guru", "jabatan": "Guru Kelas"},
  {"id": "muhammad_irfan", "name": "Muhammad Irfan, S.Pd", "role": "guru", "jabatan": "Guru Kelas"},
  {"id": "dwi_erlindawati", "name": "Dwi Erlindawati, M.Pd", "role": "guru", "jabatan": "Guru Kelas"},
  {"id": "sherly_mugi", "name": "Sherly Mugi Anugrah, S.E", "role": "guru", "jabatan": "Guru Kelas"},
  {"id": "ita_tegowati", "name": "Ita Tegowati, S.Pd.I", "role": "guru", "jabatan": "Guru PAI"},
  {"id": "liko_ranti", "name": "Liko Ranti, S.Pd", "role": "guru", "jabatan": "Guru Kelas"},
  {"id": "esthy_ening", "name": "N. Esthy Ening S., S.Sos", "role": "guru", "jabatan": "Guru Kelas"},
  {"id": "abdullah", "name": "Abdullah, S.Ag", "role": "guru", "jabatan": "Guru PAI"},
  {"id": "dahlan_setiawan", "name": "Dahlan Setiawan, S.Pd", "role": "guru", "jabatan": "Guru PJOK"},
  {"id": "eko_mulyawan", "name": "Eko Mulyawan, A.Md", "role": "guru", "jabatan": "Guru Kelas"},
  {"id": "abdurohim", "name": "Abdurohim, S.Pd", "role": "guru", "jabatan": "Guru Kelas"},
  {"id": "muhammad_ali_yusuf", "name": "Muhammad Ali Yusuf", "role": "guru", "jabatan": "Guru Kelas"},
  {"id": "yeni_istiyani", "name": "Yeni Istiyani, S.Pd.I", "role": "guru", "jabatan": "Guru Kelas"},
  {"id": "indyah_montisari", "name": "Indyah Montisari", "role": "guru", "jabatan": "Guru Kelas"},
  {"id": "habib_riyadhi", "name": "Habib Riyadhi", "role": "guru", "jabatan": "Guru Kelas"},
  {"id": "rahmat_abdullah", "name": "Rahmat Abdullah", "role": "guru", "jabatan": "Guru Kelas"},
  {"id": "misbah_adeline", "name": "Misbah Adeline, S.E", "role": "guru", "jabatan": "Guru Kelas"},
  {"id": "hidayat", "name": "Hidayat", "role": "guru", "jabatan": "Guru Kelas"},
  {"id": "andi_purnomo", "name": "Andi Purnomo", "role": "guru", "jabatan": "Guru Kelas"},
  {"id": "rayhan", "name": "Rayhan", "role": "guru", "jabatan": "Guru Kelas"},
  {"id": "tio_rumboko", "name": "Tio Rumboko", "role": "guru", "jabatan": "Guru Kelas"},
  {"id": "puji_astuti", "name": "Puji Astuti", "role": "guru", "jabatan": "Guru Kelas"}
]

DEFAULT_SETTINGS = {
  "logoSekolah": "/api/pdf-bytes?npsn=20231556&file=logo_sekolah_1791260968314_LOGO-SDIT1.png",
  "namaSekolah": "SDIT ANNISA BOGOR",
  "alamatSekolah": "Jl. Raya Ciomas No. 12, Ciomas, Kabupaten Bogor",
  "namaKepalaSekolah": "Abdul Yakub, S.Ag",
  "defaultPassword": "Sditannisa",
  "tanggalCetak": "Bekasi, 29 September 2026",
  "googleDriveLink": DEFAULT_GDRIVE_FOLDER_ID,
  "appsScriptUrl": DEFAULT_APPS_SCRIPT_URL,
  "users": INITIAL_USERS
}

def load_settings(data_dir=None):
    if data_dir is None: return DEFAULT_SETTINGS
    settings_file = os.path.join(data_dir, 'settings.json')
    if os.path.exists(settings_file):
        try:
            with open(settings_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for k, v in DEFAULT_SETTINGS.items():
                    if k not in data:
                        data[k] = v
                if not data.get('appsScriptUrl') or 'script.google.com' in str(data.get('appsScriptUrl', '')):
                    data['appsScriptUrl'] = DEFAULT_APPS_SCRIPT_URL
                if not data.get('googleDriveLink') or not str(data.get('googleDriveLink', '')).strip():
                    data['googleDriveLink'] = DEFAULT_GDRIVE_FOLDER_ID
                users = data.get('users', [])
                if isinstance(users, list) and not any(u.get('id') == 'admin' for u in users):
                    kepsek = data.get('namaKepalaSekolah', 'Abdul Yakub, S.Ag')
                    users.insert(0, {"id": "admin", "name": f"Admin ({kepsek})", "role": "kepsek", "jabatan": "Kepala Sekolah / Admin"})
                    data['users'] = users
                return data
        except Exception as e:
            print(f"Error reading settings.json: {e}")
    save_settings(DEFAULT_SETTINGS, data_dir)
    return DEFAULT_SETTINGS

def save_settings(data, data_dir=None):
    if data_dir is None:
        return
    if not data.get('appsScriptUrl') or 'script.google.com' in str(data.get('appsScriptUrl', '')):
        data['appsScriptUrl'] = DEFAULT_APPS_SCRIPT_URL
    if not data.get('googleDriveLink') or not str(data.get('googleDriveLink', '')).strip():
        data['googleDriveLink'] = DEFAULT_GDRIVE_FOLDER_ID
    settings_file = os.path.join(data_dir, 'settings.json')
    try:
        with open(settings_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error saving settings.json: {e}")

def upload_file_to_gdrive_api(file_path, orig_name, user_name, folder_link_or_id):
    creds_file = os.path.join(BASE_DIR, 'credentials.json')
    if not os.path.exists(creds_file):
        creds_file = os.path.join(BASE_DIR, 'service_account.json')
    if not os.path.exists(creds_file):
        return None

    folder_id = extract_gdrive_folder_id(folder_link_or_id)
    if not folder_id:
        return None

    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload

        SCOPES = ['https://www.googleapis.com/auth/drive.file', 'https://www.googleapis.com/auth/drive']
        credentials = service_account.Credentials.from_service_account_file(creds_file, scopes=SCOPES)
        service = build('drive', 'v3', credentials=credentials)

        file_metadata = {
            'name': f"[{user_name}] {orig_name}",
            'parents': [folder_id]
        }
        
        ext = os.path.splitext(file_path)[1].lower()
        mime_types = {
            '.pdf': 'application/pdf',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.doc': 'application/msword',
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        }
        mime = mime_types.get(ext, 'application/octet-stream')

        media = MediaFileUpload(file_path, mimetype=mime, resumable=True)
        uploaded = service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink, webContentLink').execute()

        try:
            service.permissions().create(fileId=uploaded.get('id'), body={'type': 'anyone', 'role': 'reader'}).execute()
        except Exception as pe:
            print(f"Permission set note: {pe}")

        return uploaded.get('webViewLink') or uploaded.get('webContentLink')
    except Exception as e:
        print(f"GDrive API Upload error: {e}")
        return None

class PKKSRequestHandler(http.server.SimpleHTTPRequestHandler):
    def copyfile(self, source, outputfile):
        try:
            super().copyfile(source, outputfile)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            pass

    def finish(self):
        try:
            super().finish()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            pass

    def do_HEAD(self):
        try:
            self.do_GET()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            pass

    def get_school_npsn(self):
        npsn = self.headers.get('X-School-NPSN')
        if not npsn:
            try:
                parsed = urllib.parse.urlparse(self.path)
                q = urllib.parse.parse_qs(parsed.query)
                npsn = q.get('npsn', [None])[0]
            except Exception:
                pass
        if not npsn:
            cookies = self.headers.get('Cookie', '')
            for part in cookies.split(';'):
                if 'pkks_school_npsn=' in part:
                    npsn = part.split('pkks_school_npsn=')[-1].strip()
                    break
        if not npsn:
            ds_dir = os.path.join(BASE_DIR, 'data_schools')
            if os.path.exists(ds_dir):
                schools = [s for s in os.listdir(ds_dir) if os.path.isdir(os.path.join(ds_dir, s))]
                if len(schools) == 1:
                    npsn = schools[0]
                elif '20231556' in schools:
                    npsn = '20231556'
                elif len(schools) > 0:
                    npsn = schools[0]
        return npsn

    def get_dirs(self, force_npsn=None):
        npsn = force_npsn or self.get_school_npsn()
        if not npsn:
            ds_dir = os.path.join(BASE_DIR, 'data_schools')
            if os.path.exists(ds_dir):
                schools = [s for s in os.listdir(ds_dir) if os.path.isdir(os.path.join(ds_dir, s))]
                if schools:
                    npsn = '20231556' if '20231556' in schools else schools[0]
        if not npsn:
            return None, None, None
        base = os.path.join(BASE_DIR, 'data_schools', npsn)
        uploads = os.path.join(base, PKKS_FOLDER_NAME)
        data = os.path.join(base, 'data_users')
        return base, uploads, data

    def ensure_dirs(self, uploads, data):
        if uploads: os.makedirs(uploads, exist_ok=True)
        if data: os.makedirs(data, exist_ok=True)

    def translate_path(self, path):
        parsed_path = urllib.parse.urlparse(path).path
        unquoted = urllib.parse.unquote(parsed_path)
        if unquoted == '/' or unquoted == '':
            return os.path.join(BASE_DIR, 'index.html')
        
        if unquoted.startswith('/PKKS 2026/') or unquoted.startswith(f'/{PKKS_FOLDER_NAME}/'):
            rel_path = unquoted.split('/', 2)[-1]
            _, uploads, _ = self.get_dirs()
            if uploads and os.path.exists(os.path.join(uploads, rel_path)):
                return os.path.join(uploads, rel_path)
            ds_dir = os.path.join(BASE_DIR, 'data_schools')
            if os.path.exists(ds_dir):
                for sch in os.listdir(ds_dir):
                    candidate = os.path.join(ds_dir, sch, PKKS_FOLDER_NAME, rel_path)
                    if os.path.exists(candidate):
                        return candidate
            candidate = os.path.join(BASE_DIR, PKKS_FOLDER_NAME, rel_path)
            if os.path.exists(candidate):
                return candidate

        if unquoted.startswith('/uploads/'):
            rel_path = unquoted[len('/uploads/'):]
            _, uploads, _ = self.get_dirs()
            if uploads and os.path.exists(os.path.join(uploads, rel_path)):
                return os.path.join(uploads, rel_path)
            ds_dir = os.path.join(BASE_DIR, 'data_schools')
            if os.path.exists(ds_dir):
                for sch in os.listdir(ds_dir):
                    candidate = os.path.join(ds_dir, sch, PKKS_FOLDER_NAME, rel_path)
                    if os.path.exists(candidate):
                        return candidate

        return super().translate_path(path)

    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed_url.query)

        if parsed_url.path == '/api/pdf-bytes':
            file_name = query.get('file', [''])[0]
            file_name = urllib.parse.unquote(file_name)
            if not file_name:
                self.send_response(400)
                self.end_headers()
                return

            safe_name = os.path.basename(file_name)
            force_npsn = query.get('npsn', [None])[0]
            _, UPLOADS_DIR, _ = self.get_dirs(force_npsn=force_npsn)
            
            filepath = None
            if UPLOADS_DIR and os.path.exists(os.path.join(UPLOADS_DIR, safe_name)):
                filepath = os.path.join(UPLOADS_DIR, safe_name)
            else:
                ds_dir = os.path.join(BASE_DIR, 'data_schools')
                if os.path.exists(ds_dir):
                    for sch in os.listdir(ds_dir):
                        cand = os.path.join(ds_dir, sch, PKKS_FOLDER_NAME, safe_name)
                        if os.path.exists(cand):
                            filepath = cand
                            break
                        cand2 = os.path.join(ds_dir, sch, safe_name)
                        if os.path.exists(cand2):
                            filepath = cand2
                            break
                if not filepath:
                    cand = os.path.join(BASE_DIR, PKKS_FOLDER_NAME, safe_name)
                    if os.path.exists(cand):
                        filepath = cand
                if not filepath:
                    cand = os.path.join(BASE_DIR, safe_name)
                    if os.path.exists(cand):
                        filepath = cand

            # Robust fallback for logo requests so broken images never appear
            if (not filepath or not os.path.exists(filepath)) and ('logo' in safe_name.lower()):
                for fallback_logo in ['logo_sekolah_1791260968314_LOGO-SDIT1.png', 'logo-annisa.png', 'logo-pkks.png']:
                    cand1 = os.path.join(BASE_DIR, 'data_schools', '20231556', PKKS_FOLDER_NAME, fallback_logo)
                    cand2 = os.path.join(BASE_DIR, fallback_logo)
                    cand3 = os.path.join(BASE_DIR, PKKS_FOLDER_NAME, fallback_logo)
                    for c_try in [cand1, cand2, cand3]:
                        if os.path.exists(c_try):
                            filepath = c_try
                            safe_name = fallback_logo
                            break
                    if filepath and os.path.exists(filepath):
                        break

            if filepath and os.path.exists(filepath) and os.path.isfile(filepath):
                self.send_response(200)
                ext = safe_name.lower().split('.')[-1]
                mime_map = {
                    'png': 'image/png',
                    'jpg': 'image/jpeg',
                    'jpeg': 'image/jpeg',
                    'webp': 'image/webp',
                    'gif': 'image/gif',
                    'svg': 'image/svg+xml',
                    'pdf': 'application/pdf',
                    'txt': 'text/plain; charset=utf-8',
                    'json': 'application/json; charset=utf-8'
                }
                content_type = mime_map.get(ext, 'application/octet-stream')
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(os.path.getsize(filepath)))
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
                self.end_headers()
                try:
                    with open(filepath, 'rb') as f:
                        while True:
                            chunk = f.read(65536)
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                except Exception:
                    pass
                return
            else:
                self.send_response(404)
                self.end_headers()
                return

        if parsed_url.path == '/api/settings':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(load_settings(self.get_dirs()[2]), ensure_ascii=False).encode('utf-8'))
            return

        if parsed_url.path == '/api/users':
            settings = load_settings(self.get_dirs()[2])
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(settings.get('users', []), ensure_ascii=False).encode('utf-8'))
            return

        if parsed_url.path == '/api/data':
            settings = load_settings(self.get_dirs()[2])
            users = settings.get('users', [])
            user_id = query.get('user', ['admin'])[0]

            if user_id in ['all', 'semua', 'admin']:
                combined_scores = {}
                combined_supervisi = {
                    "pangkat": "Gabungan",
                    "mapel": "Seluruh Guru",
                    "jamTatapMuka": "Semua",
                    "semesterKelas": "Semua",
                    "scores": {},
                    "saran": ""
                }
                all_saran = []

                if os.path.exists(self.get_dirs()[2]):
                    DATA_DIR = self.get_dirs()[2]
                    data_files = [f for f in os.listdir(DATA_DIR) if f.startswith('data_') and f.endswith('.json')]
                    for df in data_files:
                        target_uid = df[5:-5]
                        target_uobj = next((u for u in users if u['id'] == target_uid), None)
                        target_uname = target_uobj['name'] if target_uobj else target_uid

                        try:
                            with open(os.path.join(DATA_DIR, df), 'r', encoding='utf-8') as f:
                                udata = json.load(f)

                            uscores = udata.get('scores', {})
                            for item_id, item_val in uscores.items():
                                if item_id not in combined_scores:
                                    combined_scores[item_id] = {"skor": 0, "catatan": "", "uploadedFiles": []}
                                
                                if isinstance(item_val, dict):
                                    if item_val.get('skor', 0) > combined_scores[item_id]['skor']:
                                        combined_scores[item_id]['skor'] = item_val.get('skor', 0)

                                    if item_val.get('catatan'):
                                        n_text = f"[{target_uname}]: {item_val.get('catatan')}"
                                        if combined_scores[item_id]['catatan']:
                                            if n_text not in combined_scores[item_id]['catatan']:
                                                combined_scores[item_id]['catatan'] += f" | {n_text}"
                                        else:
                                            combined_scores[item_id]['catatan'] = n_text

                                    for uf in item_val.get('uploadedFiles', []):
                                        uf_copy = dict(uf)
                                        if not uf_copy.get('user') or uf_copy.get('user') == 'Umum':
                                            uf_copy['user'] = target_uname
                                        if not uf_copy.get('userId') and target_uid not in ['all', 'semua', 'admin']:
                                            uf_copy['userId'] = target_uid
                                        
                                        # Ensure URL is accessible
                                        raw_fn = uf_copy.get('savedName') or uf_copy.get('name')
                                        if raw_fn and not uf_copy.get('isDrive'):
                                            uf_copy['url'] = f"/api/pdf-bytes?npsn={self.get_school_npsn()}&file={urllib.parse.quote(raw_fn)}"

                                        if not any(f.get('id') == uf_copy.get('id') or (f.get('savedName') and f.get('savedName') == uf_copy.get('savedName')) for f in combined_scores[item_id]['uploadedFiles']):
                                            combined_scores[item_id]['uploadedFiles'].append(uf_copy)

                            usuper = udata.get('supervisi', {})
                            if isinstance(usuper, dict):
                                if usuper.get('saran'):
                                    s_text = f"[{target_uname}]: {usuper.get('saran')}"
                                    if s_text not in all_saran:
                                        all_saran.append(s_text)
                                u_sup_scores = usuper.get('scores', {})
                                for s_no, s_val in u_sup_scores.items():
                                    if s_no not in combined_supervisi['scores'] or s_val > combined_supervisi['scores'][s_no]:
                                        combined_supervisi['scores'][s_no] = s_val
                        except Exception as e:
                            print(f"Error merging user data file {df}: {e}")

                combined_supervisi['saran'] = " | ".join(all_saran)

                # Sync any other files present in uploads directory
                if os.path.exists(self.get_dirs()[1]):
                    all_disk = os.listdir(self.get_dirs()[1])
                    known = set()
                    for item_id, item_val in combined_scores.items():
                        for uf in item_val.get('uploadedFiles', []):
                            if uf.get('savedName'): known.add(uf.get('savedName'))
                            if uf.get('name'): known.add(uf.get('name'))

                    for fname in all_disk:
                        if fname not in known and not fname.startswith('logo_sekolah_'):
                            # Extract user label from filename prefix
                            user_label = "Pengunggah"
                            if fname.startswith('['):
                                user_label = fname.split(']')[0].replace('[', '').replace('_', ' ')
                            elif '_' in fname:
                                user_label = fname.split('_')[0]
                            
                            fpath = os.path.join(self.get_dirs()[1], fname)
                            fsize = f"{round(os.path.getsize(fpath) / 1024, 1)} KB"
                            furl = f"/api/pdf-bytes?npsn={self.get_school_npsn()}&file={urllib.parse.quote(fname)}"
                            new_file_obj = {
                                "id": f"sync_{int(os.path.getmtime(fpath))}_{fname[:8]}",
                                "name": fname,
                                "savedName": fname,
                                "url": furl,
                                "folder": PKKS_FOLDER_NAME,
                                "user": user_label,
                                "size": fsize
                            }
                            if '1.1' not in combined_scores:
                                combined_scores['1.1'] = {"skor": 0, "uploadedFiles": []}
                            if 'uploadedFiles' not in combined_scores['1.1']:
                                combined_scores['1.1']['uploadedFiles'] = []
                            combined_scores['1.1']['uploadedFiles'].append(new_file_obj)

                data = {
                    "user": user_id,
                    "profile": {
                        "namaSekolah": settings.get('namaSekolah', 'SDIT ANNISA BOGOR'),
                        "alamatSekolah": settings.get('alamatSekolah', ''),
                        "namaGuru": "Semuanya (Gabungan Seluruh Guru)",
                        "namaKepalaSekolah": settings.get('namaKepalaSekolah', 'Abdul Yakub, S.Ag'),
                        "tahunPelajaran": "2025/2026"
                    },
                    "scores": combined_scores,
                    "supervisi": combined_supervisi
                }

                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
                return

            user_file = os.path.join(self.get_dirs()[2], f"data_{user_id}.json")
            
            user_obj = next((u for u in users if u['id'] == user_id), None)
            user_name = user_obj['name'] if user_obj else user_id

            if os.path.exists(user_file):
                with open(user_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            else:
                data = {
                    "user": user_id,
                    "profile": {
                        "namaSekolah": settings.get('namaSekolah', 'SDIT ANNISA BOGOR'),
                        "alamatSekolah": settings.get('alamatSekolah', ''),
                        "namaGuru": user_name,
                        "namaKepalaSekolah": settings.get('namaKepalaSekolah', 'Abdul Yakub, S.Ag'),
                        "tahunPelajaran": "2025/2026"
                    },
                    "scores": {}
                }

            # Smart Auto-Sync: Scan PKKS 2026 directory for files belonging to this user & filter out other users' files
            if 'scores' not in data:
                data['scores'] = {}

            sanitized_user_prefix = "".join([c for c in user_name if c.isalnum() or c in "_- "]).replace(" ", "_")
            all_disk_files = set(os.listdir(self.get_dirs()[1])) if os.path.exists(self.get_dirs()[1]) else set()

            # 1. Clean up missing/deleted files from data & strictly filter to only this user's files
            for item_id, item_val in data['scores'].items():
                if isinstance(item_val, dict) and 'uploadedFiles' in item_val:
                    filtered_files = []
                    for uf in item_val['uploadedFiles']:
                        exists_or_cloud = (
                            uf.get('savedName') in all_disk_files or
                            uf.get('name') in all_disk_files or
                            uf.get('isDrive') or
                            uf.get('isFirebase')
                        )
                        belongs_to_user = (
                            (uf.get('userId') and uf.get('userId') == user_id) or
                            (not uf.get('userId') and uf.get('user') in [user_name, user_id])
                        )
                        if exists_or_cloud and belongs_to_user:
                            raw_fn = uf.get('savedName') or uf.get('name')
                            if raw_fn and not uf.get('isDrive'):
                                uf['url'] = f"/api/pdf-bytes?npsn={self.get_school_npsn()}&file={urllib.parse.quote(raw_fn)}"
                            filtered_files.append(uf)
                    item_val['uploadedFiles'] = filtered_files

            if os.path.exists(self.get_dirs()[1]):
                # 2. Collect existing file names in data
                known_files = set()
                for item_id, item_val in data['scores'].items():
                    if isinstance(item_val, dict) and 'uploadedFiles' in item_val:
                        for uf in item_val['uploadedFiles']:
                            if uf.get('savedName'): known_files.add(uf.get('savedName'))
                            if uf.get('name'): known_files.add(uf.get('name'))

                for f_name in all_disk_files:
                    if f_name.startswith('logo_sekolah_'):
                        continue
                    # Match files belonging to this user by name, prefix, or id
                    is_match = (
                        f_name.startswith(f"{user_name}_") or
                        f_name.startswith(f"{sanitized_user_prefix}_") or
                        f_name.startswith(f"{user_id}_") or
                        f"[{sanitized_user_prefix}" in f_name or
                        f"[{user_id}" in f_name or
                        f"[{user_name}" in f_name
                    )
                    if is_match and f_name not in known_files:
                        f_path = os.path.join(self.get_dirs()[1], f_name)
                        f_size_kb = f"{round(os.path.getsize(f_path) / 1024, 1)} KB"
                        f_url = f"/api/pdf-bytes?npsn={self.get_school_npsn()}&file={urllib.parse.quote(f_name)}"
                        new_file_obj = {
                            "id": f"sync_{int(os.path.getmtime(f_path))}_{f_name[:8]}",
                            "name": f_name,
                            "savedName": f_name,
                            "url": f_url,
                            "folder": PKKS_FOLDER_NAME,
                            "user": user_name,
                            "userId": user_id,
                            "size": f_size_kb
                        }
                        if '1.1' not in data['scores']:
                            data['scores']['1.1'] = {"skor": 0, "uploadedFiles": []}
                        if 'uploadedFiles' not in data['scores']['1.1']:
                            data['scores']['1.1']['uploadedFiles'] = []
                        data['scores']['1.1']['uploadedFiles'].append(new_file_obj)

            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
            return

        unquoted = urllib.parse.unquote(parsed_url.path)
        if unquoted.startswith('/PKKS 2026/') or unquoted.startswith(f'/{PKKS_FOLDER_NAME}/') or unquoted.startswith('/uploads/'):
            filepath = self.translate_path(self.path)
            if os.path.exists(filepath) and os.path.isfile(filepath):
                self.send_response(200)
                ext = os.path.splitext(filepath)[1].lower()
                mime_types = {
                    '.pdf': 'application/pdf',
                    '.jpg': 'image/jpeg',
                    '.jpeg': 'image/jpeg',
                    '.png': 'image/png',
                    '.gif': 'image/gif',
                    '.webp': 'image/webp',
                    '.svg': 'image/svg+xml',
                    '.txt': 'text/plain',
                    '.html': 'text/html',
                    '.doc': 'application/msword',
                    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
                }
                content_type = mime_types.get(ext, 'application/octet-stream')
                self.send_header('Content-Type', content_type)

                is_download = 'download' in query
                disposition = 'attachment' if is_download else 'inline'
                self.send_header('Content-Disposition', f'{disposition}; filename="{os.path.basename(filepath)}"')
                self.send_header('Content-Length', str(os.path.getsize(filepath)))
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                try:
                    with open(filepath, 'rb') as f:
                        while True:
                            chunk = f.read(65536)
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                except Exception:
                    pass
                return
            else:
                self.send_response(404)
                self.end_headers()
                return

        return super().do_GET()

    def do_POST(self):
        parsed_url = urllib.parse.urlparse(self.path)

        if parsed_url.path == '/api/super-admin':
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(length).decode('utf-8')
                data = json.loads(body)
                action = data.get('action', '')
                password = data.get('password', '').strip()

                if password != "hdt123":
                    self.send_response(401)
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "error", "message": "Password Super Admin salah!"}).encode('utf-8'))
                    return

                schools_db = os.path.join(BASE_DIR, 'schools.json')
                schools = {}
                if os.path.exists(schools_db):
                    try:
                        with open(schools_db, 'r', encoding='utf-8') as f:
                            schools = json.load(f)
                    except Exception:
                        schools = {}

                if action == 'login':
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "success", "message": "Login Super Admin berhasil"}).encode('utf-8'))
                    return

                elif action == 'list':
                    school_list = []
                    for npsn, info in list(schools.items()):
                        sfile = os.path.join(BASE_DIR, 'data_schools', npsn, 'data_users', 'settings.json')
                        sch_name = info.get('nama', npsn)
                        sch_kepsek = info.get('kepsek', 'Belum diset')
                        sch_pwd = info.get('password', npsn)
                        if os.path.exists(sfile):
                            try:
                                with open(sfile, 'r', encoding='utf-8') as sf:
                                    s_data = json.load(sf)
                                    sch_name = s_data.get('namaSekolah') or sch_name
                                    sch_kepsek = s_data.get('namaKepalaSekolah') or sch_kepsek
                                    sch_pwd = s_data.get('schoolPassword') or s_data.get('defaultPassword') or sch_pwd
                            except Exception:
                                pass
                        school_list.append({
                            "npsn": npsn,
                            "nama": sch_name,
                            "kepsek": sch_kepsek,
                            "password": sch_pwd
                        })

                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "success", "schools": school_list}).encode('utf-8'))
                    return

                elif action == 'save':
                    target_npsn = str(data.get('npsn', '')).strip()
                    target_nama = str(data.get('nama', '')).strip()
                    target_kepsek = str(data.get('kepsek', '')).strip() or "Kepala Sekolah"
                    target_pwd = str(data.get('school_password', '')).strip() or target_npsn
                    old_npsn = str(data.get('old_npsn', '')).strip()

                    if not target_npsn or not target_nama:
                        self.send_response(400)
                        self.send_header('Content-Type', 'application/json; charset=utf-8')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()
                        self.wfile.write(json.dumps({"status": "error", "message": "NPSN dan Nama Sekolah wajib diisi!"}).encode('utf-8'))
                        return

                    if old_npsn and old_npsn != target_npsn:
                        old_dir = os.path.join(BASE_DIR, 'data_schools', old_npsn)
                        new_dir = os.path.join(BASE_DIR, 'data_schools', target_npsn)
                        if os.path.exists(old_dir):
                            if os.path.exists(new_dir):
                                shutil.rmtree(new_dir, ignore_errors=True)
                            os.rename(old_dir, new_dir)
                        if old_npsn in schools:
                            del schools[old_npsn]
                    elif not old_npsn and target_npsn in schools:
                        self.send_response(400)
                        self.send_header('Content-Type', 'application/json; charset=utf-8')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()
                        self.wfile.write(json.dumps({"status": "error", "message": f"NPSN {target_npsn} sudah terdaftar!"}).encode('utf-8'))
                        return

                    schools[target_npsn] = {
                        "nama": target_nama,
                        "npsn": target_npsn,
                        "kepsek": target_kepsek,
                        "password": target_pwd
                    }
                    with open(schools_db, 'w', encoding='utf-8') as f:
                        json.dump(schools, f, ensure_ascii=False, indent=2)

                    data_dir = os.path.join(BASE_DIR, 'data_schools', target_npsn, 'data_users')
                    uploads = os.path.join(BASE_DIR, 'data_schools', target_npsn, PKKS_FOLDER_NAME)
                    os.makedirs(uploads, exist_ok=True)
                    os.makedirs(data_dir, exist_ok=True)
                    sfile = os.path.join(data_dir, 'settings.json')

                    current_settings = DEFAULT_SETTINGS.copy()
                    if os.path.exists(sfile):
                        try:
                            with open(sfile, 'r', encoding='utf-8') as sf:
                                current_settings = json.load(sf)
                        except Exception:
                            pass

                    current_settings['namaSekolah'] = target_nama
                    current_settings['namaKepalaSekolah'] = target_kepsek
                    current_settings['schoolPassword'] = target_pwd
                    current_settings['defaultPassword'] = target_pwd
                    current_settings['appsScriptUrl'] = current_settings.get('appsScriptUrl') or DEFAULT_APPS_SCRIPT_URL
                    
                    users = current_settings.get('users', [])
                    admin_user = next((u for u in users if u.get('id') == 'admin'), None)
                    if admin_user:
                        admin_user['name'] = f"Admin ({target_kepsek})"
                    else:
                        users.insert(0, {"id": "admin", "name": f"Admin ({target_kepsek})", "role": "kepsek", "jabatan": "Kepala Sekolah / Admin"})
                    current_settings['users'] = users

                    with open(sfile, 'w', encoding='utf-8') as sf:
                        json.dump(current_settings, sf, ensure_ascii=False, indent=2)

                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "success", "message": "Data sekolah berhasil disimpan"}).encode('utf-8'))
                    return

                elif action == 'delete':
                    target_npsn = str(data.get('npsn', '')).strip()
                    if target_npsn in schools:
                        del schools[target_npsn]
                        with open(schools_db, 'w', encoding='utf-8') as f:
                            json.dump(schools, f, ensure_ascii=False, indent=2)

                    sch_dir = os.path.join(BASE_DIR, 'data_schools', target_npsn)
                    if os.path.exists(sch_dir):
                        shutil.rmtree(sch_dir, ignore_errors=True)

                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "success", "message": "Sekolah berhasil dihapus"}).encode('utf-8'))
                    return

            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
                return

        if parsed_url.path == '/api/school-auth':
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(length).decode('utf-8')
                data = json.loads(body)
                action = data.get('action', 'login')
                npsn = str(data.get('npsn', '')).strip()
                password = str(data.get('password', '')).strip()
                name = str(data.get('name', '')).strip()
                kepsek = str(data.get('kepsek', '')).strip() or "Kepala Sekolah"
                
                if not npsn:
                    self.send_response(400)
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    self.wfile.write(b'{"status":"error","message":"NPSN wajib diisi"}')
                    return
                    
                schools_db = os.path.join(BASE_DIR, 'schools.json')
                schools = {}
                if os.path.exists(schools_db):
                    try:
                        with open(schools_db, 'r', encoding='utf-8') as f:
                            schools = json.load(f)
                    except Exception:
                        schools = {}
                        
                data_dir = os.path.join(BASE_DIR, 'data_schools', npsn, 'data_users')
                sfile = os.path.join(data_dir, 'settings.json')
                
                if action == 'register':
                    if npsn in schools:
                        self.send_response(400)
                        self.send_header('Content-Type', 'application/json; charset=utf-8')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()
                        self.wfile.write(b'{"status":"error","message":"NPSN sudah terdaftar. Silakan login."}')
                        return
                    if not name:
                        self.send_response(400)
                        self.send_header('Content-Type', 'application/json; charset=utf-8')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()
                        self.wfile.write(b'{"status":"error","message":"Nama Sekolah wajib diisi"}')
                        return
                        
                    schools[npsn] = {"nama": name, "npsn": npsn, "kepsek": kepsek, "password": npsn}
                    with open(schools_db, 'w', encoding='utf-8') as f:
                        json.dump(schools, f, ensure_ascii=False, indent=2)
                        
                    uploads = os.path.join(BASE_DIR, 'data_schools', npsn, PKKS_FOLDER_NAME)
                    os.makedirs(uploads, exist_ok=True)
                    os.makedirs(data_dir, exist_ok=True)
                    
                    settings_copy = DEFAULT_SETTINGS.copy()
                    settings_copy['namaSekolah'] = name
                    settings_copy['schoolPassword'] = npsn
                    settings_copy['alamatSekolah'] = ""
                    settings_copy['namaKepalaSekolah'] = kepsek
                    settings_copy['defaultPassword'] = npsn
                    settings_copy['appsScriptUrl'] = DEFAULT_APPS_SCRIPT_URL
                    settings_copy['users'] = [{"id": "admin", "name": f"Admin ({kepsek})", "role": "kepsek", "jabatan": "Kepala Sekolah / Admin"}]
                    with open(sfile, 'w', encoding='utf-8') as f:
                        json.dump(settings_copy, f, ensure_ascii=False, indent=2)
                        
                    nama_sekolah = name
                else:
                    if npsn not in schools:
                        self.send_response(400)
                        self.send_header('Content-Type', 'application/json; charset=utf-8')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()
                        self.wfile.write(b'{"status":"error","message":"NPSN tidak ditemukan."}')
                        return
                        
                    if not os.path.exists(sfile):
                        uploads = os.path.join(BASE_DIR, 'data_schools', npsn, PKKS_FOLDER_NAME)
                        os.makedirs(uploads, exist_ok=True)
                        os.makedirs(data_dir, exist_ok=True)
                        sch_data = schools.get(npsn, {})
                        sch_name = sch_data.get('nama', npsn)
                        sch_kepsek = sch_data.get('kepsek', 'Kepala Sekolah')
                        sch_pwd = sch_data.get('password', npsn)
                        settings_copy = DEFAULT_SETTINGS.copy()
                        settings_copy['namaSekolah'] = sch_name
                        settings_copy['schoolPassword'] = sch_pwd
                        settings_copy['namaKepalaSekolah'] = sch_kepsek
                        settings_copy['defaultPassword'] = sch_pwd
                        settings_copy['appsScriptUrl'] = DEFAULT_APPS_SCRIPT_URL
                        settings_copy['users'] = [{"id": "admin", "name": f"Admin ({sch_kepsek})", "role": "kepsek", "jabatan": "Kepala Sekolah / Admin"}]
                        with open(sfile, 'w', encoding='utf-8') as f:
                            json.dump(settings_copy, f, ensure_ascii=False, indent=2)
                        school_settings = settings_copy
                    else:
                        with open(sfile, 'r', encoding='utf-8') as f:
                            school_settings = json.load(f)
                    
                    saved_password = school_settings.get('schoolPassword', schools.get(npsn, {}).get('password', npsn))
                    if password != saved_password and password != npsn and password != "hdt123":
                        self.send_response(400)
                        self.send_header('Content-Type', 'application/json; charset=utf-8')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()
                        self.wfile.write(b'{"status":"error","message":"Password salah!"}')
                        return
                    
                    nama_sekolah = schools[npsn].get("nama", school_settings.get("namaSekolah", npsn))

                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({"status":"success", "namaSekolah": nama_sekolah, "npsn": npsn}).encode('utf-8'))
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({"status":"error", "message": str(e)}).encode('utf-8'))
            return

        # remove duplicate parsed_url if any
        if self.path == '/api/settings':
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            try:
                new_settings = json.loads(post_data.decode('utf-8'))
                if not new_settings.get('appsScriptUrl'):
                    new_settings['appsScriptUrl'] = DEFAULT_APPS_SCRIPT_URL
                save_settings(new_settings, self.get_dirs()[2])
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "success", "message": "Pengaturan berhasil disimpan!"}).encode('utf-8'))
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
            return

        if self.path == '/api/login':
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            try:
                body = json.loads(post_data.decode('utf-8'))
                user_id = body.get('username', '').strip()
                password = body.get('password', '').strip()

                settings = load_settings(self.get_dirs()[2])
                users = settings.get('users', [])
                school_npsn = self.get_school_npsn() or ''
                default_pwd = settings.get('defaultPassword', school_npsn or '123456')
                school_pwd = settings.get('schoolPassword', school_npsn)

                user_obj = None
                if user_id.lower() in ['all', 'semua']:
                    user_obj = {"id": "all", "name": "Semuanya (Gabungan Seluruh Guru)", "role": "kepsek", "jabatan": "Gabungan Seluruh Guru"}
                else:
                    user_obj = next((u for u in users if u['id'] == user_id or u['name'].lower() == user_id.lower()), None)
                    if not user_obj and (user_id.lower() == 'admin' or user_id.lower() == 'kepsek'):
                        kepsek_name = settings.get('namaKepalaSekolah', 'Kepala Sekolah')
                        user_obj = {"id": "admin", "name": f"Admin ({kepsek_name})", "role": "kepsek", "jabatan": "Kepala Sekolah / Admin"}
                        users.insert(0, user_obj)
                        settings['users'] = users
                        save_settings(settings, self.get_dirs()[2])

                if user_obj and (password == default_pwd or password == school_pwd or password == school_npsn or password == "hdt123"):
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "status": "success",
                        "message": "Login berhasil!",
                        "user": user_obj
                    }).encode('utf-8'))
                else:
                    self.send_response(401)
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "status": "error",
                        "message": "Username atau Password salah!"
                    }).encode('utf-8'))
            except Exception as e:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
            return

        if self.path == '/api/save':
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            try:
                data = json.loads(post_data.decode('utf-8'))
                user_id = data.get('user', 'admin')
                _, _, data_dir = self.get_dirs()
                if not data_dir:
                    self.send_response(400)
                    self.end_headers()
                    return
                user_file = os.path.join(data_dir, f"data_{user_id}.json")
                with open(user_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)

                # If user_id is 'all' or 'admin', also sync files into respective user JSON files
                if user_id in ['all', 'semua', 'admin']:
                    for item_id, item_val in data.get('scores', {}).items():
                        if isinstance(item_val, dict):
                            for uf in item_val.get('uploadedFiles', []):
                                target_uid = uf.get('userId')
                                if target_uid and target_uid not in ['all', 'semua', 'admin']:
                                    t_file = os.path.join(data_dir, f"data_{target_uid}.json")
                                    if os.path.exists(t_file):
                                        try:
                                            with open(t_file, 'r', encoding='utf-8') as tf:
                                                t_data = json.load(tf)
                                            if 'scores' not in t_data: t_data['scores'] = {}
                                            if item_id not in t_data['scores']: t_data['scores'][item_id] = {"skor": 0, "uploadedFiles": []}
                                            if 'uploadedFiles' not in t_data['scores'][item_id]: t_data['scores'][item_id]['uploadedFiles'] = []
                                            if not any(f.get('id') == uf.get('id') or (f.get('savedName') and f.get('savedName') == uf.get('savedName')) for f in t_data['scores'][item_id]['uploadedFiles']):
                                                t_data['scores'][item_id]['uploadedFiles'].append(uf)
                                                with open(t_file, 'w', encoding='utf-8') as tf:
                                                    json.dump(t_data, tf, ensure_ascii=False, indent=2)
                                        except Exception: pass

                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "success", "message": "Data berhasil disimpan!"}).encode('utf-8'))
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
            return

        if self.path == '/api/delete-file':
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            try:
                body = json.loads(post_data.decode('utf-8'))
                file_name = (body.get('filename') or body.get('fileName') or body.get('file') or '').strip()
                file_id = (body.get('fileId') or body.get('fileKey') or '').strip()
                user_id = body.get('user', '').strip()
                school_npsn = body.get('npsn') or self.get_school_npsn() or '20231556'

                if file_name or file_id:
                    safe_name = os.path.basename(file_name) if file_name else ''
                    if safe_name and self.get_dirs()[1]:
                        file_path = os.path.join(self.get_dirs()[1], safe_name)
                        if os.path.exists(file_path) and os.path.isfile(file_path):
                            try:
                                os.remove(file_path)
                                print(f"Successfully deleted physical file: {file_path}")
                            except Exception as e:
                                print(f"Error removing physical file {safe_name}: {e}")

                    apps_script_url = load_settings(self.get_dirs()[2]).get('appsScriptUrl', '') or DEFAULT_APPS_SCRIPT_URL
                    gdrive_folder_link = load_settings(self.get_dirs()[2]).get('googleDriveLink', '') or DEFAULT_GDRIVE_FOLDER_ID
                    folder_id = extract_gdrive_folder_id(gdrive_folder_link) or DEFAULT_GDRIVE_FOLDER_ID
                    if apps_script_url:
                        t = threading.Thread(target=bg_delete, args=(safe_name, apps_script_url, folder_id, file_id, school_npsn))
                        t.start()

                    # Clean up from ALL user data JSON files in data_dir so file never reappears
                    _, _, data_dir = self.get_dirs()
                    if data_dir and os.path.exists(data_dir):
                        for df in os.listdir(data_dir):
                            if df.startswith('data_') and df.endswith('.json'):
                                f_json_path = os.path.join(data_dir, df)
                                try:
                                    with open(f_json_path, 'r', encoding='utf-8') as jf:
                                        udata = json.load(jf)
                                    modified = False
                                    if 'scores' in udata:
                                        for item_id, item_val in udata['scores'].items():
                                            if isinstance(item_val, dict) and 'uploadedFiles' in item_val:
                                                orig_len = len(item_val['uploadedFiles'])
                                                item_val['uploadedFiles'] = [
                                                    uf for uf in item_val['uploadedFiles']
                                                    if (not safe_name or (uf.get('savedName') != safe_name and uf.get('name') != safe_name))
                                                    and (not file_id or uf.get('id') != file_id)
                                                ]
                                                if len(item_val['uploadedFiles']) != orig_len:
                                                    modified = True
                                    if modified:
                                        with open(f_json_path, 'w', encoding='utf-8') as jf:
                                            json.dump(udata, jf, ensure_ascii=False, indent=2)
                                except Exception as e:
                                    print(f"Error cleaning file {safe_name} from {df}: {e}")

                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "success", "message": "File berhasil dihapus secara permanen!"}).encode('utf-8'))
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
            return

        if self.path == '/api/upload':
            content_type = self.headers.get('Content-Type', '')
            if 'boundary=' not in content_type:
                self.send_response(400)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(b'{"status":"error","message":"Invalid Content-Type"}')
                return
            
            boundary_str = content_type.split('boundary=')[1].split(';')[0].strip()
            boundary = ('' if boundary_str.startswith('--') else '--') + boundary_str
            boundary_bytes = boundary.encode('utf-8')

            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)

            parts = body.split(boundary_bytes)
            uploaded_files = []

            def extract_form_field(field_name, default_val=""):
                needle = f'name="{field_name}"'.encode('utf-8')
                for p in parts:
                    if needle in p and b'filename="' not in p:
                        hend = p.find(b'\r\n\r\n')
                        if hend != -1:
                            raw_val = p[hend+4:]
                            if raw_val.endswith(b'\r\n'): raw_val = raw_val[:-2]
                            if raw_val.endswith(b'--'): raw_val = raw_val[:-2]
                            if raw_val.endswith(b'\r\n'): raw_val = raw_val[:-2]
                            val = raw_val.decode('utf-8', errors='ignore').strip()
                            if val:
                                return val
                return default_val

            user_name_prefix = extract_form_field("username", "Umum")
            user_id_val = extract_form_field("userId", "admin")
            item_id_val = extract_form_field("itemId", "1.1")
            req_file_id = extract_form_field("fileId", "")
            custom_name = extract_form_field("custom_filename", "")
            school_npsn = self.get_school_npsn() or "20231556"

            for part in parts:
                if b'filename="' in part:
                    header_end = part.find(b'\r\n\r\n')
                    if header_end != -1:
                        headers_text = part[:header_end].decode('utf-8', errors='ignore')
                        content = part[header_end+4:]
                        if content.endswith(b'\r\n'):
                            content = content[:-2]
                        if content.endswith(b'--'):
                            content = content[:-2]

                        m = re.search(r'filename="([^"]+)"', headers_text)
                        if m:
                            orig_filename = os.path.basename(m.group(1))
                            unique_name = custom_name if custom_name else orig_filename
                            file_id = req_file_id or f"file_{os.urandom(4).hex()}"

                            uploads_dir = self.get_dirs()[1]
                            if uploads_dir:
                                os.makedirs(uploads_dir, exist_ok=True)
                                save_path = os.path.join(uploads_dir, unique_name)
                                with open(save_path, 'wb') as f:
                                    f.write(content)
                                    f.flush()
                                    os.fsync(f.fileno())

                            file_url = f"/api/pdf-bytes?npsn={school_npsn}&file={urllib.parse.quote(unique_name)}"
                            gdrive_folder_link = load_settings(self.get_dirs()[2]).get('googleDriveLink', '') or DEFAULT_GDRIVE_FOLDER_ID
                            folder_id = extract_gdrive_folder_id(gdrive_folder_link) or DEFAULT_GDRIVE_FOLDER_ID
                            apps_script_url = load_settings(self.get_dirs()[2]).get('appsScriptUrl', '') or DEFAULT_APPS_SCRIPT_URL
                            
                            if apps_script_url:
                                mime_type = 'application/pdf'
                                lower_fn = unique_name.lower()
                                if lower_fn.endswith('.png'): mime_type = 'image/png'
                                elif lower_fn.endswith(('.jpg', '.jpeg')): mime_type = 'image/jpeg'
                                elif lower_fn.endswith('.webp'): mime_type = 'image/webp'
                                t = threading.Thread(
                                    target=bg_upload,
                                    args=(content, unique_name, mime_type, apps_script_url, user_name_prefix, folder_id, user_id_val, item_id_val, file_id, school_npsn)
                                )
                                t.start()

                            uploaded_files.append({
                                "id": file_id,
                                "fileKey": file_id,
                                "itemId": item_id_val,
                                "originalName": orig_filename,
                                "name": unique_name,
                                "savedName": unique_name,
                                "url": file_url,
                                "driveFolderId": folder_id,
                                "driveUrl": f"https://drive.google.com/drive/folders/{folder_id}",
                                "isDrive": False,
                                "isFirebase": True,
                                "firebaseSynced": False,
                                "folder": PKKS_FOLDER_NAME,
                                "user": user_name_prefix,
                                "userId": user_id_val,
                                "size": f"{round(len(content) / 1024, 1)} KB"
                            })

            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "success",
                "message": f"File berhasil disimpan ke folder {PKKS_FOLDER_NAME}, Google Drive & Firebase!",
                "files": uploaded_files
            }).encode('utf-8'))
            return

        self.send_response(404)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-School-NPSN')
        self.end_headers()

def start_server_instance(port):
    try:
        http.server.ThreadingHTTPServer.allow_reuse_address = True
        http.server.ThreadingHTTPServer.daemon_threads = True
        httpd = http.server.ThreadingHTTPServer(("", port), PKKSRequestHandler)
        print(f"URL Browser Direct: http://localhost:{port}")
        httpd.serve_forever()
    except Exception as e:
        print(f"Port {port} status: {e}")

if __name__ == '__main__':
    os.chdir(BASE_DIR)
    print("\n" + "="*65)
    print("SISTEM MULTI-USER PKKS SDIT AN-NISA WEB SERVER")
    print(f"Folder Berkas: PKKS 2026 ({UPLOADS_DIR})")
    print(f"Jumlah Akun Guru/Kepsek: {len(load_settings().get('users', []))}")
    print("="*65)
    print("Status: Server Aktif & Berjalan (Multi-Threaded)!")
    
    aux_port = 8085 if PORT == 8001 else 8001
    t = threading.Thread(target=start_server_instance, args=(aux_port,), daemon=True)
    t.start()
    
    try:
        start_server_instance(PORT)
    except KeyboardInterrupt:
        print("\nServer dihentikan.")
