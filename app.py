from flask import Flask, request, render_template, send_file, session, jsonify
import os
import re
import json
import uuid
import time
import tempfile
from google.cloud import texttospeech
from google.oauth2 import service_account
import shutil
from werkzeug.utils import secure_filename
from pydub import AudioSegment
import io
import gc  # для очищення пам'яті

app = Flask(__name__)
app.secret_key = os.urandom(24)  # для роботи session

# Директорії для файлів
UPLOAD_FOLDER = "uploads"
AUDIO_FOLDER = "audio_chunks"
OUTPUT_FOLDER = "output"

# Максимальний розмір файлу (5MB)
MAX_FILE_SIZE = 5 * 1024 * 1024

# Створення директорій, якщо не існують
for folder in [UPLOAD_FOLDER, AUDIO_FOLDER, OUTPUT_FOLDER]:
    os.makedirs(folder, exist_ok=True)

# Завантаження credentials
CREDENTIALS_PATH = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "credentials.json")

# Перевірка наявності credentials файлу або середовища
try:
    if os.path.exists(CREDENTIALS_PATH):
        with open(CREDENTIALS_PATH, 'r') as f:
            credentials_info = json.load(f)
        credentials = service_account.Credentials.from_service_account_info(credentials_info)
    else:
        # Якщо файл не знайдено, спробуємо використати значення змінних середовища
        credentials = None  # Буде використовуватись автовизначення Google Cloud
except Exception as e:
    print(f"Помилка зчитування credentials: {e}")
    credentials = None

# Список доступних голосів
VOICE_OPTIONS = [
    # HD голоси (високої якості)
    "en-US-Chirp3-HD-Leda",
    "en-US-Chirp3-HD-Kore",
    "en-US-Chirp3-HD-Charon",
    "en-US-Chirp3-HD-Fenrir", 
    "en-US-Chirp3-HD-Puck",
    # Стандартні голоси
    "uk-UA-Standard-A",
    "en-US-Standard-C", 
    "en-US-Wavenet-F",
    "en-GB-Standard-A",
    "ru-RU-Standard-A",
]

# Розумне розбиття тексту по реченнях
def split_text_by_sentences(text, max_chars=4800):
    sentences = re.split(r'(?<=[.!?]) +', text)
    chunks = []
    current_chunk = ""

    for sentence in sentences:
        if len(current_chunk) + len(sentence) + 1 <= max_chars:
            current_chunk += sentence + " "
        else:
            chunks.append(current_chunk.strip())
            current_chunk = sentence + " "

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks

# Генерування аудіо з тексту
def synthesize_speech(text, voice_name, output_path):
    try:
        # Визначення мови з назви голосу
        language_code = voice_name.split("-")[0] + "-" + voice_name.split("-")[1]
        
        # Створення клієнта TTS
        if credentials:
            client = texttospeech.TextToSpeechClient(credentials=credentials)
        else:
            client = texttospeech.TextToSpeechClient()
        
        input_text = texttospeech.SynthesisInput(text=text)
        voice = texttospeech.VoiceSelectionParams(
            language_code=language_code,
            name=voice_name
        )
        
        # Налаштування якості аудіо (HD налаштування для HD голосів)
        if "HD" in voice_name:
            audio_config = texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.MP3,
                speaking_rate=1.0,
                pitch=0.0,
                sample_rate_hertz=24000
            )
        else:
            audio_config = texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.MP3
            )

        # Генерування аудіо
        response = client.synthesize_speech(
            input=input_text, voice=voice, audio_config=audio_config
        )
        
        # Запис у файл
        with open(output_path, "wb") as out:
            out.write(response.audio_content)
        
        return True
    except Exception as e:
        print(f"Помилка при синтезі мовлення: {e}")
        return False

