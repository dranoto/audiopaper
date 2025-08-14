from app import app, db, PDFFile, Folder
import os

with app.app_context():
    # Clean up previous dummy data if it exists
    PDFFile.query.filter_by(filename="dummy_for_test.pdf").delete()
    Folder.query.filter_by(name="Dummy Folder").delete()
    db.session.commit()

    # Create a dummy folder
    dummy_folder = Folder(name="Dummy Folder")
    db.session.add(dummy_folder)
    db.session.commit()

    # Create a dummy file on disk
    dummy_filename = "dummy_for_test.pdf"
    dummy_filepath = os.path.join(app.config['UPLOAD_FOLDER'], dummy_filename)
    with open(dummy_filepath, "w") as f:
        f.write("dummy pdf content")

    # Create a dummy record in the database, associated with the folder
    new_file = PDFFile(filename=dummy_filename, text="dummy text", folder_id=dummy_folder.id, figures="[]", captions="[]")
    db.session.add(new_file)
    db.session.commit()
    print(f"Created dummy folder and file: {dummy_filename} in 'Dummy Folder'")
