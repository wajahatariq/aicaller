import os
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from twilio.twiml.voice_response import VoiceResponse, Gather
from litellm import completion
from prompt import get_system_prompt

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")

# GLOBAL STATE
# Note: On Vercel, this may reset if the server "sleeps". 
# For production, you'd use a database (Redis/Postgres).
SYSTEM_ACTIVE = False 
conversation_logs = []

GROQ_API_KEY = os.getenv("GROQ_API_KEY") 
VOICE_ID = "Polly.Joanna-Neural"

# --- DASHBOARD & CONTROL ENDPOINTS ---

@app.get("/", response_class=HTMLResponse)
async def read_root():
    with open("static/index.html", "r") as f:
        return f.read()

@app.get("/status")
async def get_status():
    """Frontend polls this to see if we are Live or Stopped"""
    return JSONResponse(content={
        "active": SYSTEM_ACTIVE, 
        "logs": conversation_logs
    })

@app.post("/toggle-system")
async def toggle_system():
    """Button clicks hit this to flip the switch"""
    global SYSTEM_ACTIVE
    SYSTEM_ACTIVE = not SYSTEM_ACTIVE
    status = "LIVE" if SYSTEM_ACTIVE else "STOPPED"
    # Log this change so it shows in the chat window
    conversation_logs.append({"role": "system", "content": f"System switched to {status}"})
    return {"active": SYSTEM_ACTIVE}

# --- CALLER ENDPOINTS ---

@app.post("/incoming-call")
async def incoming_call(request: Request):
    global conversation_logs
    
    # 1. THE GATEKEEPER CHECK
    if not SYSTEM_ACTIVE:
        resp = VoiceResponse()
        resp.say("The AI system is currently offline. Please try again later.")
        resp.hangup()
        return HTMLResponse(content=str(resp), media_type="application/xml")

    # 2. If Active, proceed as normal
    conversation_logs = [] # Reset logs for new call
    params = request.query_params
    user_name = params.get("name", "there")
    
    resp = VoiceResponse()
    resp.pause(length=1)
    
    greeting = f"Hi {user_name}, this is Sarah from Expert Logo Designer. Do you have a quick minute?"
    
    conversation_logs.append({"role": "ai", "content": greeting})
    
    gather = Gather(
        input='speech',
        action='/process-speech',
        speechTimeout='auto',
        enhanced=True,
        actionOnEmptyResult=True
    )
    gather.say(greeting, voice=VOICE_ID)
    resp.append(gather)
    return HTMLResponse(content=str(resp), media_type="application/xml")

# REPLACE THE 'process-speech' FUNCTION IN main.py WITH THIS:

@app.post("/process-speech")
async def process_speech(request: Request, SpeechResult: str = Form(None)):
    global conversation_logs
    resp = VoiceResponse()

    if not SpeechResult:
        gather = Gather(input='speech', action='/process-speech', speechTimeout='auto')
        gather.say("Hello? Are you there?", voice=VOICE_ID)
        resp.append(gather)
        return HTMLResponse(content=str(resp), media_type="application/xml")

    conversation_logs.append({"role": "user", "content": SpeechResult})

    messages = [
        {"role": "system", "content": get_system_prompt("the customer")},
        {"role": "user", "content": SpeechResult}
    ]

    try:
        response = completion(
            model="groq/llama3-8b-8192", 
            messages=messages,
            api_key=GROQ_API_KEY,
            max_tokens=150,
            temperature=0.6
        )
        ai_reply = response.choices[0].message.content
    except Exception as e:
        # --- DEBUGGING: Print the ACTUAL error to the dashboard ---
        error_msg = f"SYSTEM ERROR: {str(e)}"
        print(error_msg) # Prints to Vercel logs
        conversation_logs.append({"role": "system", "content": error_msg}) 
        ai_reply = "I am having a technical issue connecting to my brain."

    conversation_logs.append({"role": "ai", "content": ai_reply})

    clean_reply = ai_reply.replace("*", "").replace("-", " ")
    gather = Gather(input='speech', action='/process-speech', speechTimeout='auto', enhanced=True)
    gather.say(clean_reply, voice=VOICE_ID)
    resp.append(gather)
    resp.redirect('/process-speech')
    
    return HTMLResponse(content=str(resp), media_type="application/xml")
