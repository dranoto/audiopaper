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
    elements = []
    figure_dir = os.path.join('static', 'figures', os.path.basename(filepath).replace('.pdf', ''))
    os.makedirs(figure_dir, exist_ok=True)

    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        text += page.get_text()
        text_blocks = page.get_text("blocks")

        # --- Process Images ---
        image_list = page.get_images(full=True)
        for img_index, img in enumerate(image_list):
            xref = img[0]
            try:
                img_bbox = page.get_image_bbox(img)
            except ValueError:
                continue  # Skip if bbox cannot be found

            base_image = doc.extract_image(xref)
            # Filter out small decorative images based on size
            if base_image["width"] < 100 and base_image["height"] < 100:
                continue

            # Search for a caption below the image
            found_caption = ""
            for tb in text_blocks:
                text_bbox = fitz.Rect(tb[:4])
                # Check if text block is below the image and reasonably close
                if text_bbox.y0 > img_bbox.y1 and (text_bbox.y0 - img_bbox.y1) < 50:
                    # Check if text is horizontally aligned with the image
                    text_center_x = (text_bbox.x0 + text_bbox.x1) / 2
                    if img_bbox.x0 < text_center_x < img_bbox.x1:
                        block_text = tb[4].strip().replace('\n', ' ')
                        if block_text.lower().startswith(('figure', 'fig.')):
                            found_caption = block_text
                            break

            if found_caption:
                image_bytes = base_image["image"]
                image_ext = base_image["ext"]
                image_filename = f"image_{page_num+1}_{img_index}.{image_ext}"
                image_path = os.path.join(figure_dir, image_filename)
                with open(image_path, "wb") as f:
                    f.write(image_bytes)

                elements.append({
                    "type": "figure",
                    "path": image_path,
                    "caption": found_caption
                })

        # --- Process Tables ---
        try:
            tables = page.find_tables()
            for table_index, table in enumerate(tables):
                table_bbox = fitz.Rect(table.bbox)

                # Search for a caption (typically above the table)
                found_caption = ""
                for tb in text_blocks:
                    text_bbox = fitz.Rect(tb[:4])
                    # Check if text block is above the table and reasonably close
                    if table_bbox.y0 > text_bbox.y1 and (table_bbox.y0 - text_bbox.y1) < 50:
                        # Check if text is horizontally aligned
                        text_center_x = (text_bbox.x0 + text_bbox.x1) / 2
                        if table_bbox.x0 < text_center_x < table_bbox.x1:
                            block_text = tb[4].strip().replace('\n', ' ')
                            if block_text.lower().startswith(('table', 'tbl.')):
                                found_caption = block_text
                                break

                if found_caption:
                    table_data = table.extract()
                    # Filter out empty or very small tables
                    if table_data and len(table_data) > 1:
                        elements.append({
                            "type": "table",
                            "data": table_data,
                            "caption": found_caption,
                            "page": page_num + 1
                        })
        except Exception as e:
            # Log error if table processing fails for a page
            logging.warning(f"Could not process tables on page {page_num+1}: {e}")


    # Sort elements by page and then by vertical position
    # This is a bit tricky since we don't store y-pos, but page order is a good start.
    # A more robust solution would store the y-coordinate of each element.
    # For now, we assume the order of discovery is sufficient.

    return text, json.dumps(elements), json.dumps([]) # Return empty list for old captions

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'pdf'}
