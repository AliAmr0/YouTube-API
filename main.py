from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import yt_dlp
import os
import json
from typing import Optional, List, Dict, Any
import asyncio
from concurrent.futures import ThreadPoolExecutor
import uvicorn
from urllib.parse import urlparse
import re
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="YouTube Downloader API",
    description="A comprehensive YouTube video and playlist downloader API for RapidAPI",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Thread pool for CPU-intensive tasks
executor = ThreadPoolExecutor(max_workers=4)

# Quality options mapping
QUALITY_OPTIONS = {
    "highest": "best",
    "high": "best[height<=720]",
    "medium": "best[height<=480]",
    "low": "best[height<=360]",
    "audio_only": "bestaudio/best"
}

def validate_youtube_url(url: str) -> bool:
    """Validate if the URL is a valid YouTube URL"""
    youtube_regex = re.compile(
        r'(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.(com|be)/'
        r'(watch\?v=|embed/|v/|.+\?v=)?([^&=%\?]{11})'
    )
    return bool(youtube_regex.match(url))

def extract_video_info(url: str) -> Dict[str, Any]:
    """Extract video information using yt-dlp"""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extractaudio': False,
        'audioformat': 'mp3',
        'outtmpl': '%(title)s.%(ext)s',
        'ignoreerrors': True,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info
    except Exception as e:
        logger.error(f"Error extracting video info: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Error extracting video info: {str(e)}")

