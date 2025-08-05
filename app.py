from flask import Flask, render_template, request, jsonify, Response
import yt_dlp
import os
import threading
import time
import random
from urllib.parse import quote

app = Flask(__name__)
progress_data = {}

# Common yt-dlp options to prevent bot detection
BASE_YTDL_OPTS = {
    'quiet': True,
    'no_warnings': True,
    'ignoreerrors': True,
    'extractor_args': {
        'youtube': {
            'skip': ['authcheck', 'agegate', 'download']  # Bypass common checks
        }
    },
    'http_headers': {
        'User-Agent': random.choice([
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36',
            'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1',
            'Mozilla/5.0 (Linux; Android 10; SM-G981B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/80.0.3987.162 Mobile Safari/537.36'
        ]),
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer': 'https://www.youtube.com/'
    },
    'retries': 3,
    'fragment_retries': 3,
    'skip_unavailable_fragments': True
}

def get_info(url):
    opts = BASE_YTDL_OPTS.copy()
    
    # Add cookies if available
    if os.path.exists('cookies.txt'):
        opts['cookiefile'] = 'cookies.txt'
    else:
        print("Warning: No cookies.txt found. Some videos may require authentication.")
    
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                raise Exception("No video info returned")
            return info
    except Exception as e:
        print(f"Error fetching info: {str(e)}")
        return None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get-formats', methods=['POST'])
def get_formats():
    if not request.json or 'url' not in request.json:
        return jsonify({'error': 'Missing URL parameter'}), 400
    
    url = request.json['url']
    info = get_info(url)
    
    if not info:
        return jsonify({
            'error': 'Failed to fetch formats. YouTube may be blocking requests. Try again later or use cookies.'
        }), 500

    videos = []
    audios = []

    for f in info.get('formats', []):
        try:
            filesize = f.get('filesize') or f.get('filesize_approx')
            size = f"{round(filesize / 1024 / 1024, 2)} MB" if filesize else "Unknown"

            if f.get('vcodec') != 'none' and f.get('ext') in ['mp4', 'webm']:
                res = f.get('resolution') or f'{f.get("height", "N/A")}p'
                videos.append({
                    'id': f['format_id'],
                    'res': res,
                    'size': size,
                    'ext': f.get('ext', 'mp4')
                })
            elif f.get('vcodec') == 'none' and f.get('acodec') != 'none':
                audios.append({
                    'id': f['format_id'],
                    'bitrate': f.get('abr', 'N/A'),
                    'size': size,
                    'ext': f.get('ext', 'mp3')
                })
        except Exception as e:
            print(f"Error processing format {f.get('format_id')}: {str(e)}")
            continue

    return jsonify({
        'title': info.get('title', 'Unknown'),
        'thumbnail': info.get('thumbnail', ''),
        'duration': info.get('duration', 0),
        'videos': videos,
        'audios': audios
    })

@app.route('/download', methods=['POST'])
def download():
    if not request.json or 'url' not in request.json or 'format_id' not in request.json:
        return jsonify({'error': 'Missing parameters'}), 400
    
    url = request.json['url']
    format_id = request.json['format_id']
    
    info = get_info(url)
    if not info:
        return jsonify({'error': 'Failed to fetch video info'}), 500

    safe_title = ''.join(c for c in info['title'] if c.isalnum() or c in ' -_').rstrip()
    filename = f"downloads/{safe_title}-{format_id}.%(ext)s"

    os.makedirs('downloads', exist_ok=True)
    download_id = str(time.time())
    progress_data[download_id] = {
        "status": "downloading",
        "progress": 0,
        "filename": "",
        "error": ""
    }

    def hook(d):
        if d['status'] == 'downloading':
            downloaded = d.get('downloaded_bytes', 0)
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 1
            percent = int(downloaded * 100 / total)
            mb = round(downloaded / 1024 / 1024, 2)
            total_mb = round(total / 1024 / 1024, 2)
            progress_data[download_id].update({
                "status": "downloading",
                "progress": percent,
                "downloaded_mb": mb,
                "total_mb": total_mb
            })
        elif d['status'] == 'finished':
            progress_data[download_id].update({
                "status": "finished",
                "filename": quote(os.path.basename(d['filename']))
            })

    def run_download():
        try:
            video_only = format_id.startswith("audio")
            format_string = format_id if video_only else format_id + "+bestaudio/best"

            ydl_opts = BASE_YTDL_OPTS.copy()
            ydl_opts.update({
                'format': format_string,
                'outtmpl': filename,
                'progress_hooks': [hook],
                'merge_output_format': 'mp4'
            })

            if os.path.exists('cookies.txt'):
                ydl_opts['cookiefile'] = 'cookies.txt'

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
                
        except Exception as e:
            print(f"Download error: {str(e)}")
            progress_data[download_id].update({
                "status": "failed",
                "error": str(e)
            })

    thread = threading.Thread(target=run_download)
    thread.start()

    return jsonify({
        "download_id": download_id,
        "title": info.get('title', 'video')
    })

@app.route('/progress/<download_id>')
def progress(download_id):
    data = progress_data.get(download_id, {"status": "unknown"})
    return jsonify(data)

@app.route('/download-file/<filename>')
def download_file(filename):
    filepath = os.path.join('downloads', filename)
    if not os.path.exists(filepath):
        return jsonify({'error': 'File not found'}), 404
    
    def generate():
        with open(filepath, 'rb') as f:
            while chunk := f.read(1024*1024):  # 1MB chunks
                yield chunk
        # Clean up after download
        try:
            os.remove(filepath)
        except:
            pass

    response = Response(generate(), mimetype='application/octet-stream')
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    return response

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/how-to-use')
def how_to_use():
    return render_template('how_to_use.html')

@app.route('/privacy')
def privacy():
    return render_template('privacy.html')

if __name__ == '__main__':
    if not os.path.exists('downloads'):
        os.makedirs('downloads')
    app.run(host='0.0.0.0', port=5000, debug=True)
