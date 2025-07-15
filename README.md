# YouTube Downloader API

A comprehensive YouTube video and playlist downloader API built with FastAPI, designed for RapidAPI marketplace and Render deployment.

## Features

- **Video Information**: Get detailed information about YouTube videos
- **Video Downloads**: Generate download links for videos in various qualities
- **Playlist Support**: Download entire playlists with customizable limits
- **Multiple Formats**: Support for MP4, WebM, MKV, and MP3 formats
- **Quality Options**: Choose from highest, high, medium, low, or audio-only quality
- **RapidAPI Ready**: Fully compatible with RapidAPI marketplace
- **Production Ready**: Optimized for Render deployment

## API Endpoints

### 1. Root Endpoint
- **GET** `/` - API information and available endpoints

### 2. Health Check
- **GET** `/health` - Check API health status

### 3. Video Information
- **GET** `/video/info`
  - **Parameters:**
    - `url` (required): YouTube video URL
    - `include_formats` (optional): Include available download formats
  - **Response:** Detailed video information including title, description, duration, views, etc.

### 4. Video Download Links
- **GET** `/video/download`
  - **Parameters:**
    - `url` (required): YouTube video URL
    - `quality` (optional): Video quality (highest, high, medium, low, audio_only)
    - `format` (optional): Preferred format (mp4, webm, mkv, mp3)
  - **Response:** Download links and metadata

### 5. Playlist Information
- **GET** `/playlist/info`
  - **Parameters:**
    - `url` (required): YouTube playlist URL
    - `limit` (optional): Maximum number of videos to retrieve (1-100)
  - **Response:** Playlist information with video list

### 6. Playlist Download Links
- **GET** `/playlist/download`
  - **Parameters:**
    - `url` (required): YouTube playlist URL
    - `quality` (optional): Video quality
    - `format` (optional): Preferred format
    - `limit` (optional): Maximum number of videos to process (1-50)
  - **Response:** Download links for all videos in playlist

## Quality Options

- `highest`: Best available quality
- `high`: Up to 720p
- `medium`: Up to 480p
- `low`: Up to 360p
- `audio_only`: Audio only (for MP3 conversion)

## Supported Formats

- **Video**: MP4, WebM, MKV
- **Audio**: MP3

## Example Usage

### Get Video Information
```bash
GET /video/info?url=https://www.youtube.com/watch?v=VIDEO_ID
```

### Download Video
```bash
GET /video/download?url=https://www.youtube.com/watch?v=VIDEO_ID&quality=high&format=mp4
```

### Get Playlist Information
```bash
GET /playlist/info?url=https://www.youtube.com/playlist?list=PLAYLIST_ID&limit=20
```

### Download Playlist
```bash
GET /playlist/download?url=https://www.youtube.com/playlist?list=PLAYLIST_ID&quality=medium&format=mp4&limit=10
```

## Installation

1. Clone the repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run the API:
   ```bash
   python main.py
   ```

## Deployment

### Render Deployment

1. Connect your GitHub repository to Render
2. Create a new Web Service
3. Use the following settings:
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
   - Environment: Python 3.11+

### RapidAPI Integration

1. Deploy to a hosting platform (Render, Heroku, etc.)
2. Get your API base URL
3. Submit to RapidAPI with the OpenAPI specification
4. Configure endpoints and pricing

## Environment Variables

- `PORT`: Port number (default: 8000)

## Error Handling

The API includes comprehensive error handling:
- Invalid URL validation
- Quality option validation
- Rate limiting protection
- Graceful error responses

## Rate Limiting

For production use, consider implementing rate limiting to prevent abuse:
- Per-IP request limits
- API key authentication
- Usage quotas

## Dependencies

- FastAPI: Web framework
- yt-dlp: YouTube downloading library
- uvicorn: ASGI server
- pydantic: Data validation

## License

This project is licensed under the MIT License.

## Support

For issues and questions, please create an issue in the GitHub repository.

## Disclaimer

This API is for educational and personal use only. Please respect YouTube's Terms of Service and copyright laws when using this API.
