import os
import re
import json
import smtplib
import subprocess
import streamlit as st
from deep_translator import GoogleTranslator
from fpdf import FPDF
from email.message import EmailMessage
import google.generativeai as genai

# Load API key from JSON file
def load_api_key():
    try:
        with open('config.json', 'r') as f:
            config = json.load(f)
        return config.get('GEMINI_API_KEY')
    except FileNotFoundError:
        st.error("Config file not found. Please ensure 'config.json' is present.")
        return None
    except json.JSONDecodeError:
        st.error("Error decoding config file. Please ensure 'config.json' is properly formatted.")
        return None

API_KEY = load_api_key()

if API_KEY:
    # Configure the Generative AI client
    genai.configure(api_key=API_KEY)

# Function to extract the video ID from a YouTube URL
def extract_video_id(yt_url):
    video_id_match = re.search(r"v=([^&]+)", yt_url)
    if video_id_match:
        return video_id_match.group(1)
    else:
        st.error("Invalid YouTube URL. Please provide a valid URL.")
        return None

# Function to download transcript using yt-dlp
def download_transcript(video_url):
    video_id = extract_video_id(video_url)
    if not video_id:
        return None

    # Define paths
    vtt_file_path = f"{video_id}.en.vtt"

    # Run yt-dlp to download the captions
    try:
        subprocess.run(['yt-dlp', '--write-auto-captions', '--skip-download', '--no-post-overwrites', video_url], check=True)
    except subprocess.CalledProcessError as e:
        st.error(f"An error occurred while running yt-dlp: {str(e)}")
        return None

    # Convert VTT to plain text
    if os.path.exists(vtt_file_path):
        with open(vtt_file_path, 'r', encoding='utf-8') as file:
            content = file.read()

        # Remove VTT metadata and timing information
        content = re.sub(r'^\d{2}:\d{2}:\d{2}\.\d{3} --> \d{2}:\d{2}:\d{2}\.\d{3}\n', '', content, flags=re.MULTILINE)
        content = re.sub(r'\n\n+', '\n\n', content).strip()  # Normalize new lines
        return content
    else:
        st.error(f"Caption file {vtt_file_path} not found.")
        return None

# Function to translate text if needed
def translate_text(text, target_lang='en'):
    try:
        translated = GoogleTranslator(source='auto', target=target_lang).translate(text)
        return translated
    except Exception as e:
        st.error(f"Translation error: {str(e)}")
        return text

# Function to generate summary using Gemini
def generate_summary(transcript, user_info=None):
    if user_info:
        prompt = (f"Summarize the following podcast transcript from the perspective of someone with the following background and goals:\n"
                  f"Field: {user_info['field']}\nBackground: {user_info['background']}\nFuture Plans: {user_info['plans']}\n\n"
                  f"Transcript:\n\n{transcript}\n\n"
                  f"Provide: a brief summary, quick lessons, dos and don'ts, key pointers and takeaways, any special mentions or quotes.")
    else:
        prompt = (f"Summarize the following podcast transcript.\n\nTranscript:\n\n{transcript}\n\n"
                  f"Provide: a brief summary, quick lessons, dos and don'ts, key pointers and takeaways, any special mentions or quotes.")
    
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(prompt)
        return {
            'summary': response.text,  # Adjust as needed based on actual API response
            'quick_lessons': [],  # Populate these lists based on actual content
            'dos': [],
            'donts': [],
            'key_pointers': [],
            'special_mentions': []
        }
    except Exception as e:
        st.error(f"Error generating summary: {str(e)}")
        return {}

def clean_text(text):
    replacements = {
        '“': '"',
        '”': '"',
        '‘': "'",
        '’': "'",
        '—': '-',
        '–': '-',
        '…': '...',
        '**': ''  # Ensure that ** is removed from text
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text.strip()

class PDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 12)
        self.cell(0, 10, 'NeuralBee - Podcast Summarizer', 0, 1, 'C')
        self.ln(5)  # Reduced line space after the header

    def chapter_title(self, title):
        self.set_font('Arial', 'B', 14)
        self.cell(0, 10, clean_text(title), 0, 1, 'C')
        self.ln(5)

    def chapter_body(self, body):
        self.set_font('Arial', '', 12)
        self.multi_cell(0, 10, clean_text(body))  # Adjusted for multi-line text handling
        self.ln(2)  # Minimized space after paragraphs

    def add_bold_left(self, content):
        self.set_font('Arial', 'B', 12)
        self.multi_cell(0, 10, clean_text(content))
        self.ln(2)  # Minimized space after bold text

    def add_numbered_bullets(self, items):
        self.set_font('Arial', '', 12)
        for idx, item in enumerate(items, start=1):
            self.multi_cell(0, 10, f"{idx}. {clean_text(item)}")
        self.ln(2)  # Minimized space after bullets

    def add_special_mentions(self, items):
        self.set_font('Arial', '', 12)
        for idx, item in enumerate(items, start=1):
            self.multi_cell(0, 10, f"{idx}. {clean_text(item)}")
        self.ln(2)  # Minimized space after special mentions

