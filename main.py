import os
import httpx
from fastapi import FastAPI, Request, Form, UploadFile, File, Path
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv
import assemblyai as aai
import google.generativeai as genai
import uuid
from typing import Dict, List
import logging
from pathlib import Path as PathLib

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# API Keys with fallback handling
MURF_API_KEY = os.getenv("MURF_API_KEY")
ASSEMBLYAI_API_KEY = os.getenv("ASSEMBLYAI_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Comment out these lines to simulate API failures:
# MURF_API_KEY = None
# ASSEMBLYAI_API_KEY = None
# GEMINI_API_KEY = None

MURF_API_URL = "https://api.murf.ai/v1/speech/generate"


# Configure APIs with error handling
def configure_apis():
    """Configure external APIs with proper error handling"""
    try:
        if ASSEMBLYAI_API_KEY:
            aai.settings.api_key = ASSEMBLYAI_API_KEY
            logger.info("AssemblyAI configured successfully")
        else:
            logger.warning("AssemblyAI API key not found")

        if GEMINI_API_KEY:
            genai.configure(api_key=GEMINI_API_KEY)
            logger.info("Gemini AI configured successfully")
        else:
            logger.warning("Gemini API key not found")

        if MURF_API_KEY:
            logger.info("Murf AI API key found")
        else:
            logger.warning("Murf API key not found")

    except Exception as e:
        logger.error(f"Error configuring APIs: {str(e)}")


configure_apis()

# Ensure uploads directory exists
os.makedirs("uploads", exist_ok=True)

app = FastAPI()

# Mount static and uploads directories
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

templates = Jinja2Templates(directory="templates")

# In-memory chat history storage
chat_histories: Dict[str, List[Dict[str, str]]] = {}


def create_fallback_response(message: str, error_type: str = "general"):
    """Create a standardized fallback response for errors"""
    fallback_messages = {
        "stt": "I'm having trouble hearing you right now. Could you please try again?",
        "llm": "I'm having difficulty processing your request at the moment. Please try again later.",
        "tts": "I'm having trouble generating audio right now. Here's my text response instead.",
        "general": "I'm experiencing technical difficulties. Please try again in a moment.",
    }

    return {
        "error": True,
        "error_type": error_type,
        "message": message,
        "fallback_message": fallback_messages.get(
            error_type, fallback_messages["general"]
        ),
        "audio_url": None,
    }


async def safe_transcribe_audio(audio_data):
    """Safely transcribe audio with error handling"""
    try:
        if not ASSEMBLYAI_API_KEY:
            raise Exception("AssemblyAI API key not configured")

        transcriber = aai.Transcriber()
        transcript = transcriber.transcribe(audio_data)

        if not transcript or not transcript.text:
            raise Exception("Transcription returned empty result")

        logger.info(f"Transcription successful: {transcript.text[:50]}...")
        return transcript.text, None

    except Exception as e:
        logger.error(f"Transcription error: {str(e)}")
        return None, str(e)


async def safe_generate_llm_response(
    prompt: str, conversation_history: List[Dict] = None
):
    """Safely generate LLM response with error handling"""
    try:
        if not GEMINI_API_KEY:
            raise Exception("Gemini API key not configured")

        model = genai.GenerativeModel("gemini-1.5-flash")

        # Prepare context if conversation history exists
        if conversation_history:
            context = ""
            for message in conversation_history:
                role = "User" if message["role"] == "user" else "Assistant"
                context += f"{role}: {message['content']}\n"
            context += f"User: {prompt}\nAssistant:"
            response = model.generate_content(context)
        else:
            response = model.generate_content(prompt)

        if not response or not response.text:
            raise Exception("LLM returned empty response")

        logger.info(f"LLM response generated successfully: {response.text[:50]}...")
        return response.text, None

    except Exception as e:
        logger.error(f"LLM generation error: {str(e)}")
        fallback_responses = [
            "I apologize, but I'm having trouble processing your request right now. Could you please try again?",
            "I'm experiencing some technical difficulties. Please rephrase your question and try again.",
            "Sorry, I'm unable to generate a proper response at the moment. Please try again later.",
        ]
        return fallback_responses[0], str(e)


async def safe_generate_tts(text: str):
    """Safely generate TTS with error handling"""
    try:
        if not MURF_API_KEY:
            raise Exception("Murf API key not configured")

        headers = {"Content-Type": "application/json", "api-key": MURF_API_KEY}
        payload = {
            "text": text,
            "voiceId": "en-US-terrell",
            "format": "mp3",
            "sampleRate": "24000",
            "channelType": "STEREO",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(MURF_API_URL, headers=headers, json=payload)

        if response.status_code == 200:
            audio_url = response.json().get("audioFile")
            if audio_url:
                logger.info("TTS generation successful")
                return audio_url, None
            else:
                raise Exception("No audio URL in response")
        else:
            raise Exception(
                f"TTS API returned status {response.status_code}: {response.text}"
            )

    except Exception as e:
        logger.error(f"TTS generation error: {str(e)}")
        return None, str(e)


# Serve index.html
@app.get("/", response_class=HTMLResponse)
async def read_index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# Enhanced TTS generation endpoint
@app.post("/tts")
async def generate_tts(text: str = Form(...)):
    try:
        if not text.strip():
            return JSONResponse(
                content=create_fallback_response("Empty text provided", "tts"),
                status_code=400,
            )

        audio_url, error = await safe_generate_tts(text)

        if error:
            return JSONResponse(
                content=create_fallback_response(error, "tts"), status_code=500
            )

        return JSONResponse(content={"audio_url": audio_url, "error": False})

    except Exception as e:
        logger.error(f"TTS endpoint error: {str(e)}")
        return JSONResponse(
            content=create_fallback_response(str(e), "tts"), status_code=500
        )


# Enhanced upload audio endpoint
@app.post("/upload")
async def upload_audio(file: UploadFile = File(...)):
    try:
        contents = await file.read()
        upload_path = os.path.join("uploads", file.filename)

        with open(upload_path, "wb") as f:
            f.write(contents)

        return {
            "filename": file.filename,
            "content_type": file.content_type,
            "size": len(contents),
            "url": f"/uploads/{file.filename}",
            "error": False,
        }

    except Exception as e:
        logger.error(f"File upload error: {str(e)}")
        return JSONResponse(
            content=create_fallback_response(str(e), "general"), status_code=500
        )


# Enhanced transcription endpoint
@app.post("/transcribe/file")
async def transcribe_audio(file: UploadFile = File(...)):
    try:
        contents = await file.read()
        transcription, error = await safe_transcribe_audio(contents)

        if error:
            return JSONResponse(
                content=create_fallback_response(error, "stt"), status_code=500
            )

        return {"transcription": transcription, "error": False}

    except Exception as e:
        logger.error(f"Transcription endpoint error: {str(e)}")
        return JSONResponse(
            content=create_fallback_response(str(e), "stt"), status_code=500
        )


# Enhanced Echo Bot endpoint with comprehensive error handling
@app.post("/tts/echo")
async def echo_tts(file: UploadFile = File(...)):
    try:
        # Step 1: Read uploaded audio
        contents = await file.read()

        # Step 2: Transcribe with error handling
        transcription, transcribe_error = await safe_transcribe_audio(contents)
        if transcribe_error:
            return JSONResponse(
                content=create_fallback_response(transcribe_error, "stt"),
                status_code=500,
            )

        # Step 3: Generate TTS with error handling
        audio_url, tts_error = await safe_generate_tts(transcription)
        if tts_error:
            return JSONResponse(
                content={
                    "transcription": transcription,
                    "error": True,
                    "error_type": "tts",
                    "message": tts_error,
                    "fallback_message": "I heard you say: "
                    + transcription
                    + " (Audio generation failed)",
                    "audio_url": None,
                }
            )

        return JSONResponse(
            content={
                "audio_url": audio_url,
                "transcription": transcription,
                "error": False,
            }
        )

    except Exception as e:
        logger.error(f"Echo TTS error: {str(e)}")
        return JSONResponse(
            content=create_fallback_response(str(e), "general"), status_code=500
        )


# Enhanced LLM Query endpoint
@app.post("/llm/query")
async def llm_query(text: str = Form(...)):
    try:
        if not text.strip():
            return JSONResponse(
                content=create_fallback_response("Empty text provided", "llm"),
                status_code=400,
            )

        response, error = await safe_generate_llm_response(text)

        if error and not response:
            return JSONResponse(
                content=create_fallback_response(error, "llm"), status_code=500
            )

        return JSONResponse(
            content={
                "response": response,
                "input": text,
                "error": False,
                "has_fallback": bool(error),  # Indicates if response is a fallback
            }
        )

    except Exception as e:
        logger.error(f"LLM query endpoint error: {str(e)}")
        return JSONResponse(
            content=create_fallback_response(str(e), "llm"), status_code=500
        )


# Enhanced LLM Query with audio input
@app.post("/llm/query/audio")
async def llm_query_audio(file: UploadFile = File(...)):
    try:
        # Step 1: Read uploaded audio
        contents = await file.read()

        # Step 2: Transcribe with error handling
        transcription, transcribe_error = await safe_transcribe_audio(contents)
        if transcribe_error:
            return JSONResponse(
                content=create_fallback_response(transcribe_error, "stt"),
                status_code=500,
            )

        # Step 3: Generate LLM response with error handling
        llm_response, llm_error = await safe_generate_llm_response(transcription)

        # Step 4: Generate TTS with error handling
        audio_url, tts_error = await safe_generate_tts(llm_response)

        response_data = {
            "transcription": transcription,
            "llm_response": llm_response,
            "error": False,
        }

        if tts_error:
            response_data.update(
                {
                    "audio_url": None,
                    "tts_error": True,
                    "fallback_message": "I'm having trouble generating audio right now. Here's my text response: "
                    + llm_response,
                }
            )
        else:
            response_data["audio_url"] = audio_url

        if llm_error:
            response_data["has_llm_fallback"] = True

        return JSONResponse(content=response_data)

    except Exception as e:
        logger.error(f"LLM audio query error: {str(e)}")
        return JSONResponse(
            content=create_fallback_response(str(e), "general"), status_code=500
        )


# Enhanced Chat endpoint with comprehensive error handling
@app.post("/agent/chat/{session_id}")
async def agent_chat(session_id: str = Path(...), file: UploadFile = File(...)):
    try:
        # Step 1: Read uploaded audio
        contents = await file.read()

        # Step 2: Transcribe with error handling
        transcription, transcribe_error = await safe_transcribe_audio(contents)
        if transcribe_error:
            return JSONResponse(
                content=create_fallback_response(transcribe_error, "stt"),
                status_code=500,
            )

        # Step 3: Initialize session if it doesn't exist
        if session_id not in chat_histories:
            chat_histories[session_id] = []

        # Step 4: Add user message to chat history
        chat_histories[session_id].append({"role": "user", "content": transcription})

        # Step 5: Generate LLM response with conversation context
        llm_response, llm_error = await safe_generate_llm_response(
            transcription,
            chat_histories[session_id][:-1],  # Exclude the current message
        )

        # Step 6: Add assistant response to chat history
        chat_histories[session_id].append(
            {"role": "assistant", "content": llm_response}
        )

        # Step 7: Generate TTS with error handling
        audio_url, tts_error = await safe_generate_tts(llm_response)

        response_data = {
            "transcription": transcription,
            "llm_response": llm_response,
            "session_id": session_id,
            "chat_history": chat_histories[session_id],
            "error": False,
        }

        if tts_error:
            response_data.update(
                {
                    "audio_url": None,
                    "tts_error": True,
                    "fallback_message": "I'm having trouble with audio generation. Here's my response: "
                    + llm_response,
                }
            )
        else:
            response_data["audio_url"] = audio_url

        if llm_error:
            response_data["has_llm_fallback"] = True

        return JSONResponse(content=response_data)

    except Exception as e:
        logger.error(f"Chat endpoint error: {str(e)}")
        return JSONResponse(
            content=create_fallback_response(str(e), "general"), status_code=500
        )


# Get chat history for a session
@app.get("/agent/chat/{session_id}/history")
async def get_chat_history(session_id: str = Path(...)):
    try:
        if session_id in chat_histories:
            return JSONResponse(
                content={
                    "session_id": session_id,
                    "chat_history": chat_histories[session_id],
                    "error": False,
                }
            )
        else:
            return JSONResponse(
                content={"session_id": session_id, "chat_history": [], "error": False}
            )
    except Exception as e:
        logger.error(f"Get chat history error: {str(e)}")
        return JSONResponse(
            content=create_fallback_response(str(e), "general"), status_code=500
        )


# Clear chat history for a session
@app.delete("/agent/chat/{session_id}/history")
async def clear_chat_history(session_id: str = Path(...)):
    try:
        if session_id in chat_histories:
            del chat_histories[session_id]

        return JSONResponse(
            content={
                "session_id": session_id,
                "message": "Chat history cleared",
                "error": False,
            }
        )
    except Exception as e:
        logger.error(f"Clear chat history error: {str(e)}")
        return JSONResponse(
            content=create_fallback_response(str(e), "general"), status_code=500
        )


# Generate new session ID
@app.post("/agent/session/new")
async def create_new_session():
    try:
        session_id = str(uuid.uuid4())
        return JSONResponse(content={"session_id": session_id, "error": False})
    except Exception as e:
        logger.error(f"Create session error: {str(e)}")
        return JSONResponse(
            content=create_fallback_response(str(e), "general"), status_code=500
        )


# Enhanced health check endpoint
@app.get("/health")
async def health_check():
    try:
        api_status = {
            "murf_api": bool(MURF_API_KEY),
            "assemblyai_api": bool(ASSEMBLYAI_API_KEY),
            "gemini_api": bool(GEMINI_API_KEY),
        }
        return JSONResponse(
            content={"status": "ok", "api_status": api_status, "error": False},
            status_code=200,
        )
    except Exception as e:
        logger.error(f"Health check error: {str(e)}")
        return JSONResponse(
            content={"status": "error", "message": str(e), "error": True},
            status_code=500,
        )
