import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
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
DOMAIN = "https://myaicaller.vercel.app" # UPDATE THIS with your actual Vercel URL
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")
GOOGLE_JSON = os.getenv("Googlesheetapi") # The JSON string from Vercel Env
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

# --- GOOGLE SHEET AUTO-DIALER ---
@app.post("/start-campaign")
async def start_campaign():
    global conversation_logs
    
    if not GOOGLE_JSON:
        return {"status": "error", "message": "Google Credentials missing in Vercel"}
    
    try:
        # 1. Authenticate with Google
        creds_dict = json.loads(GOOGLE_JSON)
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client_google = gspread.authorize(creds)
        
        # 2. Open Sheet
        sheet = client_google.open("AI Caller Agent").sheet1
        rows = sheet.get_all_records() # Expects headers: Name, Contact
        
        # 3. Initialize Twilio
        client_twilio = Client(TWILIO_SID, TWILIO_TOKEN)
        
        dialed_count = 0
        
        # 4. Loop through every row and fire a call
        for row in rows:
            name = row.get("Name", "Client")
            phone = str(row.get("Contact", "")).strip()
            
            if phone:
                # Add '+' if missing (Twilio needs E.164 format)
                if not phone.startswith('+'): phone = f"+{phone}"
                
                print(f"Dialing {name} at {phone}...")
                
                callback_url = f"{DOMAIN}/call-connected?name={name}"
                
                client_twilio.calls.create(
                    to=phone,
                    from_=TWILIO_NUMBER,
                    url=callback_url
                )
                dialed_count += 1
        
        conversation_logs.append({"role": "system", "content": f"Campaign Started: Dialing {dialed_count} leads from Sheet."})
        return {"status": "success", "count": dialed_count}

    except Exception as e:
        return {"status": "error", "message": str(e)}

# --- MANUAL DIALER ---
@app.post("/make-call")
async def make_call(payload: dict = Body(...)):
    # ... (Keep your existing manual dialer code here) ...
    # For brevity, I'm assuming you keep the previous make_call logic
    return {"status": "success"} 

# --- VOICE LOGIC ---
@app.post("/call-connected")
async def call_connected(request: Request):
    params = request.query_params
    user_name = params.get("name", "there")
    
    resp = VoiceResponse()
    resp.pause(length=1)
    
    greeting = f"Hi {user_name}, this is Sarah calling from Expert Logo Designer. I saw your inquiry about our logo packages—do you have a quick minute?"
    
    global conversation_logs
    conversation_logs.append({"role": "ai", "content": greeting})
    
    gather = Gather(input='speech', action='/process-speech', speechTimeout='auto', enhanced=True)
    gather.say(greeting, voice=VOICE_ID)
    resp.append(gather)
    return HTMLResponse(content=str(resp), media_type="application/xml")

@app.post("/process-speech")
async def process_speech(request: Request, SpeechResult: str = Form(None)):
    global conversation_logs
    resp = VoiceResponse()

    if not SpeechResult:
        resp.say("Hello? I couldn't quite hear you.", voice=VOICE_ID)
        gather = Gather(input='speech', action='/process-speech')
        resp.append(gather)
        return HTMLResponse(content=str(resp), media_type="application/xml")

    conversation_logs.append({"role": "user", "content": SpeechResult})

    messages = [
        {"role": "system", "content": get_system_prompt("the customer")},
        {"role": "user", "content": SpeechResult}
    ]

    try:
        response = completion(
            model="groq/llama-3.3-70b-versatile",
            messages=messages,
            api_key=GROQ_API_KEY,
            max_tokens=150,
            temperature=0.7
        )
        ai_reply = response.choices[0].message.content
    except Exception as e:
        ai_reply = "I'm sorry, the connection is a bit bad. Could you repeat that?"

    conversation_logs.append({"role": "ai", "content": ai_reply})

    clean_reply = ai_reply.replace("*", "").replace("-", " ")
    
    gather = Gather(input='speech', action='/process-speech', speechTimeout='auto', enhanced=True)
    gather.say(clean_reply, voice=VOICE_ID)
    resp.append(gather)
    
    return HTMLResponse(content=str(resp), media_type="application/xml")
