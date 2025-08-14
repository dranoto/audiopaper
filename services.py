import os
import json
import fitz  # PyMuPDF
from google import genai
from google.genai import types
import io
import re
import pathlib
from pydub import AudioSegment
from database import get_settings

# --- Global lists for models and voices ---
available_text_models = []
available_tts_models = []
# The Gemini API does not currently provide an endpoint to list voices,
# so we are using a hardcoded list of available prebuilt voices.
available_voices = [
    'Zephyr', 'Puck', 'Charon', 'Kore', 'Fenrir', 'Leda', 'Orus', 'Aoede',
    'Callirrhoe', 'Autonoe', 'Enceladus', 'Iapetus', 'Umbriel', 'Algieba',
    'Despina', 'Erinome', 'Algenib', 'Rasalgethi', 'Laomedeia', 'Achernar',
    'Alnilam', 'Schedar', 'Gacrux', 'Pulcherrima', 'Achird', 'Zubenelgenubi',
    'Vindemiatrix', 'Sadachbia', 'Sadaltager', 'Sulafat'
]

def init_gemini_client(app_instance):
    global available_text_models, available_tts_models
    with app_instance.app_context():
        settings = get_settings()
        api_key = settings.gemini_api_key or os.environ.get('GEMINI_API_KEY')
        if api_key:
            try:
                client = genai.Client(api_key=api_key)
                app_instance.gemini_client = client
                app_instance.logger.info("Gemini Client initialized successfully.")

                # Fetch and filter models
                available_text_models.clear()
                available_tts_models.clear()
                for model in client.models.list():
                    model_name = model.name.replace("models/", "")
                    if 'generateContent' in model.supported_actions:
                         # Heuristic to separate TTS from other generative models
                        if 'tts' in model_name:
                            available_tts_models.append(model_name)
                        else:
                            available_text_models.append(model_name)

                available_text_models = sorted(available_text_models)
                available_tts_models = sorted(available_tts_models)
                app_instance.logger.info(f"Found {len(available_text_models)} text models and {len(available_tts_models)} TTS models.")

            except Exception as e:
                app_instance.gemini_client = None
                app_instance.logger.error(f"Failed to initialize Gemini Client or fetch models: {e}")
        else:
            app_instance.gemini_client = None
            app_instance.logger.warning("Gemini API key not found. Generative features will be disabled.")


def process_pdf(filepath):
    doc = fitz.open(filepath)
    text = ""
    figures = []
    captions = []
    figure_dir = os.path.join('static', 'figures', os.path.basename(filepath).replace('.pdf', ''))
    os.makedirs(figure_dir, exist_ok=True)

    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        text += page.get_text()
        text_blocks = page.get_text("blocks")
        image_list = page.get_images(full=True)

        for img_index, img in enumerate(image_list):
            xref = img[0]
            try:
                img_bbox = page.get_image_bbox(img)
            except ValueError:
                continue

            base_image = doc.extract_image(xref)
            image_bytes = base_image["image"]
            image_ext = base_image["ext"]
            image_filename = f"image_{page_num+1}_{img_index}.{image_ext}"
            image_path = os.path.join(figure_dir, image_filename)

            with open(image_path, "wb") as f:
                f.write(image_bytes)
            figures.append(image_path)

            found_caption = ""
            for tb in text_blocks:
                text_bbox = fitz.Rect(tb[:4])
                if text_bbox.y0 > img_bbox.y1 and (text_bbox.y0 - img_bbox.y1) < 50:
                    text_center_x = (text_bbox.x0 + text_bbox.x1) / 2
                    if img_bbox.x0 < text_center_x < img_bbox.x1 and tb[4].strip().lower().startswith(('figure', 'fig.')):
                        found_caption = tb[4].strip().replace('\n', ' ')
                        break
            captions.append(found_caption if found_caption else f"Figure {len(figures)}")

    return text, json.dumps(figures), json.dumps(captions)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'pdf'}