def create_pdf(summary, filename="podcast_summary.pdf"):
    pdf = PDF()
    pdf.add_page()

    content = summary.get('summary', '')
    lines = content.split('\n')

    bullet_items = []
    special_mentions = []
    in_bullet_section = False
    in_special_mentions = False

    for line in lines:
        line = line.strip()
        
        # Match headers starting with ##
        if re.match(r'^##', line):
            if in_bullet_section:
                pdf.add_numbered_bullets(bullet_items)
                bullet_items = []
                in_bullet_section = False
            if in_special_mentions:
                pdf.add_special_mentions(special_mentions)
                special_mentions = []
                in_special_mentions = False
            title = line[2:].strip()
            pdf.chapter_title(title)
        
        # Match bold text and remove surrounding **
        elif re.match(r'^\*\*.*\*\*$', line):
            if in_bullet_section:
                pdf.add_numbered_bullets(bullet_items)
                bullet_items = []
                in_bullet_section = False
            if in_special_mentions:
                pdf.add_special_mentions(special_mentions)
                special_mentions = []
                in_special_mentions = False
            bold_text = line[2:-2].strip()  # Remove surrounding **
            pdf.add_bold_left(bold_text)
        
        # Match special mentions starting with * **
        elif re.match(r'^\* \*\*', line):
            if not in_special_mentions:
                in_special_mentions = True
            special_mention_text = line[4:].strip()  # Remove * ** at the beginning
            special_mentions.append(special_mention_text)
        
        # Match bullet items starting with * without **
        elif re.match(r'^\* [^\*]', line):
            if not in_bullet_section:
                in_bullet_section = True
            bullet_text = line[1:].strip()  # Remove * at the beginning
            if bullet_text.endswith('**'):
                bullet_text = bullet_text[:-2].strip()  # Remove trailing **
            bullet_items.append(bullet_text)
        
        # Regular paragraph text
        else:
            if in_bullet_section:
                pdf.add_numbered_bullets(bullet_items)
                bullet_items = []
                in_bullet_section = False
            if in_special_mentions:
                pdf.add_special_mentions(special_mentions)
                special_mentions = []
                in_special_mentions = False
            pdf.chapter_body(line)

    # Handle any remaining bullet items
    if bullet_items:
        pdf.add_numbered_bullets(bullet_items)
    
    # Handle any remaining special mentions
    if special_mentions:
        pdf.add_special_mentions(special_mentions)

    # Add additional content
    pdf.chapter_title('Generated By Neural Bee')

    pdf.output(filename)

# Function to send email with attachment
def send_email(to_email, pdf_filename):
    from_email = 'adityajangam25@gmail.com'  # Replace with your Gmail address
    from_password = 'oucm rdfi triv cabd'  # Replace with your App Password

    msg = EmailMessage()
    msg['Subject'] = 'Your Podcast Summary PDF'
    msg['From'] = from_email
    msg['To'] = to_email
    msg.set_content('Please find attached the PDF summarizing the podcast you requested.')

    try:
        with open(pdf_filename, 'rb') as pdf_file:
            pdf_data = pdf_file.read()
            msg.add_attachment(pdf_data, maintype='application', subtype='pdf', filename=pdf_filename)

        with smtplib.SMTP('smtp.gmail.com', 587) as server:  # Gmail's SMTP server
            server.starttls()
            server.login(from_email, from_password)
            server.send_message(msg)
        st.success('Email sent successfully!')
    except Exception as e:
        st.error(f"Error sending email: {str(e)}")

# Streamlit app layout
st.title('Podcast Summarizer')

yt_url = st.text_input('Enter YouTube URL:')

if yt_url:
    transcript_text = download_transcript(yt_url)
    if transcript_text:
        st.subheader('Transcript')
        st.write(transcript_text)

        # Optionally translate transcript
        target_lang = st.selectbox('Translate to:', ['en', 'es', 'fr', 'de'])
        translated_text = translate_text(transcript_text, target_lang)
        st.subheader('Translated Transcript')
        st.write(translated_text)

        # Generate summary
        user_info = {
            'field': st.text_input('Field:'),
            'background': st.text_input('Background:'),
            'plans': st.text_input('Future Plans:')
        }
        
        if st.button('Generate Summary'):
            summary = generate_summary(translated_text, user_info)
            if summary:
                pdf_filename = 'podcast_summary.pdf'
                create_pdf(summary, pdf_filename)
                st.success('PDF created successfully!')

                # Send email with PDF attachment
                email_address = st.text_input('Enter your email to receive the PDF:')
                if email_address and st.button('Send Email'):
                    send_email(email_address, pdf_filename)
