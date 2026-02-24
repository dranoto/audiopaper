import os
import json
import fitz  # PyMuPDF
import io
import re
import pathlib
from typing import Optional, Generator, List, Tuple, Any
from pydub import AudioSegment
from database import get_settings

# Try to import OpenAI for DeepInfra Kokoro TTS
try:
    from openai import OpenAI

    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

# --- Default settings from environment ---
SUMMARY_MODEL = os.environ.get("SUMMARY_MODEL", "openai/gpt-5.2")
TRANSCRIPT_MODEL = os.environ.get("TRANSCRIPT_MODEL", "openai/gpt-5.2")
CHAT_MODEL = os.environ.get("CHAT_MODEL", "openai/gpt-5.2")
TTS_MODEL = os.environ.get("TTS_MODEL", "hexgrad/Kokoro-82M")
TTS_HOST_VOICE = os.environ.get("TTS_HOST_VOICE", "af_bella")
TTS_EXPERT_VOICE = os.environ.get("TTS_EXPERT_VOICE", "am_onyx")
TTS_LENGTH = os.environ.get("TTS_LENGTH", "")

# --- Global lists for models and voices ---
available_text_models = []
available_tts_models = []

# Kokoro voices from DeepInfra - see https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md
# Format: (voice_id, description)
available_voices = [
    # American English Female
    ("af_heart", "AF Heart ❤️ - Best quality"),
    ("af_bella", "AF Bella 🔥 - High quality"),
    ("af_alloy", "AF Alloy"),
    ("af_aoede", "AF Aoede"),
    ("af_kore", "AF Kore"),
    ("af_nicole", "AF Nicole 🎧"),
    ("af_nova", "AF Nova"),
    ("af_river", "AF River"),
    ("af_sarah", "AF Sarah"),
    ("af_sky", "AF Sky"),
    ("af_jessica", "AF Jessica"),
    # American English Male
    ("am_adam", "AM Adam"),
    ("am_echo", "AM Echo"),
    ("am_eric", "AM Eric"),
    ("am_fenrir", "AM Fenrir"),
    ("am_liam", "AM Liam"),
    ("am_michael", "AM Michael"),
    ("am_onyx", "AM Onyx"),
    ("am_puck", "AM Puck"),
    ("am_santa", "AM Santa"),
    # British English
    ("bf_alice", "BF Alice"),
    ("bf_emma", "BF Emma"),
    ("bf_isabella", "BF Isabella"),
    ("bf_lily", "BF Lily"),
    ("bm_daniel", "BM Daniel"),
    ("bm_fable", "BM Fable"),
    ("bm_george", "BM George"),
    ("bm_lewis", "BM Lewis"),
    # Japanese
    ("jf_alpha", "JF Alpha"),
    ("jf_gongitsune", "JF Gongitsune"),
    ("jf_nezumi", "JF Nezumi"),
    ("jf_tebukuro", "JF Tebukuro"),
    ("jm_kumo", "JM Kumo"),
    # Mandarin Chinese
    ("zf_xiaobei", "ZF Xiaobei"),
    ("zf_xiaoni", "ZF Xiaoni"),
    ("zf_xiaoxiao", "ZF Xiaoxiao"),
    ("zf_xiaoyi", "ZF Xiaoyi"),
    ("zm_yunjian", "ZM Yunjian"),
    ("zm_yunxi", "ZM Yunxi"),
    ("zm_yunxia", "ZM Yunxia"),
    ("zm_yunyang", "ZM Yunyang"),
    # Spanish
    ("ef_dora", "EF Dora"),
    ("em_alex", "EM Alex"),
    ("em_santa", "EM Santa"),
    # French
    ("ff_siwis", "FF Siwis"),
    # Hindi
    ("hf_alpha", "HF Alpha"),
    ("hf_beta", "HF Beta"),
    ("hm_omega", "HM Omega"),
    ("hm_psi", "HM Psi"),
    # Italian
    ("if_sara", "IF Sara"),
    ("im_nicola", "IM Nicola"),
    # Brazilian Portuguese
    ("pf_dora", "PF Dora"),
    ("pm_alex", "PM Alex"),
    ("pm_santa", "PM Santa"),
]


