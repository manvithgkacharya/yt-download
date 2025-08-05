from flask import Flask, render_template, request, jsonify, Response
import yt_dlp
import os
import threading
import time

app = Flask(__name__)
progress_data = {}

def get_info(url):
    with yt_dlp.YoutubeDL({}) as ydl:
        return ydl.extract_info(url, download=False)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get-formats', methods=['POST'])
def get_formats():
    url = request.json['url']
    info = get_info(url)

    videos = []
    audios = []

    for f in info['formats']:
        filesize = f.get('filesize') or f.get('filesize_approx')
        size = f"{round(filesize / 1024 / 1024, 2)} MB" if filesize else "Unknown"

        if f.get('vcodec') != 'none' and f.get('ext') == 'mp4':
            res = f.get('resolution') or f.get('height', 'N/A')
            videos.append({'id': f['format_id'], 'res': res, 'size': size})
        elif f.get('vcodec') == 'none' and f.get('acodec') != 'none':
            audios.append({'id': f['format_id'], 'bitrate': f.get('abr', 'N/A'), 'size': size})

    return jsonify({'videos': videos, 'audios': audios})

@app.route('/download', methods=['POST'])
def download():
    data = request.json
    url = data['url']
    format_id = data['format_id']
    info = get_info(url)
    safe_title = ''.join(c for c in info['title'] if c.isalnum() or c in ' -_').rstrip()
    filename = f"downloads/{safe_title}-%(format_id)s.%(ext)s"

    os.makedirs('downloads', exist_ok=True)
    download_id = str(time.time())
    progress_data[download_id] = {"status": "downloading", "progress": 0}

    def hook(d):
        if d['status'] == 'downloading':
            downloaded = d.get('downloaded_bytes', 0)
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 1
            percent = int(downloaded * 100 / total)
            mb = round(downloaded / 1024 / 1024, 2)
            total_mb = round(total / 1024 / 1024, 2)
            progress_data[download_id] = {
                "status": "downloading",
                "progress": percent,
                "downloaded_mb": mb,
                "total_mb": total_mb
            }
        elif d['status'] == 'finished':
            progress_data[download_id]["status"] = "finished"

    def run_download():
        video_only = format_id.startswith("audio")
        format_string = format_id if video_only else format_id + "+bestaudio/best"

        ydl_opts = {
            'format': format_string,
            'outtmpl': filename,
            'progress_hooks': [hook]
        }

        if not video_only:
            ydl_opts['merge_output_format'] = 'mp4'

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

    thread = threading.Thread(target=run_download)
    thread.start()

    return jsonify({"download_id": download_id})

@app.route('/progress/<download_id>')
def progress(download_id):
    return jsonify(progress_data.get(download_id, {"status": "unknown"}))

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/how-to-use')
def how_to_use():
    return render_template('how_to_use.html')

@app.route('/privacy')
def privacy():
    return render_template('about.html')  # Reuse about page for privacy

if __name__ == '__main__':
    app.run(debug=True)