def get_download_formats(info: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract available download formats"""
    formats = []
    
    if 'formats' in info:
        for fmt in info['formats']:
            if fmt.get('vcodec') != 'none' or fmt.get('acodec') != 'none':
                formats.append({
                    'format_id': fmt.get('format_id'),
                    'ext': fmt.get('ext'),
                    'quality': fmt.get('quality', 'N/A'),
                    'filesize': fmt.get('filesize'),
                    'vcodec': fmt.get('vcodec'),
                    'acodec': fmt.get('acodec'),
                    'fps': fmt.get('fps'),
                    'width': fmt.get('width'),
                    'height': fmt.get('height'),
                    'url': fmt.get('url')
                })
    
    return formats

@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "message": "YouTube Downloader API",
        "version": "1.0.0",
        "endpoints": {
            "/video/info": "Get video information",
            "/video/download": "Get video download links",
            "/playlist/info": "Get playlist information",
            "/playlist/download": "Get playlist download links",
            "/health": "Health check endpoint"
        }
    }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "message": "API is running"}

@app.get("/video/info")
async def get_video_info(
    url: str = Query(..., description="YouTube video URL"),
    include_formats: bool = Query(False, description="Include available download formats")
):
    """Get detailed information about a YouTube video"""
    
    if not validate_youtube_url(url):
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")
    
    try:
        # Run in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(executor, extract_video_info, url)
        
        video_info = {
            "id": info.get("id"),
            "title": info.get("title"),
            "description": info.get("description"),
            "duration": info.get("duration"),
            "view_count": info.get("view_count"),
            "like_count": info.get("like_count"),
            "uploader": info.get("uploader"),
            "upload_date": info.get("upload_date"),
            "thumbnail": info.get("thumbnail"),
            "tags": info.get("tags", []),
            "categories": info.get("categories", []),
            "age_limit": info.get("age_limit"),
            "webpage_url": info.get("webpage_url")
        }
        
        if include_formats:
            video_info["formats"] = get_download_formats(info)
        
        return video_info
        
    except Exception as e:
        logger.error(f"Error getting video info: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error getting video info: {str(e)}")

@app.get("/video/download")
async def get_video_download_links(
    url: str = Query(..., description="YouTube video URL"),
    quality: str = Query("high", description="Video quality: highest, high, medium, low, audio_only"),
    format: str = Query("mp4", description="Preferred format: mp4, webm, mkv, mp3")
):
    """Get download links for a YouTube video"""
    
    if not validate_youtube_url(url):
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")
    
    if quality not in QUALITY_OPTIONS:
        raise HTTPException(status_code=400, detail="Invalid quality option")
    
    try:
        # Configure yt-dlp options based on quality and format
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'format': QUALITY_OPTIONS[quality],
            'ignoreerrors': True,
        }
        
        if format == "mp3":
            ydl_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
            })
        
        loop = asyncio.get_event_loop()
        
        def get_download_info():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return info
        
        info = await loop.run_in_executor(executor, get_download_info)
        
        # Extract download information
        download_info = {
            "title": info.get("title"),
            "id": info.get("id"),
            "duration": info.get("duration"),
            "filesize": info.get("filesize"),
            "ext": info.get("ext"),
            "format_id": info.get("format_id"),
            "quality": quality,
            "requested_format": format,
            "download_url": info.get("url"),
            "thumbnail": info.get("thumbnail")
        }
        
        return download_info
        
    except Exception as e:
        logger.error(f"Error getting download links: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error getting download links: {str(e)}")

@app.get("/playlist/info")
async def get_playlist_info(
    url: str = Query(..., description="YouTube playlist URL"),
    limit: int = Query(50, description="Maximum number of videos to retrieve", ge=1, le=100)
):
    """Get information about a YouTube playlist"""
    
    if "playlist" not in url.lower():
        raise HTTPException(status_code=400, detail="Invalid playlist URL")
    
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'ignoreerrors': True,
            'playlistend': limit
        }
        
        loop = asyncio.get_event_loop()
        
        def get_playlist_data():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return info
        
        info = await loop.run_in_executor(executor, get_playlist_data)
        
        playlist_info = {
            "id": info.get("id"),
            "title": info.get("title"),
            "description": info.get("description"),
            "uploader": info.get("uploader"),
            "video_count": len(info.get("entries", [])),
            "videos": []
        }
        
        for entry in info.get("entries", []):
            if entry:
                playlist_info["videos"].append({
                    "id": entry.get("id"),
                    "title": entry.get("title"),
                    "url": entry.get("url"),
                    "duration": entry.get("duration"),
                    "uploader": entry.get("uploader")
                })
        
        return playlist_info
        
    except Exception as e:
        logger.error(f"Error getting playlist info: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error getting playlist info: {str(e)}")

@app.get("/playlist/download")
async def get_playlist_download_links(
    url: str = Query(..., description="YouTube playlist URL"),
    quality: str = Query("high", description="Video quality: highest, high, medium, low, audio_only"),
    format: str = Query("mp4", description="Preferred format: mp4, webm, mkv, mp3"),
    limit: int = Query(10, description="Maximum number of videos to process", ge=1, le=50)
):
    """Get download links for videos in a YouTube playlist"""
    
    if "playlist" not in url.lower():
        raise HTTPException(status_code=400, detail="Invalid playlist URL")
    
    if quality not in QUALITY_OPTIONS:
        raise HTTPException(status_code=400, detail="Invalid quality option")
    
    try:
        # First get playlist info
        playlist_info = await get_playlist_info(url, limit)
        
        download_links = []
        
        # Process each video in the playlist
        for video in playlist_info["videos"][:limit]:
            try:
                video_url = f"https://www.youtube.com/watch?v={video['id']}"
                download_info = await get_video_download_links(video_url, quality, format)
                download_links.append({
                    "video_info": video,
                    "download_info": download_info
                })
            except Exception as e:
                logger.error(f"Error processing video {video['id']}: {str(e)}")
                download_links.append({
                    "video_info": video,
                    "error": str(e)
                })
        
        return {
            "playlist_info": playlist_info,
            "download_links": download_links,
            "total_processed": len(download_links)
        }
        
    except Exception as e:
        logger.error(f"Error getting playlist download links: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error getting playlist download links: {str(e)}")

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Custom exception handler for HTTP exceptions"""
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail, "status_code": exc.status_code}
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """General exception handler"""
    logger.error(f"Unexpected error: {str(exc)}")
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "status_code": 500}
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)