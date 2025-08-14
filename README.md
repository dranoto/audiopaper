# AudioPaper

AudioPaper is a web application that allows you to upload PDF documents, and it will generate a text summary of the document using the Gemini API.

## Prerequisites

Before you begin, ensure you have the following installed on your system:
- [Docker](https://docs.docker.com/get-docker/)
- [Docker Compose](https://docs.docker.com/compose/install/)

## Setup

1.  **Clone the repository:**
    ```bash
    git clone <repository-url>
    cd audiopaper
    ```

2.  **Create a `.env` file:**
    Create a file named `.env` in the root of the project directory. This file will hold your Gemini API key.

    ```
    GEMINI_API_KEY=YOUR_API_KEY
    ```
    Replace `YOUR_API_KEY` with your actual Gemini API key.

## Running the Application

1.  **Build and run the application using Docker Compose:**
    ```bash
    docker-compose up --build
    ```
    This command will build the Docker image for the application and start the service. The `--build` flag is only necessary the first time you run the command, or if you make changes to the application code or dependencies.

2.  **Access the application:**
    Once the container is running, you can access the application by navigating to `http://localhost:8000` in your web browser.

## How to Use

1.  Open the application in your web browser.
2.  Click on the "Choose File" button to select a PDF file you want to summarize.
3.  Click "Upload".
4.  The uploaded file will appear in the list of files.
5.  Click on the "Summarize" link next to the file to view the generated summary.

## Project Structure

-   `app.py`: The main Flask application file.
-   `Dockerfile`: Defines the Docker container for the application.
-   `docker-compose.yml`: Defines the services, networks, and volumes for the application.
-   `requirements.txt`: A list of Python dependencies for the project.
-   `templates/`: Contains the HTML templates for the application.
-   `uploads/`: A directory where uploaded PDF files are stored (created automatically).
-   `static/figures`: A directory where extracted figures from the PDFs are stored (created automatically).
-   `instance/`: A directory where the SQLite database is stored (created automatically).
