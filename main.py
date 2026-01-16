import os
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from twilio.twiml.voice_response import VoiceResponse, Gather
from litellm import completion
from prompt import get_system_prompt

app = FastAPI()

# 1. SETUP
# Make sure these are in your Vercel Environment Variables
GROQ_API_KEY = os.getenv("GROQ_API_KEY") 
VOICE_ID = "Polly.Joanna-Neural" # High-quality US Female Voice

@app.get("/")
async def root():
    return {"status": "active", "service": "Expert Logo Designer AI"}

@app.post("/incoming-call")
async def incoming_call(request: Request):
    """
    Step 1: The phone rings. We pick up and greet.
    """
    params = request.query_params
    user_name = params.get("name", "there")
    
    resp = VoiceResponse()
    
    # A small pause makes it feel like a human picking up the receiver
    resp.pause(length=1)
    
    greeting = f"Hi {user_name}, this is Sarah calling from Expert Logo Designer. I saw you were checking out our packages, do you have a quick minute?"
    
    # Gather acts as the "Ears"
    gather = Gather(
        input='speech',
        action='/process-speech', # Send audio text to this endpoint
        speechTimeout='auto',     # Smart silence detection
        enhanced=True,            # Better transcription accuracy
        actionOnEmptyResult=True  # Handle silence gracefully
    )
    
    # Speak the greeting using the Neural Voice
    gather.say(greeting, voice=VOICE_ID)
    
    resp.append(gather)
    return HTMLResponse(content=str(resp), media_type="application/xml")

@app.post("/process-speech")
async def process_speech(request: Request, SpeechResult: str = Form(None)):
    """
    Step 2: User spoke. We send text to Groq -> Get Reply -> Speak back.
    """
    resp = VoiceResponse()

    # Handle Silence (User didn't say anything)
    if not SpeechResult:
        gather = Gather(input='speech', action='/process-speech', speechTimeout='auto')
        gather.say("Hello? I couldn't quite hear you.", voice=VOICE_ID)
        resp.append(gather)
        return HTMLResponse(content=str(resp), media_type="application/xml")

    # Call Groq (The Brain)
    messages = [
        {"role": "system", "content": get_system_prompt("the customer")},
        {"role": "user", "content": SpeechResult}
    ]

    try:
        # We use Llama3-8b because it is FAST (Critical for phone calls)
        response = completion(
            model="groq/llama3-8b-8192", 
            messages=messages,
            api_key=GROQ_API_KEY,
            max_tokens=150,
            temperature=0.6 # Balance between creative and accurate
        )
        ai_reply = response.choices[0].message.content
    except Exception as e:
        print(f"Error: {e}")
        ai_reply = "I'm so sorry, the line is breaking up a bit. Could you say that one more time?"

    # Sanitize text for Speech-to-Text engine (Remove asterisks/formatting)
    clean_reply = ai_reply.replace("*", "").replace("#", "").replace("-", " ")

    # Setup the next turn
    gather = Gather(
        input='speech',
        action='/process-speech',
        speechTimeout='auto',
        enhanced=True
    )
    
    gather.say(clean_reply, voice=VOICE_ID)
    resp.append(gather)
    
    # Keep line open if they don't hang up
    resp.redirect('/process-speech')
    
    return HTMLResponse(content=str(resp), media_type="application/xml")
