from flask import Flask, request, render_template, send_file, session, jsonify
import os
import re
import json
import uuid
import time
import tempfile
from google.cloud import texttospeech
from google.oauth2 import service_account
import io
import gc  # для очищення пам'яті
from werkzeug.utils import secure_filename
from pydub import AudioSegment

app = Flask(__name__)
app.secret_key = os.urandom(24)  # для роботи session
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB максимальний розмір запиту
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0  # Відключаємо кешування файлів

# Максимальний розмір тексту
MAX_TEXT_SIZE = 50000  # символів

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

# Генерування аудіо з тексту (повертає байти напряму)
def synthesize_speech_to_bytes(text, voice_name):
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
        
        # Повертаємо байти аудіо
        return response.audio_content
    except Exception as e:
        print(f"Помилка при синтезі мовлення: {e}")
        return None

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        try:
            # Отримання голосу
            voice_name = request.form['voice']
            
            # Завантаження файлу або отримання тексту
            if 'text_file' in request.files and request.files['text_file'].filename:
                file = request.files['text_file']
                if file.content_length and file.content_length > app.config['MAX_CONTENT_LENGTH']:
                    return render_template('index.html', 
                                      error=f"Файл занадто великий. Максимальний розмір {app.config['MAX_CONTENT_LENGTH'] // (1024*1024)}MB.",
                                      voice_options=VOICE_OPTIONS)
                
                # Читання вмісту файлу в пам'ять
                file_content = file.read().decode('utf-8')
                text = file_content
                filename = secure_filename(file.filename)
            elif 'text_content' in request.form and request.form['text_content'].strip():
                text = request.form['text_content']
                filename = "text.txt"
            else:
                return render_template('index.html', 
                                      error="Будь ласка, завантажте файл або введіть текст",
                                      voice_options=VOICE_OPTIONS)
            
            # Перевірка розміру тексту
            if len(text) > MAX_TEXT_SIZE:
                return render_template('index.html', 
                                      error=f"Текст занадто великий. Максимальний розмір {MAX_TEXT_SIZE} символів.",
                                      voice_options=VOICE_OPTIONS)
            
            # Для невеликих текстів - швидка обробка без розбиття
            if len(text) <= 1000:
                # Генеруємо аудіо напряму як байти
                audio_bytes = synthesize_speech_to_bytes(text, voice_name)
                
                if audio_bytes:
                    # Створюємо ім'я вихідного файлу
                    output_filename = os.path.splitext(filename)[0] + ".mp3"
                    
                    # Зберігаємо аудіо в сесії
                    session['audio_data'] = audio_bytes
                    session['output_filename'] = output_filename
                    
                    return render_template('result.html', 
                                          filename=output_filename,
                                          text_length=len(text),
                                          chunks_count=1)
                else:
                    return render_template('index.html', 
                                          error="Помилка при генерації аудіо. Спробуйте інший текст або голос.",
                                          voice_options=VOICE_OPTIONS)
            
            # Розбиття тексту на фрагменти
            chunks = split_text_by_sentences(text, max_chars=3000)  # Зменшили розмір для швидшої обробки
            
            # Генерування аудіо для кожного фрагмента
            audio_segments = []
            for chunk in chunks:
                audio_bytes = synthesize_speech_to_bytes(chunk, voice_name)
                if audio_bytes:
                    # Завантажуємо байти в AudioSegment
                    segment = AudioSegment.from_mp3(io.BytesIO(audio_bytes))
                    audio_segments.append(segment)
                # Невелика пауза для уникнення Rate Limit API
                time.sleep(0.5)
            
            # Об'єднання аудіофрагментів
            if audio_segments:
                # Об'єднання аудіо в пам'яті
                final_audio = AudioSegment.empty()
                for segment in audio_segments:
                    final_audio += segment
                
                # Експорт в байти
                output_buffer = io.BytesIO()
                final_audio.export(output_buffer, format="mp3")
                
                # Отримання байтів
                output_buffer.seek(0)
                audio_data = output_buffer.getvalue()
                
                # Створюємо ім'я вихідного файлу
                output_filename = os.path.splitext(filename)[0] + ".mp3"
                
                # Зберігаємо аудіо в сесії
                session['audio_data'] = audio_data
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
    try:
        if 'audio_data' in session and 'output_filename' in session:
            audio_data = session['audio_data']
            output_filename = session['output_filename']
            
            # Створення буферу з байтів
            buffer = io.BytesIO(audio_data)
            
            # Відправка файлу
            return send_file(
                buffer,
                mimetype='audio/mp3',
                as_attachment=True,
                download_name=output_filename,
                max_age=0
            )
        else:
            return "Аудіо не знайдено. Спробуйте знову створити аудіо.", 404
    except Exception as e:
        print(f"Помилка завантаження: {str(e)}")
        return f"Помилка під час завантаження: {str(e)}", 500

@app.route('/play')
def play():
    try:
        if 'audio_data' in session:
            audio_data = session['audio_data']
            
            # Створення буферу з байтів
            buffer = io.BytesIO(audio_data)
            
            # Відправка файлу
            return send_file(
                buffer,
                mimetype='audio/mp3',
                conditional=True
            )
        else:
            return "Аудіо не знайдено. Спробуйте знову створити аудіо.", 404
    except Exception as e:
        print(f"Помилка відтворення: {str(e)}")
        return f"Помилка під час відтворення: {str(e)}", 500

@app.route('/cleanup', methods=['POST'])
def cleanup():
    # Очищення сесії
    if 'audio_data' in session:
        del session['audio_data']
    if 'output_filename' in session:
        del session['output_filename']
    
    # Примусове очищення пам'яті
    gc.collect()
    
    return "OK"

@app.route('/health')
def health():
    return "OK"

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
