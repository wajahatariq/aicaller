import os
from fastapi import FastAPI, Form, Request, Body
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from twilio.twiml.voice_response import VoiceResponse, Gather
from twilio.rest import Client
from litellm import completion
from prompt import get_system_prompt

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

# --- CONFIGURATION ---
# REPLACE THIS WITH YOUR VERCEL DOMAIN AFTER DEPLOYING
DOMAIN = "https://myaicaller.vercel.app" 

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")
VOICE_ID = "Polly.Joanna-Neural"

# --- GLOBAL STATE ---
conversation_logs = []
call_active = False

# --- FRONTEND ENDPOINTS ---
@app.get("/", response_class=HTMLResponse)
async def read_root():
    with open("static/index.html", "r") as f: return f.read()

@app.get("/status")
async def get_status():
    return JSONResponse(content={"logs": conversation_logs, "call_active": call_active})

# --- DIALER LOGIC (OUTBOUND) ---
@app.post("/make-call")
async def make_call(payload: dict = Body(...)):
    global conversation_logs, call_active
    
    target_phone = payload.get("phone")
    target_name = payload.get("name", "there")
    
    if not TWILIO_SID or not TWILIO_TOKEN:
        return {"status": "error", "message": "Twilio Credentials Missing in Vercel"}

    try:
        client = Client(TWILIO_SID, TWILIO_TOKEN)
        
        # This URL tells Twilio what to do when the human answers
        callback_url = f"{DOMAIN}/call-connected?name={target_name}"

        call = client.calls.create(
            to=target_phone,
            from_=TWILIO_NUMBER,
            url=callback_url 
        )
        
        conversation_logs = [{"role": "system", "content": f"Initiating call to {target_name}..."}]
        call_active = True
        return {"status": "success", "call_sid": call.sid}
        
    except Exception as e:
        return {"status": "error", "message": str(e)}

# --- VOICE LOGIC ---
@app.post("/call-connected")
async def call_connected(request: Request):
    """Triggered when the user answers the phone"""
    params = request.query_params
    user_name = params.get("name", "there")
    
    resp = VoiceResponse()
    resp.pause(length=1) # Natural pause
    
    # The Cold Call Opener
    greeting = f"Hi {user_name}, this is Sarah calling from Expert Logo Designer. How are you doing today?"
    
    global conversation_logs
    conversation_logs.append({"role": "ai", "content": greeting})
    
    gather = Gather(input='speech', action='/process-speech', speechTimeout='auto', enhanced=True)
    gather.say(greeting, voice=VOICE_ID)
    resp.append(gather)
    return HTMLResponse(content=str(resp), media_type="application/xml")

@app.post("/process-speech")
async def process_speech(request: Request, SpeechResult: str = Form(None)):
    global conversation_logs, call_active
    resp = VoiceResponse()

    # 1. Handle Silence
    if not SpeechResult:
        resp.say("Hello? I couldn't quite hear you.", voice=VOICE_ID)
        gather = Gather(input='speech', action='/process-speech')
        resp.append(gather)
        return HTMLResponse(content=str(resp), media_type="application/xml")

    # 2. Log User Speech
    conversation_logs.append({"role": "user", "content": SpeechResult})

    # 3. AI Brain
    messages = [
        {"role": "system", "content": get_system_prompt("the customer")},
        {"role": "user", "content": SpeechResult}
    ]

    try:
        response = completion(
            model="groq/llama-3.3-70b-versatile", # High-intelligence model for sales
            messages=messages,
            api_key=GROQ_API_KEY,
            max_tokens=150,
            temperature=0.7
        )
        ai_reply = response.choices[0].message.content
    except Exception as e:
        ai_reply = "I'm sorry, the connection is a bit bad. Could you repeat that?"
        conversation_logs.append({"role": "system", "content": f"Error: {str(e)}"})

    # 4. Log AI Reply
    conversation_logs.append({"role": "ai", "content": ai_reply})

    # 5. Speak & Loop
    clean_reply = ai_reply.replace("*", "").replace("-", " ")
    
    gather = Gather(input='speech', action='/process-speech', speechTimeout='auto', enhanced=True)
    gather.say(clean_reply, voice=VOICE_ID)
    resp.append(gather)
    
    return HTMLResponse(content=str(resp), media_type="application/xml")