def init_tts_client(app_instance):
    """
    Initialize the TTS client for DeepInfra Kokoro.
    Uses OpenAI-compatible API.
    """
    global available_tts_models
    with app_instance.app_context():
        settings = get_settings()
        api_key = settings.deepinfra_api_key or os.environ.get("DEEPINFRA_API_KEY")

        if api_key and OPENAI_AVAILABLE:
            try:
                client = OpenAI(
                    base_url="https://api.deepinfra.com/v1/openai", api_key=api_key
                )
                app_instance.tts_client = client
                app_instance.logger.info(
                    "DeepInfra Kokoro TTS Client initialized successfully."
                )

                # Kokoro is the only model for now
                available_tts_models = ["hexgrad/Kokoro-82M"]
            except Exception as e:
                app_instance.tts_client = None
                app_instance.logger.error(
                    f"Failed to initialize DeepInfra TTS Client: {e}"
                )
        else:
            app_instance.tts_client = None
            if not api_key:
                app_instance.logger.warning(
                    "DeepInfra API key not found. TTS features will be disabled."
                )
            if not OPENAI_AVAILABLE:
                app_instance.logger.warning(
                    "OpenAI package not installed. Run: pip install openai"
                )


def init_text_client(app_instance):
    """
    Initialize the text generation client for NanoGPT.
    Uses OpenAI-compatible API.
    """
    global available_text_models
    with app_instance.app_context():
        settings = get_settings()
        api_key = settings.nanogpt_api_key or os.environ.get("NANOGPT_API_KEY")

        if api_key and OPENAI_AVAILABLE:
            try:
                client = OpenAI(base_url="https://nano-gpt.com/api/v1", api_key=api_key)
                app_instance.text_client = client
                app_instance.logger.info(
                    "NanoGPT text client initialized successfully."
                )

                # List available models - try to get them from the API
                try:
                    models = client.models.list()
                    available_text_models = [m.id for m in models.data]
                    app_instance.logger.info(
                        f"Found {len(available_text_models)} text models."
                    )
                except Exception as e:
                    app_instance.logger.warning(f"Could not fetch models list: {e}")
                    # Default models if we can't fetch the list
                    available_text_models = [
                        SUMMARY_MODEL,
                        TRANSCRIPT_MODEL,
                        CHAT_MODEL,
                    ]
            except Exception as e:
                app_instance.text_client = None
                app_instance.logger.error(
                    f"Failed to initialize NanoGPT text client: {e}"
                )
        else:
            app_instance.text_client = None
            if not api_key:
                app_instance.logger.warning(
                    "NanoGPT API key not found. Text generation features will be disabled."
                )
            if not OPENAI_AVAILABLE:
                app_instance.logger.warning(
                    "OpenAI package not installed. Run: pip install openai"
                )


def generate_text_completion(text_client, model, prompt, system_prompt=None):
    """
    Generate text completion using NanoGPT.
    Returns the generated text.
    """
    if not text_client:
        raise Exception("Text client not initialized")

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    response = text_client.chat.completions.create(model=model, messages=messages)

    return response.choices[0].message.content


def generate_text_with_file(
    text_client, model, file_content, prompt, system_prompt=None
):
    """
    Generate text using a document and prompt via NanoGPT.
    Uses the file content as context.
    """
    if not text_client:
        raise Exception("Text client not initialized")

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    # Add the document content as context
    context = f"Document content:\n{file_content}\n\n---\n\nUser question: {prompt}"
    messages.append({"role": "user", "content": context})

    response = text_client.chat.completions.create(model=model, messages=messages)

    return response.choices[0].message.content


def generate_text_stream(text_client, model, file_content, prompt, system_prompt=None):
    """
    Generate text using streaming via NanoGPT.
    Yields tokens as they are generated.
    """
    if not text_client:
        raise Exception("Text client not initialized")

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    # Add the document content as context
    context = f"Document content:\n{file_content}\n\n---\n\nUser question: {prompt}"
    messages.append({"role": "user", "content": context})

    response = text_client.chat.completions.create(
        model=model, messages=messages, stream=True
    )

    for chunk in response:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content


def generate_voice_sample(tts_client, voice_id, text, speed=1.0):
    """
    Generates a voice sample using DeepInfra Kokoro.
    Returns a tuple of (audio_data, format).
    """
    if not tts_client:
        raise Exception("TTS client not initialized")

    response = tts_client.audio.speech.create(
        model="hexgrad/Kokoro-82M",
        voice=voice_id,
        input=text,
        response_format="mp3",
        speed=speed,
    )

    # Read the audio content
    audio_data = response.content
    return audio_data, "mp3"


