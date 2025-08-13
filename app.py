import os
from flask import Flask, render_template, request, redirect, url_for
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy
import json
import fitz # PyMuPDF
import google.generativeai as genai

# Configure the Gemini API
# IMPORTANT: Replace "YOUR_API_KEY" with your actual Gemini API key
genai.configure(api_key="YOUR_API_KEY")
model = genai.GenerativeModel('gemini-pro')

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['GENERATED_AUDIO_FOLDER'] = 'generated_audio'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///db.sqlite3'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
ALLOWED_EXTENSIONS = {'pdf'}

db = SQLAlchemy(app)

class PDFFile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(100), unique=True, nullable=False)
    text = db.Column(db.Text, nullable=False)
    figures = db.Column(db.Text)  # JSON-encoded list of figure paths
    captions = db.Column(db.Text)  # JSON-encoded list of captions

    def __repr__(self):
        return f'<PDFFile {self.filename}>'

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

        # Get text blocks for caption finding
        text_blocks = page.get_text("blocks")

        # Extract images
        image_list = page.get_images(full=True)
        for img_index, img in enumerate(image_list):
            xref = img[0]

            # Get image bounding box
            try:
                img_bbox = page.get_image_bbox(img)
            except ValueError:
                # Skip if bbox not found
                continue

            base_image = doc.extract_image(xref)
            image_bytes = base_image["image"]
            image_ext = base_image["ext"]
            image_filename = f"image_{page_num+1}_{img_index}.{image_ext}"
            image_path = os.path.join(figure_dir, image_filename)

            with open(image_path, "wb") as f:
                f.write(image_bytes)
            figures.append(image_path)

            # Find caption for the image
            found_caption = ""
            for tb in text_blocks:
                text_bbox = fitz.Rect(tb[:4])
                block_text = tb[4]

                # Check if text block is below the image and close to it
                if text_bbox.y0 > img_bbox.y1 and (text_bbox.y0 - img_bbox.y1) < 50:
                    # Check for horizontal alignment
                    text_center_x = (text_bbox.x0 + text_bbox.x1) / 2
                    if img_bbox.x0 < text_center_x < img_bbox.x1:
                        if block_text.strip().lower().startswith(('figure', 'fig.')):
                            found_caption = block_text.strip().replace('\n', ' ')
                            break

            captions.append(found_caption if found_caption else f"Figure {len(figures)}")

    return text, json.dumps(figures), json.dumps(captions)


def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    files = PDFFile.query.all()
    return render_template('index.html', files=files)

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return redirect(request.url)
    file = request.files['file']
    if file.filename == '':
        return redirect(request.url)
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        # Process the PDF and save to database
        text, figures, captions = process_pdf(filepath)
        new_file = PDFFile(filename=filename, text=text, figures=figures, captions=captions)
        db.session.add(new_file)
        db.session.commit()

        return redirect(url_for('index'))
    return redirect(request.url)

@app.route('/summarize/<int:file_id>')
def summarize(file_id):
    pdf_file = PDFFile.query.get_or_404(file_id)
    text = pdf_file.text

    # Generate summary using Gemini
    response = model.generate_content(f"Summarize the following text:\n\n{text}")
    summary = response.text

    return render_template('summary.html', summary=summary)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, use_reloader=False)