# Обробка маленьких текстів напряму без розбиття
@app.route('/synthesize_small', methods=['POST'])
def synthesize_small():
    try:
        voice_name = request.form['voice']
        text = request.form['text']
        
        if len(text) > 4800:
            return jsonify({"error": "Текст занадто довгий для швидкої обробки"}), 400
        
        # Створюємо тимчасовий файл
        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tmp:
            tmp_path = tmp.name
        
        # Синтезуємо мовлення
        if not synthesize_speech(text, voice_name, tmp_path):
            return jsonify({"error": "Помилка при синтезі мовлення"}), 500
        
        # Повертаємо аудіо
        return send_file(tmp_path, mimetype='audio/mp3')
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        try:
            # Перевірка розміру файлу
            if 'text_file' in request.files and request.files['text_file'].filename:
                file = request.files['text_file']
                if file.content_length and file.content_length > MAX_FILE_SIZE:
                    return render_template('index.html', 
                                       error="Файл занадто великий. Максимальний розмір 5MB.",
                                       voice_options=VOICE_OPTIONS)
            
            # Створюємо унікальний ID для сесії
            session_id = str(uuid.uuid4())
            session['session_id'] = session_id
            
            # Отримання голосу
            voice_name = request.form['voice']
            
            # Завантаження файлу або отримання тексту
            if 'text_file' in request.files and request.files['text_file'].filename:
                file = request.files['text_file']
                filename = secure_filename(file.filename)
                file_path = os.path.join(UPLOAD_FOLDER, f"{session_id}_{filename}")
                file.save(file_path)
                
                # Читання вмісту файлу
                with open(file_path, 'r', encoding='utf-8') as f:
                    text = f.read()
            elif 'text_content' in request.form and request.form['text_content'].strip():
                text = request.form['text_content']
                file_path = os.path.join(UPLOAD_FOLDER, f"{session_id}_text.txt")
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(text)
            else:
                return render_template('index.html', 
                                      error="Будь ласка, завантажте файл або введіть текст",
                                      voice_options=VOICE_OPTIONS)
            
            # Для невеликих текстів - швидка обробка без розбиття
            if len(text) <= 1000:
                # Створюємо вихідний файл
                output_filename = os.path.splitext(os.path.basename(file_path))[0].replace(f"{session_id}_", "") + ".mp3"
                output_path = os.path.join(OUTPUT_FOLDER, f"{session_id}_{output_filename}")
                
                # Синтезуємо мовлення напряму
                if synthesize_speech(text, voice_name, output_path):
                    # Зберігання шляху у сесії
                    session['output_file'] = output_path
                    session['output_filename'] = output_filename
                    
                    return render_template('result.html', 
                                          filename=output_filename,
                                          text_length=len(text),
                                          chunks_count=1)
            
            # Створення каталогу для аудіофрагментів
            session_audio_folder = os.path.join(AUDIO_FOLDER, session_id)
            os.makedirs(session_audio_folder, exist_ok=True)
            
            # Розбиття тексту на фрагменти
            chunks = split_text_by_sentences(text, max_chars=3000)  # Зменшили розмір для швидшої обробки
            
            # Генерування аудіо для кожного фрагмента
            mp3_files = []
            for i, chunk in enumerate(chunks):
                chunk_path = os.path.join(session_audio_folder, f"chunk_{i:02d}.mp3")
                if synthesize_speech(chunk, voice_name, chunk_path):
                    mp3_files.append(chunk_path)
                # Невелика пауза для уникнення Rate Limit API
                time.sleep(0.5)
            
            # Об'єднання аудіофрагментів (поетапно для економії пам'яті)
            if len(mp3_files) > 0:
                # Визначення вихідного файлу
                output_filename = os.path.splitext(os.path.basename(file_path))[0].replace(f"{session_id}_", "") + ".mp3"
                output_path = os.path.join(OUTPUT_FOLDER, f"{session_id}_{output_filename}")
                
                # Об'єднання аудіо блоками по 5 файлів для економії пам'яті
                block_size = 5
                for i in range(0, len(mp3_files), block_size):
                    block = mp3_files[i:i+block_size]
                    
                    # Для першого блоку створюємо початковий файл
                    if i == 0:
                        combined = AudioSegment.empty()
                        for mp3 in block:
                            segment = AudioSegment.from_mp3(mp3)
                            combined += segment
                            del segment  # видалення для звільнення пам'яті
                            gc.collect()  # примусове очищення пам'яті
                        combined.export(output_path, format="mp3")
                        del combined
                        gc.collect()
                    # Для наступних - додаємо до існуючого
                    else:
                        existing = AudioSegment.from_mp3(output_path)
                        for mp3 in block:
                            segment = AudioSegment.from_mp3(mp3)
                            existing += segment
                            del segment
                            gc.collect()
                        existing.export(output_path, format="mp3")
                        del existing
                        gc.collect()
                
                # Зберігання шляху у сесії
                session['output_file'] = output_path
                session['output_filename'] = output_filename
                
                return render_template('result.html', 
                                      filename=output_filename,
                                      text_length=len(text),
                                      chunks_count=len(chunks))
            else:
                return render_template('index.html', 
                                      error="Помилка при генерації аудіо. Спробуйте інший текст або голос.",
                                      voice_options=VOICE_OPTIONS)
        except Exception as e:
            print(f"Помилка: {e}")
            return render_template('index.html', 
                                 error=f"Виникла помилка: {str(e)}",
                                 voice_options=VOICE_OPTIONS)
    
    # Якщо GET запит, показуємо форму
    return render_template('index.html', voice_options=VOICE_OPTIONS)

@app.route('/download')
def download():
    if 'output_file' in session and 'output_filename' in session:
        output_path = session['output_file']
        output_filename = session['output_filename']
        return send_file(output_path, as_attachment=True, download_name=output_filename)
    else:
        return "Файл не знайдено. Спробуйте знову створити аудіо."

@app.route('/play')
def play():
    if 'output_file' in session:
        output_path = session['output_file']
        return send_file(output_path, mimetype='audio/mp3')
    else:
        return "Файл не знайдено. Спробуйте знову створити аудіо."

@app.route('/cleanup', methods=['POST'])
def cleanup():
    # Очищення тимчасових файлів після завершення
    if 'session_id' in session:
        session_id = session['session_id']
        session_audio_folder = os.path.join(AUDIO_FOLDER, session_id)
        
        # Видалення аудіофрагментів
        if os.path.exists(session_audio_folder):
            shutil.rmtree(session_audio_folder)
        
        # Видалення завантаженого файлу та вихідного аудіо
        for folder in [UPLOAD_FOLDER, OUTPUT_FOLDER]:
            for filename in os.listdir(folder):
                if filename.startswith(f"{session_id}_"):
                    try:
                        os.remove(os.path.join(folder, filename))
                    except:
                        pass
    
    # Очищення сесії
    session.clear()
    
    # Примусове очищення пам'яті
    gc.collect()
    
    return "OK"

@app.route('/health')
def health():
    return "OK"

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