def generate_podcast_audio(tts_client, transcript, host_voice, expert_voice, speed=1.0):
    """
    Generates podcast audio from a transcript with two speakers.

    The transcript should contain markers like:
    "Host: Hello and welcome..."
    "Expert: Thank you for having me..."

    Returns the combined audio data as MP3.
    """
    if not tts_client:
        raise Exception("TTS client not initialized")

    # Parse the transcript for speaker segments
    # Pattern: "Host:" or "Expert:" at the beginning of lines
    segments = []
    current_speaker = None
    current_text = []

    for line in transcript.split("\n"):
        line = line.strip()
        # Handle markdown bold like **Host:** or **Expert:**
        line_clean = line.replace("**", "").strip()
        if line_clean.startswith("Host:"):
            if current_speaker and current_text:
                segments.append((current_speaker, " ".join(current_text)))
            current_speaker = "host"
            current_text = [line_clean[5:].strip()]
        elif line_clean.startswith("Expert:"):
            if current_speaker and current_text:
                segments.append((current_speaker, " ".join(current_text)))
            current_speaker = "expert"
            current_text = [line_clean[7:].strip()]
        elif current_speaker and line:
            current_text.append(line)

    # Add the last segment
    if current_speaker and current_text:
        segments.append((current_speaker, " ".join(current_text)))

    # If no segments found, try as single speaker
    if not segments:
        segments = [("host", transcript)]

    # Generate audio for each segment
    combined_audio = AudioSegment.empty()

    # Small pause between segments (in milliseconds)
    pause = AudioSegment.silent(duration=500)

    for speaker, text in segments:
        voice_id = host_voice if speaker == "host" else expert_voice

        try:
            audio_data, _ = generate_voice_sample(tts_client, voice_id, text, speed)
            segment_audio = AudioSegment.from_file(io.BytesIO(audio_data), format="mp3")
            combined_audio += segment_audio + pause
        except Exception as e:
            print(f"Error generating audio for {speaker}: {e}")
            continue

    return combined_audio


def process_pdf(filepath):
    doc = fitz.open(filepath)
    text = ""
    elements = []
    figure_dir = os.path.join(
        "static", "figures", os.path.basename(filepath).replace(".pdf", "")
    )
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
                        block_text = tb[4].strip().replace("\n", " ")
                        if block_text.lower().startswith(("figure", "fig.")):
                            found_caption = block_text
                            break

            if found_caption:
                image_bytes = base_image["image"]
                image_ext = base_image["ext"]
                image_filename = f"image_{page_num + 1}_{img_index}.{image_ext}"
                image_path = os.path.join(figure_dir, image_filename)
                with open(image_path, "wb") as f:
                    f.write(image_bytes)

                elements.append(
                    {"type": "figure", "path": image_path, "caption": found_caption}
                )

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
                    if (
                        table_bbox.y0 > text_bbox.y1
                        and (table_bbox.y0 - text_bbox.y1) < 50
                    ):
                        # Check if text is horizontally aligned
                        text_center_x = (text_bbox.x0 + text_bbox.x1) / 2
                        if table_bbox.x0 < text_center_x < table_bbox.x1:
                            block_text = tb[4].strip().replace("\n", " ")
                            if block_text.lower().startswith(("table", "tbl.")):
                                found_caption = block_text
                                break

                if found_caption:
                    table_data = table.extract()
                    # Filter out empty or very small tables
                    if table_data and len(table_data) > 1:
                        elements.append(
                            {
                                "type": "table",
                                "data": table_data,
                                "caption": found_caption,
                                "page": page_num + 1,
                            }
                        )
        except Exception as e:
            # Log error if table processing fails for a page
            import logging

            logging.warning(f"Could not process tables on page {page_num + 1}: {e}")

    # Sort elements by page and then by vertical position
    # This is a bit tricky since we don't store y-pos, but page order is a good start.
    # A more robust solution would store the y-coordinate of each element.
    # For now, we assume the order of discovery is sufficient.

    return (
        text,
        json.dumps(elements),
        json.dumps([]),
    )  # Return empty list for old captions


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in {"pdf"}


# Legacy function - kept for compatibility but uses DeepInfra now
def generate_voice_sample_legacy(client, model_name, voice_name, text):
    """
    Legacy function for compatibility.
    Now uses DeepInfra Kokoro instead of Gemini.
    """
    # This is now handled by generate_voice_sample above
    pass
