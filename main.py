import os
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from twilio.twiml.voice_response import VoiceResponse, Gather
from litellm import completion
from prompt import get_system_prompt

app = FastAPI()

# Mount the static folder so CSS/HTML works
app.mount("/static", StaticFiles(directory="static"), name="static")

# GLOBAL MEMORY (Note: On Vercel this resets occasionally, but works for live demos)
conversation_logs = []

# ENV VARIABLES
GROQ_API_KEY = os.getenv("GROQ_API_KEY") 
VOICE_ID = "Polly.Joanna-Neural" 

# --- DASHBOARD ENDPOINTS ---

@app.get("/", response_class=HTMLResponse)
async def read_root():
    # Reads the HTML file and sends it to the browser
    with open("static/index.html", "r") as f:
        return f.read()

@app.get("/logs")
async def get_logs():
    # The frontend calls this to get the captions
    return JSONResponse(content={"logs": conversation_logs})

# --- CALLER ENDPOINTS ---

@app.post("/incoming-call")
async def incoming_call(request: Request):
    global conversation_logs
    conversation_logs = [] # Reset logs for new call
    
    params = request.query_params
    user_name = params.get("name", "there")
    
    resp = VoiceResponse()
    resp.pause(length=1)
    
    greeting = f"Hi {user_name}, this is Sarah from Expert Logo Designer. Do you have a quick minute?"
    
    # Log the AI's greeting
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

@app.post("/process-speech")
async def process_speech(request: Request, SpeechResult: str = Form(None)):
    global conversation_logs
    resp = VoiceResponse()

    if not SpeechResult:
        gather = Gather(input='speech', action='/process-speech', speechTimeout='auto')
        gather.say("Hello? Are you there?", voice=VOICE_ID)
        resp.append(gather)
        return HTMLResponse(content=str(resp), media_type="application/xml")

    # 1. Log the User's Speech
    conversation_logs.append({"role": "user", "content": SpeechResult})

    # 2. Get AI Reply
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
    except Exception:
        ai_reply = "Could you say that again?"

    # 3. Log the AI's Reply
    conversation_logs.append({"role": "ai", "content": ai_reply})

    # 4. Speak
    clean_reply = ai_reply.replace("*", "").replace("-", " ")
    gather = Gather(input='speech', action='/process-speech', speechTimeout='auto', enhanced=True)
    gather.say(clean_reply, voice=VOICE_ID)
    resp.append(gather)
    resp.redirect('/process-speech')
    
    return HTMLResponse(content=str(resp), media_type="application/xml")
