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
import time
from functools import wraps
import hashlib
import random

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

# Caching and rate limiting
video_cache = {}
last_request_time = {}

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
    
    # Also check for youtu.be short URLs
    youtu_be_regex = re.compile(
        r'(https?://)?(www\.)?youtu\.be/([^&=%\?]{11})'
    )
    
    return bool(youtube_regex.match(url) or youtu_be_regex.match(url))

def normalize_youtube_url(url: str) -> str:
    """Normalize YouTube URL to standard format"""
    # Handle youtu.be URLs
    if 'youtu.be' in url:
        video_id = url.split('/')[-1].split('?')[0]
        return f"https://www.youtube.com/watch?v={video_id}"
    
    # Handle other formats
    if 'youtube.com' in url and 'v=' in url:
        return url
    
    return url

def rate_limit(calls_per_minute: int = 30):
    """Rate limiting decorator"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            current_time = time.time()
            client_ip = kwargs.get('client_ip', 'unknown')
            
            if client_ip in last_request_time:
                time_diff = current_time - last_request_time[client_ip]
                if time_diff < (60 / calls_per_minute):
                    wait_time = (60 / calls_per_minute) - time_diff
                    raise HTTPException(
                        status_code=429, 
                        detail=f"Rate limit exceeded. Please wait {wait_time:.1f} seconds before making another request."
                    )
            
            last_request_time[client_ip] = current_time
            return await func(*args, **kwargs)
        return wrapper
    return decorator

def get_cache_key(url: str, quality: str = "", format: str = "") -> str:
    """Generate cache key for video info"""
    cache_string = f"{url}_{quality}_{format}"
    return hashlib.md5(cache_string.encode()).hexdigest()

def cache_video_info(url: str, info: dict, expiry_minutes: int = 30):
    """Cache video information"""
    cache_key = get_cache_key(url)
    expiry_time = time.time() + (expiry_minutes * 60)
    video_cache[cache_key] = {
        'info': info,
        'expiry': expiry_time
    }

def get_cached_video_info(url: str) -> dict:
    """Get cached video information"""
    cache_key = get_cache_key(url)
    if cache_key in video_cache:
        cached_data = video_cache[cache_key]
        if time.time() < cached_data['expiry']:
            return cached_data['info']
        else:
            # Remove expired cache
            del video_cache[cache_key]
    return None

def extract_video_info(url: str) -> Dict[str, Any]:
    """Extract video information using yt-dlp with enhanced anti-bot measures"""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extractaudio': False,
        'audioformat': 'mp3',
        'outtmpl': '%(title)s.%(ext)s',
        'ignoreerrors': True,
        # Enhanced extractor arguments
        'extractor_args': {
            'youtube': {
                'skip': ['dash', 'hls'],
                'player_client': ['android', 'web', 'ios', 'mweb'],
                'player_skip': ['webpage'],
                'innertube_host': 'www.youtube.com',
                'innertube_key': None,
                'use_oauth': False,
                'check_formats': None
            }
        },
        # Add user agent rotation
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        },
        # Add retry mechanism
        'retries': 3,
        'fragment_retries': 3,
        'socket_timeout': 30,
        # Use different extraction methods
        'extract_flat': False,
        'force_json': False,
        'simulate': False
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info is None:
                raise HTTPException(status_code=400, detail="Could not extract video information. Video may be private, deleted, or require sign-in.")
            return info
    except yt_dlp.utils.DownloadError as e:
        error_msg = str(e)
        if "Sign in to confirm you're not a bot" in error_msg:
            # Try alternative extraction method
            return try_alternative_extraction(url)
        elif "Private video" in error_msg:
            raise HTTPException(status_code=403, detail="This video is private and cannot be accessed.")
        elif "Video unavailable" in error_msg:
            raise HTTPException(status_code=404, detail="This video is unavailable or has been deleted.")
        else:
            raise HTTPException(status_code=400, detail=f"Error extracting video info: {error_msg}")
    except Exception as e:
        logger.error(f"Error extracting video info: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error while processing video.")

def try_alternative_extraction(url: str) -> Dict[str, Any]:
    """Try alternative extraction methods when sign-in is required"""
    
    # Method 1: Try with Android client only
    ydl_opts_android = {
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': True,
        'extractor_args': {
            'youtube': {
                'player_client': ['android'],
                'skip': ['dash', 'hls'],
                'innertube_host': 'www.youtube.com'
            }
        }
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts_android) as ydl:
            info = ydl.extract_info(url, download=False)
            if info is not None:
                return info
    except:
        pass
    
    # Method 2: Try with iOS client
    ydl_opts_ios = {
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': True,
        'extractor_args': {
            'youtube': {
                'player_client': ['ios'],
                'skip': ['dash', 'hls']
            }
        }
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts_ios) as ydl:
            info = ydl.extract_info(url, download=False)
            if info is not None:
                return info
    except:
        pass
    
    # Method 3: Try with embed extraction
    ydl_opts_embed = {
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': True,
        'extractor_args': {
            'youtube': {
                'player_client': ['web'],
                'skip': ['dash', 'hls'],
                'player_skip': ['configs']
            }
        }
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts_embed) as ydl:
            info = ydl.extract_info(url, download=False)
            if info is not None:
                return info
    except:
        pass
    
    # If all methods fail, raise appropriate exception
    raise HTTPException(
        status_code=403, 
        detail={
            "error": "Sign-in required",
            "message": "This video requires sign-in verification and cannot be accessed through automated means",
            "suggestion": "Try a different video or check if the video has age restrictions",
            "workaround": "Some videos may work later due to YouTube's rotating restrictions"
        }
    )

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
            "/video/status": "Check video accessibility status",
            "/video/fallback": "Try alternative extraction methods",
            "/playlist/info": "Get playlist information",
            "/playlist/download": "Get playlist download links",
            "/health": "Health check endpoint"
        },
        "important_notes": {
            "restricted_content": "Some videos cannot be downloaded due to age restrictions, geo-blocking, premium content, or copyright protection",
            "check_availability": "Use /video/status to verify if content is downloadable",
            "fallback_methods": "Use /video/fallback for videos that require sign-in verification"
        }
    }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "message": "API is running"}

@app.get("/video/info")
@rate_limit(calls_per_minute=30)
async def get_video_info(
    url: str = Query(..., description="YouTube video URL"),
    include_formats: bool = Query(False, description="Include available download formats"),
    force_extract: bool = Query(False, description="Force extraction even if cached"),
    request: Request = None
):
    """Get detailed information about a YouTube video"""
    
    if not validate_youtube_url(url):
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")
    
    # Normalize URL
    url = normalize_youtube_url(url)
    
    # Check cache first
    if not force_extract:
        cached_info = get_cached_video_info(url)
        if cached_info:
            return {
                "cached": True,
                **cached_info
            }
    
    try:
        # Run in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(executor, extract_video_info, url)
        
        # Cache the result
        cache_video_info(url, info)
        
        # Safely extract video information
        video_info = {
            "cached": False,
            "id": info.get("id", "Unknown ID"),
            "title": info.get("title", "Unknown Title"),
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
            "webpage_url": info.get("webpage_url", url)
        }
        
        if include_formats:
            video_info["formats"] = get_download_formats(info)
        
        return video_info
        
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Error getting video info: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error while processing video information.")

@app.get("/video/status")
async def check_video_status(
    url: str = Query(..., description="YouTube video URL")
):
    """Check if a YouTube video is accessible and get basic status"""
    
    if not validate_youtube_url(url):
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")
    
    # Normalize URL
    url = normalize_youtube_url(url)
    
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'extract_flat': True,
            'ignoreerrors': True,
            'extractor_args': {
                'youtube': {
                    'skip': ['dash', 'hls'],
                    'player_client': ['android', 'web']
                }
            }
        }
        
        loop = asyncio.get_event_loop()
        
        def check_status():
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    if info is None:
                        return {
                            "accessible": False,
                            "status": "unavailable",
                            "message": "Video is not accessible"
                        }
                    return {
                        "accessible": True,
                        "status": "available",
                        "message": "Video is accessible",
                        "title": info.get("title", "Unknown Title"),
                        "uploader": info.get("uploader"),
                        "duration": info.get("duration")
                    }
            except yt_dlp.utils.DownloadError as e:
                error_msg = str(e)
                if "Sign in to confirm you're not a bot" in error_msg:
                    return {
                        "accessible": False,
                        "status": "restricted",
                        "message": "Video requires sign-in verification"
                    }
                elif "Private video" in error_msg:
                    return {
                        "accessible": False,
                        "status": "private",
                        "message": "Video is private"
                    }
                elif "Video unavailable" in error_msg:
                    return {
                        "accessible": False,
                        "status": "unavailable",
                        "message": "Video is unavailable or deleted"
                    }
                else:
                    return {
                        "accessible": False,
                        "status": "error",
                        "message": f"Error accessing video: {error_msg}"
                    }
        
        result = await loop.run_in_executor(executor, check_status)
        return result
        
    except Exception as e:
        logger.error(f"Error checking video status: {str(e)}")
        return {
            "accessible": False,
            "status": "error",
            "message": "Internal server error while checking video status"
        }

@app.get("/video/download")
@rate_limit(calls_per_minute=20)
async def get_video_download_links(
    url: str = Query(..., description="YouTube video URL"),
    quality: str = Query("high", description="Video quality: highest, high, medium, low, audio_only"),
    format: str = Query("mp4", description="Preferred format: mp4, webm, mkv, mp3"),
    force_extract: bool = Query(False, description="Force extraction even if cached"),
    request: Request = None
):
    """Get download links for a YouTube video with enhanced anti-bot measures"""
    
    if not validate_youtube_url(url):
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")
    
    if quality not in QUALITY_OPTIONS:
        raise HTTPException(status_code=400, detail="Invalid quality option")
    
    # Normalize URL
    url = normalize_youtube_url(url)
    
    # Check cache first
    if not force_extract:
        cached_info = get_cached_video_info(url)
        if cached_info:
            return {
                "cached": True,
                "title": cached_info.get("title", "Unknown Title"),
                "id": cached_info.get("id", "Unknown ID"),
                "duration": cached_info.get("duration"),
                "download_url": cached_info.get("url"),
                "quality": quality,
                "format": format
            }
    
    try:
        # Configure yt-dlp options with enhanced anti-bot measures
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'format': QUALITY_OPTIONS[quality],
            'ignoreerrors': True,
            'extractor_args': {
                'youtube': {
                    'skip': ['dash', 'hls'],
                    'player_client': ['android', 'web', 'ios', 'mweb'],
                    'player_skip': ['webpage'],
                    'innertube_host': 'www.youtube.com',
                    'check_formats': None
                }
            },
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Linux; Android 10; SM-G973F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.120 Mobile Safari/537.36'
            },
            'retries': 5,
            'fragment_retries': 5,
            'socket_timeout': 30,
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
        
        def get_download_info_enhanced():
            attempts = 0
            max_attempts = 3
            
            while attempts < max_attempts:
                try:
                    # Try different client configurations
                    clients = ['android', 'ios', 'web', 'mweb']
                    current_client = clients[attempts % len(clients)]
                    
                    ydl_opts['extractor_args']['youtube']['player_client'] = [current_client]
                    
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(url, download=False)
                        if info is not None:
                            # Cache the successful result
                            cache_video_info(url, info)
                            return info
                        
                except yt_dlp.utils.DownloadError as e:
                    error_msg = str(e)
                    attempts += 1
                    
                    if attempts >= max_attempts:
                        if "Sign in to confirm you're not a bot" in error_msg:
                            raise HTTPException(
                                status_code=403, 
                                detail={
                                    "error": "Sign-in verification required",
                                    "message": "This video requires sign-in verification and cannot be accessed",
                                    "suggestion": "Try a different video or check back later",
                                    "technical_info": "YouTube's anti-bot measures are preventing access",
                                    "fallback": "Try using /video/fallback endpoint"
                                }
                            )
                        elif "Private video" in error_msg:
                            raise HTTPException(status_code=403, detail="This video is private and cannot be accessed.")
                        elif "Video unavailable" in error_msg:
                            raise HTTPException(status_code=404, detail="This video is unavailable or has been deleted.")
                        else:
                            raise HTTPException(status_code=400, detail=f"Error extracting video: {error_msg}")
                    
                    # Wait before retrying
                    time.sleep(1)
                
                except Exception as e:
                    attempts += 1
                    if attempts >= max_attempts:
                        raise e
                    time.sleep(1)
            
            raise HTTPException(status_code=400, detail="Could not extract video information after multiple attempts.")
        
        info = await loop.run_in_executor(executor, get_download_info_enhanced)
        
        # Safely extract download information
        download_info = {
            "title": info.get("title", "Unknown Title"),
            "id": info.get("id", "Unknown ID"),
            "duration": info.get("duration"),
            "filesize": info.get("filesize"),
            "ext": info.get("ext"),
            "format_id": info.get("format_id"),
            "quality": quality,
            "requested_format": format,
            "download_url": info.get("url"),
            "thumbnail": info.get("thumbnail"),
            "cached": False,
            "extraction_method": "enhanced"
        }
        
        # Validate that we have a download URL
        if not download_info["download_url"]:
            raise HTTPException(
                status_code=503, 
                detail={
                    "error": "No download URL available",
                    "message": "Unable to generate download link. The video may be protected or unavailable.",
                    "suggestion": "Try a different quality or format option"
                }
            )
        
        return download_info
        
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Error getting download links: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error while processing download request.")

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

@app.get("/video/fallback")
async def get_video_fallback_info(
    url: str = Query(..., description="YouTube video URL"),
    method: str = Query("basic", description="Extraction method: basic, embed, mobile")
):
    """Fallback endpoint for videos that require sign-in"""
    
    if not validate_youtube_url(url):
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")
    
    url = normalize_youtube_url(url)
    
    # Try different extraction methods
    if method == "embed":
        # Try embed extraction
        embed_url = url.replace("watch?v=", "embed/")
        return await try_embed_extraction(embed_url)
    
    elif method == "mobile":
        # Try mobile extraction
        return await try_mobile_extraction(url)
    
    else:
        # Basic extraction with minimal options
        return await try_basic_extraction(url)

async def try_embed_extraction(url: str):
    """Try extraction using embed URL"""
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'ignoreerrors': True,
        }
        
        loop = asyncio.get_event_loop()
        
        def extract():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(url, download=False)
        
        info = await loop.run_in_executor(executor, extract)
        
        return {
            "method": "embed",
            "title": info.get("title", "Unknown Title"),
            "id": info.get("id", "Unknown ID"),
            "duration": info.get("duration"),
            "available": True
        }
    
    except Exception as e:
        return {
            "method": "embed",
            "available": False,
            "error": str(e)
        }

async def try_mobile_extraction(url: str):
    """Try extraction using mobile user agent"""
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'ignoreerrors': True,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0.3 Mobile/15E148 Safari/604.1'
            },
            'extractor_args': {
                'youtube': {
                    'player_client': ['ios'],
                    'skip': ['dash', 'hls']
                }
            }
        }
        
        loop = asyncio.get_event_loop()
        
        def extract():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(url, download=False)
        
        info = await loop.run_in_executor(executor, extract)
        
        return {
            "method": "mobile",
            "title": info.get("title", "Unknown Title"),
            "id": info.get("id", "Unknown ID"),
            "duration": info.get("duration"),
            "download_url": info.get("url"),
            "available": True
        }
    
    except Exception as e:
        return {
            "method": "mobile",
            "available": False,
            "error": str(e)
        }

async def try_basic_extraction(url: str):
    """Try basic extraction with minimal options"""
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'ignoreerrors': True,
            'extractor_args': {
                'youtube': {
                    'player_client': ['android']
                }
            }
        }
        
        loop = asyncio.get_event_loop()
        
        def extract():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(url, download=False)
        
        info = await loop.run_in_executor(executor, extract)
        
        return {
            "method": "basic",
            "title": info.get("title", "Unknown Title"),
            "id": info.get("id", "Unknown ID"),
            "duration": info.get("duration"),
            "download_url": info.get("url"),
            "available": True
        }
    
    except Exception as e:
        return {
            "method": "basic",
            "available": False,
            "error": str(e)
        }