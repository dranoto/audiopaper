import os
import re


def get_audio_filename(pdf_file):
    name = pdf_file.filename
    if name:
        name = os.path.splitext(name)[0]
        name = re.sub(r"[^a-zA-Z0-9\-_]", "", name)
        name = name[:40]
        if name:
            return f"{name}_{pdf_file.id}.mp3"
    return f"audio_{pdf_file.id}.mp3"
